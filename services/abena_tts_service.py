"""Server-side Abena AI synthesis for AgriBotGH Twi responses."""

from __future__ import annotations

import base64
import logging
import os
import re
from typing import Any

import requests

import configuration  # noqa: F401 - loads the optional project-root .env


LOGGER = logging.getLogger(__name__)
DEFAULT_API_URL = "https://abena.mobobi.com/playground/api/v1/tts/synthesize/"
DEFAULT_TWI_VOICE = "abena_twi_lite"
DEFAULT_SPEED = 1.0
DEFAULT_TIMEOUT = (5, 120)
PROVIDER_MAX_CHARS = 500
CHUNK_TARGET_CHARS = 480
MAX_TTS_TEXT_LENGTH = 4000


def _environment_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _configured_speed() -> float:
    try:
        value = float(os.getenv("ABENA_TTS_SPEED", str(DEFAULT_SPEED)))
    except (TypeError, ValueError):
        return DEFAULT_SPEED
    return value if 0.5 <= value <= 2.0 else DEFAULT_SPEED


def chunk_twi_text(text: str, target: int = CHUNK_TARGET_CHARS) -> list[str]:
    """Split Unicode text near natural boundaries without exceeding 500 chars."""
    if not isinstance(text, str):
        raise TypeError("TTS text must be a string")
    if not isinstance(target, int) or not 1 <= target <= PROVIDER_MAX_CHARS:
        raise ValueError("Chunk target must be between 1 and 500 characters")

    remaining = re.sub(r"\s+", " ", text).strip()
    chunks: list[str] = []
    while remaining:
        if len(remaining) <= target:
            chunks.append(remaining)
            break

        window = remaining[: target + 1]
        minimum_natural_cut = max(1, int(target * 0.70))
        cut = 0
        for pattern in (r"[.!?;:]\s", r"[,]\s", r"\s"):
            matches = list(re.finditer(pattern, window))
            eligible = [match for match in matches if match.end() >= minimum_natural_cut]
            if eligible:
                cut = eligible[-1].end()
                break
        if not cut:
            cut = target

        chunk = remaining[:cut].strip()
        if not chunk:
            chunk = remaining[:target]
            cut = target
        chunks.append(chunk)
        remaining = remaining[cut:].strip()

    if any(len(chunk) > PROVIDER_MAX_CHARS for chunk in chunks):
        raise AssertionError("Abena TTS chunk exceeded provider limit")
    return chunks


class AbenaTTSService:
    """Synthesize Twi audio while keeping credentials and provider details server-side."""

    def __init__(
        self,
        session: Any = None,
        timeout: tuple[int, int] = DEFAULT_TIMEOUT,
        *,
        enabled: bool | None = None,
        api_url: str | None = None,
        voice: str | None = None,
        speed: float | None = None,
        api_key: str | None = None,
    ):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.enabled = _environment_flag("ABENA_TTS_ENABLED", False) if enabled is None else enabled
        self.api_url = (api_url or os.getenv("ABENA_TTS_API_URL") or DEFAULT_API_URL).strip()
        self.voice = (voice or os.getenv("ABENA_TTS_TWI_VOICE") or DEFAULT_TWI_VOICE).strip()
        self.speed = _configured_speed() if speed is None else speed
        configured_key = os.getenv("ABENA_API_KEY", "") if api_key is None else api_key
        self.api_key = configured_key.strip()

    def availability(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "provider": "abena",
            "voice": self.voice,
        }

    def synthesize(self, text: str) -> dict[str, Any]:
        if not self.enabled:
            return self._unavailable("disabled")

        chunks = chunk_twi_text(text)
        clips = []
        for chunk in chunks:
            result = self._synthesize_chunk(chunk)
            if not result.get("success"):
                return result
            clips.append(result["clip"])

        return {
            "success": True,
            "language": "twi",
            "provider": "abena",
            "voice": self.voice,
            "chunk_count": len(clips),
            "clips": clips,
        }

    def _synthesize_chunk(self, text: str) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = self.session.post(
                self.api_url,
                json={"text": text, "voice": self.voice, "speed": self.speed},
                headers=headers,
                timeout=self.timeout,
            )
        except requests.Timeout:
            LOGGER.warning("Abena TTS request failed: timeout")
            return self._unavailable("timeout")
        except requests.RequestException:
            LOGGER.warning("Abena TTS request failed: transport_error")
            return self._unavailable("provider_unavailable")
        except Exception:
            LOGGER.exception("Unexpected Abena TTS transport failure")
            return self._unavailable("provider_unavailable")

        if not 200 <= response.status_code < 300:
            code = self._http_error_code(response.status_code)
            LOGGER.warning("Abena TTS request failed: %s (HTTP %s)", code, response.status_code)
            return self._unavailable(code)

        try:
            payload = response.json()
        except (TypeError, ValueError):
            return self._unavailable("invalid_response")
        if not isinstance(payload, dict) or payload.get("status") != "success":
            return self._unavailable("invalid_response")

        audio = payload.get("audio_base64")
        if not isinstance(audio, str) or not audio.strip():
            return self._unavailable("invalid_response")
        audio = audio.strip()
        try:
            base64.b64decode(audio, validate=True)
        except (ValueError, TypeError):
            return self._unavailable("invalid_response")

        mime_type = payload.get("mime_type")
        if not isinstance(mime_type, str) or not mime_type.startswith("audio/"):
            mime_type = "audio/wav"
        duration = payload.get("duration_seconds")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            duration = None

        return {
            "success": True,
            "clip": {
                "audio_base64": audio,
                "mime_type": mime_type,
                "duration_seconds": duration,
            },
        }

    @staticmethod
    def _http_error_code(status_code: int) -> str:
        if status_code in {401, 403}:
            return "authentication_failed"
        if status_code == 402:
            return "credits_exhausted"
        if status_code == 413:
            return "provider_limit"
        if status_code == 429:
            return "rate_limited"
        return "provider_unavailable"

    @staticmethod
    def _unavailable(code: str) -> dict[str, Any]:
        return {
            "success": False,
            "error": "Natural Twi audio is temporarily unavailable.",
            "code": code,
            "fallback_allowed": True,
        }
