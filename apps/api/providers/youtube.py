"""YouTube adapter.

Metadata comes from YouTube's public oEmbed endpoint (no authentication) and,
when `yt-dlp` is installed, from a `--simulate` run so we can see whether the
video is private, age-restricted, live or DRM-protected *before* downloading.

Policy: ViralCut never bypasses DRM, sign-in walls, age gates or download
restrictions. Anything requiring those is refused with a clear reason.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .base import SourceKind, SourceResolution, VideoSourceProvider

logger = logging.getLogger("viralcut.providers.youtube")

OEEMBED_URL = "https://www.youtube.com/oembed"

DRM_HINTS = ("drm", "widevine", "playready", "fairplay")


def _default_fetch_json(url: str, timeout: int = 15) -> tuple[int, dict[str, Any]]:
    """Tiny dependency-free GET so `resolve` works without httpx installed."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={"user-agent": "ViralCut/1.0 (+https://viralcut.app)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as err:  # 401/404 == private or removed
        return err.code, {}
    except Exception as err:  # network unreachable, DNS, TLS, timeout
        logger.warning("youtube oembed lookup failed: %s", err)
        return 0, {}


class YouTubeProvider(VideoSourceProvider):
    kind = SourceKind.YOUTUBE
    name = "youtube"
    hosts = (
        "youtube.com",
        "youtu.be",
        "youtube-nocookie.com",
        "music.youtube.com",
    )
    capability_note = (
        "Public YouTube videos only. Private, unlisted-with-sign-in, age-gated, "
        "live and DRM-protected videos are refused."
    )

    def __init__(
        self,
        *,
        ytdlp_path: str | None = None,
        fetch_json: Callable[[str, int], tuple[int, dict[str, Any]]] | None = None,
        runner: Callable[[list[str], int], tuple[int, str]] | None = None,
    ) -> None:
        self.ytdlp_path = ytdlp_path or shutil.which("yt-dlp")
        self._fetch_json = fetch_json or _default_fetch_json
        self._runner = runner or self._default_runner

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _default_runner(argv: list[str], timeout: int) -> tuple[int, str]:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    def extract_video_id(self, url: str) -> str | None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().lstrip("www.")
        if host == "youtu.be":
            candidate = parsed.path.split("/")[1:2]
            return candidate[0] if candidate else None
        parts = [p for p in parsed.path.split("/") if p]
        if parts and parts[0] in {"shorts", "live", "embed", "v"} and len(parts) > 1:
            return parts[1]
        query = parse_qs(parsed.query)
        values = query.get("v")
        return values[0] if values else None

    def is_playlist_only(self, url: str) -> bool:
        query = parse_qs(urlparse(url).query)
        return bool(query.get("list")) and not self.extract_video_id(url)

    # -- contract -----------------------------------------------------------
    def resolve(self, url: str) -> SourceResolution:
        if not self.enabled:
            return self.refuse(url, "YouTube import is disabled on this ViralCut instance.")

        if self.is_playlist_only(url):
            return self.refuse(
                url, "That link points at a playlist, not a single video. Paste one video URL."
            )

        video_id = self.extract_video_id(url)
        if not video_id:
            return self.refuse(url, "Could not find a video id in that YouTube URL.")

        base = SourceResolution(
            kind=self.kind,
            provider=self.name,
            permitted=True,
            input_url=url,
            external_id=video_id,
            meta={"videoId": video_id},
        )

        # 1. Cheap public check: oEmbed only answers for videos that are
        #    publicly embeddable. Private / removed videos return 401/404.
        status, payload = self._fetch_json(
            f"{OEEMBED_URL}?url=https%3A//www.youtube.com/watch%3Fv%3D{video_id}&format=json"
        )
        if status == 200 and payload:
            base.title = payload.get("title")
            base.uploader = payload.get("author_name")
            base.meta["oembed"] = payload
        elif status in (401, 403, 404):
            base.permitted = False
            base.is_private = True
            base.reason = (
                "This video appears to be private or unavailable. "
                "ViralCut does not bypass sign-in or privacy settings."
            )
            return base
        # status == 0 means the lookup itself failed (offline). Fall through to
        # yt-dlp, and if that is also absent we report the network problem.

        # 2. If yt-dlp is present, ask it for real metadata without downloading.
        if self.ytdlp_path:
            info = self._simulate(url)
            if not info:
                # An empty/failed probe carries no evidence either way. When
                # oEmbed also failed we have verified nothing, so refuse rather
                # than claiming the source is processable.
                if status == 0:
                    base.permitted = False
                    base.reason = (
                        "Could not reach YouTube to verify this video. "
                        "Check the network connection and try again."
                    )
                return base
            base.meta["probe"] = info
            base.title = base.title or info.get("title")
            base.uploader = base.uploader or info.get("uploader")
            if info.get("duration"):
                base.duration_seconds = float(info["duration"])
            base.is_live = bool(info.get("is_live"))

            if info.get("availability") in {"private", "needs_auth", "unlisted_needs_auth"}:
                base.permitted = False
                base.is_private = True
                base.requires_login = True
                base.reason = "This video is private or requires signing in. ViralCut never logs in on your behalf."
                return base
            if info.get("age_limit", 0) and info.get("age_limit") >= 18:
                base.permitted = False
                base.reason = "This video is age-restricted. ViralCut does not bypass age gates."
                return base
            if info.get("is_live"):
                base.permitted = False
                base.reason = "Live streams cannot be analysed. Wait for the broadcast to finish and import the VOD."
                return base
            if _looks_drm(info):
                base.permitted = False
                base.drm_protected = True
                base.reason = "This video is DRM-protected. ViralCut never circumvents DRM."
                return base

        elif status == 0:
            base.permitted = False
            base.reason = (
                "Could not reach YouTube to verify this video. "
                "Check the network connection and try again."
            )

        return base

    def fetch(self, resolution: SourceResolution, dest_path: str) -> dict[str, Any]:
        if not self.ytdlp_path:
            raise RuntimeError(
                "yt-dlp is not installed. Install it (`pip install yt-dlp`) to enable YouTube ingestion."
            )
        argv = [
            self.ytdlp_path,
            "--no-playlist",
            "--no-write-playlist-metafiles",
            # Refuse DRM formats outright rather than discovering it mid-download.
            "--format",
            "bestvideo[ext=mp4][protocol^=https]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format",
            "mp4",
            "--no-overwrites",
            "--restrict-filenames",
            "--output",
            dest_path,
            resolution.input_url,
        ]
        code, output = self._runner(argv, timeout=1800)
        if code != 0:
            lowered = output.lower()
            if "private video" in lowered or "sign in" in lowered:
                raise PermissionError("This video is private or requires signing in.")
            if any(h in lowered for h in DRM_HINTS):
                raise PermissionError("This video is DRM-protected and cannot be processed.")
            raise RuntimeError(f"yt-dlp exited with code {code}: {output[-500:]}")
        return {"tool": "yt-dlp", "videoId": resolution.external_id, "title": resolution.title}

    # -- internals ----------------------------------------------------------
    def _simulate(self, url: str) -> dict[str, Any] | None:
        assert self.ytdlp_path is not None
        argv = [self.ytdlp_path, "--no-playlist", "--skip-download", "--dump-single-json", url]
        try:
            code, output = self._runner(argv, timeout=120)
        except subprocess.TimeoutExpired:
            logger.warning("yt-dlp simulate timed out for %s", url)
            return None
        if code != 0:
            logger.warning("yt-dlp simulate failed (%s) for %s: %s", code, url, output[-300:])
            return None
        try:
            start = output.index("{")
            return json.loads(output[start:])
        except (ValueError, json.JSONDecodeError):
            return None


def _looks_drm(info: dict[str, Any]) -> bool:
    if info.get("drm"):
        return True
    for fmt in info.get("formats") or []:
        if fmt.get("has_drm"):
            return True
        name = str(fmt.get("format_note") or "").lower()
        if any(h in name for h in DRM_HINTS):
            return True
    return False
