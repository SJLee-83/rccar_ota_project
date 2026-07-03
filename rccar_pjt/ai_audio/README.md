# Raspberry Pi 5 AI Audio Assistant

SPH0645 I2S 마이크로 질문을 녹음하고, SSAFY GMS를 통해 STT → GPT 응답 →
`gpt-4o-mini-tts` 음성 합성을 수행한 뒤 라즈베리파이 스피커로 재생하는 Qt GUI입니다.

## 1. 동작 흐름

```text
SPH0645 → WAV 녹음 → Whisper STT → gpt-5.4-mini → gpt-4o-mini-tts → MP3 재생
```

- 음성 질문: 기본 5초 녹음 후 전체 과정을 자동 실행합니다.
- 텍스트 질문: 마이크 없이 GPT와 TTS 구간을 먼저 시험할 수 있습니다.
- API 호출은 OpenAI Python SDK 대신 GMS 프록시 주소에 `requests`로 직접 요청합니다.
- GMS 키는 소스가 아니라 `.env`에서만 읽습니다.

## 2. SPH0645 배선

전원을 끈 상태에서 아래와 같이 연결합니다. 표의 물리 핀 번호는 40핀 헤더 번호입니다.

| SPH0645 | Raspberry Pi 5 | 물리 핀 | 역할 |
|---|---|---:|---|
| `3V3` / `VIN` | 3.3 V | 1 | 전원 |
| `GND` | GND | 6 | 접지 |
| `BCLK` / `SCK` | GPIO18 / PCM_CLK | 12 | I2S 비트 클럭 |
| `LRCLK` / `WS` | GPIO19 / PCM_FS | 35 | I2S 워드 선택 |
| `DOUT` / `SD` | GPIO20 / PCM_DIN | 38 | 마이크 데이터 입력 |
| `SEL` / `L/R` | GND | 6 등 | Left 채널 선택 |

`SEL`을 3.3 V에 연결하면 Right 채널이 됩니다. 한 개만 사용할 때는 우선 GND에
연결합니다. SPH0645는 3.3 V 장치이므로 5 V 핀에 연결하면 안 됩니다.

라즈베리파이 5에는 3.5 mm 아날로그 오디오 단자가 없습니다. TTS 출력에는 USB
스피커/USB DAC, HDMI 오디오 또는 Bluetooth 스피커가 별도로 필요합니다.

## 3. Raspberry Pi OS에서 I2S 마이크 준비

Debian 13/Trixie 기반 Raspberry Pi OS의 설정 파일은 일반적으로
`/boot/firmware/config.txt`입니다. 다음 항목이 없으면 추가하고 재부팅합니다.

```ini
dtparam=i2s=on
dtoverlay=adau7002-simple
```

```bash
sudo nano /boot/firmware/config.txt
sudo reboot
```

중요: `dtparam=i2s=on`은 핀을 활성화할 뿐, 그 자체로 ALSA 녹음 장치를 만들지는
않습니다. Debian 13/Trixie의 Raspberry Pi 6.12 커널에서 제공하는
`adau7002-simple` overlay를 사용해 SPH0645와 호환되는 I2S 캡처 카드를 등록합니다.
인터넷의 오래된 Pi 3/4용 설치 스크립트를 Pi 5에 실행할 필요는 없습니다. 현재
이미지가 제공하는 overlay는 다음처럼 확인할 수 있습니다.

```bash
grep -i -E "i2s|mic|sph|adau" /boot/firmware/overlays/README
dtoverlay -h <확인한-overlay-이름>
```

overlay 설치 후 아래 명령에서 `card ... device ...` 형태의 캡처 장치가 보여야 다음
단계로 진행할 수 있습니다.

```bash
arecord -l
arecord -L
```

OS 이미지나 별도 HAT가 제공한 장치가 `card 1, device 0`이라면 다음처럼 원시 녹음을
검사합니다. 카드/장치 번호는 실제 출력에 맞춰 바꿉니다.

```bash
arecord -D plughw:1,0 -c 2 -r 48000 -f S32_LE -d 5 sph0645-test.wav
aplay sph0645-test.wav
```

이 단계에서 소리가 없으면 Python/API 문제가 아니라 배선, 채널(`SEL`), overlay 또는
ALSA 설정 문제입니다. 한쪽 채널만 잡히는 드라이버라면 `SEL`을 GND와 3.3 V 사이에서
바꾸고 다시 시험합니다.

## 4. 개발 PC에서 Raspberry Pi로 프로젝트 옮기기

새 라즈베리파이에는 `ai_audio` 폴더 전체를 옮기는 것이 가장 안전합니다. 실행에
필요한 파일은 다음과 같습니다.

```text
ai_audio/
├── app.py
├── config.py
├── gms_client.py
├── audio_recorder.py
├── audio_player.py
├── audio_devices.py
├── test_recording.py
├── requirements.txt
├── setup_pi.sh
├── .env.example
└── README.md
```

`day3-car.py`, `day3-arglass.py`, `gms_stt_client.py`는 기존 참고 코드이므로 함께
보관해도 되지만 현재 GUI 실행에는 필요하지 않습니다. `.venv`, `__pycache__`, WAV,
MP3 파일은 옮기지 말고 라즈베리파이에서 새로 생성합니다. 실제 키가 들어 있는
`.env`도 공유 PC나 Git을 통해 옮기지 않는 것을 권장합니다.

### 방법 A: Windows에서 SCP로 전송

먼저 Raspberry Pi에서 SSH를 활성화하고 IP를 확인합니다.

```bash
hostname -I
```

Windows PowerShell에서 다음 명령을 실행합니다. 사용자 이름과 IP는 실제 값으로
변경합니다.

```powershell
ssh pi@192.168.0.50 "mkdir -p /home/pi/pjt1"
scp -r "C:\Users\SSAFY\Desktop\관통pjt\ai_audio" pi@192.168.0.50:/home/pi/pjt1/
```

전송 후 Raspberry Pi에서 파일을 확인합니다.

```bash
cd ~/pjt1/ai_audio
ls -la
```

### 방법 B: USB 메모리로 전송

Windows에서 `ai_audio` 폴더를 USB에 복사한 뒤 Raspberry Pi에서 다음처럼 옮깁니다.
USB 마운트 경로와 이름은 실제 값으로 변경합니다.

```bash
mkdir -p ~/pjt1
cp -r "/media/$USER/USB이름/ai_audio" ~/pjt1/
cd ~/pjt1/ai_audio
```

### 방법 C: Git 저장소에서 받기

키가 들어 있는 `.env`를 커밋하지 않은 상태에서 저장소를 clone하고 이동합니다.

```bash
git clone <저장소-주소> ~/pjt1
cd ~/pjt1/ai_audio
```

### 전송 직후 정리

Windows에서 복사한 셸 스크립트는 줄바꿈 형식과 실행 권한을 정리합니다.

```bash
cd ~/pjt1/ai_audio
sed -i 's/\r$//' setup_pi.sh
chmod +x setup_pi.sh
```

필수 파일이 모두 있는지 확인합니다.

```bash
for file in app.py config.py gms_client.py audio_recorder.py audio_player.py \
  audio_devices.py test_recording.py requirements.txt setup_pi.sh .env.example; do
  test -f "$file" || echo "누락: $file"
done
```

아무 메시지도 나오지 않으면 필수 파일이 모두 복사된 것입니다.

## 5. 프로그램 설치

```bash
cd ~/pjt1/ai_audio
chmod +x setup_pi.sh
./setup_pi.sh
```

수동 설치가 필요하면 다음 패키지가 핵심입니다.

```bash
sudo apt install python3-venv python3-dev build-essential \
  portaudio19-dev libasound2-dev alsa-utils mpg123
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 6. GMS 및 오디오 설정

```bash
cp .env.example .env
nano .env
```

최소한 다음 값을 입력합니다.

```dotenv
GMS_KEY=발급받은_GMS_KEY
CHAT_MODEL=gpt-5.4-mini
```

`.env`는 라즈베리파이에서 새로 만들고 다음 권한으로 보호합니다.

```bash
chmod 600 .env
```

PyAudio가 인식한 입력 장치를 확인합니다.

```bash
source .venv/bin/activate
python audio_devices.py
```

출력에서 SPH0645 카드에 해당하는 번호가 `2`라면 `.env`를 다음처럼 수정합니다.

```dotenv
AUDIO_INPUT_DEVICE=2
AUDIO_CHANNELS=2
```

먼저 API 없이 녹음만 검사합니다.

```bash
python test_recording.py
aplay microphone_test.wav
```

출력 장치는 `aplay -l`로 확인합니다. `mpg123` 기본 출력이 원하는 스피커가 아닐 때만
`.env`의 `AUDIO_OUTPUT_DEVICE`에 `plughw:카드,장치`를 지정합니다.

## 7. GUI 실행

라즈베리파이 데스크톱 터미널에서 실행합니다.

```bash
cd ~/pjt1/ai_audio
source .venv/bin/activate
python app.py
```

1. 텍스트 질문으로 GPT 응답과 TTS 재생을 먼저 확인합니다.
2. `음성 질문`을 누르고 상태가 `마이크 녹음 중`일 때 질문합니다.
3. 녹음 시간이 지나면 인식 문장과 AI 답변이 GUI에 표시되고 MP3가 재생됩니다.

## 8. API 설정

기본 엔드포인트는 다음과 같습니다.

```text
https://gms.ssafy.io/gmsapi/api.openai.com/v1
```

사용 경로는 `/audio/transcriptions`, `/chat/completions`, `/audio/speech`입니다. TTS
요청은 다음 설정을 사용합니다.

```json
{
  "model": "gpt-4o-mini-tts",
  "input": "안녕하세요.",
  "voice": "nova",
  "response_format": "mp3"
}
```

OpenAI 원본 사용법은 [Text-to-Speech 가이드](https://platform.openai.com/docs/guides/text-to-speech)를
참고하되, 이 프로젝트에서는 주소 앞부분을 GMS 프록시로 바꾸고 OpenAI API 키 대신
GMS 키를 사용합니다.

SSAFY GMS의 기본 채팅 모델은 `gpt-5.4-mini`로 설정했습니다. 다른 채팅 모델을 시험할
때는 `.env`의 `CHAT_MODEL`만 변경하면 됩니다. 음성 답변은 비용과 지연 시간을 줄이기
위해 시스템 프롬프트에서 짧게 답하도록 설정했습니다.

## 9. 새 장치에서 권장하는 전체 실행 순서

파일을 새 Raspberry Pi로 옮긴 경우 다음 순서대로 하나씩 검사합니다.

1. SPH0645 배선 후 I2S overlay/driver를 설정합니다.
2. `arecord -l`에서 캡처 장치가 보이는지 확인합니다.
3. `arecord` 명령으로 API 없이 실제 음성을 녹음합니다.
4. `./setup_pi.sh`로 시스템 패키지와 Python 가상환경을 설치합니다.
5. `.env.example`을 `.env`로 복사하고 GMS 키를 입력합니다.
6. `python audio_devices.py`로 PyAudio 장치 번호를 확인합니다.
7. `python test_recording.py`로 Python 녹음을 확인합니다.
8. `python app.py`를 실행하고 텍스트 질문으로 GPT/TTS를 검사합니다.
9. 마지막으로 음성 질문 전체 흐름을 검사합니다.

문제가 생기면 바로 다음 단계로 넘어가지 말고 실패한 단계부터 해결해야 합니다.
특히 `arecord`가 실패하는 상태에서는 Python 패키지나 GMS API를 수정해도 마이크가
동작하지 않습니다.

## 10. 음성 명령 제어로 확장할 때

현재 `app.py`는 질문에 답하는 **대화형 음성 챗봇**입니다. 차량을 음성으로 제어하려면
STT 결과를 바로 차량에 보내지 않고 명령 해석과 검증 단계를 추가해야 합니다.

```text
음성 → STT → 규칙/AI 명령 해석 → 허용 명령 검증 → MQTT/WebSocket → 차량
                                                └→ TTS 실행 결과 안내
```

AI가 반환할 명령은 자유 문장 대신 다음과 같은 JSON으로 제한합니다.

```json
{
  "type": "vehicle_command",
  "command": "left",
  "duration_ms": 1000
}
```

실행 가능한 명령은 `go`, `back`, `left`, `right`, `stop`, `mid`처럼 코드에 등록한
화이트리스트만 허용해야 합니다. “왼쪽”, “좌회전”, “왼쪽으로 가” 같은 명확한 표현은
규칙 기반으로 먼저 처리하고, 규칙으로 해석하지 못한 문장만 AI에 전달하는 구성이
비용과 오동작을 줄일 수 있습니다. AI 출력 문자열을 검증 없이 GPIO, MQTT 또는
WebSocket 명령으로 직접 실행하면 안 됩니다.

## 11. 문제 해결

- `GMS_KEY가 없습니다`: `.env`가 `app.py`와 같은 폴더에 있는지 확인합니다.
- `Invalid input device`: `python audio_devices.py`를 다시 실행하고 장치 번호를
  수정합니다. 재부팅하면 번호가 바뀔 수 있습니다.
- `Invalid sample rate`: `.env`의 `AUDIO_RATE`를 ALSA 장치가 지원하는 48000으로
  맞추고, 필요하면 `plughw` 변환 장치를 기본 입력으로 구성합니다.
- 녹음은 되지만 무음: `SEL` 채널과 DOUT(GPIO20) 배선을 확인합니다.
- MP3가 재생되지 않음: `mpg123 answer.mp3`와 `speaker-test`로 출력 장치를 먼저
  검사합니다.
- HTTP 401/403: GMS 키, 키 만료 여부, GMS 포털의 모델 사용 권한을 확인합니다.
- GUI가 뜨지 않음: SSH만 사용 중이라면 X11 전달 또는 라즈베리파이 데스크톱 세션에서
  실행해야 합니다.

## 파일 구성

- `app.py`: PySide6 GUI와 백그라운드 작업 스레드
- `gms_client.py`: STT, GPT, TTS GMS API 클라이언트
- `audio_recorder.py`: PyAudio WAV 녹음
- `audio_player.py`: `mpg123` MP3 재생
- `audio_devices.py`: 입력 장치 목록 확인
- `test_recording.py`: API 없는 마이크 녹음 시험
- 기존 `gms_stt_client.py`, `day3-*.py`: 원본 참고 코드로 보존
