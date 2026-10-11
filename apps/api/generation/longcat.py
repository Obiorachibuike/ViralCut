"""LongCat-Video text-to-video backend.

LongCat is ViralCut's self-hosted GPU worker. Unlike the hosted adapters it does
not need a third-party key — only `LONGCAT_ENABLED` and `LONGCAT_API_URL` — which
makes it the default choice for on-prem deployments.

Contract (implemented by the worker in `infrastructure/workers`):

    POST {LONGCAT_API_URL}/v1/generate
      -> {"status": "completed", "videoUrl"|"videoBase64": ..., "durationSeconds": n}
      -> {"status": "processing", "jobId": "..."}      (we poll /v1/jobs/{id})

The B-roll path (`ai/longcat.py`) stays separate: it must keep degrading to
"no insert" so ordinary clipping never depends on a GPU being online.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

import httpx

from app.config import get_settings

from .base import (
    GenerationError,
    GenerationRequest,
    GenerationResult,
    ProgressHook,
    TextToVideoProvider,
)

logger = logging.getLogger("viralcut.generation.longcat")


class LongCatTextToVideo(TextToVideoProvider):
    name = "longcat"
    label = "LongCat-Video (self-hosted GPU)"
    max_seconds = 12.0
    supported_aspects = ("9:16", "1:1", "16:9", "4:5")

    def __init__(self) -> None:
        settings = get_settings()
        self.enabled = settings.longcat_enabled
        self.base_url = settings.longcat_api_url.rstrip("/") if settings.longcat_api_url else ""
        self.token = settings.longcat_worker_token
        self.timeout = settings.longcat_timeout_seconds
        self.max_seconds = max(self.max_seconds, get_settings().t2v_max_seconds)

    def configured(self) -> bool:
        return self.enabled and bool(self.base_url)

    def status(self) -> dict[str, Any]:
        base = super().status()
        base["requiresNetwork"] = False
        if not self.enabled:
            base["reason"] = "LONGCAT_ENABLED is false"
        elif not self.base_url:
            base["reason"] = "LONGCAT_API_URL is not set"
        return base

    def _headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.token}"} if self.token else {}

    def generate(
        self,
        request: GenerationRequest,
        on_progress: ProgressHook | None = None,
    ) -> GenerationResult:
        if not self.configured():
            raise GenerationError(
                "LongCat-Video is not enabled on this instance.",
                log_detail="LONGCAT_ENABLED/LONGCAT_API_URL missing",
            )

        payload = {
            "prompt": request.prompt,
            "negativePrompt": request.negative_prompt,
            "seconds": request.seconds,
            "aspectRatio": request.aspect_ratio,
            "seed": request.seed,
            "mode": "text_to_video",
        }
        if request.model:
            payload["model"] = request.model

        if on_progress:
            on_progress(0.05, "Submitting to the LongCat GPU worker")

        try:
            response = httpx.post(
                f"{self.base_url}/v1/generate",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
        except httpx.HTTPError as err:
            raise GenerationError(
                "Could not reach the LongCat GPU worker.",
                log_detail=f"{err.__class__.__name__}: {err}",
            ) from err

        if response.status_code >= 400:
            raise GenerationError(
                f"The LongCat worker rejected the request (HTTP {response.status_code}).",
                log_detail=response.text[:800],
            )

        body = response.json()
        job_id = body.get("jobId") or body.get("id")

        if body.get("status") == "processing" and job_id:
            body = self._poll(job_id, on_progress)

        return self._to_result(body, request)

    def _poll(self, job_id: str, on_progress: ProgressHook | None) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            time.sleep(2.0)
            try:
                response = httpx.get(
                    f"{self.base_url}/v1/jobs/{job_id}",
                    headers=self._headers(),
                    timeout=30,
                )
            except httpx.HTTPError:
                continue
            if response.status_code >= 400:
                continue
            body = response.json()
            status = str(body.get("status", "")).lower()
            if on_progress:
                on_progress(min(0.9, float(body.get("progress", 0.5))), f"LongCat: {status}")
            if status in {"completed", "succeeded", "success"}:
                return body
            if status in {"failed", "error", "cancelled"}:
                raise GenerationError(
                    "LongCat generation failed.",
                    log_detail=str(body.get("error"))[:800],
                )
        raise GenerationError("LongCat generation timed out.", log_detail=f"jobId={job_id}")

    def _to_result(self, body: dict[str, Any], request: GenerationRequest) -> GenerationResult:
        url = body.get("videoUrl") or body.get("url")
        b64 = body.get("videoBase64") or body.get("video")
        data: bytes | None = None
        if not url and isinstance(b64, str):
            try:
                data = base64.b64decode(b64, validate=True)
            except Exception as err:  # noqa: BLE001
                raise GenerationError(
                    "LongCat returned video data that could not be decoded.",
                    log_detail=f"{err.__class__.__name__}: {err}",
                ) from err

        if not url and not data:
            raise GenerationError(
                "LongCat finished but returned no video.",
                log_detail=str(body)[:800],
            )

        return GenerationResult(
            provider=self.name,
            model=str(body.get("model") or request.model or "longcat-video"),
            video_url=url,
            video_bytes=data,
            duration_seconds=body.get("durationSeconds"),
            width=body.get("width"),
            height=body.get("height"),
            provider_job_id=body.get("jobId") or body.get("id"),
            meta={"backend": "longcat", "seed": body.get("seed", request.seed)},
        )
