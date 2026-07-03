from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests

from config import AppConfig


SYSTEM_PROMPT = (
    "너는 라즈베리파이 차량에 탑재된 한국어 음성 비서다. "
    "친절하고 정확하게 답하되 음성으로 듣기 좋게 3~5문장 이내로 간결하게 답한다. "
    "실제로 수행하지 않은 차량 제어나 외부 작업을 수행했다고 말하지 않는다."
)

COMMAND_PROMPT = (
    "너는 RC카 음성 명령 해석기다. 사용자의 한국어/영어 문장을 차량 명령 JSON으로만 변환한다. "
    "허용 command는 start, go, back, left, right, mid, stop 뿐이다. "
    "명확한 차량 제어 명령이 아니면 command를 unknown으로 둔다. "
    "응답은 설명 없이 JSON 하나만 출력한다. "
    '형식: {"command":"go","confidence":0.95,"reason":"앞으로 이동 요청"}'
)

COMMAND_ALIASES = (
    ("stop", ("정지", "멈춰", "멈추", "스톱", "stop", "브레이크")),
    ("start", ("시작", "출발 준비", "start")),
    ("go", ("앞", "앞으로", "전진", "직진", "go", "forward")),
    ("back", ("뒤", "뒤로", "후진", "back", "reverse")),
    ("left", ("왼", "좌", "좌회전", "left")),
    ("right", ("오른", "우", "우회전", "right")),
    ("mid", ("중앙", "가운데", "센터", "정렬", "mid", "center")),
)


def rule_based_command(text: str) -> dict[str, object] | None:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    if not normalized:
        return None
    for command, aliases in COMMAND_ALIASES:
        if any(alias in normalized for alias in aliases):
            return {
                "command": command,
                "confidence": 0.99,
                "reason": "규칙 기반 명령 매칭",
            }
    return None


class GMSClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {config.gms_key}"})

    def _error_message(self, response: requests.Response) -> str:
        try:
            body: Any = response.json()
            if isinstance(body, dict):
                error = body.get("error", body)
                if isinstance(error, dict):
                    return str(error.get("message") or error)
                return str(error)
        except (ValueError, json.JSONDecodeError):
            pass
        return response.text[:500] or f"HTTP {response.status_code}"

    def _raise_for_status(self, response: requests.Response) -> None:
        if not response.ok:
            raise RuntimeError(
                f"GMS API 오류 ({response.status_code}): {self._error_message(response)}"
            )

    def transcribe(self, wav_path: Path) -> str:
        with wav_path.open("rb") as audio_file:
            response = self.session.post(
                f"{self.config.base_url}/audio/transcriptions",
                data={"model": self.config.stt_model, "language": "ko"},
                files={"file": (wav_path.name, audio_file, "audio/wav")},
                timeout=(10, self.config.request_timeout_seconds),
            )
        self._raise_for_status(response)
        text = str(response.json().get("text", "")).strip()
        if not text:
            raise RuntimeError("STT 응답에 변환된 텍스트가 없습니다.")
        return text

    def chat(self, history: list[dict[str, str]], user_text: str) -> str:
        messages = [{"role": "developer", "content": SYSTEM_PROMPT}]
        messages.extend(history[-12:])
        messages.append({"role": "user", "content": user_text})
        response = self.session.post(
            f"{self.config.base_url}/chat/completions",
            headers={"Content-Type": "application/json"},
            json={
                "model": self.config.chat_model,
                "messages": messages,
            },
            timeout=(10, self.config.request_timeout_seconds),
        )
        self._raise_for_status(response)
        try:
            text = response.json()["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise RuntimeError("GPT 응답 형식을 해석할 수 없습니다.") from exc
        if not text:
            raise RuntimeError("GPT 응답이 비어 있습니다.")
        return text

    def interpret_vehicle_command(self, user_text: str) -> dict[str, object]:
        direct = rule_based_command(user_text)
        if direct is not None:
            return direct

        response = self.session.post(
            f"{self.config.base_url}/chat/completions",
            headers={"Content-Type": "application/json"},
            json={
                "model": self.config.chat_model,
                "messages": [
                    {"role": "developer", "content": COMMAND_PROMPT},
                    {"role": "user", "content": user_text},
                ],
            },
            timeout=(10, self.config.request_timeout_seconds),
        )
        self._raise_for_status(response)
        try:
            raw = response.json()["choices"][0]["message"]["content"].strip()
            if raw.startswith("```"):
                raw = raw.strip("`")
                raw = raw.removeprefix("json").strip()
            parsed = json.loads(raw)
        except (KeyError, IndexError, TypeError, AttributeError, json.JSONDecodeError) as exc:
            raise RuntimeError("차량 명령 해석 응답 형식을 해석할 수 없습니다.") from exc

        command = str(parsed.get("command", "unknown")).strip().lower()
        if command not in {"start", "go", "back", "left", "right", "mid", "stop", "unknown"}:
            command = "unknown"
        confidence = float(parsed.get("confidence", 0.0) or 0.0)
        reason = str(parsed.get("reason", "") or "")
        return {"command": command, "confidence": confidence, "reason": reason}

    def synthesize(self, text: str, output_path: Path) -> Path:
        # Keep a conservative margin under the TTS model's 2,000-token input
        # limit. Normal responses are already constrained to 3-5 sentences.
        if len(text) > 3000:
            text = text[:3000]
        response = self.session.post(
            f"{self.config.base_url}/audio/speech",
            headers={"Content-Type": "application/json"},
            json={
                "model": self.config.tts_model,
                "input": text,
                "voice": self.config.tts_voice,
                "response_format": "mp3",
            },
            timeout=(10, self.config.request_timeout_seconds),
        )
        self._raise_for_status(response)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)
        if output_path.stat().st_size == 0:
            raise RuntimeError("TTS 음성 파일이 비어 있습니다.")
        return output_path
