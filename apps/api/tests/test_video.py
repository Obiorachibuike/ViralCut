"""Video pipeline: captions, reframing and (when FFmpeg is present) real renders."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from transcription.base import Segment, Word
from video.captions import (
    CaptionLine,
    CaptionStyle,
    STYLE_PRESETS,
    _ass_timestamp,
    build_caption_lines,
    to_ass,
    to_srt,
    to_vtt,
)
from video.reframe import (
    Keyframe,
    ReframeMode,
    crop_filter,
    plan_reframe,
    target_size,
)

def _ffmpeg_path() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


needs_ffmpeg = pytest.mark.skipif(_ffmpeg_path() is None, reason="FFmpeg not installed")


# ---------------------------------------------------------------------------
# Caption line construction
# ---------------------------------------------------------------------------


def _segment(text: str, start_ms: int, *, with_words: bool = True) -> Segment:
    tokens = text.split()
    end_ms = start_ms + len(tokens) * 400
    words = [
        Word(text=t, start_ms=start_ms + i * 400, end_ms=start_ms + (i + 1) * 400)
        for i, t in enumerate(tokens)
    ] if with_words else []
    return Segment(index=0, start_ms=start_ms, end_ms=end_ms, text=text, words=words)


def test_caption_lines_chunk_by_word_count():
    segment = _segment("the quick brown fox jumps over the lazy dog again and again", 0)
    lines = build_caption_lines([segment], words_per_line=3)
    assert all(len(l.text.split()) <= 3 for l in lines)
    assert len(lines) >= 3


def test_caption_lines_are_uppercased_when_requested():
    segment = _segment("hiring too quickly nearly killed the company", 0)
    lines = build_caption_lines([segment], words_per_line=3, uppercase=True)
    assert all(l.text == l.text.upper() for l in lines)


def test_caption_lines_hold_the_minimum_time():
    segment = _segment("hi there", 0)
    lines = build_caption_lines([segment], words_per_line=3, uppercase=True)
    assert lines and (lines[0].end_ms - lines[0].start_ms) >= 700


def test_caption_lines_fall_back_to_even_splits_without_words():
    segment = _segment("one two three four five six", 0, with_words=False)
    lines = build_caption_lines([segment], words_per_line=2)
    assert len(lines) >= 3
    assert all(l.end_ms > l.start_ms for l in lines)


# ---------------------------------------------------------------------------
# ASS / SRT / VTT rendering
# ---------------------------------------------------------------------------


def test_ass_timestamps_are_centisecond_correct():
    assert _ass_timestamp(0) == "0:00:00.00"
    assert _ass_timestamp(300) == "0:00:00.30"
    assert _ass_timestamp(2200) == "0:00:02.20"
    assert _ass_timestamp(3_712_340) == "1:01:52.34"


def test_ass_document_has_all_six_styles():
    for style in CaptionStyle:
        assert style in STYLE_PRESETS


def test_ass_output_contains_events_and_playres():
    line = CaptionLine(index=0, start_ms=300, end_ms=2200, text="THE BIGGEST MISTAKE")
    ass = to_ass([line], style=CaptionStyle.BOLD, width=1080, height=1920)
    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    assert "Dialogue: 0,0:00:00.30,0:00:02.20,Default" in ass
    assert "THE BIGGEST MISTAKE" in ass


def test_ass_karaoke_emits_k_tags():
    line = CaptionLine(
        index=0, start_ms=0, end_ms=1000, text="HELLO WORLD",
        words=[Word(text="HELLO", start_ms=0, end_ms=500), Word(text="WORLD", start_ms=500, end_ms=1000)],
    )
    ass = to_ass([line], style=CaptionStyle.KARAOKE)
    assert "\\k" in ass


def test_ass_watermark_appends_second_style_and_event():
    line = CaptionLine(index=0, start_ms=0, end_ms=1000, text="CAPTION")
    ass = to_ass([line], style=CaptionStyle.CREATOR, watermark_text="VIRALCUT", total_duration_ms=5000)
    assert "Style: Watermark," in ass
    assert "VIRALCUT" in ass


def test_srt_and_vtt_have_matching_content():
    line = CaptionLine(index=0, start_ms=1000, end_ms=3000, text="HELLO")
    srt = to_srt([line])
    vtt = to_vtt([line])
    assert "00:00:01,000 --> 00:00:03,000" in srt
    assert "00:00:01.000 --> 00:00:03.000" in vtt
    assert "HELLO" in srt and "HELLO" in vtt
    assert vtt.startswith("WEBVTT")


# ---------------------------------------------------------------------------
# Reframing
# ---------------------------------------------------------------------------


def test_target_size_caps_short_side():
    assert target_size("9:16", max_short_side=1080) == (1080, 1920)
    assert target_size("9:16", max_short_side=720) == (720, 1280)
    assert target_size("16:9", max_short_side=1080) == (1920, 1080)
    assert target_size("4:5", max_short_side=720) == (720, 900)


def test_unknown_aspect_is_rejected():
    from app.errors import ValidationError

    with pytest.raises(ValidationError):
        target_size("21:9")


def test_crop_box_matches_target_aspect():
    from video.reframe import crop_box_for_aspect

    w, h = crop_box_for_aspect(1920, 1080, 1080, 1920)
    assert abs(w / h - 1080 / 1920) < 0.01
    assert h == 1080  # crop the full height of the landscape source


def test_center_plan_is_static():
    plan = plan_reframe(src_w=1920, src_h=1080, aspect="9:16", mode="CENTER")
    assert plan.is_animated is False
    assert plan.crop_width < 1920


def test_speaker_track_plan_is_animated():
    boxes = [Keyframe(0, 0.1, 0.2, 0.3, 0.5), Keyframe(3000, 0.6, 0.2, 0.3, 0.5)]
    plan = plan_reframe(src_w=1920, src_h=1080, aspect="9:16", mode="SPEAKER_TRACK", boxes=boxes)
    assert plan.is_animated is True
    assert len(plan.keyframes) == 2


def test_animated_crop_filter_is_a_time_expression():
    boxes = [Keyframe(0, 0.1, 0.0, 0.3, 1.0), Keyframe(3000, 0.6, 0.0, 0.3, 1.0)]
    plan = plan_reframe(src_w=1920, src_h=1080, aspect="9:16", mode="SPEAKER_TRACK", boxes=boxes)
    f = crop_filter(plan, 1920, 1080)
    assert "if(lt(t" in f  # piecewise keyframe interpolation


def test_auto_falls_back_to_center_without_boxes():
    plan = plan_reframe(src_w=1920, src_h=1080, aspect="9:16", mode="AUTO", boxes=None)
    assert plan.mode is ReframeMode.CENTER


# ---------------------------------------------------------------------------
# Real renders (skipped when FFmpeg is absent)
# ---------------------------------------------------------------------------


@pytest.fixture()
def source_video(tmp_path):
    path = tmp_path / "src.mp4"
    cmd = [
        _ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=5",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(path),
    ]
    subprocess.run(cmd, capture_output=True, check=True, timeout=120)
    return path


@needs_ffmpeg
def test_render_produces_vertical_video_with_audio(source_video, tmp_path):
    from services.media import MediaProbe
    from video.render import RenderRequest, render_clip

    probe = MediaProbe()
    out = tmp_path / "out.mp4"
    result = render_clip(
        RenderRequest(
            source_path=str(source_video),
            output_path=str(out),
            start_ms=0,
            end_ms=4000,
            src_width=1920,
            src_height=1080,
            aspect="9:16",
            reframe_mode="CENTER",
            caption_lines=[CaptionLine(index=0, start_ms=200, end_ms=3000, text="A CAPTION")],
            caption_style=CaptionStyle.BOLD,
            max_short_side=720,
            preset="ultrafast",
            crf=30,
        ),
        probe=probe,
    )
    assert result.width == 720
    assert result.height == 1280
    assert result.size_bytes > 0
    assert result.captions_burned is True
    info = probe.inspect(out)
    assert info.has_video
    assert info.has_audio


@needs_ffmpeg
def test_render_muted_has_no_audio(source_video, tmp_path):
    from services.media import MediaProbe
    from video.render import RenderRequest, render_clip

    probe = MediaProbe()
    result = render_clip(
        RenderRequest(
            source_path=str(source_video),
            output_path=str(tmp_path / "muted.mp4"),
            start_ms=0,
            end_ms=3000,
            src_width=1920,
            src_height=1080,
            aspect="9:16",
            reframe_mode="CENTER",
            muted=True,
            max_short_side=720,
            preset="ultrafast",
            crf=30,
        ),
        probe=probe,
    )
    info = probe.inspect(result.output_path)
    assert info.has_video
    assert info.has_audio is False


@needs_ffmpeg
def test_cut_source_clip_is_real(source_video, tmp_path):
    from services.media import MediaProbe
    from video.render import cut_source_clip

    probe = MediaProbe()
    out = cut_source_clip(str(source_video), str(tmp_path / "cut.mp4"), start_ms=1000, end_ms=4000)
    info = probe.inspect(out)
    assert 2800 <= info.duration_ms <= 3200


@needs_ffmpeg
def test_split_screen_render(source_video, tmp_path):
    from services.media import MediaProbe
    from video.render import RenderRequest, render_clip

    probe = MediaProbe()
    result = render_clip(
        RenderRequest(
            source_path=str(source_video),
            output_path=str(tmp_path / "split.mp4"),
            start_ms=0,
            end_ms=3000,
            src_width=1920,
            src_height=1080,
            aspect="9:16",
            reframe_mode="SPLIT_SCREEN",
            max_short_side=720,
            preset="ultrafast",
            crf=30,
        ),
        probe=probe,
    )
    assert result.width == 720
    assert result.height == 1280


@needs_ffmpeg
def test_empty_range_is_rejected(source_video, tmp_path):
    from video.render import RenderRequest, render_clip
    from app.errors import MediaError

    with pytest.raises(MediaError, match="empty"):
        render_clip(
            RenderRequest(
                source_path=str(source_video),
                output_path=str(tmp_path / "bad.mp4"),
                start_ms=5000,
                end_ms=5000,
                src_width=1920,
                src_height=1080,
            )
        )
