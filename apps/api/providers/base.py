"""VideoSourceProvider — the ingestion abstraction.

Every supported origin implements this protocol. The rest of ViralCut only ever
talks to `SourceResolution`, so adding a provider never touches the pipeline.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse


class SourceKind(StrEnum):
    UPLOAD = "UPLOAD"
    YOUTUBE = "YOUTUBE"
    TIKTOK = "TIKTOK"
    FACEBOOK = "FACEBOOK"
    GENERIC = "GENERIC"


class SourceState(StrEnum):
    RESOLVED = "RESOLVED"
    DOWNLOADING = "DOWNLOADING"
    DOWNLOADED = "DOWNLOADED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


@dataclass(slots=True)
class SourceResolution:
    """Outcome of inspecting a URL, *before* any bytes are fetched."""

    kind: SourceKind
    provider: str
    permitted: bool
    input_url: str
    external_id: str | None = None
    title: str | None = None
    uploader: str | None = None
    duration_seconds: float | None = None
    is_live: bool = False
    is_private: bool = False
    requires_login: bool = False
    drm_protected: bool = False
    reason: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def rejected(self) -> bool:
        return not self.permitted


class VideoSourceProvider(ABC):
    """Adapter contract for one origin platform."""

    kind: SourceKind
    name: str
    #: Hosts this adapter claims. Matched as an exact host or a dotted suffix.
    hosts: tuple[str, ...] = ()
    #: Set False to disable an adapter without deleting it (spec 39).
    enabled: bool = True
    #: Human-readable capability line surfaced in the UI.
    capability_note: str = ""

    # -- matching -----------------------------------------------------------
    def matches(self, url: str) -> bool:
        host = urlparse(url).hostname
        if not host:
            return False
        host = host.lower().rstrip(".")
        return any(host == h or host.endswith(f".{h}") for h in self.hosts)

    # -- resolution ---------------------------------------------------------
    @abstractmethod
    def resolve(self, url: str) -> SourceResolution:
        """Inspect the URL and decide whether ViralCut may process it.

        Implementations MUST NOT bypass DRM, authentication or paywalls. When a
        source needs any of those, return `permitted=False` with a reason.
        """

    # -- ingestion ----------------------------------------------------------
    @abstractmethod
    def fetch(self, resolution: SourceResolution, dest_path: str) -> dict[str, Any]:
        """Download permitted media to `dest_path`. Returns provider metadata."""

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def looks_like_video_id(value: str | None, pattern: str = r"^[A-Za-z0-9_-]{6,}$") -> bool:
        return bool(value and re.match(pattern, value))

    def refuse(self, url: str, reason: str) -> SourceResolution:
        return SourceResolution(
            kind=self.kind,
            provider=self.name,
            permitted=False,
            input_url=url,
            reason=reason,
        )


def is_private_host(host: str) -> bool:
    """Block loopback / RFC1918 / link-local hosts (SSRF guard).

    Mirrors `isPrivateHost()` in @viralcut/shared — both sides are asserted
    against the same fixture set. The ingest worker runs inside the VPC, so a
    pasted metadata-service or localhost URL must never be fetched.
    """
    if not host:
        return False
    host = host.lower().rstrip(".")
    if host in ("localhost", "metadata.google.internal"):
        return True
    if host.startswith(("127.", "10.", "192.168.", "169.254.", "0.")):
        return True
    if host.startswith("172."):
        parts = host.split(".")
        if len(parts) > 1 and parts[1].isdigit() and 16 <= int(parts[1]) <= 31:
            return True
    if ":" in host:
        stripped = host.strip("[]").lower()
        return stripped == "::1" or stripped.startswith("fe80")
    return False
