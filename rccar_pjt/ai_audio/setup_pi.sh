#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

sudo apt update
sudo apt install -y \
  python3-venv python3-dev build-essential \
  portaudio19-dev libasound2-dev alsa-utils mpg123

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo ".env 파일을 만들었습니다. GMS_KEY와 오디오 장치를 설정하세요."
fi

echo "설치 완료"
echo "1) source .venv/bin/activate"
echo "2) python audio_devices.py"
echo "3) python app.py"
