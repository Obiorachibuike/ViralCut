"""LongCat-Video GPU worker client.

LongCat is an *optional*, independently-deployed GPU service (spec 24, 30). It
is used only for AI B-roll / generated visual inserts — never for ordinary
clipping. The client degrades cleanly: when the worker is absent or the call
fails, the clip renders without the insert and a warning is recorded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger("viralcut.ai.longcat")


@dataclass(slots=True)
class BrollInsert:
    prompt: str
    negative_prompt: str
    seconds: float
    aspect_ratio: str = "9:16"


class LongCatClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.enabled = settings.longcat_enabled
        self.url = settings.longcat_api_url.rstrip("/") if settings.longcat_api_url else ""
        self.token = settings.longcat_worker_token
        self.timeout = settings.longcat_timeout_seconds

    @property
    def available(self) -> bool:
        return self.enabled and bool(self.url)

    def health(self) -> dict[str, Any]:
        if not self.available:
            return {"enabled": self.enabled, "available": False, "reason": "not configured"}
        try:
            response = httpx.get(f"{self.url}/health", headers=self._headers(), timeout=10)
            return {"enabled": True, "available": response.status_code == 200, "detail": response.json() if response.ok else None}
        except Exception as err:
            return {"enabled": True, "available": False, "reason": str(err.__class__.__name__)}

    def generate(self, insert: BrollInsert) -> dict[str, Any] | None:
        """Ask the GPU worker to produce footage. Returns None on any failure."""
        if not self.available:
            return None
        try:
            response = httpx.post(
                f"{self.url}/v1/generate",
                headers=self._headers(),
                json={
                    "prompt": insert.prompt,
                    "negativePrompt": insert.negative_prompt,
                    "seconds": insert.seconds,
                    "aspectRatio": insert.aspect_ratio,
                },
                timeout=self.timeout,
            )
            if response.status_code != 200:
                logger.warning("LongCat worker returned %s", response.status_code)
                return None
            return response.json()
        except Exception as err:
            logger.warning("LongCat worker unreachable (%s); skipping B-roll", err)
            return None

    def _headers(self) -> dict[str, str]:
        headers = {}
        if self.token:
            headers["authorization"] = f"Bearer {self.token}"
        return headers
