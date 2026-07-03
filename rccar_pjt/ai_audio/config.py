from __future__ import annotations

import os
from dataclasses import dataclass


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    return int(value) if value else None


@dataclass(frozen=True)
class AppConfig:
    gms_key: str
    base_url: str
    stt_model: str
    chat_model: str
    tts_model: str
    tts_voice: str
    record_seconds: float
    audio_rate: int
    audio_sample_bits: int
    audio_channels: int
    audio_input_device: int | None
    audio_output_device: str | None
    request_timeout_seconds: int

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            gms_key=os.getenv("GMS_KEY", "").strip(),
            base_url=os.getenv(
                "GMS_BASE_URL",
                "https://gms.ssafy.io/gmsapi/api.openai.com/v1",
            ).rstrip("/"),
            stt_model=os.getenv("STT_MODEL", "whisper-1").strip(),
            chat_model=os.getenv("CHAT_MODEL", "gpt-5.4-mini").strip(),
            tts_model=os.getenv("TTS_MODEL", "gpt-4o-mini-tts").strip(),
            tts_voice=os.getenv("TTS_VOICE", "nova").strip(),
            record_seconds=float(os.getenv("RECORD_SECONDS", "5")),
            audio_rate=int(os.getenv("AUDIO_RATE", "48000")),
            audio_sample_bits=int(os.getenv("AUDIO_SAMPLE_BITS", "32")),
            audio_channels=int(os.getenv("AUDIO_CHANNELS", "2")),
            audio_input_device=_optional_int("AUDIO_INPUT_DEVICE"),
            audio_output_device=os.getenv("AUDIO_OUTPUT_DEVICE", "").strip() or None,
            request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "120")),
        )

    def validate(self) -> None:
        if not self.gms_key:
            raise ValueError("GMS_KEY가 없습니다. .env 파일에 GMS_KEY를 설정하세요.")
        if self.audio_sample_bits not in (16, 32):
            raise ValueError("AUDIO_SAMPLE_BITS는 16 또는 32만 사용할 수 있습니다.")
        if self.audio_channels not in (1, 2):
            raise ValueError("AUDIO_CHANNELS는 1 또는 2만 사용할 수 있습니다.")
        if self.record_seconds <= 0:
            raise ValueError("RECORD_SECONDS는 0보다 커야 합니다.")
