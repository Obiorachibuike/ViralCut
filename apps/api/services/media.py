"""Media inspection.

Primary path is `ffprobe -print_format json`. When only a bare `ffmpeg` binary
is available (common with static bundles such as imageio-ffmpeg) we fall back to
parsing `ffmpeg -i` stderr, which yields the same facts.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.errors import MediaError

logger = logging.getLogger("viralcut.media")


@dataclass(slots=True)
class MediaInfo:
    path: str
    duration_ms: int = 0
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    audio_channels: int | None = None
    audio_sample_rate: int | None = None
    bitrate: int | None = None
    size_bytes: int = 0
    container: str | None = None
    has_audio: bool = False
    has_video: bool = False
    rotation: int = 0
    streams: list[dict[str, Any]] = field(default_factory=list)
    prober: str = "ffprobe"

    @property
    def aspect_ratio(self) -> float | None:
        if self.width and self.height:
            return round(self.width / self.height, 4)
        return None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
# FFmpeg 7 emits `Stream #0:0[0x1](und): Video: h264 (Constrained Baseline) (avc1 / 0x...), ...`
# so the track id may be followed by a bracketed stream id and a parenthesised language tag.
_STREAM_RE = re.compile(
    r"Stream\s+#\d+(?::\d+)?(?:\[[^\]]*\])?(?:\([^)]*\))?:\s*"
    r"(?P<kind>Video|Audio):\s*(?P<codec>[^,]+)(?P<rest>.*)"
)
_INPUT_RE = re.compile(r"Input\s+#\d+,\s*([^,]+(?:,[^,]+)*?),\s*from\s")
_CHANNEL_RE = re.compile(r"(?:(\d+)\s+channels|(mono|stereo)|(\d+(?:\.\d+)?)\s*\()")
_VIDEO_DIM_RE = re.compile(r"(\d{2,5})x(\d{2,5})")
_FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*fps")
_BITRATE_RE = re.compile(r"bitrate:\s*(\d+)\s*kb/s")
_ROTATE_RE = re.compile(r"rotate\s*:\s*(-?\d+)")
_DISPLAYMATRIX_RE = re.compile(r"rotation of\s*(-?\d+(?:\.\d+)?)\s*degrees")


def resolve_ffmpeg(preferred: str = "ffmpeg") -> str | None:
    """Locate an ffmpeg binary, falling back to the imageio-ffmpeg static build."""
    found = shutil.which(preferred)
    if found:
        return found
    try:
        import imageio_ffmpeg

        candidate = imageio_ffmpeg.get_ffmpeg_exe()
        if candidate and Path(candidate).exists():
            return candidate
    except Exception:  # pragma: no cover - optional dependency
        pass
    return None


def resolve_ffprobe(preferred: str = "ffprobe", ffmpeg: str | None = None) -> str | None:
    found = shutil.which(preferred)
    if found:
        return found
    # Static bundles usually ship ffmpeg only.
    if ffmpeg:
        sibling = Path(ffmpeg).with_name("ffprobe")
        if sibling.exists():
            return str(sibling)
    return None


class MediaProbe:
    def __init__(self, ffmpeg_path: str | None = None, ffprobe_path: str | None = None) -> None:
        self.ffmpeg = ffmpeg_path or resolve_ffmpeg()
        self.ffprobe = ffprobe_path or resolve_ffprobe(ffmpeg=self.ffmpeg)
        if not self.ffmpeg:
            raise MediaError(
                "FFmpeg was not found. Install FFmpeg, or `pip install imageio-ffmpeg` "
                "for a bundled static binary, and set FFMPEG_PATH."
            )

    # -- capabilities -------------------------------------------------------
    _filter_cache: dict[str, bool] | None = None

    def supports_filter(self, name: str) -> bool:
        """True when this FFmpeg build provides `name` (e.g. ass, drawtext)."""
        if MediaProbe._filter_cache is None:
            try:
                proc = subprocess.run(
                    [self.ffmpeg, "-hide_banner", "-filters"],
                    capture_output=True, text=True, timeout=60, check=False,
                )
                MediaProbe._filter_cache = {
                    line.split()[1]
                    for line in (proc.stdout or "").splitlines()
                    if len(line.split()) > 1 and line[0:4].strip()
                }
            except Exception:  # pragma: no cover
                MediaProbe._filter_cache = set()
        return name in MediaProbe._filter_cache

    # -- public -------------------------------------------------------------
    def inspect(self, path: str | Path) -> MediaInfo:
        path = Path(path)
        if not path.exists():
            raise MediaError("The media file is missing.", details={"path": str(path)})

        info: MediaInfo
        if self.ffprobe:
            info = self._inspect_ffprobe(path)
        else:
            info = self._inspect_ffmpeg_stderr(path)

        info.size_bytes = path.stat().st_size
        return info

    def extract_audio(
        self,
        video_path: str | Path,
        dest: str | Path,
        *,
        sample_rate: int = 16000,
        channels: int = 1,
        timeout: int = 1800,
    ) -> Path:
        """16 kHz mono WAV — what Whisper and pyannote both want."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(video_path),
            "-vn", "-sn", "-dn",
            "-ac", str(channels), "-ar", str(sample_rate),
            "-c:a", "pcm_s16le",
            str(dest),
        ]
        self._run(argv, timeout=timeout)
        if not dest.exists() or dest.stat().st_size == 0:
            raise MediaError("Audio extraction produced an empty file.")
        return dest

    def thumbnail(self, video_path: str | Path, dest: str | Path, at_ms: int, *, width: int = 480) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-ss", f"{max(0, at_ms) / 1000:.3f}", "-i", str(video_path),
            "-frames:v", "1", "-vf", f"scale={width}:-2", str(dest),
        ]
        self._run(argv, timeout=120)
        return dest

    # -- internals ----------------------------------------------------------
    def _inspect_ffprobe(self, path: Path) -> MediaInfo:
        argv = [
            self.ffprobe, "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
        except FileNotFoundError as err:
            raise MediaError("ffprobe is not runnable.") from err
        except subprocess.TimeoutExpired as err:
            raise MediaError("ffprobe timed out while inspecting the file.") from err
        if proc.returncode != 0:
            raise MediaError(
                "Could not read that media file. It may be corrupt or use an unsupported codec.",
                log_detail=proc.stderr[-800:],
            )
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as err:
            raise MediaError("ffprobe returned unparseable output.") from err

        info = MediaInfo(path=str(path), prober="ffprobe")
        fmt = data.get("format") or {}
        if fmt.get("duration"):
            info.duration_ms = int(float(fmt["duration"]) * 1000)
        if fmt.get("bit_rate"):
            info.bitrate = int(fmt["bit_rate"])
        names = (fmt.get("format_name") or "").split(",")
        info.container = names[0] if names and names[0] else None

        for stream in data.get("streams") or []:
            info.streams.append(
                {
                    "index": stream.get("index"),
                    "codec_type": stream.get("codec_type"),
                    "codec_name": stream.get("codec_name"),
                    "width": stream.get("width"),
                    "height": stream.get("height"),
                }
            )
            kind = stream.get("codec_type")
            if kind == "video" and not info.has_video:
                info.has_video = True
                info.video_codec = stream.get("codec_name")
                info.width = stream.get("width")
                info.height = stream.get("height")
                fps = _parse_fps(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
                info.fps = fps
                tags = stream.get("tags") or {}
                if tags.get("rotate"):
                    info.rotation = int(tags["rotate"])
                for side in stream.get("side_data_list") or []:
                    if "rotation" in side:
                        info.rotation = int(side["rotation"])
            elif kind == "audio" and not info.has_audio:
                info.has_audio = True
                info.audio_codec = stream.get("codec_name")
                info.audio_channels = stream.get("channels")
                rate = stream.get("sample_rate")
                info.audio_sample_rate = int(rate) if rate else None

        if not info.has_video and not info.has_audio:
            raise MediaError("That file contains no audio or video stream.")
        return info

    def _inspect_ffmpeg_stderr(self, path: Path) -> MediaInfo:
        """Fallback probe for builds that ship ffmpeg without ffprobe."""
        argv = [self.ffmpeg, "-hide_banner", "-i", str(path)]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
        except subprocess.TimeoutExpired as err:
            raise MediaError("ffmpeg timed out while inspecting the file.") from err
        output = proc.stderr or ""
        # `ffmpeg -i` with no output file always exits non-zero; that is expected.
        if "Duration:" not in output and "Stream #" not in output:
            raise MediaError(
                "Could not read that media file. It may be corrupt or use an unsupported codec.",
                log_detail=output[-800:],
            )

        info = MediaInfo(path=str(path), prober="ffmpeg-stderr")
        if match := _DURATION_RE.search(output):
            hours, minutes, seconds = match.groups()
            info.duration_ms = int((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000)
        if match := _BITRATE_RE.search(output):
            info.bitrate = int(match.group(1)) * 1000
        if match := _ROTATE_RE.search(output) or _DISPLAYMATRIX_RE.search(output):
            info.rotation = int(float(match.group(1)))

        if container := _INPUT_RE.search(output):
            info.container = container.group(1).split(",")[0].strip() or None

        for match in _STREAM_RE.finditer(output):
            kind = match.group("kind")
            rest = match.group("rest")
            # `h264 (Constrained Baseline) (avc1 / 0x31637661)` -> `h264`
            codec = match.group("codec").strip().split()[0]
            info.streams.append({"codec_type": kind.lower(), "codec_name": codec})
            if kind == "Video" and not info.has_video:
                info.has_video = True
                info.video_codec = codec
                if dims := _VIDEO_DIM_RE.search(rest):
                    info.width, info.height = int(dims.group(1)), int(dims.group(2))
                if fps := _FPS_RE.search(rest):
                    info.fps = float(fps.group(1))
            elif kind == "Audio" and not info.has_audio:
                info.has_audio = True
                info.audio_codec = codec
                info.audio_channels = _parse_channels(rest)
                if rate := re.search(r"(\d+)\s*Hz", rest):
                    info.audio_sample_rate = int(rate.group(1))

        if not info.has_video and not info.has_audio:
            raise MediaError("That file contains no audio or video stream.")
        return info

    @staticmethod
    def _run(argv: list[str], *, timeout: int) -> None:
        assert argv[0] is not None
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        except FileNotFoundError as err:
            raise MediaError("FFmpeg is not runnable at the configured path.") from err
        except subprocess.TimeoutExpired as err:
            raise MediaError("FFmpeg timed out. The file may be very large or the codec unsupported.") from err
        if proc.returncode != 0:
            raise MediaError(
                "FFmpeg failed to process that file.",
                log_detail=(proc.stderr or "")[-1000:],
            )


def _parse_fps(value: str | None) -> float | None:
    if not value:
        return None
    try:
        if "/" in value:
            num, den = value.split("/", 1)
            den_f = float(den)
            return round(float(num) / den_f, 3) if den_f else None
        return float(value)
    except (ValueError, ZeroDivisionError):
        return None


def _parse_channels(rest: str) -> int | None:
    """`mono`, `stereo`, `5.1`, `6 channels` all appear depending on the build."""
    if channels := re.search(r"(\d+)\s+channels", rest):
        return int(channels.group(1))
    layout = re.search(r"\b(mono|stereo|quad|5\.1|7\.1)\b", rest)
    if layout:
        return {"mono": 1, "stereo": 2, "quad": 4, "5.1": 6, "7.1": 8}[layout.group(1)]
    return None
