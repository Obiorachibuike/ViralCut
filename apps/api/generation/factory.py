"""Provider selection for text-to-video.

`VIRALCUT_T2V_PROVIDER` picks the active backend. Every registered backend is
reported by `describe_providers()` so the UI can show which ones a deployment
could enable and exactly what is missing — no silent no-ops.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings

from .base import TextToVideoProvider
from .hosted import FalProvider, LumaProvider, ReplicateProvider, RunwayProvider
from .longcat import LongCatTextToVideo

logger = logging.getLogger("viralcut.generation.factory")

#: Registry order == display order in the UI.
REGISTRY: dict[str, type[TextToVideoProvider]] = {
    LongCatTextToVideo.name: LongCatTextToVideo,
    FalProvider.name: FalProvider,
    ReplicateProvider.name: ReplicateProvider,
    LumaProvider.name: LumaProvider,
    RunwayProvider.name: RunwayProvider,
}


def all_providers() -> list[TextToVideoProvider]:
    return [cls() for cls in REGISTRY.values()]


def describe_providers() -> dict[str, Any]:
    """Honest capability matrix for the UI."""
    settings = get_settings()
    providers = [p.status() for p in all_providers()]
    active = settings.t2v_provider if settings.t2v_provider != "none" else None
    active_status = next((p for p in providers if p["name"] == active), None)
    return {
        "active": active,
        "activeConfigured": bool(active_status and active_status.get("configured")),
        "maxSeconds": settings.t2v_max_seconds,
        "providers": providers,
    }


def create_provider(name: str | None = None) -> TextToVideoProvider:
    """Instantiate the active (or explicitly requested) backend."""
    settings = get_settings()
    chosen = (name or settings.t2v_provider or "").strip().lower()
    if chosen in {"", "none", "disabled"}:
        raise ProviderNotConfigured(
            "Text-to-video is disabled on this instance. Set VIRALCUT_T2V_PROVIDER "
            "to one of: " + ", ".join(REGISTRY) + "."
        )
    if chosen not in REGISTRY:
        raise ProviderNotConfigured(
            f"Unknown text-to-video provider '{chosen}'. "
            f"Supported: {', '.join(REGISTRY)}."
        )
    return REGISTRY[chosen]()


class ProviderNotConfigured(RuntimeError):
    """Raised when no usable backend has been selected."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
