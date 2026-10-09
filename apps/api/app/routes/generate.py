"""Text-to-video routes.

Generation is long-running, so it follows the same async contract as
/v1/process: POST returns a runId immediately and the caller tracks progress via
GET /v1/runs/{id} (or the callback fan-out). Re-POSTing the same runId is a
no-op, which keeps retries idempotent.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends

from app.deps import verify_worker_token
from app.errors import DependencyUnavailableError, ViralCutError
from app.runs import get_registry
from app.schemas import TextToVideoRequest
from generation.base import GenerationError
from generation.factory import ProviderNotConfigured, create_provider, describe_providers
from generation.service import GenerationService

logger = logging.getLogger("viralcut.routes.generate")
router = APIRouter(prefix="/v1", tags=["generate"], dependencies=[Depends(verify_worker_token)])


@router.get("/generate/providers")
async def providers() -> dict[str, Any]:
    """Which text-to-video backends this instance can actually use, and why not."""
    return describe_providers()


@router.post("/generate/text-to-video")
async def text_to_video(body: TextToVideoRequest) -> dict[str, Any]:
    registry = get_registry()
    existing = registry.get(body.runId)
    if existing is not None:
        return {"runId": body.runId, "state": existing.state, "queued": False}

    # Fail fast (before creating a run) when no backend is usable, so the caller
    # gets a 503 with a clear reason instead of a run that can never finish.
    try:
        create_provider(body.provider)
    except ProviderNotConfigured as err:
        raise DependencyUnavailableError(err.message) from err

    registry.create(body.runId)
    registry.set_state(body.runId, "QUEUED", progress=0)
    asyncio.create_task(_run(body))
    return {"runId": body.runId, "state": "QUEUED", "queued": True}


async def _run(body: TextToVideoRequest) -> None:
    registry = get_registry()

    def on_stage(stage: str, progress: int, message: str) -> None:
        registry.add_event(body.runId, stage, progress, message)
        registry.set_state(body.runId, stage, progress=progress)

    try:
        service = GenerationService(
            provider=create_provider(body.provider),
            on_stage=on_stage,
        )
        payload = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: service.generate(
                prompt=body.prompt,
                run_id=body.runId,
                negativePrompt=body.negativePrompt,
                seconds=body.seconds,
                aspectRatio=body.aspectRatio,
                seed=body.seed,
                model=body.model,
            ),
        )
        registry.finish(body.runId, result=payload)
    except (GenerationError, ProviderNotConfigured) as err:
        detail = getattr(err, "log_detail", None)
        if detail:
            logger.error("generation failed for run %s: %s", body.runId, detail)
        registry.finish(body.runId, error=str(err), error_code="generation_failed")
    except ViralCutError as err:
        registry.finish(body.runId, error=err.message, error_code=err.code)
    except Exception:  # pragma: no cover - defensive
        logger.exception("generation crashed for run %s", body.runId)
        registry.finish(
            body.runId,
            error="Video generation failed unexpectedly.",
            error_code="internal_error",
        )
