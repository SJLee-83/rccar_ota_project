import sys
from PySide6.QtWidgets import (QApplication, QMainWindow, QFileDialog,
                               QTableWidgetItem)
from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtGui import QColor
import paho.mqtt.client as mqtt
from ui_form import Ui_MainWindow
import json
from datetime import datetime
import pytz
import binascii
import struct
import time
import uuid
import re
import html
from pathlib import Path

APP_FILE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_FILE_DIR if (APP_FILE_DIR / "ai_audio").exists() else APP_FILE_DIR.parent
AI_AUDIO_DIR = PROJECT_DIR / "ai_audio"
if str(AI_AUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(AI_AUDIO_DIR))

AI_AUDIO_IMPORT_ERROR = None
VOICE_AUDIO_IMPORT_ERROR = None
try:
    from dotenv import load_dotenv
    from config import AppConfig
    from gms_client import GMSClient
except ModuleNotFoundError as exc:
    AI_AUDIO_IMPORT_ERROR = exc
    load_dotenv = None
    AppConfig = None
    GMSClient = None

try:
    from audio_recorder import record_wav
except ModuleNotFoundError as exc:
    VOICE_AUDIO_IMPORT_ERROR = exc
    record_wav = None

korea_timezone = pytz.timezone("Asia/Seoul")
address = "70.12.107.50"
port = 1883
commandTopic = "RCCar/command"
sensingTopic = "RCCar/sensing"
AI_RUNTIME_DIR = Path.home() / ".local" / "share" / "ai_audio"
ALLOWED_VOICE_COMMANDS = {"start", "go", "back", "left", "right", "mid", "stop"}


class AIChatWorker(QThread):
    status_changed = Signal(str)
    answer_ready = Signal(str)
    failed = Signal(str)

    def __init__(self, config, history, user_text):
        super().__init__()
        self.config = config
        self.history = history
        self.user_text = user_text

    def run(self):
        try:
            self.status_changed.emit("⬤  THINKING")
            answer = GMSClient(self.config).chat(self.history, self.user_text)
            self.answer_ready.emit(answer)
            self.status_changed.emit("⬤  IDLE")
        except Exception as exc:
            self.failed.emit(str(exc))


class VoiceCommandWorker(QThread):
    status_changed = Signal(str)
    recognized = Signal(str)
    command_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self):
        try:
            client = GMSClient(self.config)
            if record_wav is None:
                raise RuntimeError(
                    "PyAudio/audio_recorder를 사용할 수 없습니다. "
                    f"현재 Python={sys.executable}, 오류={VOICE_AUDIO_IMPORT_ERROR}"
                )
            self.status_changed.emit(
                f"Status:  Recording  —  {self.config.record_seconds:g}초 동안 말하세요")
            wav_path = record_wav(
                AI_RUNTIME_DIR / "voice_command.wav",
                seconds=self.config.record_seconds,
                rate=self.config.audio_rate,
                sample_bits=self.config.audio_sample_bits,
                channels=self.config.audio_channels,
                input_device_index=self.config.audio_input_device,
            )
            self.status_changed.emit("Status:  STT  —  음성을 텍스트로 변환 중")
            text = client.transcribe(wav_path)
            self.recognized.emit(text)
            self.status_changed.emit("Status:  AI  —  명령어 해석 중")
            command = client.interpret_vehicle_command(text)
            self.command_ready.emit(command)
            self.status_changed.emit("Status:  Standby  —  버튼을 누르면 명령어를 녹음합니다")
        except Exception as exc:
            self.failed.emit(str(exc))

class MainWindow(QMainWindow):
    sensorData = list()
    sensingDataList = list()
    commandData = dict()
    commandDataList = list()

    # Custom signals for cross-thread GUI updates
    sig_append_log = Signal(str, str)
    sig_ota_ready = Signal()
    sig_chunk_ack = Signal(object)
    sig_chunk_error = Signal(object)
    sig_ota_complete = Signal()
    sig_ota_error = Signal()
    sig_ra6e1_status = Signal(str)
    sig_ra6e1_log = Signal(str)
    sig_mqtt_connected = Signal(int)
    sig_mqtt_subscription = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        if load_dotenv is not None:
            load_dotenv(AI_AUDIO_DIR / ".env")
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.ai_config = AppConfig.from_env() if AppConfig is not None else None
        self.ai_history = []
        self.ai_worker = None
        self.voice_worker = None
        self.last_voice_text = ""
        if self.ai_config is not None:
            self.ui.llm_endpoint_label.setText(self.ai_config.base_url)
            self.ui.llm_model_label.setText(self.ai_config.chat_model)
        else:
            self.ui.llm_status_dot.setText("⬤  AI MODULE MISSING")
            self.ui.llm_status_dot.setStyleSheet(
                "font-size:11px; font-weight:bold; color:#FF4444; border:none;")

        self.ui.startButton.clicked.connect(self.start)
        self.ui.stopButton.clicked.connect(self.stop)
        self.ui.goButton.clicked.connect(self.go)
        self.ui.backButton.clicked.connect(self.back)
        self.ui.leftButton.clicked.connect(self.left)
        self.ui.rightButton.clicked.connect(self.right)
        self.ui.midButton.clicked.connect(self.mid)
        
        self.ui.btn_ping_ra6e1.clicked.connect(self.ping_ra6e1)
        self.ui.btn_led_on.clicked.connect(self.led_on)
        self.ui.btn_led_off.clicked.connect(self.led_off)

        # OTA 로직 변수 및 버튼 연결
        self.fw_data = None
        self.fw_size = 0
        self.fw_crc32 = 0
        self.chunk_size = 256
        self.current_chunk = 0
        self.total_chunks = 0
        self.pre_ota_version = None
        self.ota_in_progress = False
        self.chunk_retries = 0
        self.total_retries = 0
        self.acked_chunks = 0
        self.pending_chunk_id = None
        self.chunk_sent_at = 0.0
        self.ota_started_at = 0.0
        self.ota_session = ""
        self.timeout_phase = ""
        # Consecutive failures of the same chunk. This resets to zero whenever
        # any chunk is ACKed, so a progressing transfer is never stopped by
        # the accumulated retry count.
        self.max_chunk_retries = 20
        self.ota_status_subscribed = False
        self.subscription_topics = {}
        self.mqtt_loop_running = False

        self.ota_timeout_timer = QTimer(self)
        self.ota_timeout_timer.setSingleShot(True)
        self.ota_timeout_timer.timeout.connect(self.handle_ota_timeout)
        
        self.ui.btn_select_bin.clicked.connect(self.select_bin_file)
        self.ui.btn_start_ota.clicked.connect(self.start_ota)
        self.ui.btn_abort_ota.clicked.connect(self.abort_ota)
        self.ui.llm_send_btn.clicked.connect(self.send_ai_chat)
        self.ui.llm_clear_btn.clicked.connect(self.clear_ai_chat)
        self.ui.voice_command_button.clicked.connect(self.start_voice_command)
        if AI_AUDIO_IMPORT_ERROR is None:
            self.append_ai_chat(
                "System",
                "GMS_KEY는 ai_audio/.env에서 읽습니다. 챗봇 모델은 gpt-5.4-mini로 설정되어 있습니다.\n"
                f"Python: {sys.executable}\n"
                f"ai_audio: {AI_AUDIO_DIR}",
                "#94A3B8")
            if VOICE_AUDIO_IMPORT_ERROR is not None:
                self.append_voice_log(
                    "⚠ 음성 녹음 모듈을 불러오지 못했습니다.\n"
                    f"Python: {sys.executable}\n"
                    f"ai_audio: {AI_AUDIO_DIR}\n"
                    f"오류: {VOICE_AUDIO_IMPORT_ERROR}\n"
                    "챗봇은 사용할 수 있고, 음성 제어만 PyAudio 설치/실행 환경 확인이 필요합니다.",
                    "#FFB800")
        else:
            self.append_ai_chat(
                "System",
                "AI Audio 모듈을 찾지 못했습니다. OTA 폴더와 같은 위치에 ai_audio 폴더를 복사하고, "
                "가상환경에 requirements.txt를 설치하세요.\n"
                f"상세 오류: {AI_AUDIO_IMPORT_ERROR}",
                "#FF4444")

        # Connect custom signals to GUI thread slots
        self.sig_append_log.connect(self.append_log)
        self.sig_ota_ready.connect(self.handle_ota_ready)
        self.sig_chunk_ack.connect(self.handle_chunk_ack)
        self.sig_chunk_error.connect(self.handle_chunk_error)
        self.sig_ota_complete.connect(self.handle_ota_complete)
        self.sig_ota_error.connect(self.handle_ota_error)
        self.sig_ra6e1_status.connect(self.handle_ra6e1_status)
        self.sig_ra6e1_log.connect(self.handle_ra6e1_log)
        self.sig_mqtt_connected.connect(self.handle_mqtt_connected)
        self.sig_mqtt_subscription.connect(self.handle_mqtt_subscription)

    def append_ai_chat(self, speaker, text, color="#C8D8E8"):
        safe_text = html.escape(text).replace("\n", "<br>")
        self.ui.llm_chat_display.append(
            f'<p style="color:{color}; margin:6px 0;">'
            f'<b>{html.escape(speaker)}</b><br>{safe_text}</p>')

    def append_voice_log(self, text, color="#A0B8C8"):
        safe_text = html.escape(text).replace("\n", "<br>")
        self.ui.voice_command_log.append(
            f'<p style="color:{color}; margin:4px 0; font-family:Consolas;">'
            f'{safe_text}</p>')

    def set_ai_busy(self, busy):
        self.ui.llm_send_btn.setDisabled(busy)
        self.ui.llm_clear_btn.setDisabled(busy)
        self.ui.llm_input.setDisabled(busy)

    def set_voice_busy(self, busy):
        self.ui.voice_command_button.setDisabled(busy)

    def _validate_ai_config(self):
        if AI_AUDIO_IMPORT_ERROR is not None or self.ai_config is None:
            self.append_ai_chat(
                "System",
                "AI Audio 모듈이 준비되지 않았습니다. ai_audio 폴더 위치와 Python 패키지 설치를 확인하세요.",
                "#FF4444")
            self.append_voice_log(
                "❌ AI Audio 모듈이 준비되지 않았습니다. ai_audio 폴더 위치와 Python 패키지 설치를 확인하세요.",
                "#FF4444")
            return False
        try:
            self.ai_config.validate()
            return True
        except ValueError as exc:
            self.append_ai_chat("System", f"❌ {exc}", "#FF4444")
            self.append_voice_log(f"❌ {exc}", "#FF4444")
            return False

    def send_ai_chat(self):
        if self.ai_worker is not None:
            return
        text = self.ui.llm_input.toPlainText().strip()
        if not text:
            return
        if not self._validate_ai_config():
            return

        self.ui.llm_input.clear()
        context = self.ai_history.copy()
        self.ai_history.append({"role": "user", "content": text})
        self.append_ai_chat("나", text, "#93C5FD")
        self.set_ai_busy(True)
        self.ai_worker = AIChatWorker(self.ai_config, context, text)
        self.ai_worker.status_changed.connect(self.set_ai_status)
        self.ai_worker.answer_ready.connect(self.handle_ai_answer)
        self.ai_worker.failed.connect(self.handle_ai_error)
        self.ai_worker.finished.connect(self.handle_ai_finished)
        self.ai_worker.start()

    def set_ai_status(self, text):
        color = "#00E878" if "IDLE" in text else "#FFB800"
        self.ui.llm_status_dot.setText(text)
        self.ui.llm_status_dot.setStyleSheet(
            f"font-size:11px; font-weight:bold; color:{color}; border:none;")

    def handle_ai_answer(self, answer):
        self.ai_history.append({"role": "assistant", "content": answer})
        self.ai_history = self.ai_history[-12:]
        self.append_ai_chat("AI", answer, "#86EFAC")

    def handle_ai_error(self, message):
        self.set_ai_status("⬤  ERROR")
        self.append_ai_chat("System", f"❌ {message}", "#FF4444")

    def handle_ai_finished(self):
        worker = self.ai_worker
        self.ai_worker = None
        self.set_ai_busy(False)
        if worker is not None:
            worker.deleteLater()

    def clear_ai_chat(self):
        if self.ai_worker is not None:
            return
        self.ai_history.clear()
        self.ui.llm_chat_display.clear()
        self.append_ai_chat("System", "AI 대화 기록을 지웠습니다.", "#94A3B8")

    def start_voice_command(self):
        if self.voice_worker is not None:
            return
        if not self._validate_ai_config():
            return
        if record_wav is None:
            self.append_voice_log(
                "❌ 음성 녹음 모듈을 사용할 수 없습니다.\n"
                f"Python: {sys.executable}\n"
                f"오류: {VOICE_AUDIO_IMPORT_ERROR}",
                "#FF4444")
            return
        self.set_voice_busy(True)
        self.append_voice_log("▶ 음성 명령 녹음을 시작합니다.", "#00C8FF")
        self.voice_worker = VoiceCommandWorker(self.ai_config)
        self.voice_worker.status_changed.connect(self.ui.voice_command_status.setText)
        self.voice_worker.recognized.connect(self.handle_voice_recognized)
        self.voice_worker.command_ready.connect(self.handle_voice_command)
        self.voice_worker.failed.connect(self.handle_voice_error)
        self.voice_worker.finished.connect(self.handle_voice_finished)
        self.voice_worker.start()

    def handle_voice_recognized(self, text):
        self.last_voice_text = text
        self.append_voice_log(f"STT: {text}", "#93C5FD")

    def handle_voice_command(self, result):
        command = str(result.get("command", "unknown")).strip().lower()
        confidence = float(result.get("confidence", 0.0) or 0.0)
        reason = str(result.get("reason", "") or "")

        if command not in ALLOWED_VOICE_COMMANDS or confidence < 0.55:
            self.append_voice_log(
                f"❌ 명령 거부: command={command}, confidence={confidence:.2f}, reason={reason}",
                "#FF4444")
            return

        if not hasattr(self, 'client') or not self.client.is_connected():
            self.append_voice_log("❌ MQTT 미연결 상태라 차량 명령을 보낼 수 없습니다. START를 먼저 누르세요.", "#FF4444")
            return

        if self.ota_in_progress and command != "stop":
            self.append_voice_log("❌ OTA 진행 중에는 stop 외 음성 제어를 차단합니다.", "#FF4444")
            return

        self.publishCommand(command)
        self.append_voice_log(
            f"✅ MQTT 명령 전송: {command}  confidence={confidence:.2f}  reason={reason}",
            "#00E878")
        self.ui._rc_status_val.setText(f"VOICE: {command.upper()}")
        self.ui._rc_status_val.setStyleSheet("font-size:20px; font-weight:bold; color:#00C8FF;")

    def handle_voice_error(self, message):
        self.ui.voice_command_status.setText("Status:  Error")
        self.append_voice_log(f"❌ {message}", "#FF4444")

    def handle_voice_finished(self):
        worker = self.voice_worker
        self.voice_worker = None
        self.set_voice_busy(False)
        if worker is not None:
            worker.deleteLater()

    def select_bin_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Firmware BIN", "", "BIN Files (*.bin)")
        if file_path:
            with open(file_path, "rb") as f:
                self.fw_data = bytearray(f.read())
                
            # 무결성 검증을 위해 256바이트의 배수로 0xFF 패딩
            remainder = len(self.fw_data) % self.chunk_size
            if remainder != 0:
                self.fw_data.extend(b'\xFF' * (self.chunk_size - remainder))

            if len(self.fw_data) > 0x80000:
                self.append_log(
                    f"❌ Firmware is {len(self.fw_data)} bytes after padding; "
                    "the configured inactive bank limit is 524288 bytes.",
                    "#FF4444")
                self.fw_data = None
                self.fw_size = 0
                self.total_chunks = 0
                self.ui.btn_start_ota.setEnabled(False)
                return
                
            self.fw_size = len(self.fw_data)
            self.fw_crc32 = binascii.crc32(self.fw_data) & 0xFFFFFFFF
            self.total_chunks = self.fw_size // self.chunk_size
            
            self.ui.selected_file_label.setText(file_path.split("/")[-1])
            self.ui.file_size_label.setText(f"SIZE  {self.fw_size} B")
            self.ui.file_crc_label.setText(f"CRC32  {self.fw_crc32:08X}")
            self.ui.file_chunks_label.setText(f"CHUNKS  {self.total_chunks}")
            self.prepare_chunk_table()
            self.append_log(f"📁 Selected Firmware: {self.fw_size} bytes, CRC: {hex(self.fw_crc32)}", "#FFB800")
            self.ui.btn_start_ota.setEnabled(True)
            
    def start_ota(self):
        if not hasattr(self, 'client') or not self.client.is_connected():
            self.append_log("❌ MQTT Not Connected! Please START first.", "#FF4444")
            return
        if not self.fw_data:
            self.append_log("❌ No firmware selected!", "#FF4444")
            return
        if not self.ota_status_subscribed:
            self.append_log(
                "❌ OTA/Status subscription is not confirmed. Reconnect MQTT and try again.",
                "#FF4444")
            return
            
        self.pre_ota_version = self.ui.current_version_label.text()
        self.current_chunk = 0
        self.chunk_retries = 0
        self.total_retries = 0
        self.acked_chunks = 0
        self.pending_chunk_id = None
        self.ota_session = uuid.uuid4().hex[:12]
        self.ota_started_at = time.monotonic()
        self.ui.progress_bar.setValue(0)
        self.prepare_chunk_table()
        self.update_transfer_stats()
        self.append_log(
            f"▶ OTA session={self.ota_session} size={self.fw_size} "
            f"chunks={self.total_chunks} image_crc32={self.fw_crc32:08X}",
            "#00C8FF")
        self.ui._ota_card_val.setText("UPLOADING")
        self.ui._ota_card_val.setStyleSheet("font-size:20px; font-weight:bold; color:#FFB800;")
        
        self.ui.btn_start_ota.setEnabled(False)
        self.ui.btn_select_bin.setEnabled(False)
        self.ui.btn_abort_ota.setEnabled(True)
        self.set_rc_controls_enabled(False)
        
        self.ota_in_progress = True
        
        meta = {
            "cmd": "OTA_START",
            "size": self.fw_size,
            "chunks": self.total_chunks,
            "crc32": self.fw_crc32,
            "session_id": self.ota_session,
            "protocol": 2
        }
        self.client.publish("OTA/Command", json.dumps(meta), qos=1)
        self.arm_ota_timeout("START", 75000)

    def send_next_chunk(self):
        if not self.ota_in_progress:
            return
            
        if self.current_chunk >= self.total_chunks:
            self.pending_chunk_id = None
            self.client.publish("OTA/Command", json.dumps({
                "cmd": "OTA_END", "session_id": self.ota_session,
                "chunks": self.total_chunks, "crc32": self.fw_crc32
            }), qos=1)
            self.ui.progress_bar.setValue(100)
            self.append_log("✅ All chunks ACKed by RA6E1. Verifying image CRC and requesting bank swap...", "#00E878")
            self.ui._ota_card_val.setText("WAITING")
            self.ui.ota_status_label.setText("Status: verifying full image CRC on RA6E1")
            self.arm_ota_timeout("END", 20000)
            return

        start_idx = self.current_chunk * self.chunk_size
        end_idx = start_idx + self.chunk_size
        chunk = self.fw_data[start_idx:end_idx]
        
        chunk_crc32 = binascii.crc32(chunk) & 0xFFFFFFFF
        
        # Binary OTA/Data v2 packet (282 bytes):
        # magic[4] + session[12] + chunk_id[4] + length[2] + crc32[4] + data[256]
        # This avoids base64 expansion and ArduinoJson string-field loss.
        session_bytes = self.ota_session.encode("ascii")
        header = (b"OTD2" + session_bytes +
                  struct.pack(">IHI", self.current_chunk, len(chunk), chunk_crc32))
        payload = header + bytes(chunk)
        result = self.client.publish("OTA/Data", payload, qos=1)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            self.retry_current_chunk(f"MQTT publish rc={result.rc}")
            return

        self.pending_chunk_id = self.current_chunk
        self.chunk_sent_at = time.monotonic()
        self.set_chunk_row(self.current_chunk, "SENT", self.chunk_retries, None)
        self.ui.ota_status_label.setText(
            f"Status: waiting for RA6E1 ACK — chunk {self.current_chunk}/{self.total_chunks - 1}")
        self.append_log(
            f"TX  chunk={self.current_chunk} bytes={len(chunk)} "
            f"crc32={chunk_crc32:08X} attempt={self.chunk_retries + 1}",
            "#6090B0")
        self.arm_ota_timeout("CHUNK", 6000)

    def abort_ota(self):
        self.ota_timeout_timer.stop()
        self.ota_in_progress = False
        if hasattr(self, 'client') and self.client.is_connected():
            self.client.publish("OTA/Command", json.dumps({
                "cmd": "OTA_ABORT", "session_id": self.ota_session
            }), qos=1)
        self.ui.progress_bar.setValue(0)
        self.ui._ota_card_val.setText("READY")
        self.ui._ota_card_val.setStyleSheet("font-size:20px; font-weight:bold; color:#A0B8C8;")
        self.append_log("🛑 OTA Aborted by user.", "#FF4444")
        
        self.ui.btn_start_ota.setEnabled(True)
        self.ui.btn_select_bin.setEnabled(True)
        self.ui.btn_abort_ota.setEnabled(False)
        self.set_rc_controls_enabled(True)

    def ping_ra6e1(self):
        if hasattr(self, 'client'):
            self.append_log("▶ Requesting PING to RA6E1 via ESP32...", "#00C8FF")
            self.client.publish("RA6E1/UART/Ping", "PING")
        else:
            self.append_log("❌ MQTT Not Connected! Please press START first.", "#FF4444")

    def led_on(self):
        if hasattr(self, 'client'):
            self.append_log("💡 Requesting ESP32 LED ON...", "#00C8FF")
            self.client.publish("ESP32/LED_Control", "ON")

    def led_off(self):
        if hasattr(self, 'client'):
            self.append_log("💡 Requesting ESP32 LED OFF...", "#00C8FF")
            self.client.publish("ESP32/LED_Control", "OFF")

    def makeCommandData(self, cmd, arg, finish):
        current_time = datetime.now(korea_timezone)
        self.commandData["time"] = current_time.strftime("%Y-%m-%d %H:%M:%S")
        self.commandData["cmd_string"] = cmd
        self.commandData["arg_string"] = arg
        self.commandData["is_finish"] = finish
        return self.commandData

    def publishCommand(self, cmd):
        self.commandData = self.makeCommandData(cmd, 100, 1)
        self.client.publish(commandTopic, json.dumps(self.commandData), qos=1)
        self.commandDataList.append(self.commandData)
        self.commandData = dict()

    def start(self):
        # The RC START button must not create multiple MQTT clients.  Keep one
        # network loop alive for the entire GUI lifetime.
        if hasattr(self, 'client') and self.client.is_connected():
            self.publishCommand("start")
            return

        client_id = f"OTA_GUI_{uuid.uuid4().hex[:10]}"
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=True)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_subscribe = self.on_subscribe
        self.client.on_disconnect = self.on_disconnect
        self.client.connect(address, port)
        self.client.loop_start()
        self.mqtt_loop_running = True

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.settingUI)
        self.timer.start(500)
        self.publishCommand("start")

    def stop(self):
        self.publishCommand("stop")
        # STOP means stop the vehicle, not stop MQTT.  OTA/Status and board
        # telemetry must continue to be received after the car is stopped.

    def go(self): self.publishCommand("go")
    def back(self): self.publishCommand("back")
    def left(self): self.publishCommand("left")
    def right(self): self.publishCommand("right")
    def mid(self): self.publishCommand("mid")

    def settingUI(self):
        self.ui.logText.clear()
        for i in range(len(self.commandDataList)):
            msg = "%3d | %s | %6s | %3d | %3d" % (
                i, self.commandDataList[i]["time"],
                self.commandDataList[i]["cmd_string"],
                self.commandDataList[i]["arg_string"],
                self.commandDataList[i]["is_finish"])
            self.ui.logText.appendPlainText(msg)

        self.ui.sensingText.clear()
        for i in range(len(self.sensingDataList)):
            sd = self.sensingDataList[i]
            msg = "%3d | %s | %3.2f | %3.2f | %3d" % (
                i + 1, sd["time"], sd["num1"], sd["num2"], sd["is_finish"])
            self.ui.sensingText.appendPlainText(msg)

    def append_log(self, text, color="#A0B8C8"):
        html = f'<p style="color:{color}; margin:0px; font-family:Consolas; font-size:11px;">{text}</p>'
        self.ui.status_log.append(html)

    def prepare_chunk_table(self):
        """Create one visible row per chunk before transmission starts."""
        self.ui.chunk_table.setRowCount(self.total_chunks)
        for chunk_id in range(self.total_chunks):
            start = chunk_id * self.chunk_size
            chunk = self.fw_data[start:start + self.chunk_size] if self.fw_data else b""
            crc = binascii.crc32(chunk) & 0xFFFFFFFF if chunk else 0
            values = (str(chunk_id), str(len(chunk)), f"{crc:08X}",
                      "QUEUED", "0", "—")
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setForeground(QColor("#4A6880"))
                self.ui.chunk_table.setItem(chunk_id, column, item)

    def set_chunk_row(self, chunk_id, state, retries=0, rtt_ms=None):
        if chunk_id < 0 or chunk_id >= self.ui.chunk_table.rowCount():
            return
        colors = {
            "QUEUED": "#4A6880", "SENT": "#FFB800", "RETRY": "#FF7A00",
            "ACKED": "#00E878", "FAILED": "#FF4444"
        }
        self.ui.chunk_table.setItem(chunk_id, 3, QTableWidgetItem(state))
        self.ui.chunk_table.setItem(chunk_id, 4, QTableWidgetItem(str(retries)))
        if rtt_ms is not None:
            self.ui.chunk_table.setItem(chunk_id, 5, QTableWidgetItem(f"{rtt_ms:.1f}"))
        color = QColor(colors.get(state, "#A0B8C8"))
        for column in range(self.ui.chunk_table.columnCount()):
            item = self.ui.chunk_table.item(chunk_id, column)
            if item:
                item.setForeground(color)
        self.ui.chunk_table.scrollToItem(self.ui.chunk_table.item(chunk_id, 0))

    def update_transfer_stats(self):
        elapsed = max(time.monotonic() - self.ota_started_at, 0.001) if self.ota_started_at else 0.001
        rate_kib = (self.acked_chunks * self.chunk_size) / elapsed / 1024.0
        self.ui.ota_acked_label.setText(f"ACKED  {self.acked_chunks} / {self.total_chunks}")
        self.ui.ota_retry_label.setText(f"RETRIES  {self.total_retries}")
        self.ui.ota_rate_label.setText(f"RATE  {rate_kib:.1f} KiB/s")
        last = self.acked_chunks - 1
        self.ui.ota_last_label.setText(f"LAST  {last if last >= 0 else '—'}")

    def set_rc_controls_enabled(self, enabled):
        for button in (self.ui.goButton, self.ui.backButton, self.ui.leftButton,
                       self.ui.rightButton, self.ui.midButton,
                       self.ui.startButton, self.ui.stopButton):
            button.setEnabled(enabled)

    def arm_ota_timeout(self, phase, timeout_ms):
        self.timeout_phase = phase
        self.ota_timeout_timer.start(timeout_ms)

    def handle_ota_timeout(self):
        if not self.ota_in_progress:
            return
        if self.timeout_phase == "CHUNK":
            self.retry_current_chunk("ACK timeout")
        else:
            self.append_log(f"❌ OTA {self.timeout_phase} timeout", "#FF4444")
            self.handle_ota_error()

    def retry_current_chunk(self, reason):
        if not self.ota_in_progress:
            return
        self.ota_timeout_timer.stop()
        chunk_id = self.current_chunk
        if self.chunk_retries >= self.max_chunk_retries:
            self.set_chunk_row(chunk_id, "FAILED", self.chunk_retries, None)
            self.append_log(
                f"❌ chunk={chunk_id} failed after {self.chunk_retries + 1} attempts: {reason}",
                "#FF4444")
            self.abort_ota()
            self.ui._ota_card_val.setText("ERROR")
            return
        self.chunk_retries += 1
        self.total_retries += 1
        self.pending_chunk_id = None
        self.set_chunk_row(chunk_id, "RETRY", self.chunk_retries, None)
        self.update_transfer_stats()
        self.append_log(
            f"↻ RETRY chunk={chunk_id} retry={self.chunk_retries}/{self.max_chunk_retries} reason={reason}",
            "#FFB800")
        QTimer.singleShot(250, self.send_next_chunk)

    def handle_ota_ready(self):
        if not self.ota_in_progress:
            return
        self.ota_timeout_timer.stop()
        if self.pending_chunk_id is not None:
            self.append_log(
                f"[ESP32] duplicate READY ignored while chunk={self.pending_chunk_id} is in flight",
                "#7A5060")
            self.arm_ota_timeout("CHUNK", 6000)
            return
        self.append_log("[ESP32] OTA Status: READY. Starting transmission...", "#00C8FF")
        self.send_next_chunk()

    def handle_chunk_ack(self, status):
        if not self.ota_in_progress:
            return
        chunk_id = int(status.get("chunk_id", -1))
        session_id = status.get("session_id", "")
        if session_id and session_id != self.ota_session:
            self.append_log(f"IGNORED stale ACK session={session_id} chunk={chunk_id}", "#7A5060")
            return
        if chunk_id != self.current_chunk or self.pending_chunk_id != chunk_id:
            self.append_log(
                f"IGNORED out-of-order ACK chunk={chunk_id}, expected={self.current_chunk}",
                "#7A5060")
            return
        self.ota_timeout_timer.stop()
        rtt_ms = (time.monotonic() - self.chunk_sent_at) * 1000.0
        duplicate = bool(status.get("duplicate", False))
        self.set_chunk_row(chunk_id, "ACKED", self.chunk_retries, rtt_ms)
        self.acked_chunks += 1
        self.pending_chunk_id = None
        self.current_chunk += 1
        self.chunk_retries = 0
        progress = int((self.acked_chunks / self.total_chunks) * 100)
        self.ui.progress_bar.setValue(progress)
        self.update_transfer_stats()
        suffix = " duplicate-recovered" if duplicate else ""
        self.append_log(
            f"ACK chunk={chunk_id} rtt={rtt_ms:.1f}ms{suffix} "
            f"({self.acked_chunks}/{self.total_chunks})", "#00E878")
        self.send_next_chunk()

    def handle_chunk_error(self, status):
        chunk_id = int(status.get("chunk_id", self.current_chunk))
        reason = status.get("reason", "NACK")
        if status.get("ra_code") is not None:
            reason += f" (RA=0x{int(status['ra_code']):02X})"
        if chunk_id != self.current_chunk:
            self.append_log(
                f"IGNORED stale NACK chunk={chunk_id}, expected={self.current_chunk}",
                "#7A5060")
            return
        self.retry_current_chunk(reason)

    def handle_ota_complete(self):
        self.ota_timeout_timer.stop()
        self.ota_in_progress = False
        self.ui._ota_card_val.setText("SUCCESS")
        self.ui._ota_card_val.setStyleSheet("font-size:20px; font-weight:bold; color:#00E878;")
        self.ui.ota_status_label.setText("Status: complete — image CRC verified and bank swap accepted")
        self.ui.btn_start_ota.setEnabled(True)
        self.ui.btn_select_bin.setEnabled(True)
        self.ui.btn_abort_ota.setEnabled(False)
        self.set_rc_controls_enabled(True)
        QTimer.singleShot(3000, self.ping_ra6e1)

    def handle_ota_error(self):
        self.ota_timeout_timer.stop()
        # A GUI timeout does not automatically clear ota_active on ESP32 or
        # ota_mode on RA6E1.  Always send an explicit abort before restoring
        # the RC controls.
        if self.ota_in_progress and hasattr(self, 'client') and self.client.is_connected():
            self.client.publish("OTA/Command", json.dumps({
                "cmd": "OTA_ABORT", "session_id": self.ota_session
            }), qos=1)
            self.append_log("OTA state cleanup requested; restoring RC control.", "#FFB800")
        self.ota_in_progress = False
        self.ui._ota_card_val.setText("ERROR")
        self.ui._ota_card_val.setStyleSheet("font-size:20px; font-weight:bold; color:#FF4444;")
        self.ui.btn_start_ota.setEnabled(True)
        self.ui.btn_select_bin.setEnabled(True)
        self.ui.btn_abort_ota.setEnabled(False)
        self.set_rc_controls_enabled(True)

    def handle_ra6e1_status(self, payload):
        if payload == "ONLINE":
            self.ui._ra6e1_card_val.setText("ONLINE")
            self.ui._ra6e1_card_val.setStyleSheet("font-size:20px; font-weight:bold; color:#00E878;")
            self.append_log("✔ RA6E1 Board Connected!", "#00E878")
        else:
            self.ui._ra6e1_card_val.setText("OFFLINE")
            self.ui._ra6e1_card_val.setStyleSheet("font-size:20px; font-weight:bold; color:#FF4444;")
            self.append_log("❌ RA6E1 Board Offline!", "#FF4444")

    def handle_ra6e1_log(self, payload):
        ts = datetime.now().strftime("%H:%M:%S")
        self.append_log(f"[{ts}] [RA6E1] {payload}", "#00C8C8")
        version_match = re.search(r"\bV(\d+)\.(\d+)\.(\d+)\b", payload)
        if version_match:
            self.append_log(f"⭐ RA6E1 Firmware Version Detected: {payload}", "#FFB800")
            installed_ver = f"INSTALLED: {version_match.group(0)}"
            self.ui.current_version_label.setText(installed_ver)
            if self.ui._ota_card_val.text() == "SUCCESS":
                if self.pre_ota_version and self.pre_ota_version == installed_ver:
                    self.append_log("⚠️ BANK SWAP UNCHANGED: Board is still running the same version. (Check if bank swap failed or same version was uploaded)", "#FFB800")
                else:
                    self.append_log("✅ BANK SWAP VERIFIED! Firmware Update Successful.", "#00E878")

    def handle_mqtt_connected(self, reason_code):
        if reason_code == 0:
            self.append_log("✔ MQTT Broker Connected Successfully!", "#00E878")
            self.ui._mqtt_card_val.setText("ONLINE")
            self.ui._mqtt_card_val.setStyleSheet("font-size:20px; font-weight:bold; color:#00E878;")
            
            self.append_log("Waiting for ESP32 and RA6E1 signals...", "#FFB800")
        else:
            self.append_log(f"❌ MQTT Broker Connection Failed (Code: {reason_code})", "#FF4444")
            self.ui._mqtt_card_val.setText("OFFLINE")
            self.ui._mqtt_card_val.setStyleSheet("font-size:20px; font-weight:bold; color:#FF4444;")

    def handle_mqtt_subscription(self, topic, success):
        color = "#00E878" if success else "#FF4444"
        state = "confirmed" if success else "failed"
        self.append_log(f"MQTT subscription {state}: {topic}", color)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        code = int(getattr(reason_code, "value", reason_code))
        if code == 0:
            # Subscribe inside Paho's network callback.  Delaying this through
            # the Qt event queue could leave OTA/Status unsubscribed when an
            # OTA_START response arrived quickly.
            topics = (
                (sensingTopic, 1),
                ("OTA/Status", 1),
                ("RA6E1/Status", 1),
                ("RA6E1/UART/Log", 1),
            )
            for topic, qos in topics:
                result, mid = client.subscribe(topic, qos=qos)
                self.subscription_topics[mid] = topic
                print(f"MQTT SUB topic={topic} qos={qos} result={result} mid={mid}")
                if result != mqtt.MQTT_ERR_SUCCESS:
                    self.sig_append_log.emit(
                        f"MQTT subscribe failed: {topic} rc={result}", "#FF4444")
        self.sig_mqtt_connected.emit(code)

    def on_subscribe(self, client, userdata, mid, reason_code_list, properties):
        topic = self.subscription_topics.pop(mid, f"mid={mid}")
        granted = [int(getattr(code, "value", code)) for code in reason_code_list]
        success = bool(granted) and all(code < 128 for code in granted)
        if topic == "OTA/Status":
            self.ota_status_subscribed = success
        print(f"MQTT SUBACK topic={topic} granted={granted} success={success}")
        self.sig_mqtt_subscription.emit(topic, success)

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        self.ota_status_subscribed = False
        code = int(getattr(reason_code, "value", reason_code))
        print(f"MQTT DISCONNECTED reason={code}")
        self.sig_append_log.emit(f"MQTT disconnected: reason={code}", "#FF4444")

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8")
        
        if topic == sensingTopic:
            message = json.loads(payload)
            self.sensorData.append(message)
            self.sensingDataList = self.sensorData[-15:]
                
        elif topic == "RA6E1/Status":
            self.sig_ra6e1_status.emit(payload)
                
        elif topic == "RA6E1/UART/Log":
            self.sig_ra6e1_log.emit(payload)
                
        elif topic == "OTA/Status":
            if not payload:
                # Empty retained publish only clears a previous READY record.
                return
            print(f"MQTT RX topic=OTA/Status payload={payload}")
            try:
                status = json.loads(payload)
            except json.JSONDecodeError:
                # Backward compatibility with the original ESP32 firmware.
                status = {"status": payload}

            state = str(status.get("status", ""))
            session_id = status.get("session_id", "")
            if session_id and self.ota_session and session_id != self.ota_session:
                self.sig_append_log.emit(
                    f"[ESP32] ignored stale status session={session_id}: {state}",
                    "#7A5060")
                return

            if state == "READY":
                self.sig_ota_ready.emit()
            elif state == "CHUNK_ACK":
                self.sig_chunk_ack.emit(status)
            elif state in ("CHUNK_NACK", "CHUNK_ERROR"):
                self.sig_chunk_error.emit(status)
            elif state == "COMPLETE":
                if status.get("reason"):
                    self.sig_append_log.emit(
                        f"[ESP32] OTA complete: {status['reason']}", "#FFB800")
                self.sig_ota_complete.emit()
            elif state == "ERROR":
                self.sig_append_log.emit(
                    f"[ESP32] ERROR: {status.get('reason', 'unknown')}", "#FF4444")
                self.sig_ota_error.emit()
            else:
                self.sig_append_log.emit(f"[ESP32] OTA Status: {payload}", "#00C8FF")

    def closeEvent(self, event):
        if self.ai_worker is not None or self.voice_worker is not None:
            self.append_ai_chat("System", "현재 AI/API 작업이 진행 중입니다. 완료 후 종료하세요.", "#FFB800")
            event.ignore()
            return
        try:
            if hasattr(self, 'client') and self.client.is_connected():
                self.publishCommand("exit")
                self.client.disconnect()
            if self.mqtt_loop_running:
                self.client.loop_stop()
                self.mqtt_loop_running = False
            current_time = datetime.now(korea_timezone)
            file_name = current_time.strftime("%Y-%m-%d") + ".txt"
            with open(file_name, "w") as file:
                for value in self.sensorData:
                    file.write(str(value) + "\n")
        except Exception as e:
            print("close error:", e)
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    widget = MainWindow()
    widget.show()
    sys.exit(app.exec())
