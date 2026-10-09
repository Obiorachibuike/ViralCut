"""Word-level captions and ASS/SRT rendering.

Six styles (spec 22). ASS is used for burn-in because it supports per-word
karaoke highlighting, outlines and positioning; SRT/VTT are produced for the
platforms that want a sidecar file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable

from transcription.base import Segment, Word


class CaptionStyle(StrEnum):
    MINIMAL = "MINIMAL"
    BOLD = "BOLD"
    KARAOKE = "KARAOKE"
    CREATOR = "CREATOR"
    PODCAST = "PODCAST"
    HIGH_IMPACT = "HIGH_IMPACT"


@dataclass(slots=True)
class CaptionStyleSpec:
    font: str = "Montserrat"
    bold: bool = True
    size: int = 64
    primary: str = "#FFFFFF"      # AASS is &HBBGGRR&
    outline_color: str = "#000000"
    outline_width: float = 3.0
    shadow: float = 1.0
    background: str | None = None  # box behind the text
    uppercase: bool = True
    words_per_line: int = 3
    karaoke: bool = False
    animation: bool = True
    alignment: int = 2  # ASS: bottom-centre
    margin_v: int = 220
    highlight_color: str = "#FACC15"


STYLE_PRESETS: dict[CaptionStyle, CaptionStyleSpec] = {
    CaptionStyle.MINIMAL: CaptionStyleSpec(
        font="Inter", bold=False, size=52, outline_width=2.0, shadow=0.0,
        words_per_line=6, uppercase=False, animation=False, margin_v=180,
    ),
    CaptionStyle.BOLD: CaptionStyleSpec(
        font="Montserrat", bold=True, size=72, outline_width=5.0, shadow=2.0,
        words_per_line=3, uppercase=True,
    ),
    CaptionStyle.KARAOKE: CaptionStyleSpec(
        font="Montserrat", bold=True, size=66, words_per_line=3, uppercase=True,
        karaoke=True, highlight_color="#22C55E",
    ),
    CaptionStyle.CREATOR: CaptionStyleSpec(
        font="Montserrat", bold=True, size=64, outline_width=4.0, shadow=1.0,
        words_per_line=3, uppercase=True, karaoke=True, highlight_color="#FACC15",
    ),
    CaptionStyle.PODCAST: CaptionStyleSpec(
        font="Inter", bold=True, size=56, outline_width=3.0, shadow=1.0,
        words_per_line=5, uppercase=False, background="#000000AA",
    ),
    CaptionStyle.HIGH_IMPACT: CaptionStyleSpec(
        font="Montserrat", bold=True, size=84, outline_width=6.0, shadow=3.0,
        words_per_line=2, uppercase=True, karaoke=True, highlight_color="#EF4444",
        animation=True,
    ),
}


@dataclass(slots=True)
class CaptionLine:
    index: int
    start_ms: int
    end_ms: int
    text: str
    words: list[Word] = field(default_factory=list)
    speaker: str | None = None


def _hex_to_ass(color: str, alpha: int = 0) -> str:
    """#RRGGBB -> &HAABBGGRR (ASS byte order is reversed)."""
    cleaned = color.lstrip("#")
    if len(cleaned) == 8:  # #RRGGBBAA
        r, g, b, a = (int(cleaned[i : i + 2], 16) for i in (0, 2, 4, 6))
        return f"&H{a:02X}{b:02X}{g:02X}{r:02X}"
    if len(cleaned) != 6:
        return "&H00FFFFFF"
    r, g, b = (int(cleaned[i : i + 2], 16) for i in (0, 2, 4))
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _ass_timestamp(ms: int) -> str:
    """ASS uses `h:mm:ss.cc` (hundredths of a second)."""
    ms = max(0, int(ms))
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, msrem = divmod(rem, 1000)
    centis = msrem // 10
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centis:02d}"


def build_caption_lines(
    segments: Iterable[Segment],
    *,
    words_per_line: int = 3,
    uppercase: bool = True,
    max_line_ms: int = 2600,
    min_line_ms: int = 700,
) -> list[CaptionLine]:
    """Chunk word timings into short, readable caption lines.

    Uses real word timestamps when the ASR provided them; otherwise falls back to
    even splits inside each segment so captions still exist for engines that
    cannot emit word timings.
    """
    lines: list[CaptionLine] = []
    for segment in segments:
        words = [w for w in segment.words if w.text.strip()]
        if not words:
            text = segment.text.strip()
            if not text:
                continue
            tokens = text.split()
            step = max(1, (segment.end_ms - segment.start_ms) // max(1, len(tokens)))
            words = [
                Word(
                    text=token,
                    start_ms=segment.start_ms + i * step,
                    end_ms=segment.start_ms + (i + 1) * step,
                )
                for i, token in enumerate(tokens)
            ]

        chunk: list[Word] = []
        for word in words:
            chunk.append(word)
            duration = word.end_ms - chunk[0].start_ms
            if len(chunk) >= words_per_line or (duration >= max_line_ms and len(chunk) > 1):
                lines.append(_finalise(lines, chunk, segment.speaker, uppercase, min_line_ms))
                chunk = []
        if chunk:
            lines.append(_finalise(lines, chunk, segment.speaker, uppercase, min_line_ms))

    for index, line in enumerate(lines):
        line.index = index
    return lines


def _finalise(
    lines: list[CaptionLine],
    chunk: list[Word],
    speaker: str | None,
    uppercase: bool,
    min_line_ms: int,
) -> CaptionLine:
    text = " ".join(w.text.strip() for w in chunk).strip()
    if uppercase:
        text = text.upper()
    start = chunk[0].start_ms
    end = chunk[-1].end_ms
    # Never let a caption flash by: hold it until the next line would start.
    if end - start < min_line_ms:
        end = start + min_line_ms
    return CaptionLine(index=len(lines), start_ms=start, end_ms=end, text=text,
                       words=list(chunk), speaker=speaker)


def to_ass(
    lines: Iterable[CaptionLine],
    *,
    style: CaptionStyle = CaptionStyle.CREATOR,
    width: int = 1080,
    height: int = 1920,
    overrides: dict[str, Any] | None = None,
    watermark_text: str | None = None,
    total_duration_ms: int | None = None,
) -> str:
    """Render captions (and an optional text watermark) as a single ASS document.

    The watermark goes through ASS rather than FFmpeg's `drawtext` so rendering
    does not depend on a libfreetype/fontconfig-enabled FFmpeg build.
    """
    spec = _resolve_spec(style, overrides)
    events = [
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for line in lines:
        events.append(_ass_event(line, spec))
    if watermark_text:
        duration = total_duration_ms or (max((l.end_ms for l in lines), default=5000) + 500)
        events.append(
            f"Dialogue: 1,{_ass_timestamp(0)},{_ass_timestamp(duration)},Watermark,,0,0,0,,"
            + _escape_ass(watermark_text)
        )
    bold = -1 if spec.bold else 0
    watermark_style = _watermark_style(width, height)
    return "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
            "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            (
                f"Style: Default,{spec.font},{spec.size},"
                f"{_hex_to_ass(spec.primary)},{_hex_to_ass(spec.highlight_color)},"
                f"{_hex_to_ass(spec.outline_color)},{_hex_to_ass(spec.background or '#000000', 0x80)},"
                f"{bold},0,0,0,100,100,0,0,"
                f"{2 if spec.background else 1},{spec.outline_width},{spec.shadow},"
                f"{spec.alignment},60,60,{spec.margin_v},1"
            ),
            *([watermark_style] if watermark_text else []),
            "",
            "[Events]",
            *events,
            "",
        ]
    )


def _watermark_style(width: int, height: int) -> str:
    """Persistent, low-opacity footer watermark (layer 1, above captions)."""
    size = max(20, width // 34)
    margin_v = max(24, height // 40)
    return (
        f"Style: Watermark,Inter,{size},{_hex_to_ass('#FFFFFF')},{_hex_to_ass('#FFFFFF')},"
        f"{_hex_to_ass('#000000')},&H60000000,0,0,0,0,100,100,0,0,1,1.5,0.5,2,"
        f"40,40,{margin_v},1"
    )


def _ass_event(line: CaptionLine, spec: CaptionStyleSpec) -> str:
    start = _ass_timestamp(line.start_ms)
    end = _ass_timestamp(line.end_ms)
    body = _escape_ass(line.text)
    if spec.karaoke and line.words:
        body = _karaoke_body(line, spec)
    elif spec.animation:
        body = r"{\fad(90,90)}" + body
    return f"Dialogue: 0,{start},{end},Default,,0,0,0,,{body}"


def _karaoke_body(line: CaptionLine, spec: CaptionStyleSpec) -> str:
    """Per-word highlight using ASS \\k tags (duration in centiseconds)."""
    parts = [r"{\fad(60,60)}"]
    total = max(1, line.end_ms - line.start_ms)
    for word in line.words:
        weight = max(1, word.end_ms - word.start_ms)
        centis = max(1, int(weight / total * (total / 10)))
        parts.append(r"{\k%d}" % centis)
        parts.append(_escape_ass(word.text.strip()) + " ")
    return "".join(parts).rstrip()


def _escape_ass(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def _resolve_spec(style: CaptionStyle, overrides: dict[str, Any] | None) -> CaptionStyleSpec:
    base = STYLE_PRESETS.get(style, STYLE_PRESETS[CaptionStyle.CREATOR])
    if not overrides:
        return base
    spec = CaptionStyleSpec(**{**base.__dict__})
    mapping = {
        "font": "font",
        "size": "size",
        "primary": "primary",
        "highlight": "highlight_color",
        "outlineColor": "outline_color",
        "background": "background",
        "uppercase": "uppercase",
        "animation": "animation",
        "positionY": "margin_v",
        "wordsPerLine": "words_per_line",
    }
    for key, attr in mapping.items():
        if key in overrides and overrides[key] is not None:
            value = overrides[key]
            if key == "positionY":
                # 0 = top, 1 = bottom; ASS MarginV grows upwards from the bottom.
                spec.margin_v = int(max(40, min(1600, (1 - float(value)) * 1600)))
            else:
                setattr(spec, attr, value)
    return spec


def to_srt(lines: Iterable[CaptionLine]) -> str:
    """Standard SRT sidecar for platforms that want a caption file."""
    out: list[str] = []
    for index, line in enumerate(lines, start=1):
        out.append(str(index))
        out.append(f"{_srt_timestamp(line.start_ms)} --> {_srt_timestamp(line.end_ms)}")
        out.append(line.text)
        out.append("")
    return "\n".join(out)


def to_vtt(lines: Iterable[CaptionLine]) -> str:
    out = ["WEBVTT", ""]
    for line in lines:
        out.append(f"{_vtt_timestamp(line.start_ms)} --> {_vtt_timestamp(line.end_ms)}")
        out.append(line.text)
        out.append("")
    return "\n".join(out)


def _srt_timestamp(ms: int) -> str:
    ms = max(0, int(ms))
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _vtt_timestamp(ms: int) -> str:
    return _srt_timestamp(ms).replace(",", ".")


_WORD_SPLIT_RE = re.compile(r"\s+")


def highlight_words(lines: list[CaptionLine], highlights: Iterable[str]) -> list[CaptionLine]:
    """Wrap the user's chosen highlight words in ASS colour overrides."""
    wanted = {w.lower().strip(".,!?") for w in highlights if w.strip()}
    if not wanted:
        return lines
    for line in lines:
        tokens = _WORD_SPLIT_RE.split(line.text)
        rendered = [
            token if token.lower().strip(".,!?") not in wanted else f"{{\\c&_HIGHLIGHT_&}}{token}{{\\r}}"
            for token in tokens
        ]
        line.text = " ".join(rendered)
    return lines
