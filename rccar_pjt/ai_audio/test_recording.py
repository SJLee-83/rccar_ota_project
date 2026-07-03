from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from audio_recorder import record_wav
from config import AppConfig


def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"))
    config = AppConfig.from_env()
    output = Path(__file__).with_name("microphone_test.wav")
    print(f"{config.record_seconds:g}초 동안 녹음합니다. 말씀하세요...")
    record_wav(
        output,
        config.record_seconds,
        config.audio_rate,
        config.audio_sample_bits,
        config.audio_channels,
        config.audio_input_device,
    )
    print(f"녹음 완료: {output}")


if __name__ == "__main__":
    main()
