# HC-SR04 충돌 방지 OTA 시연 가이드

## 1. 시연 목적

동일한 RA6E1 듀얼뱅크 OTA 구조에서 다음 두 펌웨어의 기능 차이를 보여준다.

1. 업데이트 전: 전진 중 장애물이 있어도 계속 주행
2. 업데이트 후: HC-SR04가 전방 20 cm 이내 장애물을 감지하면 즉시 정지

업데이트 펌웨어는 장애물이 제거된 것을 3회 연속 확인한 뒤에만 전진 명령을 다시
허용한다. 후진은 장애물에서 빠져나오기 위해 항상 허용한다.

## 2. 기존 핀 사용 현황과 선정 결과

작업공간의 `KFC/configuration.xml`, `KFC/ra_cfg.txt`와 현재 펌웨어를 대조했다.

| 기능 | RA6E1 핀 | 상태 |
|---|---|---|
| ESP32 SPI MISO | P100 | 사용 중 |
| ESP32 SPI MOSI | P101 | 사용 중 |
| ESP32 SPI SCK | P102 | 사용 중 |
| PCA9685 I2C SCL | P400 | 사용 중 |
| PCA9685 I2C SDA | P401 | 사용 중 |
| ESP32 BUSY | P302 | 사용 중 |
| HC-SR04 TRIG | **P409 / Arduino D2** | 새로 사용 |
| HC-SR04 ECHO | **P104 / Arduino D3** | 새로 사용 |

P409와 P104는 기존 SPI, I2C, BUSY 및 모터 제어 코드에서 사용하지 않는다. 보드의
Arduino 호환 헤더에 D2/D3로 표시되어 있어 배선하기도 쉽다.

## 3. HC-SR04 배선

RA6E1과 센서의 전원을 끈 상태에서 연결한다.

| HC-SR04 | FPB-RA6E1 | 설명 |
|---|---|---|
| VCC | 5V | 센서 전원 |
| GND | GND | 공통 접지 |
| TRIG | Arduino D2 / P409 | 3.3V GPIO 출력, 직접 연결 |
| ECHO | 분압 회로를 거쳐 Arduino D3 / P104 | 3.3V GPIO 입력 |

HC-SR04의 ECHO는 5V이므로 RA6E1에 직접 연결하면 안 된다. 다음처럼 저항 두 개로
약 3.3V까지 낮춘다.

```text
HC-SR04 ECHO ---- 1 kΩ ----+---- RA6E1 D3 (P104)
                            |
                           2 kΩ
                            |
                           GND
```

센서 GND, RA6E1 GND, ESP32 GND는 반드시 공통이어야 한다.

## 4. FSP Pins 설정

코드가 부팅 시 `R_IOPORT_PinCfg()`로 핀을 다시 설정하므로 기존 FSP 설정에서도
동작한다. 그래도 e2 studio의 Pins 화면을 다음처럼 맞춰 두는 것을 권장한다.

| Pin | Symbolic Name | Mode | 초기값 |
|---|---|---|---|
| P409 | `HCSR04_TRIG` | Output mode | Low |
| P104 | `HCSR04_ECHO` | Input mode | - |

설정 후 `Generate Project Content`를 실행한다. 소스는 symbolic name에 의존하지 않고
`BSP_IO_PORT_04_PIN_09`, `BSP_IO_PORT_01_PIN_04`를 직접 사용하므로 이름이 달라도
컴파일할 수 있다.

## 5. 두 펌웨어의 소스 분리

OTA 시연 중 소스가 섞이지 않도록 두 버전은 별도 위치에 보관한다.

```text
OTA/
├── hal_entry.c                 # V1.0.0, 초음파 기능 없음
├── motorhat.c
├── motorhat.h
└── firmware_collision/
    ├── hal_entry.c             # V2.0.0, HC-SR04 충돌 방지 기능 있음
    ├── motorhat.c
    └── motorhat.h
```

기존 `OTA/hal_entry.c`, `OTA/motorhat.c`, `OTA/motorhat.h`는 수정 전 상태로 복원되어
있다. 충돌 방지 코드는 `OTA/firmware_collision` 안에만 존재한다.

## 6. 펌웨어 빌드

### 업데이트 전 펌웨어

e2 studio 프로젝트의 `src` 폴더에 다음 원본 파일을 복사한다.

```text
OTA/hal_entry.c
OTA/motorhat.c
OTA/motorhat.h
```

Clean 후 Build하고 생성된 바이너리를 `no_collision_v1.0.0.bin`으로 보관한다. 이
소스의 버전은 V1.0.0이며 HC-SR04 핀을 초기화하거나 측정하지 않는다.

### 업데이트 후 펌웨어

e2 studio 프로젝트의 `src` 폴더에 다음 세 파일을 덮어쓴다.

```text
OTA/firmware_collision/hal_entry.c
OTA/firmware_collision/motorhat.c
OTA/firmware_collision/motorhat.h
```

다시 Clean 후 Build하고 `collision_v2.0.0.bin`으로 보관한다. 이 소스의 버전은
V2.0.0이다. 파일을 바꾼 뒤 반드시 Clean Build해야 V1 오브젝트 파일이 섞이지 않는다.

## 7. 동작 원리

- DWT 사이클 카운터로 ECHO HIGH 펄스 폭을 측정한다.
- `거리(cm) = ECHO HIGH 시간(us) / 58` 공식을 사용한다.
- 센서는 약 60ms 간격으로 비차단 상태 머신에서 측정한다.
- RA6E1 SPI slave를 먼저 arm한 상태에서 센서를 검사하므로 새 SPI 명령이 없어도
  전진 중 충돌 감시가 계속된다.
- 20cm 이하에서는 `Release()`로 모터를 정지하고 장애물 상태를 latch한다.
- 28cm 이상을 3회 연속 측정해야 latch를 해제한다. 이 hysteresis로 경계 거리에서
  정지/출발이 반복되는 현상을 막는다.
- OTA가 시작되면 모터를 정지하고 센서 상태 머신을 중지하여 Flash 전송과 간섭하지
  않도록 한다.

V2의 `motorhat.c`에서만 I2C 함수에 있던 레지스터당 고정 50ms 지연을 제거했다. 이제 실제 I2C
완료 콜백을 기다린 직후 다음 작업을 수행하므로 충돌 감지 후 긴급 정지 지연이 크게
줄어든다. V1의 기존 `motorhat.c`는 변경하지 않았다.

## 8. 시험 순서

차량 바퀴가 공중에 뜬 상태에서 먼저 시험한다.

1. 전원을 켜고 센서 앞을 40cm 이상 비운다.
2. `go` 명령으로 바퀴가 전진하는지 확인한다.
3. 평평한 물체를 센서 정면에서 천천히 20cm 안으로 이동한다.
4. 모터가 자동으로 정지하는지 확인한다.
5. 물체를 둔 상태에서 다시 `go`를 보내도 전진하지 않는지 확인한다.
6. 물체를 30cm 이상 치우고 약 0.2초 기다린 뒤 `go`를 보낸다.
7. 다시 전진하는지 확인한다.
8. `back` 명령은 장애물 상태에서도 동작하는지 확인한다.
9. 바닥 주행 시험은 저속에서 시작해 실제 정지 거리를 측정한다.

## 9. 조정값

환경에 맞춰 `firmware_collision/hal_entry.c`의 값을 변경할 수 있다.

```c
#define COLLISION_STOP_DISTANCE_CM   20U
#define COLLISION_CLEAR_DISTANCE_CM  28U
#define ULTRASONIC_SAMPLE_PERIOD_US  60000U
```

실제 차량은 센서 측정 거리보다 관성으로 더 이동한다. 속도가 빠르면 정지 기준을
30~50cm로 늘려야 한다. 부드러운 천, 비스듬한 면, 매우 작은 물체는 초음파를 센서
방향으로 반사하지 않아 감지되지 않을 수 있으므로 이 기능을 실제 안전 인증 장치로
사용하면 안 된다.

## 10. 문제 해결

- 항상 0cm 또는 미감지: TRIG/ECHO가 바뀌지 않았는지, GND가 공통인지 확인한다.
- 가까운 장애물도 정지하지 않음: ECHO 분압 회로의 가운데 노드가 D3에 연결됐는지
  확인한다.
- 장애물이 없는데 정지: 센서를 차체나 바닥에서 약간 위로 향하게 하고 정지 거리를
  줄여 본다.
- `go`가 계속 차단됨: 장애물을 28cm 이상 치우고 3회 측정 시간(약 180ms) 이상
  기다린다.
- OTA가 실패함: 주행을 먼저 정지하고 OTA를 시작하며 SPI/BUSY 배선을 다시 확인한다.
