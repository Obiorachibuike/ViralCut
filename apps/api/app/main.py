"""ViralCut media engine — FastAPI application.

Stateless processing service. Long-running work is kicked off as background
tasks; the orchestrator (Next.js) tracks progress via callbacks or by polling
GET /v1/runs/{id}. The engine never talks to the browser and never exposes
storage credentials or AI keys.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.errors import ViralCutError, unhandled_exception_handler, viralcut_exception_handler
from app.routes import broll, generate, health, ingest, process, render, storage
from app.runs import get_registry

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("viralcut.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry = get_registry()
    registry.attach_loop(asyncio.get_running_loop())
    logger.info(
        "ViralCut media engine starting (storage=%s, port=%s)",
        get_settings().storage_backend,
        get_settings().port,
    )
    yield
    logger.info("ViralCut media engine shutting down")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ViralCut Media Engine",
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_exception_handler(ViralCutError, viralcut_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(ingest.router)
    app.include_router(process.router)
    app.include_router(render.router)
    app.include_router(broll.router)
    app.include_router(generate.router)
    app.include_router(storage.router)
    return app


app = create_app()
