# RA6E1 RC카 Dual-Bank OTA 구현 및 디버깅 기록

## 1. 문서 목적

이 문서는 PC GUI에서 펌웨어를 선택하여 MQTT, ESP32, SPI를 거쳐 RA6E1의 비활성 코드 플래시 뱅크에 기록하고, 검증 후 Bank Swap하는 기능을 구현하면서 진행한 작업과 문제 해결 과정을 시간순으로 정리한다.

최종 수정일: 2026-06-24

현재 주요 파일은 다음과 같다.

| 역할 | 파일 |
|---|---|
| PC GUI 및 OTA 송신 | `OTA/mainwindow.py` |
| PySide6 UI | `OTA/ui_form.py` |
| MQTT-SPI 게이트웨이 | `OTA/esp32.ino` |
| RA6E1 OTA 수신 및 Flash 제어 | `OTA/hal_entry.c` |

---

## 2. 개발 환경

### PC

- Windows
- Python 3.10.11
- PySide6 6.11.1
- paho-mqtt 2.1.0
- MQTT Broker: Mosquitto, TCP 1883

### MCU 및 통신

- RA6E1: `R7FA6E10F2CFP`, Code Flash 1 MiB
- ESP32: Wi-Fi 및 MQTT 게이트웨이
- GUI → ESP32: MQTT
- ESP32 → RA6E1: SPI
- RA6E1 → ESP32 상태 표시: BUSY GPIO
- RA6E1 모터 제어: I2C Motor HAT

### RA6E1 Dual-Bank 설정

- 전체 Code Flash: 1 MiB
- 뱅크당 크기: 512 KiB (`0x80000`)
- 실행 뱅크: `0x00000000`에 매핑
- 반대 뱅크 접근용 FSP 주소: `0x00200000`
- FSP Configuration에서 Dual Bank와 Code Flash Programming을 활성화해야 한다.

---

## 3. 최종 데이터 흐름

```text
Firmware .bin
    ↓
PySide6 GUI
    ↓ MQTT: OTA/Command, OTA/Data
ESP32
    ↓ SPI: OTAS / metadata / OTAD / OTAE
RA6E1 inactive Flash bank
    ↓ CRC32 검증
Bank Swap
    ↓ Reset
새 펌웨어 실행
```

OTA가 진행되는 동안 GUI의 RC 제어 버튼을 비활성화하고 ESP32와 RA6E1도 일반 RC 명령을 처리하지 않는다.

### 3.1 부트로더 없는 Dual-Bank OTA의 핵심 원리

일반적인 OTA 시스템은 MCU가 Reset되면 먼저 별도의 부트로더가 실행되고, 부트로더가 새 펌웨어의 유효성을 확인한 뒤 애플리케이션으로 점프한다. 이 프로젝트는 별도의 부트로더 영역이나 점프 코드를 만들지 않고 RA6E1이 하드웨어로 제공하는 Dual-Bank Code Flash와 시작 뱅크 선택 기능을 사용한다.

즉, 현재 실행 중인 애플리케이션 자체가 다음 펌웨어를 받아 반대쪽 뱅크에 기록하는 업데이트 프로그램 역할도 수행한다.

```text
별도 부트로더 방식

Reset → Bootloader → 이미지 선택/검증 → Application으로 Jump


현재 프로젝트 방식

Reset → 하드웨어가 선택된 뱅크를 0x00000000에 매핑
      → Application이 바로 실행됨
      → 실행 중인 Application이 반대 뱅크를 업데이트함
```

### 3.2 두 뱅크의 역할

RA6E1의 1 MiB Code Flash를 Dual-Bank 모드로 설정하면 512 KiB씩 두 영역으로 나누어 사용할 수 있다.

한쪽은 현재 실행 중인 Active Bank이고 다른 쪽은 업데이트 대상인 Inactive Bank다.

| 논리 주소 | 실행 중 역할 |
|---|---|
| `0x00000000` | 현재 선택된 Active Bank가 매핑되어 CPU가 실행하는 영역 |
| `0x00200000` | 반대쪽 Inactive Bank에 접근하기 위한 FSP Dual-Bank alias |

CPU는 Reset 후 항상 `0x00000000`의 Vector Table에서 초기 Stack Pointer와 Reset Handler를 읽는다. Bank Swap은 CPU가 다른 주소의 프로그램으로 직접 점프하는 동작이 아니라, 다음 Reset부터 어느 물리 뱅크가 `0x00000000`에 나타날지를 변경하는 동작이다.

따라서 OTA용 `.bin`도 현재 펌웨어와 마찬가지로 실행 시작 주소 `0x00000000`을 기준으로 링크해야 한다. 새 이미지가 Inactive Bank의 alias인 `0x00200000`에 기록되어 있어도 Bank Swap과 Reset 후에는 하드웨어가 그 뱅크를 `0x00000000`에 매핑하므로 정상적인 Vector Table과 절대 주소를 사용할 수 있다.

### 3.3 업데이트가 가능한 이유

실행 중인 Code Flash 영역을 Erase하거나 덮어쓰면 CPU가 더 이상 명령을 읽을 수 없으므로 시스템이 멈출 수 있다. Dual-Bank 방식은 현재 실행 중인 Active Bank를 건드리지 않고 반대쪽 Inactive Bank만 Erase하고 기록한다.

```text
업데이트 전

Active Bank   : 현재 펌웨어 실행 및 OTA 수신 코드 동작
Inactive Bank : 이전 이미지 또는 빈 영역


업데이트 중

Active Bank   : 계속 실행되며 MQTT/SPI/Flash 절차 제어
Inactive Bank : Erase → 새 펌웨어 청크 기록


업데이트 후

Active Bank   : 기존 정상 펌웨어가 그대로 남아 있음
Inactive Bank : 새 펌웨어와 Vector Table 저장 완료
```

이 구조 덕분에 다운로드나 CRC 검증이 실패해도 Bank Swap을 수행하지 않으면 기존 Active Bank에서 계속 실행할 수 있다.

### 3.4 실제 OTA 실행 순서

1. GUI가 펌웨어 크기, 청크 수, 전체 CRC32를 포함한 `OTA_START`를 보낸다.
2. ESP32가 SPI로 `OTAS`와 16바이트 Metadata를 전달한다.
3. RA6E1이 Metadata CRC와 이미지 범위를 검사한다.
4. RA6E1이 `0x00200000`의 필요한 Flash 블록만 Erase한다.
5. GUI가 256바이트 청크를 한 개씩 전송한다.
6. ESP32가 각 청크를 `OTAD` SPI 프레임으로 변환한다.
7. RA6E1이 청크 순서와 CRC를 확인하고 Inactive Bank에 기록한다.
8. Flash 기록이 성공한 청크에만 ACK를 반환한다.
9. 모든 청크가 끝나면 GUI가 `OTAE`를 보낸다.
10. RA6E1이 크기, 청크 수와 검증된 청크들로 계산한 전체 Running CRC를 확인한다.
11. 모든 검증이 성공했을 때만 `R_FLASH_HP_BankSwap()`을 호출한다.
12. `NVIC_SystemReset()`으로 MCU를 Reset한다.
13. Reset 후 하드웨어가 새 뱅크를 `0x00000000`에 매핑한다.
14. CPU가 새 펌웨어의 Vector Table을 읽고 새 버전을 실행한다.

### 3.5 연속 업데이트 시 뱅크 교대

Bank Swap 후에는 조금 전까지 Inactive였던 새 뱅크가 Active Bank가 되고, 이전 펌웨어가 있던 뱅크가 Inactive Bank가 된다. 다음 OTA에서도 다시 `0x00200000` alias를 통해 현재 실행 뱅크의 반대편을 갱신하고 Bank Swap한다.

```text
최초 상태 : Bank A 실행 / Bank B 업데이트 대상
첫 OTA    : Bank B 기록 → Swap → Bank B 실행
두 번째 OTA: Bank A 기록 → Swap → Bank A 실행
세 번째 OTA: Bank B 기록 → Swap → Bank B 실행
```

따라서 OTA를 여러 번 수행하면 두 뱅크가 번갈아 Active가 된다. 애플리케이션이 현재 물리 뱅크를 직접 추측하여 고정 주소를 선택하는 대신 FSP Dual-Bank alias와 `R_FLASH_HP_BankSwap()`을 사용하는 이유가 여기에 있다.

### 3.6 부트로더 방식과 비교

| 항목 | 별도 부트로더 | 현재 Dual-Bank 애플리케이션 방식 |
|---|---|---|
| Reset 직후 실행 | 부트로더 | 선택된 뱅크의 애플리케이션 |
| 새 이미지 기록 담당 | 부트로더 또는 애플리케이션 | 현재 실행 중인 애플리케이션 |
| 애플리케이션 점프 코드 | 필요 | 불필요 |
| 별도 Boot 영역 | 필요할 수 있음 | 사용하지 않음 |
| 뱅크 선택 | 부트로더 로직 | RA6E1 하드웨어/FSP Bank Swap |
| 구현 복잡도 | 상대적으로 높음 | 비교적 단순함 |
| 손상 이미지 자동 복구 | 부트로더 정책으로 구현 가능 | 별도 복구 로직이 없으면 제한적 |

### 3.7 이 방식의 안전 조건과 한계

부트로더가 없다고 해서 검증 절차가 없어도 되는 것은 아니다. 오히려 Bank Swap 전 검증이 마지막 안전선이다.

반드시 지켜야 하는 조건은 다음과 같다.

- 전체 이미지는 한 뱅크 크기인 512 KiB를 넘으면 안 된다.
- 새 이미지는 `0x00000000` 기준으로 링크된 유효한 RA6E1 애플리케이션이어야 한다.
- Vector Table의 초기 Stack Pointer와 Reset Handler가 정상이어야 한다.
- Metadata CRC, 각 청크 CRC와 전체 Streaming CRC가 모두 성공해야 한다.
- 검증이 하나라도 실패하면 `R_FLASH_HP_BankSwap()`을 호출하면 안 된다.
- 새 펌웨어에도 OTA 수신 코드가 포함되어 있어야 다음 OTA를 수행할 수 있다.
- 새 펌웨어가 부팅 직후 멈추거나 SPI를 초기화하지 못하면 애플리케이션만으로 원격 복구하기 어렵다.

현재 구조는 새 이미지가 정상적으로 기록되었는지는 확인하지만, 새 이미지가 실제로 부팅하여 일정 시간 정상 동작하는지 확인한 뒤 자동 롤백하는 기능은 아직 없다. 새 뱅크가 부팅되지 않으면 e2 studio 디버거로 정상 펌웨어를 직접 기록해야 할 수 있다.

향후 안전성을 더 높이려면 다음 기능을 추가할 수 있다.

- 새 펌웨어의 첫 부팅 성공 플래그
- 일정 시간 내 Heartbeat가 없을 때 이전 뱅크로 롤백
- Firmware Header에 MCU 종류, 버전, 빌드 번호, 이미지 크기 저장
- 서명 검증을 통한 승인된 펌웨어만 실행
- Bank Swap 전 Vector Table 값 검사

---

## 4. 구현 과정 및 문제 해결 기록

## 4.1 초기 OTA 구조 구현

초기 구현 목표는 다음과 같았다.

1. GUI에서 `.bin` 파일 선택
2. 펌웨어를 256바이트 청크로 분할
3. MQTT를 통해 ESP32로 전송
4. ESP32가 청크를 SPI로 RA6E1에 전달
5. RA6E1이 비활성 뱅크를 Erase하고 펌웨어 기록
6. 전체 데이터 검증 후 Bank Swap 및 Reset

GUI는 원본 파일 마지막 부분을 `0xFF`로 패딩하여 항상 256바이트 배수로 만든다. CRC32와 파일 크기는 패딩된 최종 데이터를 기준으로 계산한다.

---

## 4.2 SPI 수신 동기화 및 RC카 오작동

### 증상

- OTA 데이터 전송 중 RC카가 임의로 움직임
- `OTAS`, `OTAD`, `OTAE` 명령이 정상적으로 인식되지 않음
- 수신 바이트가 중복되거나 누락됨

### 원인

RA6E1이 SPI 전송 완료를 기다리지 않고 수신 버퍼를 처리하면서 이전 바이트를 반복해서 읽었다. 펌웨어 바이너리 안에 우연히 포함된 `w`, `a`, `s`, `d` 등이 일반 RC 명령으로 처리될 가능성도 있었다.

### 수정

- `spi_callback()`에서 `SPI_EVENT_TRANSFER_COMPLETE` 확인
- `R_SPI_WriteRead()` 호출 후 `spi_transfer_complete`가 설정될 때까지 대기
- `ota_mode`가 활성화된 동안 일반 RC 명령 처리 차단
- OTA 진입 시 `Release()`를 호출하여 모터 정지

---

## 4.3 RA6E1 Flash 주소 및 Erase 범위 수정

### 증상

- Metadata ACK timeout
- Flash erase 실패
- 전체 뱅크 Erase로 인한 긴 대기

### 원인

RA6E1 Dual-Bank 모드의 반대 뱅크는 일반적인 `0x00080000`이 아니라 FSP가 제공하는 `0x00200000` alias를 통해 접근해야 한다.

또한 512 KiB 전체를 매번 지울 필요가 없는데도 전체 영역을 Erase하면 BUSY 시간이 불필요하게 길어진다.

### 수정

```c
#define OTA_BANK_ADDRESS      0x00200000UL
#define OTA_BANK_SIZE         0x00080000UL
```

수신한 이미지 크기에 맞춰 필요한 블록만 Erase하도록 변경했다.

- 처음 64 KiB: 8 KiB 블록
- 이후 영역: 32 KiB 블록

예를 들어 약 15 KiB 펌웨어는 8 KiB 블록 2개만 Erase한다.

---

## 4.4 BUSY HIGH 신호를 놓치는 문제

### 증상

```text
BUSY cycle: waiting HIGH
BUSY did not rise after 60000 ms
RA6E1 metadata ACK timeout
```

### 원인

RA6E1이 마지막 Metadata 바이트를 받은 직후 BUSY를 HIGH로 올렸지만 ESP32가 SPI 함수 종료, 로그 출력 또는 MQTT Publish를 수행한 뒤 BUSY를 확인했다. 짧은 HIGH 펄스가 그 사이에 종료되면 ESP32는 신호를 보지 못한다.

### 수정

- ESP32는 마지막 SPI 바이트 직후 즉시 BUSY 감시 시작
- 마지막 바이트 뒤의 불필요한 `delayMicroseconds()` 제거
- RA6E1은 BUSY HIGH를 최소 20 ms 유지
- ACK 데이터를 먼저 SPI에 등록한 뒤 BUSY를 LOW로 내림

현재 응답 순서는 다음과 같다.

```text
RA6E1: BUSY HIGH
RA6E1: Flash 작업 및 ACK SPI 등록
RA6E1: BUSY LOW
ESP32: ACK를 읽기 위한 SPI clock 제공
```

---

## 4.5 READY가 세 번 출력된 뒤 진행되지 않는 문제

### 증상

ESP32 시리얼에는 다음 로그가 출력되지만 GUI는 첫 청크를 보내지 않았다.

```text
MQTT TX OTA/Status state=READY result=OK
MQTT TX OTA/Status state=READY result=OK
MQTT TX OTA/Status state=READY result=OK
```

### 확인 결과

- ESP32의 MQTT Publish는 성공함
- GUI의 MQTT 구독 자체는 성공함
- `MQTT subscription confirmed: OTA/Status` 확인

### 원인 및 수정

GUI의 RC `STOP` 버튼이 차량 정지만 수행해야 하는데 MQTT 네트워크 루프까지 `loop_stop()`으로 종료하고 있었다. 이 때문에 이후 `OTA/Status`를 수신하지 못할 수 있었다.

다음과 같이 정리했다.

- RC STOP은 `stop` 명령만 MQTT로 전송
- MQTT loop는 GUI가 종료될 때만 중지
- MQTT 연결 시 `on_connect()` 안에서 즉시 구독
- `on_subscribe()`에서 SUBACK 확인
- GUI MQTT Client ID를 실행마다 고유하게 생성
- `OTA/Status` 구독 확인 전에는 OTA 시작 불가

READY는 유실에 대비해 ESP32가 retained 메시지로 최대 3회 전송하며, 첫 청크 수신 시 retained READY를 삭제한다. GUI는 retained 메시지 삭제용 빈 Payload를 무시한다.

---

## 4.6 JSON/Base64 청크 데이터 손실

### 증상

```text
invalid chunk length
missing base64 data
```

GUI는 분명 256바이트를 전송했지만 ESP32의 ArduinoJson 문서에서 `data` 문자열이 누락되거나 길이가 정상적으로 해석되지 않았다.

### 원인

256바이트 데이터는 Base64 변환 후 약 344바이트가 되고 JSON 필드와 기타 Metadata까지 합치면 ArduinoJson 메모리와 PubSubClient 패킷 버퍼 사용이 복잡해졌다. MQTT 콜백 버퍼가 Publish 과정에서 재사용될 가능성도 있었다.

### 수정: Binary OTA/Data v2

GUI → ESP32 구간의 `OTA/Data`를 JSON/Base64에서 고정 Binary Packet으로 변경했다.

| Offset | 크기 | 필드 |
|---:|---:|---|
| 0 | 4 | Magic `OTD2` |
| 4 | 12 | Session ID ASCII |
| 16 | 4 | Chunk ID, Big Endian |
| 20 | 2 | Data Length, Big Endian |
| 22 | 4 | Chunk CRC32, Big Endian |
| 26 | 256 | Firmware Data |

총 MQTT Payload 크기는 282바이트이다.

ESP32는 `OTA/Data`를 C 문자열로 변환하기 전에 Binary로 처리한다. MQTT 패킷 버퍼 재사용의 영향을 피하기 위해 데이터 256바이트를 별도 정적 버퍼에 먼저 복사한다.

ESP32 → RA6E1 구간은 다음 SPI 프레임을 사용한다.

| Offset | 크기 | 필드 |
|---:|---:|---|
| 0 | 4 | Magic `OTAD` |
| 4 | 4 | Chunk ID |
| 8 | 2 | Payload Length |
| 10 | 4 | Chunk CRC32 |
| 14 | 256 | Firmware Data |

---

## 4.7 무선 환경의 재전송 정책

초기에는 같은 청크가 5회 실패하면 OTA를 중단했다. Wi-Fi와 MQTT 환경을 고려해 현재는 같은 청크의 연속 실패를 최대 20회까지 허용한다.

중요한 점은 누적 실패 횟수가 아니라 같은 청크의 연속 실패 횟수라는 것이다.

- 청크 ACK 수신: `chunk_retries = 0`
- 다음 청크로 진행
- 진행이 있는 전송은 과거 Retry 때문에 중단되지 않음
- 동일 청크가 계속 실패할 때만 최종 중단

청크 크기는 1바이트가 아니라 256바이트를 유지한다. 1바이트 단위 MQTT 전송은 Header와 ACK 오버헤드가 지나치게 커지며, 현재 구조는 256바이트 단위 CRC/ACK/Retry로 데이터 무결성을 보장한다.

---

## 4.8 전체 이미지 CRC mismatch

### 증상

```text
ACK chunk=62 (63/63)
All chunks ACKed by RA6E1
RA6E1 whole-image CRC mismatch
```

모든 청크가 개별 ACK되었는데 최종 CRC에서 실패했다.

### 분석

개별 청크 CRC가 모두 정상이라는 것은 GUI → ESP32 → RA6E1의 청크 전송 자체는 동작했다는 의미이다. 그러나 초기 Metadata는 크기, 청크 수, 이미지 CRC32의 12바이트만 전송하며 자체 무결성 검증이 없었다.

Metadata의 이미지 CRC 필드가 잘못 수신되면 모든 청크가 정상이어도 마지막 비교에서 실패할 수 있다.

### 수정

Metadata를 16바이트로 확장했다.

| Offset | 크기 | 필드 |
|---:|---:|---|
| 0 | 4 | Image Size |
| 4 | 4 | Total Chunks |
| 8 | 4 | Image CRC32 |
| 12 | 4 | 앞 12바이트의 Metadata CRC32 |

RA6E1은 Metadata CRC가 맞을 때만 Flash를 Erase한다.

OTA 종료 시 다음 항목을 각각 검사한다.

1. Flash 작업 오류 여부
2. 수신 바이트 수
3. 수신 청크 수
4. 수신 데이터 기반 Running CRC32
5. 모든 검증 성공 후에만 `R_FLASH_HP_BankSwap()` 실행

---

## 4.9 OTA 실패 후 RC 제어가 되지 않는 문제

### 원인

GUI에서 timeout이 발생해 UI만 OTA 종료 상태가 되어도 ESP32의 `ota_active` 또는 RA6E1의 `ota_mode`가 남아 있을 수 있었다. 이 경우 RC 명령이 계속 차단된다.

### 수정

- GUI timeout/error 시 `OTA_ABORT` 전송
- ESP32는 자신의 `ota_active` 상태와 무관하게 `OTAA`를 RA6E1에 전달
- RA6E1은 `OTAA` 수신 시 `ota_mode = false`
- ESP32 부팅 시에도 stale OTA 상태를 정리하기 위해 `OTAA` 전송
- 종료 후 GUI RC 제어 버튼 복구

---

## 4.10 세 자리 펌웨어 버전 및 PING 문제

### 변경 내용

초기에는 `0x11`, `0x22`, `0x33` 한 바이트를 각각 V1.0.0, V2.0.0, V3.0.0으로 간주했다. 이 방식은 세부 버전을 독립적으로 표현할 수 없고 값의 의미도 불명확했다.

현재는 RA6E1에서 세 개의 단일 숫자를 각각 지정한다.

```c
#define FW_VERSION_MAJOR 1U
#define FW_VERSION_MINOR 2U
#define FW_VERSION_PATCH 3U
```

위 설정은 SPI에서 ASCII 프레임 `V123`으로 응답하며 ESP32가 `V1.2.3`으로 변환하여 GUI에 전달한다. 각 항목은 현재 한 자리 숫자인 0~9를 지원한다.

또한 RC 명령 `d`의 동작을 테스트 목적으로 `Right()`에서 `Left()`로 변경했다.

### 증상

```text
Ping Failed! Got=0x00
RA6E1 Board Offline
```

### 확인 내용

기존 ESP32 코드는 `0x11`과 `0x22`만 정상 버전으로 인정했다. 중간 단계에서는 `0x33` 지원을 추가했고, 최종적으로는 `Vabc` 4바이트 프레임을 읽도록 변경했다. 기존 펌웨어 복구를 위해 `0x11`, `0x22`, `0x33` 한 바이트 응답도 계속 인식한다.

그러나 실제 수신값이 `0x33`이 아니라 `0x00`이었다. `0x00`은 버전 판정 문제가 아니라 RA6E1에서 MISO 응답이 나오지 않았다는 뜻이다.

기존 PING은 아래와 같이 한 번만 시도했다.

```text
'p' 전송 → 20 ms 대기 → 응답 1회 읽기
```

RA6E1 Reset 직후 SPI Slave가 아직 다음 전송을 등록하지 못하면 명령 또는 응답을 놓칠 수 있으므로 다음과 같이 수정했다.

- BUSY LOW 확인
- `'p'` 전송
- 30 ms 대기
- `Vabc` 4바이트 응답 읽기
- 실패 시 최대 5회 전체 과정 재시도
- 각 시도마다 응답과 BUSY 상태를 시리얼에 출력

정상 로그 예시는 다음과 같다.

```text
Version query attempt=1 raw=56 31 32 33 busy=0
Ping Success! Version: V1.2.3 (FRAME=V123)
```

5회 모두 `0x00`이면 단순 표시 문제가 아니다. 새 뱅크의 프로그램이 실행되지 않거나 SPI 초기화가 완료되지 않은 상태이므로 e2 studio 디버거로 RA6E1에 정상 펌웨어를 직접 기록한 뒤 다시 확인해야 한다.

### 구 버전 값 표기 주의

`0x11`, `0x22`, `0x33`은 기존 프로젝트가 임의로 정한 값이다. 이를 BCD 형태로 해석하면 각각 1.1, 2.2, 3.3처럼 보이지만 ESP32에서는 V1.0.0, V2.0.0, V3.0.0을 의미하도록 사용하고 있다.

새로 빌드하는 모든 펌웨어는 `FW_VERSION_MAJOR`, `FW_VERSION_MINOR`, `FW_VERSION_PATCH`와 `Vabc` 응답 코드를 사용해야 한다.

---

## 4.11 두 번째 OTA가 진행되지 않는 문제

### 증상

- V1.0.0에서 V2.0.0으로 첫 OTA는 성공
- V2.0.0 실행 후 V1.0.0 또는 V3.0.0으로 두 번째 OTA가 진행되지 않음

### Dual-Bank 주소 동작

RA6E1 Dual-Bank 모드에서 FSP의 `BSP_FEATURE_FLASH_HP_CF_DUAL_BANK_START`는 현재 실행 주소 `0x00000000`과 반대편에 매핑된 뱅크에 접근하는 alias다.

현재 코드는 다음처럼 대상 주소를 FSP 상수로 사용한다.

```c
#define OTA_BANK_ADDRESS BSP_FEATURE_FLASH_HP_CF_DUAL_BANK_START
```

OTA 완료 시 `R_FLASH_HP_BankSwap()`은 `0x00000000`과 반대 뱅크의 매핑을 토글한다. 따라서 동일 코드를 사용하는 한 별도로 Bank 0/1을 계산하지 않아도 다음 순서로 동작한다.

```text
V1 실행 뱅크 → 반대 뱅크에 V2 기록 → Swap → V2 실행
V2 실행 뱅크 → 반대 뱅크에 V3 기록 → Swap → V3 실행
V3 실행 뱅크 → 반대 뱅크에 V1 기록 → Swap → V1 실행
```

### 실제 핵심 원인

부트로더가 없기 때문에 첫 OTA로 올라간 V2 애플리케이션이 다음 OTA도 직접 수행해야 한다. V2 `.bin`이 예전 `hal_entry.c`로 빌드되었거나 최신 Metadata/청크 프로토콜을 포함하지 않으면 V2 부팅 후 두 번째 OTA가 실패한다.

즉, V1에만 최신 OTA 코드가 있고 V2/V3가 단순 동작 테스트용 예전 이미지라면 핑퐁 업데이트가 유지되지 않는다.

### 적용 조건

- V1, V2, V3 모두 동일한 최신 `hal_entry.c`를 사용한다.
- 버전 매크로와 테스트 동작만 버전별로 바꾼다.
- 세 이미지 모두 16바이트 Metadata, `OTAD`, 청크/전체 CRC 코드를 포함한다.
- 세 이미지 모두 Dual-Bank가 활성화된 같은 FSP 프로젝트와 링커 설정으로 빌드한다.
- 이전 버전의 `.bin`을 재사용하지 말고 최신 공통 OTA 코드를 적용한 뒤 전부 다시 빌드한다.

이 조건을 지키면 현재 `OTA_BANK_ADDRESS`와 `R_FLASH_HP_BankSwap()` 조합이 핑퐁 구조로 동작한다.

---

## 4.12 두 번째 OTA의 전체 CRC 문제와 최종 수정

### 재현 로그 분석

V1.0.0에서 V1.2.0으로 첫 업데이트한 뒤 `right.bin` 또는 `abc.bin`을 전송하면 64개 청크가 모두 ACK되지만 마지막에 `whole-image CRC mismatch`가 발생했다.

실제 `.bin`과 로그를 대조한 결과는 다음과 같았다.

- GUI가 표시한 전체 CRC가 선택한 패딩 이미지 CRC와 일치
- 로그의 각 청크 CRC가 실제 `.bin`의 해당 256바이트 CRC와 일치
- `left.bin`과 `right.bin`의 차이는 버전/동작 관련 3바이트뿐
- 실패 지점은 Flash Readback 전에 RAM의 `running_crc32`를 비교하는 단계

따라서 MQTT와 SPI 데이터가 잘못된 것이 아니라, 실행 뱅크가 바뀐 다음 세션에서 RAM Streaming CRC가 전체 이미지 검증을 조기에 중단시키는 문제로 판단했다.

### 첫 번째 수정과 추가 문제

처음에는 `0x00200000`을 일반 포인터로 직접 읽은 Flash Readback CRC를 최종 기준으로 변경했다. 하지만 실제 테스트에서 `abc.bin`으로 직접 부팅한 직후 `left.bin`을 처음 업데이트할 때부터 모든 청크가 일치함에도 `0x15 Flash readback CRC mismatch`가 발생했다.

이 결과로 FSP의 Dual-Bank Erase/Write 주소인 `0x00200000`을 현재 보드에서 일반 메모리 포인터로 읽은 값을 그대로 검증 CRC에 사용하는 방법은 적합하지 않음을 확인했다.

### 1차 수정 후 재현

Flash P/E 진입 전에 RA6E1 Running CRC를 계산하도록 순서를 바꾼 새 기준 펌웨어를 유선 기록한 후에도 `0x1A`가 재현되었다. 반면 새 로그의 모든 청크 CRC를 실제 `left.bin`, `right.bin`과 자동 대조한 결과 불일치 청크는 0개였다.

각 청크는 Flash 쓰기 전에 이미 다음 검사를 통과한다.

1. 청크 길이 256바이트
2. 청크 순서
3. 청크 CRC32

### 최종 수정: 전체 누적 CRC를 비차단 진단으로 변경

ESP32는 GUI가 보낸 각 Binary 청크를 직접 CRC 검사하고, RA6E1이 `0x79` 또는 `0x7A`로 저장 완료를 확인한 청크만 순서대로 누적한다. 그러나 이 전역 누적값도 실제 파일과 다르게 나오는 현상이 재현되어 차단 조건이 아니라 진단값으로 변경했다.

모든 청크는 256바이트로 길이가 같고 다음 값이 청크마다 일치한다.

- GUI가 원본 파일에서 계산한 청크 CRC
- ESP32가 MQTT 수신 데이터로 다시 계산한 CRC
- RA6E1이 SPI 수신 데이터로 다시 계산한 CRC
- 청크 ID와 전체 청크 순서

고정 길이의 모든 청크 CRC와 순서가 일치하면 CRC 결합 특성상 연결된 전체 이미지도 동일하다. 따라서 별도의 전역 누적 CRC는 중복 검사이며, 이 상태값 이상으로 정상 이미지를 반복 차단하면 안 된다.

```text
GUI: 전체 이미지 CRC 및 각 청크 CRC 생성
  ↓
ESP32: 실제 청크 CRC 검사 → RA6E1 전달
  ↓
RA6E1: 청크 CRC/순서/범위 검사 → Flash Write → ACK
  ↓
ESP32: ACK된 청크만 전체 CRC에 누적
  ↓
ESP32: 전체 누적 CRC 기록(불일치 시 VERIFY_WARNING)
       청크 검증이 모두 성공했으면 OTAE 전송
  ↓
RA6E1: 바이트 수/청크 수 확인 → Bank Swap
```

RA6E1에서 검증하는 항목:

- 청크별 실제 CRC32
- 청크 순서
- 전체 바이트 수
- 전체 청크 수
- Flash API Write 성공

ESP32에서 추가로 검증하는 항목:

- GUI → ESP32 청크 CRC32
- RA6E1이 저장 완료한 청크들의 전체 이미지 CRC32

이 구조는 문제가 반복된 RA6E1/ESP32 전역 Running CRC 상태에 의존하지 않는다. 누적 CRC가 다르면 계산값과 예상값을 `VERIFY_WARNING`으로 남기지만 OTA를 중단하지 않는다. 실제 차단 조건은 각 청크 CRC, 순서, 개수, 바이트 수와 Flash API 성공 여부다.

### 기존 보드 복구 시 주의

이미 보드에서 실행 중인 `abc.bin`이 직접 포인터 기반 Flash Readback 코드를 포함하고 있다면 PC의 소스만 수정해도 실행 중인 펌웨어는 바뀌지 않는다. 이 펌웨어는 새 `left.bin`과 `right.bin`의 모든 청크를 정상 수신한 뒤에도 마지막에 `0x15`로 거부한다.

따라서 이 수정 이후 최초 한 번은 다음 순서가 필요하다.

1. 수정된 최신 공통 OTA 코드에 V1.0.0 설정을 적용하여 `abc.bin` 재빌드
2. e2 studio 디버거로 새 `abc.bin`을 RA6E1에 직접 기록
3. 같은 공통 코드에서 버전/동작만 바꿔 `left.bin`, `right.bin`을 모두 재빌드
4. `abc → left → right → abc` 순서로 OTA 핑퐁 테스트

기존에 생성한 세 바이너리는 최신 수정 전 코드를 포함할 수 있으므로 파일 이름만 유지한 채 재사용하면 안 된다. ESP32 코드에도 전체 CRC 누적 변경이 있으므로 ESP32 역시 다시 업로드하고, 빌드 시각과 CRC를 다시 확인해야 한다.

---

## 5. 현재 OTA 프로토콜

## 5.1 MQTT Topic

| Topic | 방향 | 용도 |
|---|---|---|
| `OTA/Command` | GUI → ESP32 | `OTA_START`, `OTA_END`, `OTA_ABORT` |
| `OTA/Data` | GUI → ESP32 | Binary Chunk Packet |
| `OTA/Status` | ESP32 → GUI | READY, ACK, ERROR, COMPLETE |
| `RCCar/command` | GUI → ESP32 | RC카 조작 |
| `RA6E1/UART/Ping` | GUI → ESP32 | RA6E1 버전 확인 요청 |
| `RA6E1/UART/Log` | ESP32 → GUI | PING 결과 및 버전 로그 |
| `RA6E1/Status` | ESP32 → GUI | ONLINE/OFFLINE |

## 5.2 SPI 명령

| 명령 | 의미 |
|---|---|
| `OTAS` | OTA 세션 시작 |
| `OTAD` | 청크 데이터 프레임 시작 |
| `OTAE` | 전체 전송 종료 및 검증 요청 |
| `OTAA` | OTA 취소 |
| `p` | 펌웨어 버전 조회 |

PING 응답은 `Vabc` 4바이트 ASCII 프레임이다. 예를 들어 `V203`은 GUI에서 V2.0.3으로 표시된다.

## 5.3 RA6E1 응답 코드

| 코드 | 의미 |
|---:|---|
| `0x79` | 정상 ACK |
| `0x7A` | 이미 기록된 중복 청크 ACK |
| `0x1F` | 청크 길이 또는 CRC 오류 |
| `0x1E` | 청크 순서 오류 |
| `0x1D` | Flash Write 오류 |
| `0x1C` | Bank Swap 오류 |
| `0x1B` | Metadata 또는 이미지 범위 오류 |
| `0x1A` | 전체 이미지 Running CRC 오류 |
| `0x19` | Flash Erase 오류 |
| `0x18` | Flash Open 오류 |
| `0x17` | 전체 수신 바이트 수 불일치 |
| `0x16` | 전체 수신 청크 수 불일치 |
| `0x15` | 실험적 Flash Readback 검사에서 사용했던 코드(현재 미사용) |
| `0x14` | Metadata CRC 불일치 |

---

## 6. 현재 권장 빌드 및 테스트 순서

### 6.1 소스 일치 확인

RA6E1의 실제 e2 studio 빌드 파일과 `OTA/hal_entry.c`가 서로 다른 복사본일 수 있으므로 먼저 내용을 일치시켜야 한다.

실제 RA 프로젝트에서 확인할 대표 경로:

```text
C:\Users\SSAFY\e2_studio\workspace\pjt3\src\hal_entry.c
```

GUI를 다른 폴더에서 실행한다면 `mainwindow.py`와 `ui_form.py`도 최신 파일인지 확인한다.

### 6.2 최초 복구 및 기준 펌웨어 기록

1. e2 studio 프로젝트의 Dual Bank 설정 확인
2. 최신 `hal_entry.c` 적용
3. 프로젝트 Clean/Build
4. 디버거로 RA6E1에 기준 펌웨어 직접 Flash
5. ESP32 최신 스케치 업로드
6. 전원 재인가
7. PING으로 기준 버전 확인

### 6.3 OTA용 펌웨어 생성

1. 실제 e2 studio 프로젝트에서 원하는 버전 및 동작 수정
2. 같은 프로젝트를 다시 빌드
3. 생성된 `.bin`의 수정 시각 확인
4. GUI에서 해당 `.bin` 선택
5. GUI에 표시되는 패딩 후 크기, 청크 수, CRC32 기록

### 6.4 OTA 실행 중 기대 순서

```text
START_RECEIVED
BUSY HIGH → LOW
ERASING
RA6E1 response=0x79
READY
CHUNK_ACK 0 ... N
OTAE
전체 Streaming CRC 검증
Bank Swap
COMPLETE
RA6E1 Reset
PING 새 버전 확인
```

---

## 7. 장애 발생 시 확인 순서

### READY 이후 진행하지 않을 때

1. GUI 콘솔에서 `MQTT RX topic=OTA/Status` 확인
2. `MQTT subscription confirmed: OTA/Status` 확인
3. RC STOP 버튼이 MQTT loop를 종료하지 않는지 확인
4. GUI가 실제로 최신 `mainwindow.py`를 실행 중인지 확인

### Chunk 0에서 반복 실패할 때

1. GUI가 Binary `OTD2` Packet을 전송하는지 확인
2. ESP32 시리얼의 `OTA BINARY RX` 확인
3. Packet 길이가 282인지 확인
4. Session ID와 Chunk CRC 확인

### Metadata ACK timeout일 때

1. BUSY가 HIGH로 올라오는지 확인
2. Metadata가 12바이트 구버전이 아닌 16바이트인지 확인
3. ESP32와 RA6E1이 동일한 Metadata 프로토콜을 사용하는지 확인
4. P302 ↔ GPIO17 배선 확인

### 전체 CRC 오류일 때

1. 현재 코드의 전체 CRC 오류 `0x1A`인지 확인
2. GUI의 패딩 후 CRC와 ESP32 START 로그 CRC 비교
3. ESP32 Metadata CRC 로그 확인
4. 모든 구성요소가 같은 세션과 같은 `.bin`을 사용하는지 확인

### PING이 계속 `0x00`일 때

1. ESP32 시리얼에서 5회의 Version query 결과 확인
2. BUSY가 계속 HIGH인지 확인
3. RA6E1 Reset 또는 전원 재인가
4. SPI MISO, MOSI, SCK, GND 배선 확인
5. e2 studio 디버거로 기준 펌웨어 직접 재기록

---

## 8. 현재 상태 및 남은 검증

### 완료된 항목

- [x] GUI 펌웨어 선택, 패딩, CRC32 계산
- [x] MQTT START/DATA/END/ABORT 흐름
- [x] Binary `OTD2` 청크 전송
- [x] 청크 단위 CRC32 및 Stop-and-Wait ACK
- [x] 중복 청크 처리
- [x] BUSY 기반 Flash 작업 동기화
- [x] 크기 기반 Flash Erase
- [x] Metadata CRC32
- [x] Flash P/E 진입 전에 검증된 버퍼로 전체 Streaming CRC 계산
- [x] OTA 실패 시 상태 정리 및 RC 제어 복구
- [x] MQTT SUBACK 확인 및 고유 Client ID
- [x] `Vabc` 세 자리 버전 프레임 및 구버전 ACK 호환
- [x] PING 최대 5회 재동기화
- [x] FSP 반대 뱅크 alias 기반 핑퐁 대상 지정

### 추가 확인이 필요한 항목

- [ ] `Vabc` 펌웨어 Bank Swap 후 실제 부팅 및 PING 성공 확인
- [ ] V1 → V2 → V3처럼 연속 두 번 이상의 Bank Swap 검증
- [ ] OTA 중 Wi-Fi 단절 후 청크 재전송 검증
- [ ] OTA 중 전원 차단 시 기존 뱅크 부팅 여부 확인
- [ ] 오류 코드별 GUI 표시 검증
- [ ] 버전 프로토콜을 `0x01/0x02/0x03`으로 변경할지 결정

---

## 9. 핵심 교훈

1. MQTT Publish 성공은 GUI가 메시지를 처리했다는 뜻이 아니다. SUBACK과 실제 RX 로그를 함께 확인해야 한다.
2. SPI Flash 작업에서는 데이터뿐 아니라 처리 가능 시점을 BUSY/ACK로 명확히 동기화해야 한다.
3. 청크 CRC만으로는 부족하다. Metadata CRC와 전체 이미지 Streaming CRC도 함께 확인해야 한다.
4. GUI, ESP32, RA6E1 중 하나만 프로토콜을 바꾸면 통신이 깨진다. 세 구성요소의 버전을 함께 관리해야 한다.
5. 소스 파일을 여러 폴더에 복사해 사용하면 수정한 파일과 실제 빌드한 파일이 달라질 수 있다. 빌드 경로와 `.bin` 수정 시각을 항상 확인해야 한다.
6. Bank Swap 직전 검증 실패는 정상적인 안전 동작이다. 검증 실패 상태에서 새 뱅크로 부팅하는 것보다 업데이트를 중단하는 것이 맞다.
