from __future__ import annotations

from audio_recorder import list_input_devices


def main() -> None:
    devices = list_input_devices()
    if not devices:
        print("PyAudio에서 사용할 수 있는 입력 장치가 없습니다.")
        return
    print("INDEX | CHANNELS | DEFAULT RATE | NAME")
    for index, name, channels, rate in devices:
        print(f"{index:5d} | {channels:8d} | {rate:12.0f} | {name}")


if __name__ == "__main__":
    main()
