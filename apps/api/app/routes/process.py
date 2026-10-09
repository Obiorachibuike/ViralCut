from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from fastapi import Depends
from app.deps import verify_worker_token
from app.errors import ViralCutError
from app.runs import get_registry
from app.schemas import ProcessRequest, RunState
from moments.discover import DiscoverOptions
from services.pipeline import Pipeline

logger = logging.getLogger("viralcut.routes.process")
router = APIRouter(prefix="/v1", tags=["process"], dependencies=[Depends(verify_worker_token)])


def _to_options(body: ProcessRequest) -> DiscoverOptions:
    weights = None
    if body.weights:
        weights = {k: v for k, v in body.weights.model_dump().items() if v is not None}
    return DiscoverOptions(
        max_candidates=body.maxCandidates,
        min_score=body.minScore,
        min_duration_s=body.minDurationSec,
        max_duration_s=body.maxDurationSec,
        pad_before_s=body.padBeforeSec,
        pad_after_s=body.padAfterSec,
        categories=tuple(body.categories) if body.categories else None,
        weights=weights,
        dedupe_threshold=body.dedupeThreshold,
        limit=body.limit,
    )


@router.post("/process")
async def process(body: ProcessRequest) -> dict[str, Any]:
    registry = get_registry()
    if registry.get(body.runId) is not None:
        # Idempotent: re-enqueueing the same run is a no-op.
        return {"runId": body.runId, "state": registry.get(body.runId).state, "queued": False}
    registry.create(body.runId)
    registry.set_state(body.runId, "QUEUED", progress=0)

    options = _to_options(body)
    asyncio.create_task(_run(body, options))
    return {"runId": body.runId, "state": "QUEUED", "queued": True}


async def _run(body: ProcessRequest, options: DiscoverOptions) -> None:
    registry = get_registry()
    loop = asyncio.get_running_loop()

    def on_stage(stage: str, progress: int, message: str) -> None:
        registry.add_event(body.runId, stage, progress, message)
        registry.set_state(body.runId, stage, progress=progress)

    try:
        pipeline = Pipeline(on_stage=on_stage)
        result = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: pipeline.process(
                storage_key=body.storageKey,
                run_id=body.runId,
                options=options,
                language=body.language,
                skip_diarization=body.skipDiarization,
            ),
        )
        _ = loop
        payload = result_to_payload(result)
        registry.finish(body.runId, result=payload)
    except ViralCutError as err:
        registry.finish(body.runId, error=err.message, error_code=err.code)
    except Exception as err:  # pragma: no cover - defensive
        logger.exception("pipeline crashed for run %s", body.runId)
        registry.finish(body.runId, error="Unexpected processing error.",
                        error_code="internal_error")


def result_to_payload(result: Any) -> dict[str, Any]:
    return {
        "media": result.media,
        "transcript": result.transcript,
        "transcriptKey": result.artifacts.get("transcript"),
        "srtKey": result.artifacts.get("srt"),
        "vttKey": result.artifacts.get("vtt"),
        "audioKey": result.artifacts.get("audio"),
        "speakers": result.speakers,
        "scenes": result.scenes,
        "moments": result.moments,
        "artifacts": result.artifacts,
        "engine": result.engine,
        "promptVersion": result.prompt_version,
        "model": result.model,
        "skippedStages": result.stages,
    }


@router.get("/runs/{run_id}", response_model=RunState)
async def get_run(run_id: str) -> RunState:
    run = get_registry().get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown run id")
    return RunState(
        runId=run.run_id,
        state=run.state,
        progress=run.progress,
        events=run.events,
        result=run.result,
        error=run.error,
        errorCode=run.error_code,
    )
