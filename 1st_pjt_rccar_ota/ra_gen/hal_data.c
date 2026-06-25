/* generated HAL source file - do not edit */
#include "hal_data.h"
flash_hp_instance_ctrl_t g_flash0_ctrl;
const flash_cfg_t g_flash0_cfg = { .data_flash_bgo = false, .p_callback = NULL,
		.p_context = NULL,
#if defined(VECTOR_NUMBER_FCU_FRDYI)
    .irq                 = VECTOR_NUMBER_FCU_FRDYI,
#else
		.irq = FSP_INVALID_VECTOR,
#endif
#if defined(VECTOR_NUMBER_FCU_FIFERR)
    .err_irq             = VECTOR_NUMBER_FCU_FIFERR,
#else
		.err_irq = FSP_INVALID_VECTOR,
#endif
		.err_ipl = (BSP_IRQ_DISABLED), .ipl = (BSP_IRQ_DISABLED), };
/* Instance structure to use this module. */
const flash_instance_t g_flash0 = { .p_ctrl = &g_flash0_ctrl, .p_cfg =
		&g_flash0_cfg, .p_api = &g_flash_on_flash_hp };
#define RA_NOT_DEFINED (UINT32_MAX)
#if (RA_NOT_DEFINED) != (RA_NOT_DEFINED)

/* If the transfer module is DMAC, define a DMAC transfer callback. */
#include "r_dmac.h"
extern void spi_tx_dmac_callback(spi_instance_ctrl_t const * const p_ctrl);

void g_spi1_tx_transfer_callback (dmac_callback_args_t * p_args)
{
    FSP_PARAMETER_NOT_USED(p_args);
    spi_tx_dmac_callback(&g_spi1_ctrl);
}
#endif

#if (RA_NOT_DEFINED) != (RA_NOT_DEFINED)

/* If the transfer module is DMAC, define a DMAC transfer callback. */
#include "r_dmac.h"
extern void spi_rx_dmac_callback(spi_instance_ctrl_t const * const p_ctrl);

void g_spi1_rx_transfer_callback (dmac_callback_args_t * p_args)
{
    FSP_PARAMETER_NOT_USED(p_args);
    spi_rx_dmac_callback(&g_spi1_ctrl);
}
#endif
#undef RA_NOT_DEFINED

spi_instance_ctrl_t g_spi1_ctrl;

/** SPI extended configuration for SPI HAL driver */
const spi_extended_cfg_t g_spi1_ext_cfg = { .spi_clksyn = SPI_SSL_MODE_CLK_SYN,
		.spi_comm = SPI_COMMUNICATION_FULL_DUPLEX, .ssl_polarity = SPI_SSLP_LOW,
		.ssl_select = SPI_SSL_SELECT_SSL0, .mosi_idle =
				SPI_MOSI_IDLE_VALUE_FIXING_DISABLE, .parity =
				SPI_PARITY_MODE_DISABLE, .byte_swap = SPI_BYTE_SWAP_DISABLE,
		.spck_div = {
		/* Actual calculated bitrate: 12500000. */.spbr = 3, .brdv = 0 },
		.spck_delay = SPI_DELAY_COUNT_1,
		.ssl_negation_delay = SPI_DELAY_COUNT_1, .next_access_delay =
				SPI_DELAY_COUNT_1 };

/** SPI configuration for SPI HAL driver */
const spi_cfg_t g_spi1_cfg = { .channel = 1,

#if defined(VECTOR_NUMBER_SPI1_RXI)
    .rxi_irq             = VECTOR_NUMBER_SPI1_RXI,
#else
		.rxi_irq = FSP_INVALID_VECTOR,
#endif
#if defined(VECTOR_NUMBER_SPI1_TXI)
    .txi_irq             = VECTOR_NUMBER_SPI1_TXI,
#else
		.txi_irq = FSP_INVALID_VECTOR,
#endif
#if defined(VECTOR_NUMBER_SPI1_TEI)
    .tei_irq             = VECTOR_NUMBER_SPI1_TEI,
#else
		.tei_irq = FSP_INVALID_VECTOR,
#endif
#if defined(VECTOR_NUMBER_SPI1_ERI)
    .eri_irq             = VECTOR_NUMBER_SPI1_ERI,
#else
		.eri_irq = FSP_INVALID_VECTOR,
#endif

		.rxi_ipl = (12), .txi_ipl = (12), .tei_ipl = (12), .eri_ipl = (12),

		.operating_mode = SPI_MODE_SLAVE,

		.clk_phase = SPI_CLK_PHASE_EDGE_ODD, .clk_polarity =
				SPI_CLK_POLARITY_LOW,

		.mode_fault = SPI_MODE_FAULT_ERROR_DISABLE, .bit_order =
				SPI_BIT_ORDER_MSB_FIRST, .p_transfer_tx = g_spi1_P_TRANSFER_TX,
		.p_transfer_rx = g_spi1_P_TRANSFER_RX, .p_callback = spi_callback,

		.p_context = NULL, .p_extend = (void*) &g_spi1_ext_cfg, };

/* Instance structure to use this module. */
const spi_instance_t g_spi1 = { .p_ctrl = &g_spi1_ctrl, .p_cfg = &g_spi1_cfg,
		.p_api = &g_spi_on_spi };
iic_master_instance_ctrl_t g_i2c_master0_ctrl;
const iic_master_extended_cfg_t g_i2c_master0_extend =
		{ .timeout_mode = IIC_MASTER_TIMEOUT_MODE_SHORT, .timeout_scl_low =
				IIC_MASTER_TIMEOUT_SCL_LOW_ENABLED, .smbus_operation = 0,
				/* Actual calculated bitrate: 98425. Actual calculated duty cycle: 50%. */.clock_settings.brl_value =
						28, .clock_settings.brh_value = 28,
				.clock_settings.cks_value = 3, .clock_settings.sddl_value = 0,
				.clock_settings.dlcs_value = 0, };
const i2c_master_cfg_t g_i2c_master0_cfg = { .channel = 0, .rate =
		I2C_MASTER_RATE_STANDARD, .slave = 0x6f, .addr_mode =
		I2C_MASTER_ADDR_MODE_7BIT,
#define RA_NOT_DEFINED (1)
#if (RA_NOT_DEFINED == RA_NOT_DEFINED)
		.p_transfer_tx = NULL,
#else
                .p_transfer_tx       = &RA_NOT_DEFINED,
#endif
#if (RA_NOT_DEFINED == RA_NOT_DEFINED)
		.p_transfer_rx = NULL,
#else
                .p_transfer_rx       = &RA_NOT_DEFINED,
#endif
#undef RA_NOT_DEFINED
		.p_callback = iic_callback, .p_context = NULL,
#if defined(VECTOR_NUMBER_IIC0_RXI)
    .rxi_irq             = VECTOR_NUMBER_IIC0_RXI,
#else
		.rxi_irq = FSP_INVALID_VECTOR,
#endif
#if defined(VECTOR_NUMBER_IIC0_TXI)
    .txi_irq             = VECTOR_NUMBER_IIC0_TXI,
#else
		.txi_irq = FSP_INVALID_VECTOR,
#endif
#if defined(VECTOR_NUMBER_IIC0_TEI)
    .tei_irq             = VECTOR_NUMBER_IIC0_TEI,
#else
		.tei_irq = FSP_INVALID_VECTOR,
#endif
#if defined(VECTOR_NUMBER_IIC0_ERI)
    .eri_irq             = VECTOR_NUMBER_IIC0_ERI,
#else
		.eri_irq = FSP_INVALID_VECTOR,
#endif
		.ipl = (12), .p_extend = &g_i2c_master0_extend, };
/* Instance structure to use this module. */
const i2c_master_instance_t g_i2c_master0 = { .p_ctrl = &g_i2c_master0_ctrl,
		.p_cfg = &g_i2c_master0_cfg, .p_api = &g_i2c_master_on_iic };
void g_hal_init(void) {
	g_common_init();
}
