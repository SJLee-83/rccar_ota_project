from __future__ import annotations

import html
import sys
from pathlib import Path

from dotenv import load_dotenv
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from audio_player import play_mp3
from audio_recorder import list_input_devices, record_wav
from config import AppConfig
from gms_client import GMSClient


APP_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = Path.home() / ".local" / "share" / "ai_audio"


class ChatWorker(QThread):
    status_changed = Signal(str)
    recognized = Signal(str)
    answer_ready = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        config: AppConfig,
        history: list[dict[str, str]],
        user_text: str | None,
        speak: bool,
    ) -> None:
        super().__init__()
        self.config = config
        self.history = history
        self.user_text = user_text
        self.speak = speak

    def run(self) -> None:
        try:
            client = GMSClient(self.config)
            text = self.user_text
            if text is None:
                self.status_changed.emit(f"마이크 녹음 중 ({self.config.record_seconds:g}초)…")
                wav_path = record_wav(
                    RUNTIME_DIR / "question.wav",
                    seconds=self.config.record_seconds,
                    rate=self.config.audio_rate,
                    sample_bits=self.config.audio_sample_bits,
                    channels=self.config.audio_channels,
                    input_device_index=self.config.audio_input_device,
                )
                self.status_changed.emit("음성을 텍스트로 변환하는 중…")
                text = client.transcribe(wav_path)
                self.recognized.emit(text)

            self.status_changed.emit("AI가 답변을 만드는 중…")
            answer = client.chat(self.history, text)
            self.answer_ready.emit(answer)

            if self.speak:
                self.status_changed.emit("답변 음성을 생성하는 중…")
                mp3_path = client.synthesize(answer, RUNTIME_DIR / "answer.mp3")
                self.status_changed.emit("답변을 재생하는 중…")
                play_mp3(mp3_path, self.config.audio_output_device)
            self.status_changed.emit("준비됨")
        except Exception as exc:  # Show actionable hardware/API errors in the GUI.
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        load_dotenv(APP_DIR / ".env")
        self.config = AppConfig.from_env()
        self.history: list[dict[str, str]] = []
        self.worker: ChatWorker | None = None

        self.setWindowTitle("AI Audio Assistant")
        self.resize(860, 650)
        self._build_ui()
        self._apply_style()
        self._show_environment_state()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)

        title = QLabel("AI Audio Assistant")
        title.setObjectName("title")
        subtitle = QLabel("SPH0645 · Whisper STT · GPT · gpt-4o-mini-tts")
        subtitle.setObjectName("subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.chat_view = QTextBrowser()
        self.chat_view.setOpenExternalLinks(False)
        layout.addWidget(self.chat_view, 1)

        input_row = QHBoxLayout()
        self.input_line = QLineEdit()
        self.input_line.setPlaceholderText("질문을 입력하거나 음성 질문 버튼을 누르세요")
        self.input_line.returnPressed.connect(self.send_text)
        self.send_button = QPushButton("전송")
        self.send_button.clicked.connect(self.send_text)
        self.voice_button = QPushButton("🎙 음성 질문")
        self.voice_button.clicked.connect(self.start_voice_chat)
        input_row.addWidget(self.input_line, 1)
        input_row.addWidget(self.send_button)
        input_row.addWidget(self.voice_button)
        layout.addLayout(input_row)

        option_row = QHBoxLayout()
        self.speak_check = QCheckBox("답변 자동 재생")
        self.speak_check.setChecked(True)
        self.clear_button = QPushButton("대화 지우기")
        self.clear_button.clicked.connect(self.clear_chat)
        option_row.addWidget(self.speak_check)
        option_row.addStretch(1)
        option_row.addWidget(self.clear_button)
        layout.addLayout(option_row)

        self.status_label = QLabel("준비됨")
        self.status_label.setObjectName("status")
        layout.addWidget(self.status_label)
        self.setCentralWidget(root)

    def _apply_style(self) -> None:
        self.setFont(QFont("Noto Sans CJK KR", 10))
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background:#111827; color:#e5e7eb; }
            QLabel#title { font-size:28px; font-weight:700; color:#f9fafb; }
            QLabel#subtitle { color:#94a3b8; margin-bottom:8px; }
            QTextBrowser { background:#172033; border:1px solid #334155;
                           border-radius:12px; padding:14px; }
            QLineEdit { background:#0f172a; border:1px solid #475569;
                        border-radius:9px; padding:11px; color:#f8fafc; }
            QPushButton { background:#2563eb; border:0; border-radius:9px;
                          padding:10px 15px; color:white; font-weight:600; }
            QPushButton:hover { background:#3b82f6; }
            QPushButton:disabled { background:#334155; color:#94a3b8; }
            QCheckBox { color:#cbd5e1; }
            QLabel#status { color:#67e8f9; padding-top:4px; }
            """
        )

    def _show_environment_state(self) -> None:
        self.append_system("시스템 준비 완료. 텍스트 또는 음성으로 질문하세요.")
        if not self.config.gms_key:
            self.append_system("⚠ .env에 GMS_KEY를 설정해야 API를 호출할 수 있습니다.")
        try:
            devices = list_input_devices()
            if devices:
                summary = ", ".join(f"{index}: {name}" for index, name, _, _ in devices)
                self.append_system(f"입력 장치: {summary}")
            else:
                self.append_system("⚠ ALSA/PyAudio 입력 장치를 찾지 못했습니다.")
        except Exception as exc:
            self.append_system(f"⚠ 오디오 장치 조회 실패: {exc}")

    def append_system(self, text: str) -> None:
        self.chat_view.append(
            f'<p style="color:#94a3b8"><b>System</b><br>{html.escape(text)}</p>'
        )

    def append_user(self, text: str) -> None:
        self.chat_view.append(
            f'<p style="color:#93c5fd"><b>나</b><br>{html.escape(text)}</p>'
        )

    def append_assistant(self, text: str) -> None:
        self.chat_view.append(
            f'<p style="color:#86efac"><b>AI</b><br>{html.escape(text)}</p>'
        )

    def send_text(self) -> None:
        text = self.input_line.text().strip()
        if not text or self.worker is not None:
            return
        self.input_line.clear()
        context = self.history.copy()
        self.history.append({"role": "user", "content": text})
        self.append_user(text)
        self._start_worker(context, text)

    def start_voice_chat(self) -> None:
        if self.worker is not None:
            return
        self._start_worker(self.history.copy(), None)

    def _start_worker(
        self, history: list[dict[str, str]], user_text: str | None
    ) -> None:
        try:
            self.config.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "설정 오류", str(exc))
            return

        self.set_busy(True)
        self.worker = ChatWorker(
            self.config, history, user_text, self.speak_check.isChecked()
        )
        self.worker.status_changed.connect(self.status_label.setText)
        self.worker.recognized.connect(self._on_recognized)
        self.worker.answer_ready.connect(self._on_answer)
        self.worker.failed.connect(self._on_error)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_recognized(self, text: str) -> None:
        self.history.append({"role": "user", "content": text})
        self.append_user(text)

    def _on_answer(self, text: str) -> None:
        self.history.append({"role": "assistant", "content": text})
        self.history = self.history[-12:]
        self.append_assistant(text)

    def _on_error(self, message: str) -> None:
        self.status_label.setText("오류 발생")
        self.append_system(f"❌ {message}")

    def _on_finished(self) -> None:
        worker = self.worker
        self.worker = None
        self.set_busy(False)
        if worker is not None:
            worker.deleteLater()

    def set_busy(self, busy: bool) -> None:
        self.send_button.setDisabled(busy)
        self.voice_button.setDisabled(busy)
        self.input_line.setDisabled(busy)
        self.clear_button.setDisabled(busy)

    def clear_chat(self) -> None:
        self.history.clear()
        self.chat_view.clear()
        self.append_system("대화 기록을 지웠습니다.")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming convention
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(
                self, "작업 진행 중", "현재 음성/API 작업이 끝난 뒤 종료해 주세요."
            )
            event.ignore()
            return
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
