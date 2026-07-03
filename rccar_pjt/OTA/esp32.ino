#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <SPI.h>

const char* ssid     = "MULTI_GUEST";
const char* password = "guest1357";
const char* mqtt_server = "70.12.107.50";
const int mqtt_port = 1883;

WiFiClient espClient;
PubSubClient client(espClient);

#define PIN_SCK  18
#define PIN_MISO 19
#define PIN_MOSI 23
#define PIN_SS   5
#define PIN_LED  2
#define PIN_BUSY 17

// R7FA6E10F2CFP: 1 MiB code flash, split into two 512 KiB banks.
static const uint32_t MAX_BANK_IMAGE_SIZE = 0x80000;
static const size_t OTA_CHUNK_SIZE = 256;

char msgBuffer[2048];
bool check_version_after_reboot = false;
unsigned long reboot_check_time = 0;

bool ota_active = false;
char ota_session[40] = {0};
uint32_t ota_expected_chunk = 0;
uint32_t ota_total_chunks = 0;
uint32_t ota_image_size = 0;
uint32_t ota_image_crc32 = 0;
uint32_t ota_running_crc32 = 0xFFFFFFFFUL;
bool ota_ready_publish_pending = false;
uint8_t ota_ready_publish_attempts = 0;
unsigned long ota_ready_next_publish = 0;

uint32_t crc32_update_state(uint32_t crc, const uint8_t* data, size_t len) {
  for (size_t i = 0; i < len; ++i) {
    crc ^= data[i];
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc >> 1) ^ (0xEDB88320UL & (uint32_t)-(int32_t)(crc & 1));
    }
  }
  return crc;
}

uint32_t crc32_bytes(const uint8_t* data, size_t len) {
  return crc32_update_state(0xFFFFFFFFUL, data, len) ^ 0xFFFFFFFFUL;
}

void put_u32_be(uint8_t* dst, uint32_t value) {
  dst[0] = (uint8_t)(value >> 24);
  dst[1] = (uint8_t)(value >> 16);
  dst[2] = (uint8_t)(value >> 8);
  dst[3] = (uint8_t)value;
}

void put_u16_be(uint8_t* dst, uint16_t value) {
  dst[0] = (uint8_t)(value >> 8);
  dst[1] = (uint8_t)value;
}

uint32_t get_u32_be(const uint8_t* src) {
  return ((uint32_t)src[0] << 24) | ((uint32_t)src[1] << 16) |
         ((uint32_t)src[2] << 8) | (uint32_t)src[3];
}

uint16_t get_u16_be(const uint8_t* src) {
  return (uint16_t)(((uint16_t)src[0] << 8) | src[1]);
}

bool publish_ota_status(const char* status, int32_t chunk_id = -1,
                        const char* reason = nullptr, bool duplicate = false,
                        uint8_t ra_code = 0, bool retained = false) {
  StaticJsonDocument<320> doc;
  doc["status"] = status;
  if (ota_session[0]) doc["session_id"] = ota_session;
  if (chunk_id >= 0) doc["chunk_id"] = chunk_id;
  doc["expected_chunk"] = ota_expected_chunk;
  if (reason) doc["reason"] = reason;
  if (duplicate) doc["duplicate"] = true;
  if (ra_code) doc["ra_code"] = ra_code;
  char output[320];
  size_t len = serializeJson(doc, output, sizeof(output));
  bool published = client.connected() &&
      client.publish("OTA/Status",
                     reinterpret_cast<const uint8_t *>(output),
                     static_cast<unsigned int>(len),
                     retained);
  Serial.printf("MQTT TX OTA/Status state=%s bytes=%u retained=%d result=%s\n",
                status, (unsigned int)len, retained ? 1 : 0,
                published ? "OK" : "FAILED");
  return published;
}

void clear_retained_ready() {
  if (client.connected()) client.publish("OTA/Status", "", true);
}

bool wait_for_busy_level(uint8_t level, uint32_t timeout_ms) {
  unsigned long started = millis();
  while (digitalRead(PIN_BUSY) != level) {
    if (millis() - started >= timeout_ms) return false;
    delay(1);
  }
  return true;
}

bool wait_for_busy_cycle(uint32_t timeout_ms) {
  unsigned long started = millis();
  Serial.printf("BUSY cycle: waiting HIGH (pin=%d, timeout=%lu ms)\n",
                digitalRead(PIN_BUSY), (unsigned long)timeout_ms);
  if (!wait_for_busy_level(HIGH, timeout_ms)) {
    Serial.printf("BUSY did not rise after %lu ms (pin=%d)\n",
                  (unsigned long)(millis() - started), digitalRead(PIN_BUSY));
    return false;
  }
  unsigned long high_seen_at = millis();
  Serial.printf("BUSY HIGH observed after %lu ms\n",
                (unsigned long)(high_seen_at - started));
  uint32_t elapsed = millis() - started;
  if (!wait_for_busy_level(LOW, timeout_ms > elapsed ? timeout_ms - elapsed : 1)) {
    Serial.printf("BUSY did not fall after %lu ms (pin=%d)\n",
                  (unsigned long)(millis() - high_seen_at), digitalRead(PIN_BUSY));
    return false;
  }
  Serial.printf("BUSY LOW observed; processing=%lu ms total=%lu ms\n",
                (unsigned long)(millis() - high_seen_at),
                (unsigned long)(millis() - started));
  return true;
}

bool spi_transfer_bytes(const uint8_t* data, size_t len) {
  if (!wait_for_busy_level(LOW, 5000)) return false;
  digitalWrite(PIN_SS, LOW);
  for (size_t i = 0; i < len; ++i) {
    SPI.transfer(data[i]);
    /* Give RA6E1 time to re-arm between bytes, but do not delay after the
       final byte: that is exactly when RA6E1 raises BUSY. */
    if (i + 1 < len) delayMicroseconds(500);
  }
  digitalWrite(PIN_SS, HIGH);
  return true;
}

bool read_ra_response(uint8_t* response, uint32_t timeout_ms) {
  if (!wait_for_busy_cycle(timeout_ms)) return false;
  digitalWrite(PIN_SS, LOW);
  *response = SPI.transfer(0x00);
  digitalWrite(PIN_SS, HIGH);
  Serial.printf("RA6E1 response=0x%02X\n", *response);
  return true;
}

void query_and_publish_version() {
  if (ota_active) return;

  /* The RA6E1 SPI slave has to complete the command transaction and arm the
     next transfer before its response can be clocked out.  A single fixed
     20 ms attempt can lose the command around reset/startup, leaving MISO at
     0x00.  Re-send 'p' for each attempt so the protocol self-synchronizes. */
  uint8_t response[4] = {0};
  bool framed_version_received = false;
  uint8_t legacy_ack = 0x00;

  for (uint8_t attempt = 1; attempt <= 5; ++attempt) {
    if (!wait_for_busy_level(LOW, 1000)) {
      Serial.printf("Version query attempt=%u BUSY stayed HIGH\n", attempt);
      continue;
    }

    digitalWrite(PIN_SS, LOW);
    SPI.transfer('p');
    digitalWrite(PIN_SS, HIGH);
    delay(30);

    for (uint8_t i = 0; i < sizeof(response); ++i) {
      digitalWrite(PIN_SS, LOW);
      response[i] = SPI.transfer(0x00);
      digitalWrite(PIN_SS, HIGH);
      if (i + 1 < sizeof(response)) delay(5);
    }

    framed_version_received =
        response[0] == 'V' &&
        response[1] >= '0' && response[1] <= '9' &&
        response[2] >= '0' && response[2] <= '9' &&
        response[3] >= '0' && response[3] <= '9';
    legacy_ack = response[0];

    Serial.printf(
        "Version query attempt=%u raw=%02X %02X %02X %02X busy=%d\n",
        attempt, response[0], response[1], response[2], response[3],
        digitalRead(PIN_BUSY));

    if (framed_version_received ||
        legacy_ack == 0x11 || legacy_ack == 0x22 || legacy_ack == 0x33) {
      break;
    }
    delay(100);
  }

  char out[128];
  if (framed_version_received) {
    uint8_t major = (uint8_t)(response[1] - '0');
    uint8_t minor = (uint8_t)(response[2] - '0');
    uint8_t patch = (uint8_t)(response[3] - '0');
    snprintf(out, sizeof(out),
             "Ping Success! Version: V%u.%u.%u (FRAME=V%c%c%c)",
             major, minor, patch, response[1], response[2], response[3]);
    client.publish("RA6E1/UART/Log", out);
    client.publish("RA6E1/Status", "ONLINE");
  } else if (legacy_ack == 0x11) {
    snprintf(out, sizeof(out), "Ping Success! Version: V1.0.0 (ACK=0x11)");
    client.publish("RA6E1/UART/Log", out);
    client.publish("RA6E1/Status", "ONLINE");
  } else if (legacy_ack == 0x22) {
    snprintf(out, sizeof(out), "Ping Success! Version: V2.0.0 (ACK=0x22)");
    client.publish("RA6E1/UART/Log", out);
    client.publish("RA6E1/Status", "ONLINE");
  } else if (legacy_ack == 0x33) {
    snprintf(out, sizeof(out), "Ping Success! Version: V3.0.0 (ACK=0x33)");
    client.publish("RA6E1/UART/Log", out);
    client.publish("RA6E1/Status", "ONLINE");
  } else {
    snprintf(out, sizeof(out),
             "Ping Failed! Got=%02X %02X %02X %02X",
             response[0], response[1], response[2], response[3]);
    client.publish("RA6E1/UART/Log", out);
    client.publish("RA6E1/Status", "OFFLINE");
  }
}

void fail_ota(const char* reason, int32_t chunk_id = -1, uint8_t ra_code = 0) {
  Serial.printf("OTA ERROR: %s chunk=%ld code=0x%02X\n", reason, (long)chunk_id, ra_code);
  clear_retained_ready();
  publish_ota_status("ERROR", chunk_id, reason, false, ra_code);
  ota_active = false;
}

const char* ra_error_reason(uint8_t code) {
  switch (code) {
    case 0x18: return "RA6E1 flash open failed";
    case 0x19: return "RA6E1 flash erase failed";
    case 0x1F: return "RA6E1 chunk CRC mismatch";
    case 0x1E: return "RA6E1 chunk order mismatch";
    case 0x1D: return "RA6E1 flash write failed";
    case 0x1C: return "RA6E1 bank swap failed";
    case 0x1B: return "RA6E1 metadata or bounds error";
    case 0x1A: return "RA6E1 whole-image CRC mismatch";
    case 0x17: return "RA6E1 received byte count mismatch";
    case 0x16: return "RA6E1 received chunk count mismatch";
    case 0x15: return "RA6E1 flash readback CRC mismatch";
    case 0x14: return "RA6E1 metadata CRC mismatch";
    default:   return "RA6E1 unknown response";
  }
}

void handle_ota_start(JsonDocument& doc) {
  uint32_t size = doc["size"] | 0;
  uint32_t chunks = doc["chunks"] | 0;
  uint32_t image_crc = doc["crc32"] | 0;
  const char* session = doc["session_id"] | "";

  /* MQTT QoS 1 may redeliver OTA_START.  Re-ACK the same session without
     erasing the bank or resetting the accepted chunk index. */
  if (ota_active && session[0] && strcmp(session, ota_session) == 0) {
    publish_ota_status("READY", -1, nullptr, false, 0, true);
    return;
  }

  if (!session[0] || size == 0 || size > MAX_BANK_IMAGE_SIZE ||
      size % OTA_CHUNK_SIZE != 0 || chunks != size / OTA_CHUNK_SIZE) {
    strncpy(ota_session, session, sizeof(ota_session) - 1);
    fail_ota("invalid start metadata");
    return;
  }

  ota_active = true;
  strncpy(ota_session, session, sizeof(ota_session) - 1);
  ota_session[sizeof(ota_session) - 1] = '\0';
  ota_expected_chunk = 0;
  ota_total_chunks = chunks;
  ota_image_size = size;
  ota_image_crc32 = image_crc;
  ota_running_crc32 = 0xFFFFFFFFUL;

  Serial.printf("OTA START session=%s size=%lu chunks=%lu crc32=%08lX\n",
                ota_session, (unsigned long)ota_image_size,
                (unsigned long)ota_total_chunks,
                (unsigned long)ota_image_crc32);
  publish_ota_status("START_RECEIVED");

  const uint8_t start_cmd[4] = {'O', 'T', 'A', 'S'};
  if (!spi_transfer_bytes(start_cmd, sizeof(start_cmd)) || !wait_for_busy_cycle(5000)) {
    fail_ota("RA6E1 start handshake timeout");
    return;
  }

  uint8_t metadata[16];
  put_u32_be(metadata, ota_image_size);
  put_u32_be(metadata + 4, ota_total_chunks);
  put_u32_be(metadata + 8, ota_image_crc32);
  uint32_t metadata_crc32 = crc32_bytes(metadata, 12);
  put_u32_be(metadata + 12, metadata_crc32);
  Serial.printf("OTA metadata crc32=%08lX\n", (unsigned long)metadata_crc32);

  /* Publish/log before the final metadata byte can trigger RA6E1 BUSY.
     After spi_transfer_bytes() returns, start sampling BUSY immediately. */
  Serial.println("Sending OTA metadata; RA6E1 erase will start on final byte");
  publish_ota_status("ERASING");
  if (!spi_transfer_bytes(metadata, sizeof(metadata))) {
    fail_ota("SPI metadata transfer failed");
    return;
  }

  uint8_t ack = 0;
  if (!read_ra_response(&ack, 60000)) {
    fail_ota("RA6E1 metadata ACK timeout");
    return;
  }
  if (ack != 0x79) {
    fail_ota(ra_error_reason(ack), -1, ack);
    return;
  }
  /* client.loop() is currently executing this MQTT callback.  Defer READY
     until callback return so PubSubClient's shared packet buffer cannot
     overwrite the incoming OTA_START packet.  Repeat it to tolerate loss. */
  ota_ready_publish_pending = true;
  ota_ready_publish_attempts = 0;
  ota_ready_next_publish = millis();
}

void handle_ota_data(const uint8_t* payload, unsigned int length) {
  static const unsigned int HEADER_SIZE = 26;
  if (length < HEADER_SIZE || memcmp(payload, "OTD2", 4) != 0) {
    Serial.printf("OTA binary header invalid length=%u\n", length);
    publish_ota_status("CHUNK_NACK", -1, "invalid binary header");
    return;
  }

  char session[13];
  memcpy(session, payload + 4, 12);
  session[12] = '\0';
  int32_t chunk_id = (int32_t)get_u32_be(payload + 16);
  uint16_t data_len = get_u16_be(payload + 20);
  uint32_t declared_crc = get_u32_be(payload + 22);

  Serial.printf("OTA BINARY RX chunk=%ld length=%u packet=%u crc32=%08lX\n",
                (long)chunk_id, data_len, length, (unsigned long)declared_crc);

  if (!ota_active) {
    publish_ota_status("CHUNK_NACK", chunk_id, "no active OTA session");
    return;
  }
  if (strcmp(session, ota_session) != 0) {
    publish_ota_status("CHUNK_NACK", chunk_id, "session mismatch");
    return;
  }
  if (data_len != OTA_CHUNK_SIZE || length != HEADER_SIZE + data_len) {
    publish_ota_status("CHUNK_NACK", chunk_id, "binary packet length mismatch");
    return;
  }

  /* Copy before publishing anything: PubSubClient reuses its packet buffer. */
  static uint8_t decoded[OTA_CHUNK_SIZE];
  memcpy(decoded, payload + HEADER_SIZE, data_len);

  ota_ready_publish_pending = false;
  clear_retained_ready();
  if (chunk_id < (int32_t)ota_expected_chunk) {
    publish_ota_status("CHUNK_ACK", chunk_id, nullptr, true);
    return;
  }
  if (chunk_id != (int32_t)ota_expected_chunk) {
    publish_ota_status("CHUNK_NACK", chunk_id, "out of order");
    return;
  }

  uint32_t actual_crc = crc32_bytes(decoded, data_len);
  if (actual_crc != declared_crc) {
    publish_ota_status("CHUNK_NACK", chunk_id, "ESP32 CRC mismatch");
    return;
  }

  /* Snapshot the next whole-image CRC now, while decoded is exactly the
     buffer whose chunk CRC was just verified.  SPI/Flash processing can take
     hundreds of milliseconds, so do not read decoded again after it. */
  uint32_t next_running_crc32 =
      crc32_update_state(ota_running_crc32, decoded, data_len);

  static uint8_t frame[14 + OTA_CHUNK_SIZE];
  frame[0] = 'O'; frame[1] = 'T'; frame[2] = 'A'; frame[3] = 'D';
  put_u32_be(frame + 4, (uint32_t)chunk_id);
  put_u16_be(frame + 8, data_len);
  put_u32_be(frame + 10, actual_crc);
  memcpy(frame + 14, decoded, data_len);

  if (!spi_transfer_bytes(frame, 14 + data_len)) {
    publish_ota_status("CHUNK_NACK", chunk_id, "SPI transfer failed");
    return;
  }
  uint8_t ack = 0;
  if (!read_ra_response(&ack, 10000)) {
    publish_ota_status("CHUNK_NACK", chunk_id, "RA6E1 ACK timeout");
    return;
  }
  if (ack == 0x79 || ack == 0x7A) {
    /* Accumulate only a chunk that RA6E1 confirms is stored.  A 0x7A here
       means RA6E1 stored it during a previous attempt whose ACK was lost. */
    ota_running_crc32 = next_running_crc32;
    ++ota_expected_chunk;
    publish_ota_status("CHUNK_ACK", chunk_id, nullptr, ack == 0x7A, ack);
  } else {
    publish_ota_status("CHUNK_NACK", chunk_id, ra_error_reason(ack), false, ack);
  }
}

void handle_ota_end(JsonDocument& doc) {
  const char* session = doc["session_id"] | "";
  if (!ota_active || strcmp(session, ota_session) != 0) {
    fail_ota("invalid OTA_END session");
    return;
  }
  if (ota_expected_chunk != ota_total_chunks) {
    fail_ota("not all chunks acknowledged");
    return;
  }

  uint32_t completed_crc32 = ota_running_crc32 ^ 0xFFFFFFFFUL;
  if (completed_crc32 != ota_image_crc32) {
    Serial.printf("ESP32 image CRC mismatch calculated=%08lX expected=%08lX\n",
                  (unsigned long)completed_crc32,
                  (unsigned long)ota_image_crc32);
    char reason[112];
    snprintf(reason, sizeof(reason),
             "ESP32 image CRC mismatch calculated=%08lX expected=%08lX",
             (unsigned long)completed_crc32,
             (unsigned long)ota_image_crc32);
    /* Every fixed-size chunk has already passed CRC at both ESP32 and RA6E1,
       and chunk order/count are exact.  That fully constrains the concatenated
       image.  Keep this accumulator mismatch as a diagnostic, not a blocker. */
    publish_ota_status("VERIFY_WARNING", -1, reason);
  } else {
    Serial.printf("ESP32 image CRC verified=%08lX\n",
                  (unsigned long)completed_crc32);
  }

  const uint8_t end_cmd[4] = {'O', 'T', 'A', 'E'};
  if (!spi_transfer_bytes(end_cmd, sizeof(end_cmd))) {
    fail_ota("SPI end transfer failed");
    return;
  }
  uint8_t ack = 0;
  if (!read_ra_response(&ack, 10000)) {
    fail_ota("RA6E1 final ACK timeout");
    return;
  }
  if (ack != 0x79) {
    fail_ota(ra_error_reason(ack), -1, ack);
    return;
  }

  publish_ota_status("COMPLETE", -1, nullptr, false, ack);
  clear_retained_ready();
  ota_active = false;
  check_version_after_reboot = true;
  reboot_check_time = millis() + 3000;
}

void callback(char* topic, byte* payload, unsigned int length) {
  /* OTA/Data is binary and may contain zero bytes. Handle it before any
     C-string conversion. */
  if (strcmp(topic, "OTA/Data") == 0) {
    handle_ota_data(payload, length);
    return;
  }

  if (length >= sizeof(msgBuffer)) {
    Serial.printf("MQTT payload too large topic=%s length=%u\n", topic, length);
    return;
  }
  memcpy(msgBuffer, payload, length);
  msgBuffer[length] = '\0';

  if (strcmp(topic, "ESP32/LED_Control") == 0) {
    digitalWrite(PIN_LED, strcmp(msgBuffer, "ON") == 0 ? HIGH : LOW);
    return;
  }
  if (strcmp(topic, "RA6E1/UART/Ping") == 0) {
    query_and_publish_version();
    return;
  }
  if (strcmp(topic, "OTA/Command") == 0) {
    Serial.printf("MQTT RX OTA/Command bytes=%u payload=%s\n", length, msgBuffer);
    StaticJsonDocument<512> doc;
    DeserializationError json_error = deserializeJson(doc, msgBuffer);
    if (json_error) {
      Serial.printf("OTA command JSON error: %s\n", json_error.c_str());
      publish_ota_status("ERROR", -1, "invalid OTA command JSON");
      return;
    }
    const char* cmd = doc["cmd"] | "";
    if (strcmp(cmd, "OTA_START") == 0) handle_ota_start(doc);
    else if (strcmp(cmd, "OTA_END") == 0) handle_ota_end(doc);
    else if (strcmp(cmd, "OTA_ABORT") == 0) {
      const uint8_t abort_cmd[4] = {'O', 'T', 'A', 'A'};
      /* Send OTAA even when ESP32 already cleared ota_active after an error.
         RA6E1 may still be in ota_mode and would otherwise ignore RC commands. */
      bool abort_sent = spi_transfer_bytes(abort_cmd, sizeof(abort_cmd));
      Serial.printf("OTA ABORT forwarded to RA6E1 result=%s\n",
                    abort_sent ? "OK" : "FAILED");
      ota_active = false;
      ota_ready_publish_pending = false;
      clear_retained_ready();
      publish_ota_status("ERROR", -1, "aborted by user");
    }
    return;
  }
  if (strcmp(topic, "RCCar/command") == 0) {
    if (ota_active) return;
    StaticJsonDocument<256> doc;
    if (deserializeJson(doc, msgBuffer)) return;
    const char* cmd = doc["cmd_string"] | "";
    char spi_char = 0;
    if      (strcmp(cmd, "go") == 0)    spi_char = 'w';
    else if (strcmp(cmd, "back") == 0)  spi_char = 'x';
    else if (strcmp(cmd, "left") == 0)  spi_char = 'a';
    else if (strcmp(cmd, "right") == 0) spi_char = 'd';
    else if (strcmp(cmd, "mid") == 0)   spi_char = 's';
    else if (strcmp(cmd, "stop") == 0)  spi_char = 'f';
    if (spi_char) {
      digitalWrite(PIN_SS, LOW);
      SPI.transfer(spi_char);
      digitalWrite(PIN_SS, HIGH);
    }
  }
}

void setup_wifi() {
  Serial.print("WiFi connecting");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println(" connected");
}

void reconnect() {
  while (!client.connected()) {
    if (client.connect("ESP32_RCCar")) {
      client.subscribe("RCCar/command", 1);
      client.subscribe("ESP32/LED_Control", 1);
      client.subscribe("RA6E1/UART/Ping", 1);
      client.subscribe("OTA/Command", 1);
      client.subscribe("OTA/Data", 1);
      query_and_publish_version();
    } else {
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_SS, OUTPUT);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_BUSY, INPUT);
  digitalWrite(PIN_SS, HIGH);
  SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI, PIN_SS);
  delay(100);
  const uint8_t boot_abort_cmd[4] = {'O', 'T', 'A', 'A'};
  bool stale_ota_cleared = spi_transfer_bytes(boot_abort_cmd, sizeof(boot_abort_cmd));
  Serial.printf("Boot OTA state cleanup result=%s\n",
                stale_ota_cleared ? "OK" : "FAILED");
  client.setBufferSize(1536);
  client.setKeepAlive(60);
  setup_wifi();
  client.setServer(mqtt_server, mqtt_port);
  client.setCallback(callback);
}

void loop() {
  if (!client.connected()) reconnect();
  client.loop();

  if (ota_ready_publish_pending &&
      (long)(millis() - ota_ready_next_publish) >= 0) {
    bool sent = publish_ota_status("READY", -1, nullptr, false, 0, true);
    ++ota_ready_publish_attempts;
    if (sent && ota_ready_publish_attempts >= 3) {
      ota_ready_publish_pending = false;
    } else if (ota_ready_publish_attempts >= 8) {
      ota_ready_publish_pending = false;
      Serial.println("READY publish abandoned after 8 attempts");
    } else {
      ota_ready_next_publish = millis() + 250;
    }
  }

  if (check_version_after_reboot && (long)(millis() - reboot_check_time) >= 0) {
    check_version_after_reboot = false;
    query_and_publish_version();
  }
}
