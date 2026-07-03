import os
import requests
import pyaudio
import wave

# 오디오 녹음 파라미터 설정 (교재 11페이지 기준)
FORMAT = pyaudio.paInt16 # 16bit [cite: 597]
CHANNELS = 1             # 모노 [cite: 598]
RATE = 16000             # 16kHz 샘플링 레이트 [cite: 583, 599]
CHUNK = 1024
RECORD_SECONDS = 3       # 테스트용 녹음 시간 (3초)
WAVE_OUTPUT_FILENAME = "/home/pi/test.wav"

def record_voice():
    """마이크로부터 소리를 입력받아 test.wav 파일로 저장합니다."""
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                    input=True, frames_per_buffer=CHUNK)

    print("\n🎤 [녹음 시작] 마이크에 대고 명령어를 말씀하세요 (3초)...")
    frames = []

    for _ in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
        data = stream.read(CHUNK)
        frames.append(data)

    print("🛑 [녹음 종료] 변환을 시작합니다.")

    stream.stop_stream()
    stream.close()
    p.terminate()

    # WAV 파일로 저장
    wf = wave.open(WAVE_OUTPUT_FILENAME, 'wb')
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(p.get_sample_size(FORMAT))
    wf.setframerate(RATE)
    wf.writeframes(b''.join(frames))
    wf.close()

def speech_to_text():
    """저장된 WAV 파일을 GMS Whisper API로 전송하여 텍스트로 변환합니다."""
    gms_key = os.getenv("GMS_KEY")
    if not gms_key:
        print("Error: GMS_KEY 환경 변수가 없습니다.")
        return

    url = "https://gms.ssafy.io/gmsapi/api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {gms_key}"}
    
    files = {"file": (os.path.basename(WAVE_OUTPUT_FILENAME), open(WAVE_OUTPUT_FILENAME, "rb"), "audio/wav")}
    data = {"model": "whisper-1", "language": "ko"}

    try:
        response = requests.post(url, headers=headers, files=files, data=data)
        files["file"][1].close()

        if response.status_code == 200:
            text_result = response.json().get("text", "")
            print("\n" + "="*50)
            print(f"[✔ 변환된 차량 제어 명령어] : {text_result}")
            print("="*50 + "\n")
            
            # 여기서 나중에 차량 제어 로직을 엮습니다.
            # if "앞으로" in text_result: go_forward()
            
        else:
            print(f"API 오류: {response.text}")
    except Exception as e:
        print(f"예외 발생: {e}")

if __name__ == "__main__":
    # 1. 마이크로 3초 녹음 수행
    record_voice()
    # 2. 녹음된 파일을 텍스트로 변환
    speech_to_text()
