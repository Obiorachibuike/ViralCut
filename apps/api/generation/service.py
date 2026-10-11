"""Text-to-video service: prompt -> generated video stored like any other source.

Everything a normal upload gets, a generated video gets too: it is probed with
FFmpeg, stored under a stable key, thumbnailed, and handed back as a
`storageKey` so the orchestrator can create a `Video` row and run the ordinary
analyze -> moments -> clips pipeline on it.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

import httpx

from app.config import get_settings
from services.media import MediaProbe
from services.storage import create_storage

from .base import GenerationError, GenerationRequest, TextToVideoProvider
from .factory import create_provider

logger = logging.getLogger("viralcut.generation.service")

#: 512 MB ceiling — generated clips are short; this only guards against a
#: backend handing back something absurd.
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024


class GenerationService:
    def __init__(
        self,
        provider: TextToVideoProvider | None = None,
        probe: MediaProbe | None = None,
        on_stage: Callable[[str, int, str], None] | None = None,
    ) -> None:
        self._provider = provider
        self.probe = probe or MediaProbe()
        self.on_stage = on_stage or (lambda stage, pct, message: None)
        self.settings = get_settings()

    @property
    def provider(self) -> TextToVideoProvider:
        if self._provider is None:
            self._provider = create_provider()
        return self._provider

    def generate(self, *, prompt: str, run_id: str, **kwargs: Any) -> dict[str, Any]:
        provider = self.provider
        request = GenerationRequest(
            prompt=prompt,
            negative_prompt=kwargs.get("negativePrompt") or "",
            seconds=float(kwargs.get("seconds") or 5.0),
            aspect_ratio=kwargs.get("aspectRatio") or "9:16",
            seed=kwargs.get("seed"),
            model=kwargs.get("model"),
        ).validated(provider.max_seconds, provider.supported_aspects)

        if not request.prompt:
            raise GenerationError("A prompt is required.")
        if not provider.configured():
            raise GenerationError(
                f"{provider.label} is selected but not configured. Add its credentials "
                f"to enable text-to-video.",
                log_detail=f"provider={provider.name}",
            )

        self.settings.ensure_dirs()
        self.on_stage("GENERATING", 10, f"Generating with {provider.label}")

        def hook(fraction: float, message: str) -> None:
            pct = int(10 + max(0.0, min(1.0, fraction)) * 75)
            self.on_stage("GENERATING", pct, message)

        result = provider.generate(request, on_progress=hook)
        if not result.has_output:
            raise GenerationError(
                f"{provider.label} finished without producing a video.",
                log_detail=str(result.meta)[:500],
            )

        self.on_stage("GENERATING", 88, "Fetching generated footage")
        with tempfile.TemporaryDirectory(prefix="viralcut-t2v-") as tmp:
            local = Path(tmp) / "generated.mp4"
            self._materialize(result, local)

            self.on_stage("GENERATING", 92, "Inspecting generated video")
            info = self.probe.inspect(local)

            storage = create_storage()
            key = f"generated/{run_id}/source.mp4"
            storage.put_file(key, local, content_type="video/mp4")

            thumb_key: str | None = None
            try:
                thumb = Path(tmp) / "thumb.jpg"
                self.probe.thumbnail(local, thumb, 0)
                thumb_key = f"generated/{run_id}/thumb.jpg"
                storage.put_file(thumb_key, thumb, content_type="image/jpeg")
            except Exception:  # noqa: BLE001 - a missing thumbnail is not fatal
                logger.warning("thumbnail generation failed for run %s", run_id)
                thumb_key = None

            size_bytes = storage.size(key)

        self.on_stage("GENERATING", 100, "Generation complete")
        return {
            "storageKey": key,
            "thumbnailKey": thumb_key,
            "provider": result.provider,
            "model": result.model,
            "prompt": request.prompt,
            "negativePrompt": request.negative_prompt,
            "aspectRatio": request.aspect_ratio,
            "requestedSeconds": request.seconds,
            "durationMs": info.duration_ms,
            "width": info.width,
            "height": info.height,
            "fps": info.fps,
            "videoCodec": info.video_codec,
            "audioCodec": info.audio_codec,
            "hasAudio": info.has_audio,
            "sizeBytes": size_bytes,
            "providerJobId": result.provider_job_id,
            "meta": result.meta,
        }

    # -- internals ----------------------------------------------------------
    def _materialize(self, result: Any, dest: Path) -> None:
        """Normalise url / bytes / path outputs into a local file."""
        if result.video_path:
            shutil.copyfile(result.video_path, dest)
            return
        if result.video_bytes:
            dest.write_bytes(result.video_bytes)
            return
        if result.video_url:
            self._download(result.video_url, dest)
            return
        raise GenerationError("The provider returned no usable video output.")

    @staticmethod
    def _download(url: str, dest: Path) -> None:
        written = 0
        try:
            with httpx.Client(follow_redirects=True, timeout=600) as client:
                with client.stream("GET", url) as response:
                    if response.status_code >= 400:
                        raise GenerationError(
                            "Could not download the generated video "
                            f"(HTTP {response.status_code}).",
                            log_detail=url[:300],
                        )
                    with open(dest, "wb") as handle:
                        for chunk in response.iter_bytes(chunk_size=1024 * 512):
                            written += len(chunk)
                            if written > MAX_DOWNLOAD_BYTES:
                                raise GenerationError(
                                    "The generated video exceeded the 512 MB limit."
                                )
                            handle.write(chunk)
        except httpx.HTTPError as err:
            raise GenerationError(
                "Could not download the generated video.",
                log_detail=f"{err.__class__.__name__}: {err}",
            ) from err
        if written == 0:
            raise GenerationError("The generated video download was empty.")
