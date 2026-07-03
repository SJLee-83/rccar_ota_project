# -*- coding: utf-8 -*-
# SSAFY 8 embedded proj.
# day 3. AR glass (GMS Whisper API + 오타 수정본)

from PIL import Image, ImageDraw, ImageFont
import board
import digitalio
import adafruit_ssd1306
from datetime import datetime, timedelta, timezone
import RPi.GPIO as GPIO
import pyaudio
import wave
import requests
import os
import queue
import threading    
import asyncio
import websockets
import time

# SSL 인증서 건너뛰기 시 터미널에 불필요한 경고창이 도배되는 것을 방지
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# .env 파일을 사용할 경우를 위해 라이브러리 로드
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("[INFO] .env 파일이 존재하여 환경 변수를 로드했습니다.")
except ImportError:
    pass

print("[1] 시스템 환경 설정 및 초기화 시작...")
disp_width, disp_height = 64, 128 
oled_reset = digitalio.DigitalInOut(board.D24)
oled_cs = digitalio.DigitalInOut(board.D8)
oled_dc = digitalio.DigitalInOut(board.D25)
TimeZone = timezone(timedelta(hours=+9)) 

# 라즈베리파이 한글 폰트 예외 처리
try:
    font_small = ImageFont.truetype('NanumGothic.ttf', 13) 
    font_big = ImageFont.truetype('NanumGothic.ttf', 22)
    print("[INFO] NanumGothic 폰트를 성공적으로 불러왔습니다.")
except IOError:
    font_small = ImageFont.load_default()
    font_big = ImageFont.load_default()
    print("[WARN] NanumGothic 폰트가 없어 기본 시스템 폰트로 대체합니다.")

MODE_BUTTON, ACT_BUTTON = 12, 16 

# 차량 라즈베리파이의 핫스팟 IP 주소 설정
serverURI = 'ws://192.168.137.235:7890'

# 차량 매칭용 마스터 명령어 리스트
CAR_COMMANDS = ['앞으로', '뒤로', '정지', '빠르게', '느리게', '오른쪽', '왼쪽', '중앙']

mode_list = []
mode_index = 0
current_mode = None

# 모드 추상클래스
class Mode():
    def __init__(self):
        self.screenImage = Image.new('1', (disp_width, disp_height), 0) 
        self.draw = ImageDraw.Draw(self.screenImage) 

    def whenActivated(self):
        pass

    def getCurrentTime(self):
        return datetime.now(TimeZone)

    def update(self):
        self.draw.rectangle((0,0,disp_width,disp_height), fill = 0) 

    def getTextCenterAlignXY(self, text, font):
        try:
            w, h = self.draw.textsize(text, font=font)
        except AttributeError:
            bbox = self.draw.textbbox((0, 0), text, font=font)
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        centerX = (disp_width - w) // 2
        centerY = (disp_height - h) // 2
        return (centerX, centerY)

    def textMultiliner(self, text, font):
        text_multiline = '' 
        if text != '':
            for character in text:
                text_multiline += character
                try:
                    w = self.draw.textsize(text_multiline, font=font)[0]
                except AttributeError:
                    bbox = self.draw.textbbox((0, 0), text_multiline, font=font)
                    w = bbox[2] - bbox[0]
                if w >= disp_width:
                    text_multiline = text_multiline[:-1] + '\n' + text_multiline[-1] 
        return text_multiline

    def modeButtonPressed(self):
        pass

    def actButtonPressed(self):
        pass
            
# 시계모드
class ClockMode(Mode):
    def update(self):
        super().update()
        now = self.getCurrentTime()
        self.draw.text((2, 30), now.strftime('%p'), font = font_small, fill = 1) 
        self.draw.text((0, 50), now.strftime('%I:%M'), font = font_big, fill = 1) 
        self.draw.text((40, 80), now.strftime('%S'), font = font_small, fill = 1) 

# 달력모드
class CalendarMode(Mode):
    def update(self):
        super().update()
        now = self.getCurrentTime()
        year = str(now.year) 
        self.draw.text((self.getTextCenterAlignXY(year, font_small)[0], 20), year, font = font_small, fill = 1)
        
        month = str(now.month) 
        self.draw.text((10, 40), month, font = font_big, fill = 1)
        self.draw.text((10 + len(month)*13, 50), '월', font = font_small, fill = 1)

        day = str(now.day) 
        self.draw.text((10, 65), day, font = font_big, fill = 1)
        self.draw.text((10 + len(day)*13, 75), '일', font = font_small, fill = 1)

        yoil = '월화수목금토일'[now.weekday()] 
        self.draw.text((self.getTextCenterAlignXY(yoil + '요일', font_small)[0], 95), yoil + '요일', font = font_small, fill = 1)

# 음성인식 모드
class VoiceMode(Mode):
    def __init__(self):
        super().__init__()
        self.is_websocket_active = False
        self.words_to_show = []
        self.command_list = []
        self.status_text = "READY"

        self.FORMAT = pyaudio.paInt16
        self.CHANNELS = 1
        self.RATE = 16000
        self.CHUNK = 1024
        self.RECORD_SECONDS = 3  
        self.WAVE_OUTPUT_FILENAME = "/home/pi/test.wav"

        print("[VoiceMode] 백그라운드 오디오 인터페이스 스레드를 생성합니다.")
        self.voice_thread = threading.Thread(target=self.voice_control_loop, daemon=True)
        self.voice_thread.start()
    
    def update(self):
        super().update()
        if self.is_websocket_active:
            display_msg = f"[{self.status_text}]\n" + "\n".join(self.words_to_show)
        else:
            display_msg = "press\nACTION\nfor\nvoice\ninput"

        display_msg = self.textMultiliner(display_msg, font_small)
        self.draw.text(self.getTextCenterAlignXY(display_msg, font_small), display_msg, font = font_small, fill = 1)

    def actButtonPressed(self):
        self.is_websocket_active = not self.is_websocket_active
        print(f"[ACTION] 음성인식 활성화 상태 변경 -> {self.is_websocket_active}")

        if self.is_websocket_active:
            self.websocket_thread = threading.Thread(target = self.doWebsocketClient, daemon=True)
            self.websocket_thread.start()
            self.status_text = "START"
            self.words_to_show = ["Listening.."]
        else:
            self.status_text = "STOP"
            self.words_to_show = []

    def doWebsocketClient(self):
        asyncio.run(self.websocket_client())
    
    async def websocket_client(self):
        print(f"[Websocket] 차량 서버 연결 시도 중... ({serverURI})")
        try:
            async with websockets.connect(serverURI) as websocket:
                print("[Websocket] 차량 무선 서버 통신망 연결 성공!")
                while self.is_websocket_active:
                    if self.command_list:
                        for command in self.command_list:
                            print(f'[Glass -> Car] 명령어 전송 시도: "{command}"')
                            await websocket.send(command)
                            resp = await websocket.recv()
                            print(f'[Car -> Glass] 차량 제어 응답 수신: "{resp}"')
                        self.command_list = []  
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[Websocket] 차량 연결 실패 또는 통신 에러: {e}")
        finally:
            print("[Websocket] 웹소켓 클라이언트 세션이 안전하게 종료되었습니다.")

    def voice_control_loop(self):
        while True:
            if self.is_websocket_active:
                try:
                    print("\n[녹음 시작] 3초간 주변 음성을 캡처합니다.")
                    self.status_text = "REC"
                    self.words_to_show = ["말씀하세요"]
                    
                    p = pyaudio.PyAudio()
                    stream = p.open(format=self.FORMAT, channels=self.CHANNELS, rate=self.RATE,
                                    input=True, frames_per_buffer=self.CHUNK)
                    frames = []

                    for _ in range(0, int(self.RATE / self.CHUNK * self.RECORD_SECONDS)):
                        if not self.is_websocket_active: 
                            break
                        data = stream.read(self.CHUNK, exception_on_overflow=False)
                        frames.append(data)

                    stream.stop_stream()
                    stream.close()
                    p.terminate()

                    if not self.is_websocket_active: 
                        print("[녹음 중단] 사용자가 도중에 액션 모드를 비활성화했습니다.")
                        continue

                    wf = wave.open(self.WAVE_OUTPUT_FILENAME, 'wb')
                    wf.setnchannels(self.CHANNELS)
                    wf.setsampwidth(p.get_sample_size(self.FORMAT))
                    wf.setframerate(self.RATE)
                    wf.writeframes(b''.join(frames))
                    wf.close()
                    print("[SAVE] 오디오 임시 저장 완료. GMS API 서버로 전송합니다.")

                    self.status_text = "STT"
                    self.words_to_show = ["분석 중.."]
                    
                    gms_key = os.getenv("GMS_KEY")
                    if not gms_key:
                        print("[GMS API Error] GMS_KEY 환경 변수가 세팅되지 않았습니다!")
                        self.words_to_show = ["키 에러"]
                        time.sleep(2)
                        continue

                    url = "https://gms.ssafy.io/gmsapi/api.openai.com/v1/audio/transcriptions"
                    headers = {"Authorization": f"Bearer {gms_key}"}
                    files = {"file": (os.path.basename(self.WAVE_OUTPUT_FILENAME), open(self.WAVE_OUTPUT_FILENAME, "rb"), "audio/wav")}
                    data = {"model": "whisper-1", "language": "ko"}

                    response = requests.post(url, headers=headers, files=files, data=data, verify=False)
                    files["file"][1].close()

                    if response.status_code == 200:
                        text_result = response.json().get("text", "").strip()
                        print(f"[GMS API] 변환 완료 -> 인식된 문장: \"{text_result}\"")
                        self.words_to_show = [text_result]

                        matched_signals = []
                        for cmd_target in CAR_COMMANDS:
                            if cmd_target in text_result:
                                matched_signals.append(cmd_target)

                        if matched_signals:
                            print(f"[MATCH] 키워드 매칭 성공. 차량 전송 신호: {matched_signals}")
                            self.command_list = matched_signals
                            self.status_text = "SEND"
                        else:
                            print("[FAIL] 매칭 실패. 인식된 문장에 차량 제어 키워드가 없습니다.")
                            self.status_text = "FAIL"
                    else:
                        print(f"[GMS API] 오류 응답 코드: {response.status_code}, 메시지: {response.text}")
                        self.status_text = "ERR"
                        self.words_to_show = ["서버 에러"]

                    time.sleep(1.5) 

                except Exception as e:
                    print(f"[Voice Loop] 예외 발생: {e}")
                    time.sleep(2)
            else:
                time.sleep(0.2) 

def initButton():
    GPIO.setmode(GPIO.BCM)
    buttons = [MODE_BUTTON, ACT_BUTTON]
    GPIO.setup(buttons, GPIO.IN, pull_up_down = GPIO.PUD_UP) 
    for btn in buttons:
        GPIO.add_event_detect(btn, GPIO.FALLING, callback = whenButtonPressed, bouncetime = 300) 

def whenButtonPressed(channel):
    print(f'[인터럽트] 하드웨어 버튼 @GPIO {channel}번이 눌렸습니다!')
    global mode_index, current_mode, mode_list

    if channel == MODE_BUTTON:
        mode_index = (mode_index + 1) % 3
        current_mode = mode_list[mode_index]
        current_mode.whenActivated()    
        print(f'[MODE] 모드 전환 완료. 현재 모드 인덱스: {mode_index}')
    
    elif channel == ACT_BUTTON:
        current_mode.actButtonPressed()

def main():
    print("[2] SPI 오버레이 통신망을 통해 OLED 디스플레이 연결 시도 중...")
    try:
        spi = board.SPI()
        oled = adafruit_ssd1306.SSD1306_SPI(disp_height, disp_width, spi, oled_dc, oled_reset, oled_cs) 
        oled.fill(0)
        oled.show()
        print("[3] OLED 디스플레이 초기화 완료!")
    except Exception as e:
        print("[ERROR] OLED 하드웨어 초기화 도중 치명적인 오류 발생!")
        print(f"상세 원인: {e}")
        return

    global mode_list, mode_index, current_mode
    mode_list = [ClockMode(), CalendarMode(), VoiceMode()] 
    mode_index = 0
    current_mode = mode_list[mode_index]

    print("[4] 하드웨어 버튼 인터럽트(GPIO 12, 16) 활성화 세팅 중...")
    initButton()
    
    print("\n[READY] 모든 시퀀스 준비 완료! 메인 무한 루프에 진입합니다.")
    print("💡 안내: 버튼을 누르기 전까지는 콘솔에 추가 로그가 찍히지 않으며 OLED 화면에 시계가 나타납니다.\n")

    try:
        while True:
            current_mode.update()
            flippedImage = current_mode.screenImage.transpose(Image.FLIP_LEFT_RIGHT) 
            rotatedImage = flippedImage.transpose(Image.ROTATE_90) 
            oled.image(rotatedImage)
            oled.show()
    except KeyboardInterrupt:
        print('\n[EXIT] 사용자의 요청(Ctrl+C)으로 안전하게 프로그램을 종료합니다...')
    finally:
        oled.fill(0)
        oled.show()
        GPIO.cleanup()
        print('[CLEANUP] GPIO 리소스 정리를 완료했습니다.')

if __name__ == '__main__':
    main()
