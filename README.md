# SDV 시대의 RC카 — 무선 OTA 업데이트와 AI 음성 제어

SSAFY 임베디드 트랙 15기 1학기 관통 PJT. 차량이 출고 후에도 소프트웨어 업데이트로 기능이 확장되는 **SDV(Software Defined Vehicle)** 개념을 RC카 규모로 구현했습니다.

- **무선 OTA 업데이트**: 제어 MCU에 무선 모듈이 없어도 게이트웨이(ESP32)를 통해 펌웨어를 무선 배포하고, 바뀐 펌웨어가 실제 주행 동작 변화로 이어지는 것을 시연
- **AI 음성 제어**: 사용자 음성을 차량 명령으로 변환하는 인포테인먼트 기능

---

## 시스템 아키텍처

```
[PC 관제 GUI]                    [Raspberry Pi 5]
 PySide6                          SPH0645 I2S 마이크
   │ MQTT                           │ STT→LLM→TTS
   ▼                                ▼
┌─────────────────────────────────────────┐
│        MQTT Broker (Mosquitto, 1883)     │
└─────────────────────────────────────────┘
   │ MQTT
   ▼
[ESP32 게이트웨이]
   │ SPI (Master) + BUSY GPIO 핸드셰이크
   ▼
[Renesas RA6E1 (SPI Slave)]
   │ Dual-Bank Code Flash 제어 → CRC32 검증 → BankSwap → Reset
   │ I2C
   ▼
[PCA9685 Motor HAT] → 서보(조향) + DC 모터(구동)
   +
[HC-SR04 초음파 센서] → 전방 충돌 감지
```

| 구간 | 프로토콜 | 용도 |
|------|----------|------|
| GUI ↔ Broker ↔ ESP32 | MQTT | OTA 데이터, RC 조종 명령, 상태 피드백 |
| ESP32 ↔ RA6E1 | SPI + BUSY GPIO | 펌웨어 청크 전달, 명령, 핸드셰이크 |
| RA6E1 ↔ Motor HAT | I2C | 서보·DC 모터 제어 |
| RA6E1 ↔ HC-SR04 | GPIO | 전방 거리 측정 |
| Pi5 ↔ GMS | HTTPS | STT / LLM / TTS |

---

## 주요 기능

### 1. 무선 OTA (Dual-Bank 방식, 최종 채택)

부트로더 없이 RA6E1 하드웨어의 Dual-Bank + BankSwap 기능으로 구현. 실행 중인 Active Bank가 새 펌웨어를 받아 반대쪽 Inactive Bank(alias `0x00200000`)에 기록하고, 검증 성공 시 `R_FLASH_HP_BankSwap()` + Reset으로 교체합니다.

- 256바이트 청크 전송, CRC32(metadata/청크/전체) 검증
- ARQ 재전송(NACK 0x1F, 최대 20회), Session ID, 바이너리 프로토콜
- 다운로드/검증 실패 시 Bank Swap을 하지 않으면 기존 펌웨어로 계속 동작

### 2. HC-SR04 충돌 회피 (OTA 가치 시연용)

OTA로 펌웨어를 바꾸면 기능이 생기는 것을 보여주는 시연 구성.
- **V1.0.0 (업데이트 전)**: 장애물 감지 없이 계속 주행
- **V2.0.0 (업데이트 후)**: 전방 20cm 장애물 감지 시 정지, 28cm 3회 확인 후 재출발(hysteresis)

### 3. AI 음성 제어

라즈베리파이 5 + SPH0645 I2S 마이크로 음성 캡처 → SSAFY GMS 프록시로 STT → LLM → TTS 파이프라인 실행.

---

## 저장소 구성

```
rccar_ota_project/
├── 1st_pjt_rccar_ota/    # RA6E1 애플리케이션 (모터/SPI/I2C 제어)
├── ra_mcuboot_rccar/     # MCUboot 부트로더 (개인 심화 방식)
├── rccar_pjt/            # 팀 통합 작업물
│   ├── OTA/              #   Dual-Bank OTA, ESP32 게이트웨이, 충돌회피
│   ├── ai_audio/         #   AI 음성 비서 (라즈베리파이)
│   └── 최종발표.pptx
├── docs/
│   └── 01_팀프로젝트_전체정리.md
└── README.md
```

---

## 팀원 간 역할 분배

### 박찬혁 — OTA 시스템 · AI 음성
- Dual-Bank OTA 수신·기록·BankSwap 구현 (최종 시연 채택)
- OTA 전송 프로토콜 설계 (256B 청크, CRC32 검증, ARQ 재전송)
- 기존 관제 GUI에 OTA 업로드 화면·진행률 대시보드 확장
- GMS 기반 STT·LLM·TTS AI 음성 기능

### 이승재 — RA6E1 펌웨어 · 무선 제어 체인
- PySide6 관제 GUI 및 MQTT 명령 발행 (주행 제어 기반 구현)
- ESP32 게이트웨이: MQTT 수신 → JSON 파싱 → SPI 1바이트 변환
- SPI Slave/BUSY 기반 차량 명령 수신 처리
- MotorHat(PCA9685) I2C 기반 주행·조향 제어
- HC-SR04 초음파 충돌 회피 펌웨어 작성
- 주행·센서 통합 테스트 및 시연 펌웨어 안정화
- MCUboot 부트로더 기반 OTA 방식 독립 시도 (별도 저장소)

> 무선 제어 체인(GUI → MQTT → ESP32 → SPI → 모터)을 이승재가 먼저 구축하고,
> 그 위에 박찬혁이 OTA 전송·Dual-Bank 기록과 AI 음성 기능을 확장했다.

---

## OTA 두 방식의 병행 시도

OTA는 두 접근을 병행 시도한 뒤 하나를 최종 채택했습니다. Dual-Bank는 완성되어 시연에 사용되었고, MCUboot는 슬롯 교체 검증까지 도달했으나 무선 전송을 완성하지 못했습니다.

| 항목 | Dual-Bank (박찬혁, 채택) | MCUboot (이승재) |
|------|------------------------|-----------------|
| 부트로더 | 없음 (앱이 직접 수행) | 있음 (MCUboot) |
| 검증 | CRC32 | ECDSA P-256 서명 |
| 무선 전송 | ✅ 완성 | ❌ (self-programming 벽) |
| 최종 시연 | ✅ 채택 | 미완성 |

**→ MCUboot 방식 상세 및 코드**: [rccar-mcuboot-ota](https://github.com/SJLee-83/rccar-mcuboot-ota)

자세한 프로젝트 정리는 [docs/01_팀프로젝트_전체정리.md](docs/01_팀프로젝트_전체정리.md)를 참고하세요.
