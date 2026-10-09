"""Facebook adapter.

Only *public* Facebook videos. Group posts, friends-only posts, anything behind
a login and anything DRM-protected are refused — ViralCut never authenticates.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .base import SourceKind, SourceResolution, VideoSourceProvider

logger = logging.getLogger("viralcut.providers.facebook")


def _default_get_status(url: str, timeout: int = 15) -> int:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        url, method="GET", headers={"user-agent": "Mozilla/5.0 (compatible; ViralCut/1.0)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as err:
        return err.code
    except Exception as err:
        logger.warning("facebook lookup failed: %s", err)
        return 0


class FacebookProvider(VideoSourceProvider):
    kind = SourceKind.FACEBOOK
    name = "facebook"
    hosts = ("facebook.com", "fb.watch", "fb.com", "fb.me")
    capability_note = (
        "Public Facebook videos only. Group posts, friends-only posts and "
        "anything requiring a login are refused."
    )

    def __init__(
        self,
        *,
        ytdlp_path: str | None = None,
        status_getter: Callable[[str, int], int] | None = None,
        runner: Callable[[list[str], int], tuple[int, str]] | None = None,
    ) -> None:
        self.ytdlp_path = ytdlp_path or shutil.which("yt-dlp")
        self._status = status_getter or _default_get_status
        self._runner = runner or self._default_runner

    @staticmethod
    def _default_runner(argv: list[str], timeout: int) -> tuple[int, str]:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    def extract_video_id(self, url: str) -> str | None:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        for key in ("v", "video_id", "story_fbid"):
            if key in query:
                return query[key][0]
        parts = [p for p in parsed.path.split("/") if p]
        if "videos" in parts:
            idx = parts.index("videos")
            if idx + 1 < len(parts) and parts[idx + 1].isdigit():
                return parts[idx + 1]
        if "watch" in parts:
            idx = parts.index("watch")
            if idx + 1 < len(parts) and parts[idx + 1].isdigit():
                return parts[idx + 1]
        return None

    def is_group_url(self, url: str) -> bool:
        path = urlparse(url).path
        return "/groups/" in path

    def resolve(self, url: str) -> SourceResolution:
        if not self.enabled:
            return self.refuse(url, "Facebook import is disabled on this ViralCut instance.")

        if self.is_group_url(url):
            return self.refuse(
                url,
                "That is a Facebook group post. Group content is members-only, "
                "so ViralCut will not fetch it.",
            )

        video_id = self.extract_video_id(url)
        if not video_id:
            return self.refuse(
                url,
                "Could not find a video id in that Facebook URL. "
                "Use the direct video link (facebook.com/watch/?v=…).",
            )

        resolution = SourceResolution(
            kind=self.kind,
            provider=self.name,
            permitted=True,
            input_url=url,
            external_id=video_id,
            meta={"videoId": video_id},
        )

        status = self._status(url)
        if status in (401, 403):
            resolution.permitted = False
            resolution.requires_login = True
            resolution.reason = (
                "This Facebook video requires a login. ViralCut never signs in on your behalf."
            )
        elif status == 404:
            resolution.permitted = False
            resolution.reason = "This Facebook video was removed or is not publicly visible."
        elif status == 0:
            resolution.permitted = False
            resolution.reason = (
                "Could not reach Facebook to verify this video. "
                "Check the network connection and try again."
            )
        return resolution

    def fetch(self, resolution: SourceResolution, dest_path: str) -> dict[str, Any]:
        if not self.ytdlp_path:
            raise RuntimeError(
                "yt-dlp is not installed. Install it (`pip install yt-dlp`) to enable Facebook ingestion."
            )
        argv = [
            self.ytdlp_path,
            "--no-playlist",
            "--format",
            "best[ext=mp4]/best",
            "--no-overwrites",
            "--restrict-filenames",
            "--output",
            dest_path,
            resolution.input_url,
        ]
        code, output = self._runner(argv, timeout=900)
        if code != 0:
            lowered = output.lower()
            if "login" in lowered or "private" in lowered:
                raise PermissionError("This Facebook video requires a login or is private.")
            raise RuntimeError(f"yt-dlp exited with code {code}: {output[-500:]}")
        return {"tool": "yt-dlp", "videoId": resolution.external_id}
