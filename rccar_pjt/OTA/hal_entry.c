#include "hal_data.h"
#include "motorhat.h"
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

FSP_CPP_HEADER
void R_BSP_WarmStart(bsp_warm_start_event_t event);
FSP_CPP_FOOTER

#define PIN_BUSY BSP_IO_PORT_03_PIN_02
#define SET_BUSY_HIGH() R_IOPORT_PinWrite(&g_ioport_ctrl, PIN_BUSY, BSP_IO_LEVEL_HIGH)
#define SET_BUSY_LOW()  R_IOPORT_PinWrite(&g_ioport_ctrl, PIN_BUSY, BSP_IO_LEVEL_LOW)

/* Three single decimal digits.  1, 2, 3 is reported as V1.2.3. */
#define FW_VERSION_MAJOR      1U
#define FW_VERSION_MINOR      0U
#define FW_VERSION_PATCH      0U
#define FW_VERSION_DIGIT(v)   ((uint8_t) ('0' + (v)))

#if (FW_VERSION_MAJOR > 9U) || (FW_VERSION_MINOR > 9U) || (FW_VERSION_PATCH > 9U)
 #error "Each firmware version component must be a single decimal digit (0-9)."
#endif

static const uint8_t FW_VERSION_RESPONSE[4] = {
    'V',
    FW_VERSION_DIGIT(FW_VERSION_MAJOR),
    FW_VERSION_DIGIT(FW_VERSION_MINOR),
    FW_VERSION_DIGIT(FW_VERSION_PATCH)
};
/*
 * R7FA6E10F2CFP has 1 MiB of code flash, so each dual-bank image is 512 KiB.
 * In RA6E1 dual-bank mode FSP exposes the bank opposite the startup mapping
 * through BSP_FEATURE_FLASH_HP_CF_DUAL_BANK_START (0x00200000), not through
 * 0x00080000.  The mapped bank begins with eight 8 KiB blocks, followed by
 * 32 KiB blocks.  After BankSwap the mappings exchange, so this same alias
 * remains the update target for the next OTA (A -> B -> A ping-pong).
 */
#define OTA_BANK_ADDRESS      BSP_FEATURE_FLASH_HP_CF_DUAL_BANK_START
#define OTA_BANK_SIZE         0x00080000UL
#define OTA_CHUNK_SIZE        256U
#define OTA_HEADER_REMAINDER  10U
#define OTA_SMALL_REGION_SIZE 0x00010000UL
#define OTA_SMALL_BLOCK_SIZE  0x00002000UL
#define OTA_LARGE_BLOCK_SIZE  0x00008000UL
#define OTA_BUSY_VISIBLE_MS   20U

volatile bool spi_transfer_complete = false;

typedef enum e_ota_rx_state {
    OTA_RX_SYNC = 0,
    OTA_RX_HEADER,
    OTA_RX_PAYLOAD
} ota_rx_state_t;

static bool ota_mode = false;
static bool ota_flash_error = false;
static bool ota_flash_open_error = false;
static bool reading_metadata = false;
/* size[4] + chunks[4] + image CRC32[4] + metadata CRC32[4] */
static uint8_t metadata[16];
static uint8_t metadata_index = 0;

static ota_rx_state_t ota_rx_state = OTA_RX_SYNC;
static uint8_t sync_window[4] = {0};
static uint8_t frame_header[OTA_HEADER_REMAINDER];
static uint8_t frame_header_index = 0;
static uint8_t ota_buffer[OTA_CHUNK_SIZE] BSP_ALIGN_VARIABLE(4);
static uint16_t ota_buffer_index = 0;

static uint32_t frame_chunk_id = 0;
static uint16_t frame_payload_len = 0;
static uint32_t frame_crc32 = 0;
static uint32_t expected_size = 0;
static uint32_t expected_chunks = 0;
static uint32_t expected_image_crc32 = 0;
static uint32_t expected_next_chunk = 0;
static uint32_t received_count = 0;
static uint32_t flash_write_addr = OTA_BANK_ADDRESS;

static void delay_ms(uint32_t ms)
{
    R_BSP_SoftwareDelay(ms, BSP_DELAY_UNITS_MILLISECONDS);
}

void spi_callback(spi_callback_args_t *p_args)
{
    if (p_args->event == SPI_EVENT_TRANSFER_COMPLETE) {
        spi_transfer_complete = true;
    }
}

static fsp_err_t wait_for_flash_ready(void)
{
    flash_status_t status = FLASH_STATUS_BUSY;
    fsp_err_t err;
    do {
        err = R_FLASH_HP_StatusGet(&g_flash0_ctrl, &status);
        if (FSP_SUCCESS != err) return err;
    } while (FLASH_STATUS_IDLE != status);
    return FSP_SUCCESS;
}

static uint32_t read_u32_be(const uint8_t *p)
{
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) | (uint32_t)p[3];
}

static uint16_t read_u16_be(const uint8_t *p)
{
    return (uint16_t)(((uint16_t)p[0] << 8) | p[1]);
}

static uint32_t crc32_update(uint32_t crc, const uint8_t *data, uint32_t length)
{
    for (uint32_t i = 0; i < length; ++i) {
        crc ^= data[i];
        for (uint8_t bit = 0; bit < 8; ++bit) {
            crc = (crc >> 1) ^ (0xEDB88320UL & (uint32_t)-(int32_t)(crc & 1U));
        }
    }
    return crc;
}

static uint32_t crc32_block(const uint8_t *data, uint32_t length)
{
    return crc32_update(0xFFFFFFFFUL, data, length) ^ 0xFFFFFFFFUL;
}

/*
 * Arm the SPI response first, then lower BUSY.  ESP32 waits for the complete
 * HIGH->LOW cycle before supplying the response clock, so it cannot read a
 * stale MISO byte.
 */
static void ota_send_response(uint8_t response)
{
    uint8_t dummy = 0;
    spi_transfer_complete = false;
    fsp_err_t err = R_SPI_WriteRead(&g_spi1_ctrl, &response, &dummy, 1,
                                    SPI_BIT_WIDTH_8_BITS);
    /* Hold HIGH long enough for ESP32 to observe even when Flash returns an
       error immediately.  The old 2 ms pulse could be missed after SPI cleanup. */
    delay_ms(OTA_BUSY_VISIBLE_MS);
    SET_BUSY_LOW();
    if (FSP_SUCCESS == err) {
        while (!spi_transfer_complete) { }
    }
}

static void reset_frame_receiver(void)
{
    ota_rx_state = OTA_RX_SYNC;
    frame_header_index = 0;
    ota_buffer_index = 0;
    memset(sync_window, 0, sizeof(sync_window));
}

static void reset_ota_session(void)
{
    /* A previous erase failure must not poison a new OTA attempt. */
    ota_flash_error = ota_flash_open_error;
    reading_metadata = true;
    metadata_index = 0;
    expected_size = 0;
    expected_chunks = 0;
    expected_image_crc32 = 0;
    expected_next_chunk = 0;
    received_count = 0;
    flash_write_addr = OTA_BANK_ADDRESS;
    reset_frame_receiver();
}

static uint32_t ota_erase_blocks_for_size(uint32_t image_size)
{
    if (image_size <= OTA_SMALL_REGION_SIZE) {
        return (image_size + OTA_SMALL_BLOCK_SIZE - 1U) / OTA_SMALL_BLOCK_SIZE;
    }

    uint32_t small_blocks = OTA_SMALL_REGION_SIZE / OTA_SMALL_BLOCK_SIZE;
    uint32_t remaining = image_size - OTA_SMALL_REGION_SIZE;
    uint32_t large_blocks =
        (remaining + OTA_LARGE_BLOCK_SIZE - 1U) / OTA_LARGE_BLOCK_SIZE;
    return small_blocks + large_blocks;
}

static void handle_metadata_byte(uint8_t value)
{
    metadata[metadata_index++] = value;
    if (metadata_index < sizeof(metadata)) return;

    expected_size = read_u32_be(metadata);
    expected_chunks = read_u32_be(metadata + 4);
    expected_image_crc32 = read_u32_be(metadata + 8);
    uint32_t received_metadata_crc32 = read_u32_be(metadata + 12);
    uint32_t calculated_metadata_crc32 = crc32_block(metadata, 12);
    reading_metadata = false;

    bool metadata_crc_valid =
                          received_metadata_crc32 == calculated_metadata_crc32;
    bool metadata_valid = metadata_crc_valid &&
                          expected_size > 0U &&
                          expected_size <= OTA_BANK_SIZE &&
                          (expected_size % OTA_CHUNK_SIZE) == 0U &&
                          expected_chunks == (expected_size / OTA_CHUNK_SIZE);

    SET_BUSY_HIGH();

    /* Erase only after the image metadata has arrived.  A 15 KiB image now
       erases two 8 KiB blocks instead of blocking on the whole 512 KiB bank. */
    if (metadata_valid && !ota_flash_open_error) {
        uint32_t erase_blocks = ota_erase_blocks_for_size(expected_size);
        fsp_err_t err = wait_for_flash_ready();
        if (FSP_SUCCESS == err) {
            err = R_FLASH_HP_Erase(&g_flash0_ctrl, OTA_BANK_ADDRESS, erase_blocks);
        }
        if (FSP_SUCCESS == err) err = wait_for_flash_ready();
        ota_flash_error = (FSP_SUCCESS != err);
    }

    uint8_t response = ota_flash_open_error ? 0x18U :
                       !metadata_crc_valid ? 0x14U :
                       !metadata_valid ? 0x1BU :
                       ota_flash_error ? 0x19U : 0x79U;
    ota_send_response(response);
    if (response != 0x79U) ota_mode = false;
}

static void handle_complete_chunk(void)
{
    uint8_t response = 0x1FU;
    SET_BUSY_HIGH();

    uint32_t actual_crc = crc32_block(ota_buffer, frame_payload_len);
    if (frame_payload_len != OTA_CHUNK_SIZE || actual_crc != frame_crc32) {
        response = 0x1FU; /* Length or CRC error. */
    } else if (frame_chunk_id + 1U == expected_next_chunk) {
        response = 0x7AU; /* Duplicate after a lost MQTT ACK: already written. */
    } else if (frame_chunk_id != expected_next_chunk) {
        response = 0x1EU; /* Out-of-order chunk. */
    } else if (received_count + frame_payload_len > expected_size) {
        response = 0x1BU; /* Image bounds error. */
    } else {
        fsp_err_t err = wait_for_flash_ready();
        if (FSP_SUCCESS == err) {
            err = R_FLASH_HP_Write(&g_flash0_ctrl, (uint32_t)ota_buffer,
                                   flash_write_addr, frame_payload_len);
        }
        if (FSP_SUCCESS == err) err = wait_for_flash_ready();

        if (FSP_SUCCESS == err) {
            flash_write_addr += frame_payload_len;
            received_count += frame_payload_len;
            ++expected_next_chunk;
            response = 0x79U;
        } else {
            response = 0x1DU; /* Flash write error. */
        }
    }

    reset_frame_receiver();
    ota_send_response(response);
}

static void handle_ota_end(void)
{
    SET_BUSY_HIGH();

    if (ota_flash_error) {
        ota_mode = false;
        ota_send_response(0x1DU);
        return;
    }
    if (received_count != expected_size) {
        ota_mode = false;
        ota_send_response(0x17U);
        return;
    }
    if (expected_next_chunk != expected_chunks) {
        ota_mode = false;
        ota_send_response(0x16U);
        return;
    }
    fsp_err_t err = wait_for_flash_ready();
    if (FSP_SUCCESS == err) {
        /* Toggle the active and alternate banks.  This does not depend on a
           hard-coded firmware version or an assumed current bank. */
        err = R_FLASH_HP_BankSwap(&g_flash0_ctrl);
    }

    if (FSP_SUCCESS != err) {
        ota_mode = false;
        ota_send_response(0x1CU); /* Bank swap option write failed. */
        return;
    }

    ota_send_response(0x79U);
    delay_ms(100);
    NVIC_SystemReset();
}

static void handle_ota_byte(uint8_t value)
{
    if (reading_metadata) {
        handle_metadata_byte(value);
        return;
    }

    if (OTA_RX_HEADER == ota_rx_state) {
        frame_header[frame_header_index++] = value;
        if (frame_header_index == OTA_HEADER_REMAINDER) {
            frame_chunk_id = read_u32_be(frame_header);
            frame_payload_len = read_u16_be(frame_header + 4);
            frame_crc32 = read_u32_be(frame_header + 6);
            if (frame_payload_len == 0U || frame_payload_len > OTA_CHUNK_SIZE) {
                SET_BUSY_HIGH();
                reset_frame_receiver();
                ota_send_response(0x1BU);
            } else {
                ota_rx_state = OTA_RX_PAYLOAD;
                ota_buffer_index = 0;
            }
        }
        return;
    }

    if (OTA_RX_PAYLOAD == ota_rx_state) {
        ota_buffer[ota_buffer_index++] = value;
        if (ota_buffer_index == frame_payload_len) handle_complete_chunk();
        return;
    }

    sync_window[0] = sync_window[1];
    sync_window[1] = sync_window[2];
    sync_window[2] = sync_window[3];
    sync_window[3] = value;

    if (sync_window[0] == 'O' && sync_window[1] == 'T' &&
        sync_window[2] == 'A' && sync_window[3] == 'D') {
        ota_rx_state = OTA_RX_HEADER;
        frame_header_index = 0;
    } else if (sync_window[0] == 'O' && sync_window[1] == 'T' &&
               sync_window[2] == 'A' && sync_window[3] == 'E') {
        reset_frame_receiver();
        handle_ota_end();
    } else if (sync_window[0] == 'O' && sync_window[1] == 'T' &&
               sync_window[2] == 'A' && sync_window[3] == 'A') {
        ota_mode = false;
        reset_frame_receiver();
    }
}

void hal_entry(void)
{
    init(0x6f);
    setPWMFreq(60);
    Mid();
    delay_ms(10);
    setSpeed(150);
    SET_BUSY_LOW();

    uint8_t tx_data = 0x0FU;
    uint8_t rx_data = 0;
    uint8_t command_window[4] = {0};
    uint8_t version_response_index = (uint8_t) sizeof(FW_VERSION_RESPONSE);

    fsp_err_t flash_open_err = R_FLASH_HP_Open(&g_flash0_ctrl, &g_flash0_cfg);
    ota_flash_open_error = (FSP_SUCCESS != flash_open_err);
    ota_flash_error = ota_flash_open_error;

    while (1) {
        spi_transfer_complete = false;
        fsp_err_t spi_err = R_SPI_WriteRead(&g_spi1_ctrl, &tx_data, &rx_data, 1,
                                            SPI_BIT_WIDTH_8_BITS);
        if (FSP_SUCCESS != spi_err) continue;
        while (!spi_transfer_complete) { }
        tx_data = 0x0FU;

        if (ota_mode) {
            handle_ota_byte(rx_data);
            continue;
        }

        /* A version query is a pipelined SPI response.  Receiving 'p' arms
           'V'; each following dummy transfer arms the next digit. */
        if (version_response_index < sizeof(FW_VERSION_RESPONSE)) {
            tx_data = FW_VERSION_RESPONSE[version_response_index++];
        }
        else if (rx_data == 'p') {
            tx_data = FW_VERSION_RESPONSE[0];
            version_response_index = 1U;
        }
        else if (rx_data == 'w') Forward();
        else if (rx_data == 'x') Backward();
        else if (rx_data == 'f') Release();
        else if (rx_data == 's') Mid();
        else if (rx_data == 'a') Left();
        else if (rx_data == 'd') Right();

        command_window[0] = command_window[1];
        command_window[1] = command_window[2];
        command_window[2] = command_window[3];
        command_window[3] = rx_data;

        if (command_window[0] == 'O' && command_window[1] == 'T' &&
            command_window[2] == 'A' && command_window[3] == 'S') {
            ota_mode = true;
            Release();
            SET_BUSY_HIGH();
            reset_ota_session();
            /* Metadata arrives next.  The required erase range is calculated
               from its image size in handle_metadata_byte(). */
            delay_ms(OTA_BUSY_VISIBLE_MS);
            SET_BUSY_LOW();
            memset(command_window, 0, sizeof(command_window));
        }
    }
}

void R_BSP_WarmStart(bsp_warm_start_event_t event)
{
    if (BSP_WARM_START_POST_C == event) {
        R_IOPORT_Open(&g_ioport_ctrl, g_ioport.p_cfg);
        R_IIC_MASTER_Open(&g_i2c_master0_ctrl, &g_i2c_master0_cfg);
        R_SPI_Open(&g_spi1_ctrl, &g_spi1_cfg);
    }
}
