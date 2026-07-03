from __future__ import annotations

import wave
from pathlib import Path

import pyaudio


def list_input_devices() -> list[tuple[int, str, int, float]]:
    audio = pyaudio.PyAudio()
    devices: list[tuple[int, str, int, float]] = []
    try:
        for index in range(audio.get_device_count()):
            info = audio.get_device_info_by_index(index)
            if int(info.get("maxInputChannels", 0)) > 0:
                devices.append(
                    (
                        index,
                        str(info.get("name", "unknown")),
                        int(info.get("maxInputChannels", 0)),
                        float(info.get("defaultSampleRate", 0)),
                    )
                )
    finally:
        audio.terminate()
    return devices


def record_wav(
    output_path: Path,
    seconds: float,
    rate: int = 48000,
    sample_bits: int = 32,
    channels: int = 2,
    input_device_index: int | None = None,
) -> Path:
    audio = pyaudio.PyAudio()
    stream = None
    audio_format = pyaudio.paInt32 if sample_bits == 32 else pyaudio.paInt16
    frames: list[bytes] = []
    chunk = 1024
    try:
        stream = audio.open(
            format=audio_format,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=input_device_index,
            frames_per_buffer=chunk,
        )
        frame_count = int(rate / chunk * seconds)
        for _ in range(frame_count):
            frames.append(stream.read(chunk, exception_on_overflow=False))
        sample_width = audio.get_sample_size(audio_format)
    finally:
        if stream is not None:
            stream.stop_stream()
            stream.close()
        audio.terminate()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(rate)
        wav_file.writeframes(b"".join(frames))
    return output_path
