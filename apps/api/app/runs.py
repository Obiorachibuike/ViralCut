from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger("viralcut.runs")

_MAX_RUNS = 256


@dataclass(slots=True)
class RunState:
    run_id: str
    state: str = "QUEUED"
    progress: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def create(self, run_id: str) -> RunState:
        run = RunState(run_id=run_id)
        self._runs[run_id] = run
        if len(self._runs) > _MAX_RUNS:
            oldest = next(iter(self._runs))
            self._runs.pop(oldest, None)
        return run

    def get(self, run_id: str) -> RunState | None:
        return self._runs.get(run_id)

    def set_state(self, run_id: str, state: str, *, progress: int | None = None) -> None:
        run = self._runs.get(run_id)
        if not run:
            return
        run.state = state
        if progress is not None:
            run.progress = progress

    def add_event(self, run_id: str, stage: str, progress: int, message: str) -> None:
        run = self._runs.get(run_id)
        if not run:
            return
        run.progress = progress
        run.events.append({"stage": stage, "progress": progress, "message": message, "at": time.time()})
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._callback(run_id, stage, progress, message))
            )

    def finish(self, run_id: str, *, result: dict[str, Any] | None = None, error: str | None = None,
               error_code: str | None = None) -> None:
        run = self._runs.get(run_id)
        if not run:
            return
        run.state = "COMPLETED" if error is None else "FAILED"
        run.result = result
        run.error = error
        run.error_code = error_code
        run.progress = 100 if error is None else run.progress
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._callback_done(run_id))
            )

    async def _callback(self, run_id: str, stage: str, progress: int, message: str) -> None:
        await self._post({"type": "stage", "runId": run_id, "stage": stage,
                          "progress": progress, "message": message})

    async def _callback_done(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        await self._post({
            "type": "done",
            "runId": run_id,
            "state": run.state if run else "FAILED",
            "result": run.result if run else None,
            "error": run.error if run else None,
            "errorCode": run.error_code if run else None,
        })

    async def _post(self, payload: dict[str, Any]) -> None:
        settings = get_settings()
        base = settings.callback_base_url
        if not base:
            return
        headers = {}
        if settings.callback_token:
            headers["x-viralcut-callback-token"] = settings.callback_token
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(base.rstrip("/") + "/api/internal/media-callbacks",
                                  json=payload, headers=headers)
        except Exception as err:
            logger.debug("callback to orchestrator failed (%s); orchestrator will poll", err)


_registry = RunRegistry()


def get_registry() -> RunRegistry:
    return _registry
