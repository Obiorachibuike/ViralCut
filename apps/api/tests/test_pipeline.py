"""Pipeline orchestration: ingest artifact -> stages -> moments, over real FFmpeg.

The ASR and diarizer are injected (they are the only components that need model
downloads); everything else — media inspection, audio extraction, scene
detection, moment discovery, artifact storage — runs for real.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app import config as config_mod
from services.media import MediaProbe
from services.pipeline import Pipeline
from services.storage import LocalStorage
from tests.fixtures.transcript import build_podcast_transcript, strong_moment_starts
from transcription.base import Transcript
from diarization.pyannote import SpeakerSpan


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


class FakeTranscriber:
    name = "fake"

    def __init__(self, transcript: Transcript) -> None:
        self._transcript = transcript

    @property
    def available(self) -> bool:
        return True

    def transcribe(self, audio_path: str, *, language=None) -> Transcript:
        assert Path(audio_path).exists(), "pipeline must extract audio before transcribing"
        return self._transcript


class FakeDiarizer:
    def __init__(self) -> None:
        self.calls = 0

    def diarize(self, audio_path, *, num_speakers=None):
        self.calls += 1
        transcript = build_podcast_transcript()
        spans = []
        # Alternate 20-second turns across the whole episode.
        t = 0
        label = "SPEAKER_00"
        while t < transcript.duration_ms:
            spans.append(SpeakerSpan(label=label, start_ms=t, end_ms=t + 20_000))
            t += 20_000
            label = "SPEAKER_01" if label == "SPEAKER_00" else "SPEAKER_00"
        return spans


@pytest.fixture()
def work_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "store"))
    config_mod.reset_settings_cache()
    yield tmp_path
    config_mod.reset_settings_cache()


@pytest.fixture()
def source_key(tmp_path):
    storage = LocalStorage(tmp_path / "store")
    probe_src = tmp_path / "src.mp4"
    subprocess.run(
        [
            _ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=20",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(probe_src),
        ],
        capture_output=True,
        check=True,
        timeout=120,
    )
    return storage.put_file("sources/run1/media.mp4", probe_src, content_type="video/mp4")


@needs_ffmpeg
def test_pipeline_produces_moments_and_artifacts(work_env, source_key, tmp_path):
    storage = LocalStorage(tmp_path / "store")
    transcript = build_podcast_transcript()
    events: list[tuple[str, int, str]] = []

    pipeline = Pipeline(
        storage=storage,
        probe=MediaProbe(ffmpeg_path=_ffmpeg_path()),
        on_stage=lambda stage, pct, msg: events.append((stage, pct, msg)),
        transcriber=FakeTranscriber(transcript),
        diarizer=FakeDiarizer(),
    )
    result = pipeline.process(storage_key=source_key, run_id="run1")

    # Media inspection happened for real.
    assert result.media["has_video"] is True
    assert result.media["has_audio"] is True

    # Transcript + sidecars were persisted.
    assert result.transcript is not None
    assert storage.exists("media/run1/transcript.json")
    assert storage.exists("media/run1/captions.srt")
    assert storage.exists("media/run1/captions.vtt")

    # Moments were discovered and the planted strong moments surface.
    moments = result.moments["moments"]
    assert result.moments["candidateCount"] >= 20
    assert len(moments) >= 8
    top_starts = [m["startMs"] for m in moments[:10]]
    planted = strong_moment_starts()
    hits = sum(1 for p in planted if any(abs(t - p) <= 25_000 for t in top_starts))
    assert hits >= 3

    # Speakers were assigned via the injected diarizer.
    assert result.speakers, "expected speakers from the injected diarizer"

    # Stage events flowed in order and finished at 100%.
    stages = [stage for stage, _pct, _msg in events]
    assert stages[0] == "PREPARING"
    assert events[-1][1] == 100

    # The result payload serialises cleanly for the orchestrator.
    assert json.dumps(result.moments) is not None


@needs_ffmpeg
def test_pipeline_without_speech_reports_empty_moments(work_env, tmp_path):
    # A silent video has no transcript and therefore no moments; it must not crash.
    storage = LocalStorage(tmp_path / "store")
    silent_src = tmp_path / "silent.mp4"
    subprocess.run(
        [
            _ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=4",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(silent_src),
        ],
        capture_output=True,
        check=True,
        timeout=120,
    )
    key = storage.put_file("sources/run2/media.mp4", silent_src, content_type="video/mp4")

    class NoSpeech(FakeTranscriber):
        def transcribe(self, audio_path, *, language=None):
            from app.errors import TranscriptionError

            raise TranscriptionError("No speech was detected in that recording.")

    pipeline = Pipeline(
        storage=storage,
        probe=MediaProbe(ffmpeg_path=_ffmpeg_path()),
        transcriber=NoSpeech(build_podcast_transcript()),
    )
    result = pipeline.process(storage_key=key, run_id="run2")
    assert result.moments["moments"] == []
    assert result.moments["candidateCount"] == 0


@needs_ffmpeg
def test_storage_path_traversal_is_refused(work_env, tmp_path):
    from app.errors import StorageError

    storage = LocalStorage(tmp_path / "store")
    with pytest.raises(StorageError):
        storage._abs("../../etc/passwd")


def test_local_storage_roundtrip(tmp_path):
    storage = LocalStorage(tmp_path / "store")
    storage.put_bytes("a/b/c.json", b'{"hello": true}', content_type="application/json")
    assert storage.exists("a/b/c.json")
    assert storage.size("a/b/c.json") == len(b'{"hello": true}')
    dest = tmp_path / "out.json"
    storage.get_file("a/b/c.json", dest)
    assert json.loads(dest.read_text()) == {"hello": True}
    storage.delete("a/b/c.json")
    assert not storage.exists("a/b/c.json")
