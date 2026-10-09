"""FFmpeg execution helper with real progress reporting.

`-progress pipe:1` gives machine-readable out_time_us lines, so render progress
is measured rather than guessed.
"""

from __future__ import annotations

import logging
import re
import subprocess
from typing import Callable, Sequence

from app.errors import MediaError

logger = logging.getLogger("viralcut.video.ffmpeg")

_OUT_TIME_RE = re.compile(r"out_time_ms=(\d+)")


def run_ffmpeg(
    argv: Sequence[str],
    *,
    timeout: int = 3600,
    progress_total_ms: int | None = None,
    on_progress: Callable[[int], None] | None = None,
    label: str = "ffmpeg",
) -> str:
    """Run FFmpeg, streaming progress. Returns combined stderr for diagnostics."""
    command = list(argv)
    if progress_total_ms and on_progress:
        command = [command[0], "-hide_banner", "-nostdin", "-progress", "pipe:1", *command[1:]]

    logger.debug("%s: %s", label, " ".join(command))
    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as err:
        raise MediaError("FFmpeg is not installed or not on PATH.") from err

    stderr_chunks: list[str] = []
    assert proc.stdout is not None and proc.stderr is not None
    try:
        for line in proc.stdout:
            match = _OUT_TIME_RE.search(line)
            if match and progress_total_ms and on_progress:
                done_ms = int(match.group(1)) // 1000
                on_progress(min(99, int(done_ms / progress_total_ms * 100)))
        error_output = proc.stderr.read()
        stderr_chunks.append(error_output)
        returncode = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as err:
        proc.kill()
        raise MediaError(
            "FFmpeg timed out. The clip may be too long or the codec unsupported.",
            log_detail="".join(stderr_chunks)[-1000:],
        ) from err

    if returncode != 0:
        raise MediaError(
            "Video rendering failed.",
            log_detail=("".join(stderr_chunks))[-1500:],
        )
    return "".join(stderr_chunks)


def escape_filter_path(path: str) -> str:
    """Escape a path for use inside an FFmpeg filtergraph argument."""
    return (
        path.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )
