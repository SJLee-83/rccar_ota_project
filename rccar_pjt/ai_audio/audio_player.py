from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def play_mp3(path: Path, alsa_device: str | None = None) -> None:
    mpg123 = shutil.which("mpg123")
    if mpg123:
        command = [mpg123, "-q"]
        if alsa_device:
            command.extend(["-a", alsa_device])
        command.append(str(path))
    else:
        ffplay = shutil.which("ffplay")
        if not ffplay:
            raise RuntimeError("MP3 재생기가 없습니다. sudo apt install mpg123 를 실행하세요.")
        command = [ffplay, "-nodisp", "-autoexit", "-loglevel", "error", str(path)]

    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"음성 재생 실패(return code={result.returncode})")
