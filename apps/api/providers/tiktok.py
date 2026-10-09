"""TikTok adapter.

Public TikTok posts only. Short links (vm.tiktok.com / vt.tiktok.com) are
resolved by following redirects with a plain HTTP HEAD/GET — no scraping of
private profiles and no authentication.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from typing import Any, Callable
from urllib.parse import urlparse

from .base import SourceKind, SourceResolution, VideoSourceProvider

logger = logging.getLogger("viralcut.providers.tiktok")

VIDEO_PATH_RE = re.compile(r"/video/(?P<id>\d{6,})")
OEMBED_URL = "https://www.tiktok.com/oembed?url={url}"


def _default_get(url: str, timeout: int = 15) -> tuple[int, str, str]:
    """Returns (status, final_url, body). Redirects are followed."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        url, headers={"user-agent": "Mozilla/5.0 (compatible; ViralCut/1.0)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.geturl(), resp.read(64 * 1024).decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, err.url or url, ""
    except Exception as err:
        logger.warning("tiktok lookup failed: %s", err)
        return 0, url, ""


class TikTokProvider(VideoSourceProvider):
    kind = SourceKind.TIKTOK
    name = "tiktok"
    hosts = ("tiktok.com", "vm.tiktok.com", "vt.tiktok.com")
    capability_note = "Public TikTok videos only. Private accounts and deleted posts are refused."

    def __init__(
        self,
        *,
        ytdlp_path: str | None = None,
        getter: Callable[[str, int], tuple[int, str, str]] | None = None,
        runner: Callable[[list[str], int], tuple[int, str]] | None = None,
    ) -> None:
        self.ytdlp_path = ytdlp_path or shutil.which("yt-dlp")
        self._get = getter or _default_get
        self._runner = runner or self._default_runner

    @staticmethod
    def _default_runner(argv: list[str], timeout: int) -> tuple[int, str]:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    def extract_video_id(self, url: str) -> str | None:
        match = VIDEO_PATH_RE.search(urlparse(url).path)
        return match.group("id") if match else None

    def resolve(self, url: str) -> SourceResolution:
        if not self.enabled:
            return self.refuse(url, "TikTok import is disabled on this ViralCut instance.")

        resolved_url = url
        video_id = self.extract_video_id(url)

        # Short links carry no id; follow the redirect to get one.
        if not video_id:
            status, final_url, _ = self._get(url)
            if status == 0:
                return self.refuse(
                    url, "Could not reach TikTok to resolve that short link. Try the full video URL."
                )
            if status in (403, 404, 410):
                return self.refuse(
                    url,
                    "This TikTok appears to be private, removed or unavailable. "
                    "ViralCut does not bypass privacy settings.",
                )
            resolved_url = final_url
            video_id = self.extract_video_id(final_url)
            if not video_id:
                return self.refuse(
                    url, "That TikTok link does not point at a single public video."
                )

        resolution = SourceResolution(
            kind=self.kind,
            provider=self.name,
            permitted=True,
            input_url=resolved_url,
            external_id=video_id,
            meta={"videoId": video_id, "originalUrl": url},
        )

        status, _, body = self._get(OEMBED_URL.format(url=resolved_url))
        if status == 200 and body:
            try:
                payload = json.loads(body)
                resolution.title = payload.get("title")
                resolution.uploader = payload.get("author_name")
                resolution.meta["oembed"] = payload
            except json.JSONDecodeError:
                pass
        elif status in (400, 403, 404):
            resolution.permitted = False
            resolution.is_private = True
            resolution.reason = (
                "This TikTok video is private or unavailable. "
                "ViralCut only processes publicly accessible content."
            )

        return resolution

    def fetch(self, resolution: SourceResolution, dest_path: str) -> dict[str, Any]:
        if not self.ytdlp_path:
            raise RuntimeError(
                "yt-dlp is not installed. Install it (`pip install yt-dlp`) to enable TikTok ingestion."
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
            if "private" in lowered or "login" in lowered:
                raise PermissionError("This TikTok video is private or requires signing in.")
            raise RuntimeError(f"yt-dlp exited with code {code}: {output[-500:]}")
        return {"tool": "yt-dlp", "videoId": resolution.external_id}
