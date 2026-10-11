"""Hosted text-to-video backends.

Each adapter follows its vendor's documented REST API. They are selected by
`VIRALCUT_T2V_PROVIDER` and are inert until the matching key is present, so a
deployment that never sets a key simply reports "not configured" — it never
pretends to generate.

All four share the same shape: submit a generation, poll until it finishes, hand
back a URL the service layer downloads and stores.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import get_settings

from .base import (
    RATIO_DIMENSIONS,
    GenerationError,
    GenerationRequest,
    GenerationResult,
    ProgressHook,
    TextToVideoProvider,
)

logger = logging.getLogger("viralcut.generation.hosted")

POLL_INTERVAL_S = 3.0


class _PollingProvider(TextToVideoProvider):
    """Shared submit-then-poll machinery."""

    api_base: str = ""
    poll_path: str = ""

    def __init__(self) -> None:
        self.timeout = get_settings().t2v_timeout_seconds
        self.max_seconds = max(self.max_seconds, get_settings().t2v_max_seconds)

    # -- vendor hooks -------------------------------------------------------
    def headers(self) -> dict[str, str]:
        raise NotImplementedError

    def submit_payload(self, request: GenerationRequest) -> dict[str, Any]:
        raise NotImplementedError

    def extract_job_id(self, body: dict[str, Any]) -> str | None:
        raise NotImplementedError

    def extract_state(self, body: dict[str, Any]) -> tuple[str, float]:
        """Return (state, progress 0..1) where state is pending|running|succeeded|failed."""
        raise NotImplementedError

    def extract_output(self, body: dict[str, Any]) -> GenerationResult:
        raise NotImplementedError

    # -- shared flow --------------------------------------------------------
    def generate(
        self,
        request: GenerationRequest,
        on_progress: ProgressHook | None = None,
    ) -> GenerationResult:
        if not self.configured():
            raise GenerationError(
                f"{self.label} is not configured. Add its API key to enable it.",
                log_detail=f"provider={self.name}",
            )

        if on_progress:
            on_progress(0.05, f"Submitting prompt to {self.label}")

        try:
            response = httpx.post(
                self.submit_url(request),
                headers=self.headers(),
                json=self.submit_payload(request),
                timeout=120,
            )
        except httpx.HTTPError as err:
            raise GenerationError(
                f"Could not reach {self.label}.",
                log_detail=f"{err.__class__.__name__}: {err}",
            ) from err

        if response.status_code >= 400:
            raise GenerationError(
                f"{self.label} rejected the request (HTTP {response.status_code}).",
                log_detail=response.text[:800],
            )

        body = response.json()
        # Some backends answer synchronously.
        state, _ = self.extract_state(body)
        if state == "succeeded":
            return self.extract_output(body)
        if state == "failed":
            raise GenerationError(
                f"{self.label} failed the generation.",
                log_detail=str(body)[:800],
            )

        job_id = self.extract_job_id(body)
        if not job_id:
            raise GenerationError(
                f"{self.label} returned no job id to poll.",
                log_detail=str(body)[:800],
            )
        return self._poll(job_id, request, on_progress)

    def submit_url(self, request: GenerationRequest) -> str:  # noqa: ARG002
        return self.api_base

    def _poll(
        self,
        job_id: str,
        request: GenerationRequest,
        on_progress: ProgressHook | None,
    ) -> GenerationResult:
        deadline = time.monotonic() + self.timeout
        url = f"{self.poll_path}/{job_id}"
        while time.monotonic() < deadline:
            time.sleep(POLL_INTERVAL_S)
            try:
                response = httpx.get(url, headers=self.headers(), timeout=60)
            except httpx.HTTPError:
                continue
            if response.status_code >= 400:
                continue
            body = response.json()
            state, progress = self.extract_state(body)
            if on_progress:
                on_progress(min(0.95, max(0.1, progress)), f"{self.label}: {state}")
            if state == "succeeded":
                return self.extract_output(body)
            if state == "failed":
                raise GenerationError(
                    f"{self.label} generation failed.",
                    log_detail=str(body.get("error") or body)[:800],
                )
        raise GenerationError(
            f"{self.label} generation timed out.",
            log_detail=f"jobId={job_id}",
        )


class FalProvider(_PollingProvider):
    """fal.ai — synchronous `fal.run` endpoints (fast models return a URL directly)."""

    name = "fal"
    label = "fal.ai"
    max_seconds = 10.0
    supported_aspects = ("9:16", "1:1", "16:9", "4:5")
    default_model = "fal-ai/kling-video/v2.1/standard/text-to-video"

    def __init__(self) -> None:
        super().__init__()
        self.api_key = get_settings().fal_api_key
        self.model = get_settings().t2v_model or self.default_model

    def configured(self) -> bool:
        return bool(self.api_key)

    def headers(self) -> dict[str, str]:
        return {"authorization": f"Key {self.api_key}", "content-type": "application/json"}

    def submit_url(self, request: GenerationRequest) -> str:
        model = request.model or self.model
        return f"https://fal.run/{model}"

    def submit_payload(self, request: GenerationRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "prompt": request.prompt,
            "aspect_ratio": request.aspect_ratio,
            "duration": int(round(request.seconds)),
        }
        if request.negative_prompt:
            payload["negative_prompt"] = request.negative_prompt
        if request.seed is not None:
            payload["seed"] = request.seed
        return payload

    def extract_job_id(self, body: dict[str, Any]) -> str | None:
        return body.get("request_id") or body.get("id")

    def extract_state(self, body: dict[str, Any]) -> tuple[str, float]:
        if "video" in body or "videos" in body:
            return "succeeded", 1.0
        status = str(body.get("status", "")).lower()
        if status in {"completed", "succeeded"}:
            return "succeeded", 1.0
        if status in {"failed", "error"}:
            return "failed", 1.0
        return "running", 0.5

    def extract_output(self, body: dict[str, Any]) -> GenerationResult:
        video = body.get("video") or {}
        url = video.get("url")
        if not url and body.get("videos"):
            url = body["videos"][0].get("url")
        if not url:
            raise GenerationError(
                "fal.ai returned no video URL.", log_detail=str(body)[:800]
            )
        return GenerationResult(
            provider=self.name,
            model=self.model,
            video_url=url,
            duration_seconds=video.get("duration"),
            provider_job_id=body.get("request_id"),
            meta={"backend": "fal", "seed": body.get("seed")},
        )


class ReplicateProvider(_PollingProvider):
    """Replicate predictions API (any text-to-video model version)."""

    name = "replicate"
    label = "Replicate"
    max_seconds = 10.0
    supported_aspects = ("9:16", "1:1", "16:9", "4:5")
    api_base = "https://api.replicate.com/v1/predictions"
    poll_path = "https://api.replicate.com/v1/predictions"

    def __init__(self) -> None:
        super().__init__()
        self.token = get_settings().replicate_api_token
        self.model = get_settings().t2v_model  # "owner/name" or a full version hash

    def configured(self) -> bool:
        return bool(self.token) and bool(self.model)

    def status(self) -> dict[str, Any]:
        base = super().status()
        if self.token and not self.model:
            base["reason"] = "Set VIRALCUT_T2V_MODEL to a Replicate model, e.g. 'kwaivgi/kling-v2.1'"
        return base

    def headers(self) -> dict[str, str]:
        return {
            "authorization": f"Bearer {self.token}",
            "content-type": "application/json",
            "prefer": "wait",
        }

    def submit_payload(self, request: GenerationRequest) -> dict[str, Any]:
        width, height = RATIO_DIMENSIONS.get(request.aspect_ratio, (720, 1280))
        payload: dict[str, Any] = {
            "input": {
                "prompt": request.prompt,
                "aspect_ratio": request.aspect_ratio,
                "width": width,
                "height": height,
                "duration": int(round(request.seconds)),
            }
        }
        if request.negative_prompt:
            payload["input"]["negative_prompt"] = request.negative_prompt
        # A bare "owner/name" uses the latest version via /models; a hash pins one.
        if "/" in self.model and len(self.model.split("/")) == 2:
            payload["model"] = self.model
        else:
            payload["version"] = self.model
        return payload

    def extract_job_id(self, body: dict[str, Any]) -> str | None:
        return body.get("id")

    def extract_state(self, body: dict[str, Any]) -> tuple[str, float]:
        status = str(body.get("status", "")).lower()
        mapping = {"starting": "running", "processing": "running", "succeeded": "succeeded",
                   "failed": "failed", "canceled": "failed"}
        return mapping.get(status, "running"), 0.5

    def extract_output(self, body: dict[str, Any]) -> GenerationResult:
        output = body.get("output")
        url: str | None = None
        if isinstance(output, str):
            url = output
        elif isinstance(output, list) and output:
            url = output[0] if isinstance(output[0], str) else output[0].get("url")
        elif isinstance(output, dict):
            url = output.get("video") or output.get("url")
        if not url:
            raise GenerationError(
                "Replicate returned no video URL.", log_detail=str(body)[:800]
            )
        return GenerationResult(
            provider=self.name,
            model=self.model,
            video_url=url,
            provider_job_id=body.get("id"),
            meta={"backend": "replicate", "metrics": body.get("metrics")},
        )


class LumaProvider(_PollingProvider):
    """Luma Dream Machine generations API."""

    name = "luma"
    label = "Luma Dream Machine"
    max_seconds = 9.0
    supported_aspects = ("9:16", "1:1", "16:9")
    api_base = "https://api.lumalabs.ai/dream-machine/v1/generations"
    poll_path = "https://api.lumalabs.ai/dream-machine/v1/generations"

    def __init__(self) -> None:
        super().__init__()
        self.api_key = get_settings().luma_api_key
        self.model = get_settings().t2v_model or "ray-2"

    def configured(self) -> bool:
        return bool(self.api_key)

    def headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.api_key}", "content-type": "application/json"}

    def submit_payload(self, request: GenerationRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "prompt": request.prompt,
            "aspect_ratio": request.aspect_ratio,
            "model": request.model or self.model,
        }
        if request.negative_prompt:
            payload["negative_prompt"] = request.negative_prompt
        return payload

    def extract_job_id(self, body: dict[str, Any]) -> str | None:
        return body.get("id")

    def extract_state(self, body: dict[str, Any]) -> tuple[str, float]:
        state = str(body.get("state", "")).lower()
        mapping = {"queued": "running", "dreaming": "running", "completed": "succeeded",
                   "failed": "failed"}
        return mapping.get(state, "running"), 0.5

    def extract_output(self, body: dict[str, Any]) -> GenerationResult:
        assets = body.get("assets") or {}
        url = assets.get("video")
        if not url:
            raise GenerationError(
                "Luma returned no video URL.", log_detail=str(body)[:800]
            )
        return GenerationResult(
            provider=self.name,
            model=str(body.get("model") or self.model),
            video_url=url,
            duration_seconds=body.get("duration"),
            width=body.get("width"),
            height=body.get("height"),
            provider_job_id=body.get("id"),
            meta={"backend": "luma", "seed": body.get("seed")},
        )


class RunwayProvider(_PollingProvider):
    """RunwayML tasks API (text_to_video)."""

    name = "runway"
    label = "Runway"
    max_seconds = 10.0
    supported_aspects = ("9:16", "1:1", "16:9", "4:5")
    api_base = "https://api.dev.runwayml.com/v1/text_to_video"
    poll_path = "https://api.dev.runwayml.com/v1/tasks"

    def __init__(self) -> None:
        super().__init__()
        self.api_key = get_settings().runway_api_key
        self.model = get_settings().t2v_model or "gen4_turbo"

    def configured(self) -> bool:
        return bool(self.api_key)

    def headers(self) -> dict[str, str]:
        return {
            "authorization": f"Bearer {self.api_key}",
            "content-type": "application/json",
            "x-runway-version": "2024-11-06",
        }

    def submit_payload(self, request: GenerationRequest) -> dict[str, Any]:
        width, height = RATIO_DIMENSIONS.get(request.aspect_ratio, (720, 1280))
        return {
            "model": request.model or self.model,
            "promptText": request.prompt,
            "ratio": f"{width}:{height}",
            "duration": int(round(request.seconds)),
        }

    def extract_job_id(self, body: dict[str, Any]) -> str | None:
        return body.get("id")

    def extract_state(self, body: dict[str, Any]) -> tuple[str, float]:
        status = str(body.get("status", "")).upper()
        mapping = {"PENDING": "running", "RUNNING": "running", "THROTTLED": "running",
                   "SUCCEEDED": "succeeded", "FAILED": "failed", "CANCELLED": "failed"}
        progress = float(body.get("progress") or 0.5)
        return mapping.get(status, "running"), progress

    def extract_output(self, body: dict[str, Any]) -> GenerationResult:
        output = body.get("output") or []
        url = output[0] if output else None
        if not url:
            raise GenerationError(
                "Runway returned no video URL.", log_detail=str(body)[:800]
            )
        return GenerationResult(
            provider=self.name,
            model=str(body.get("model") or self.model),
            video_url=url,
            provider_job_id=body.get("id"),
            meta={"backend": "runway"},
        )
