"""Provider registry.

Two layers, deliberately separate:

* `classify(url)` — pure, offline routing. Given a URL, which adapter owns it?
  No network, no side effects. The TypeScript copy in `@viralcut/shared` mirrors
  this function; both are asserted against
  `packages/shared/src/__fixtures__/provider-cases.json`.
* `resolve(url)` — the authoritative policy check. Talks to the adapter, which
  may hit the network to confirm the source is public. This is what ingestion
  actually trusts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import parse_qs, urlparse

from .base import SourceKind, SourceResolution, VideoSourceProvider, is_private_host
from .facebook import FacebookProvider
from .generic import GenericProvider
from .tiktok import TikTokProvider
from .youtube import YouTubeProvider

logger = logging.getLogger("viralcut.providers.registry")

YOUTUBE_VIDEO_PATH_SEGMENTS = ("shorts", "live", "embed", "v")


@dataclass(slots=True, frozen=True)
class Classification:
    """Offline routing result — mirrors `detectProvider()` in @viralcut/shared."""

    kind: SourceKind
    provider: str
    external_id: str | None
    dedicated: bool
    permitted: bool
    reason: str | None = None


def _host(url: str) -> str:
    try:
        host = urlparse(url.strip()).hostname
    except ValueError:
        return ""
    return (host or "").lower().rstrip(".")


def _matches(host: str, candidates: Iterable[str]) -> bool:
    return any(host == c or host.endswith(f".{c}") for c in candidates)


YOUTUBE_HOSTS = (
    "youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "music.youtube.com",
)
TIKTOK_HOSTS = ("tiktok.com",)
FACEBOOK_HOSTS = ("facebook.com", "fb.watch", "fb.com", "fb.me")


def _youtube_id(parsed) -> str | None:
    host = (parsed.hostname or "").lower()
    if host == "youtu.be" or host.endswith(".youtu.be"):
        parts = [p for p in parsed.path.split("/") if p]
        return parts[0] if parts else None
    parts = [p for p in parsed.path.split("/") if p]
    if parts and parts[0] in YOUTUBE_VIDEO_PATH_SEGMENTS and len(parts) > 1:
        return parts[1]
    values = parse_qs(parsed.query).get("v")
    return values[0] if values else None


def _tiktok_id(path: str) -> str | None:
    parts = [p for p in path.split("/") if p]
    if "video" in parts:
        idx = parts.index("video")
        if idx + 1 < len(parts) and parts[idx + 1].isdigit():
            return parts[idx + 1]
    return None


def _facebook_id(parsed) -> str | None:
    query = parse_qs(parsed.query)
    for key in ("v", "video_id", "story_fbid"):
        if key in query:
            return query[key][0]
    parts = [p for p in parsed.path.split("/") if p]
    for marker in ("videos", "watch"):
        if marker in parts:
            idx = parts.index(marker)
            if idx + 1 < len(parts) and parts[idx + 1].isdigit():
                return parts[idx + 1]
    return None


def classify(url: str) -> Classification:
    """Pure URL routing. Never touches the network."""
    raw = (url or "").strip()
    if not raw:
        return Classification(SourceKind.GENERIC, "unknown", None, False, False,
                              "That does not look like a valid http(s) URL.")

    try:
        parsed = urlparse(raw)
    except ValueError:
        parsed = None

    if parsed is None or parsed.scheme not in ("http", "https"):
        return Classification(SourceKind.GENERIC, "unknown", None, False, False,
                              "That does not look like a valid http(s) URL.")

    host = _host(raw)

    if _matches(host, YOUTUBE_HOSTS):
        video_id = _youtube_id(parsed)
        if not video_id and parse_qs(parsed.query).get("list"):
            return Classification(
                SourceKind.YOUTUBE, "youtube", None, True, False,
                "That link points at a playlist, not a single video. Paste one video URL.",
            )
        return Classification(
            SourceKind.YOUTUBE, "youtube", video_id, True, True, None
        )

    if _matches(host, TIKTOK_HOSTS):
        return Classification(
            SourceKind.TIKTOK, "tiktok", _tiktok_id(parsed.path), True, True, None
        )

    if _matches(host, FACEBOOK_HOSTS):
        if "/groups/" in parsed.path:
            return Classification(
                SourceKind.FACEBOOK, "facebook", None, True, False,
                "That is a Facebook group post. Group content is members-only, "
                "so ViralCut will not fetch it.",
            )
        return Classification(
            SourceKind.FACEBOOK, "facebook", _facebook_id(parsed), True, True,
            "Only public Facebook videos can be processed. Private or group-only posts are refused.",
        )

    if is_private_host(host):
        return Classification(
            SourceKind.GENERIC, host, None, False, False,
            "Internal and loopback addresses cannot be imported.",
        )

    return Classification(SourceKind.GENERIC, host or "generic", None, False, True, None)


class ProviderRegistry:
    """Holds the enabled adapters. Adapters can be disabled without deletion."""

    def __init__(self, providers: Iterable[VideoSourceProvider] | None = None) -> None:
        self._providers: list[VideoSourceProvider] = list(providers) if providers is not None else [
            YouTubeProvider(),
            TikTokProvider(),
            FacebookProvider(),
            GenericProvider(),
        ]

    @property
    def providers(self) -> list[VideoSourceProvider]:
        return list(self._providers)

    def describe(self) -> list[dict[str, object]]:
        """Capability list for the UI (spec 39: disable gracefully, say why)."""
        return [
            {
                "kind": p.kind.value,
                "name": p.name,
                "enabled": p.enabled,
                "note": p.capability_note,
            }
            for p in self._providers
        ]

    def set_enabled(self, name: str, enabled: bool) -> None:
        for provider in self._providers:
            if provider.name == name:
                provider.enabled = enabled
                return
        raise KeyError(f"unknown provider: {name}")

    def for_url(self, url: str) -> VideoSourceProvider:
        for provider in self._providers:
            if provider.hosts and provider.matches(url):
                return provider
        # Terminal fallback.
        for provider in self._providers:
            if not provider.hosts:
                return provider
        raise ProviderLookupError(f"no provider available for {url!r}")

    def resolve(self, url: str) -> SourceResolution:
        """Authoritative check: routing + the adapter's own policy inspection."""
        classification = classify(url)
        if not classification.permitted:
            return SourceResolution(
                kind=classification.kind,
                provider=classification.provider,
                permitted=False,
                input_url=url,
                external_id=classification.external_id,
                reason=classification.reason,
            )
        provider = self.for_url(url)
        if not provider.enabled:
            return SourceResolution(
                kind=provider.kind,
                provider=provider.name,
                permitted=False,
                input_url=url,
                external_id=classification.external_id,
                reason=f"{provider.name} import is disabled on this ViralCut instance.",
            )
        try:
            return provider.resolve(url)
        except Exception as err:  # adapter bugs must never 500 the whole route
            logger.exception("provider %s failed to resolve %s", provider.name, url)
            return SourceResolution(
                kind=provider.kind,
                provider=provider.name,
                permitted=False,
                input_url=url,
                external_id=classification.external_id,
                reason=f"Could not verify that source ({err.__class__.__name__}).",
            )


class ProviderLookupError(Exception):
    pass


_default_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = ProviderRegistry()
    return _default_registry


def set_registry(registry: ProviderRegistry | None) -> None:
    """Test seam: swap in a registry built with injected adapters."""
    global _default_registry
    _default_registry = registry
