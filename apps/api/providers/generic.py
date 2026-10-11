"""Generic adapter: any publicly reachable direct media URL.

This is the fallback for anything without a dedicated adapter (a CDN link, an
S3 presigned URL, a conference recording, a podcast MP4 …). It refuses
anything that answers with an auth challenge, a paywall, or a non-media body.
"""

from __future__ import annotations

import logging
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from .base import SourceKind, SourceResolution, VideoSourceProvider, is_private_host

logger = logging.getLogger("viralcut.providers.generic")

MEDIA_EXTENSIONS = (".mp4", ".mov", ".webm", ".mkv", ".m4v", ".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac")
MEDIA_CONTENT_TYPES = ("video/", "audio/")


class GenericProvider(VideoSourceProvider):
    kind = SourceKind.GENERIC
    name = "generic"
    hosts = ()  # matches anything not claimed by another adapter
    capability_note = (
        "Any publicly reachable media URL. Login walls, paywalls and "
        "non-media responses are refused."
    )

    def __init__(
        self,
        *,
        max_bytes: int = 8 * 1024 * 1024 * 1024,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.max_bytes = max_bytes
        self._client_factory = client_factory or (lambda: httpx.Client(follow_redirects=True, timeout=30))

    def matches(self, url: str) -> bool:
        return True  # terminal fallback

    def has_media_extension(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        return path.endswith(MEDIA_EXTENSIONS)

    def resolve(self, url: str) -> SourceResolution:
        if not self.enabled:
            return self.refuse(url, "Generic URL import is disabled on this ViralCut instance.")

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return self.refuse(url, "Only http(s) URLs can be imported.")
        if not parsed.hostname:
            return self.refuse(url, "That URL has no host.")
        # Never let a caller point the engine at the loopback/private network.
        if is_private_host(parsed.hostname or ""):
            return self.refuse(url, "Internal and loopback addresses cannot be imported.")

        resolution = SourceResolution(
            kind=self.kind,
            provider=parsed.hostname or "generic",
            permitted=True,
            input_url=url,
            meta={"host": parsed.hostname},
        )
        resolution.meta["extensionHint"] = self.has_media_extension(url)

        try:
            with self._client_factory() as client:
                head = client.head(url)
                # Some CDNs reject HEAD; retry with a ranged GET.
                if head.status_code in (403, 405):
                    head = client.get(url, headers={"range": "bytes=0-0"})
                status = head.status_code
                headers = dict(head.headers)
                final_url = str(head.url)
        except httpx.HTTPError as err:
            resolution.permitted = False
            resolution.reason = f"Could not reach that URL: {err.__class__.__name__}."
            return resolution

        resolution.meta["finalUrl"] = final_url

        if status in (401, 403):
            resolution.permitted = False
            resolution.requires_login = True
            resolution.reason = (
                "That URL requires authentication or is not publicly accessible. "
                "ViralCut never bypasses a login or a paywall."
            )
            return resolution
        if status == 404:
            resolution.permitted = False
            resolution.reason = "That URL returned 404 — the file is missing."
            return resolution
        if status >= 400:
            resolution.permitted = False
            resolution.reason = f"That URL returned HTTP {status}."
            return resolution

        content_type = (headers.get("content-type") or "").split(";")[0].strip().lower()
        length_header = headers.get("content-length")
        if content_type and not content_type.startswith(MEDIA_CONTENT_TYPES):
            if content_type in ("text/html", "application/xhtml+xml"):
                resolution.permitted = False
                resolution.reason = (
                    "That URL serves an HTML page, not a media file. "
                    "Paste a direct link to the video or audio file."
                )
                return resolution
            resolution.meta["contentType"] = content_type

        if length_header and length_header.isdigit():
            size = int(length_header)
            resolution.meta["sizeBytes"] = size
            if size > self.max_bytes:
                resolution.permitted = False
                resolution.reason = (
                    f"That file is {size / 1e9:.1f} GB, over the "
                    f"{self.max_bytes / 1e9:.1f} GB ingest limit for this plan."
                )
                return resolution

        return resolution

    def fetch(self, resolution: SourceResolution, dest_path: str) -> dict[str, Any]:
        written = 0
        with self._client_factory() as client, open(dest_path, "wb") as handle:
            with client.stream("GET", resolution.input_url) as response:
                if response.status_code >= 400:
                    raise RuntimeError(f"Download failed with HTTP {response.status_code}")
                content_type = (response.headers.get("content-type") or "").lower()
                if content_type.startswith("text/html"):
                    raise PermissionError("The URL returned an HTML page instead of media.")
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    written += len(chunk)
                    if written > self.max_bytes:
                        raise ValueError("Download exceeded the configured ingest limit.")
                    handle.write(chunk)
        return {"bytes": written, "finalUrl": resolution.meta.get("finalUrl", resolution.input_url)}
