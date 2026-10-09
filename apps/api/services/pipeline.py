"""The full analysis pipeline.

    source (in storage) -> inspect -> extract audio -> transcribe -> diarize
    -> detect scenes -> discover moments -> (LLM refine) -> artifacts

Every stage reports progress through `on_stage` and writes its artifact to
storage, so the orchestrator (Next.js + BullMQ) persists the authoritative
records and never re-runs a stage for the same job (idempotent keys).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ai.analysis import MomentAnalyzer
from app.config import get_settings
from app.errors import MediaError, TranscriptionError, ViralCutError
from diarization.pyannote import assign_speakers, create_diarizer
from moments.discover import DiscoverOptions, discover_moments
from moments.text import word_count
from services.media import MediaProbe
from services.storage import StorageBackend, create_storage, key_for
from transcription.factory import create_transcriber
from video.scene_detect import SceneDetector, scenes_to_tuples

logger = logging.getLogger("viralcut.pipeline")

StageCallback = Callable[[str, int, str], None]


@dataclass(slots=True)
class PipelineResult:
    media: dict[str, Any]
    transcript: dict[str, Any] | None
    speakers: list[dict[str, Any]]
    scenes: list[dict[str, Any]]
    moments: dict[str, Any]
    artifacts: dict[str, str] = field(default_factory=dict)
    stages: list[dict[str, Any]] = field(default_factory=list)
    engine: str = "deterministic"
    prompt_version: str | None = None
    model: str | None = None


class Pipeline:
    def __init__(
        self,
        *,
        storage: StorageBackend | None = None,
        probe: MediaProbe | None = None,
        on_stage: StageCallback | None = None,
        transcriber: Any = None,
        diarizer: Any = None,
    ) -> None:
        self.storage = storage or create_storage()
        self.probe = probe or MediaProbe()
        self.on_stage = on_stage or (lambda stage, pct, message: None)
        self.work_dir = get_settings().work_dir
        self._transcriber = transcriber
        self._diarizer = diarizer

    # -- helpers ------------------------------------------------------------
    def _stage(self, stage: str, progress: int, message: str) -> None:
        logger.info("[%s] %d%% %s", stage, progress, message)
        self.on_stage(stage, progress, message)

    def _materialise(self, storage_key: str) -> Path:
        return self.storage.copy_to_local(storage_key, self.work_dir)

    # -- public -------------------------------------------------------------
    def process(
        self,
        *,
        storage_key: str,
        run_id: str,
        options: DiscoverOptions | None = None,
        language: str | None = None,
        skip_diarization: bool = False,
    ) -> PipelineResult:
        started = time.time()
        options = options or DiscoverOptions()
        result = PipelineResult(
            media={}, transcript=None, speakers=[], scenes=[], moments={}, engine="deterministic"
        )

        # 1. inspect --------------------------------------------------------
        self._stage("PREPARING", 5, "Inspecting media")
        local = self._materialise(storage_key)
        media = self.probe.inspect(local)
        result.media = media.to_dict()
        self.storage.put_bytes(
            key_for("media", run_id, "media.json"),
            _dumps(result.media),
            content_type="application/json",
        )

        # 2. extract audio --------------------------------------------------
        self._stage("PREPARING", 12, "Extracting audio")
        audio_path = self.work_dir / run_id / "audio.wav"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        if media.has_audio:
            self.probe.extract_audio(local, audio_path)
            self.storage.put_file(key_for("media", run_id, "audio.wav"), audio_path, content_type="audio/wav")
            result.artifacts["audio"] = key_for("media", run_id, "audio.wav")

        # 3. transcribe -----------------------------------------------------
        transcript = None
        if media.has_audio:
            self._stage("TRANSCRIBING", 30, "Transcribing speech")
            try:
                transcriber = self._transcriber or create_transcriber()
                transcript = transcriber.transcribe(str(audio_path), language=language)
            except ViralCutError as err:
                # Transcription is optional for moment discovery, but we surface it
                # so the orchestrator can show "Transcription failed. Retry."
                logger.warning("transcription skipped: %s", err.message)
                result.stages.append({"stage": "TRANSCRIBING", "skipped": True, "reason": err.message})

        if transcript is not None:
            # 4. diarize ----------------------------------------------------
            if not skip_diarization:
                self._stage("DIARIZING", 45, "Detecting speakers")
                diarizer = self._diarizer if self._diarizer is not None else create_diarizer()
                if diarizer is not None:
                    try:
                        spans = diarizer.diarize(str(audio_path))
                        assign_speakers(transcript, spans)
                        labels = sorted({s.label for s in spans})
                        for position, label in enumerate(labels):
                            total = sum(
                                s.duration_ms for s in transcript.segments if s.speaker == label
                            )
                            result.speakers.append(
                                {
                                    "label": label,
                                    "displayName": f"Speaker {position + 1}",
                                    "totalMs": total,
                                }
                            )
                    except ViralCutError as err:
                        logger.warning("diarization skipped: %s", err.message)
                        result.stages.append({"stage": "DIARIZING", "skipped": True, "reason": err.message})

            self._stage("TRANSCRIBING", 55, "Storing transcript")
            result.transcript = transcript.to_dict()
            result.artifacts["transcript"] = key_for("media", run_id, "transcript.json")
            self.storage.put_bytes(
                result.artifacts["transcript"],
                _dumps(result.transcript),
                content_type="application/json",
            )
            from video.captions import build_caption_lines, to_srt, to_vtt

            lines = build_caption_lines(transcript.segments)
            result.artifacts["srt"] = key_for("media", run_id, "captions.srt")
            result.artifacts["vtt"] = key_for("media", run_id, "captions.vtt")
            self.storage.put_bytes(result.artifacts["srt"], to_srt(lines).encode("utf-8"), content_type="text/srt")
            self.storage.put_bytes(result.artifacts["vtt"], to_vtt(lines).encode("utf-8"), content_type="text/vtt")

        # 5. scenes ---------------------------------------------------------
        self._stage("SCENE_DETECTING", 65, "Detecting scenes")
        detector = SceneDetector(
            ffmpeg_path=self.probe.ffmpeg,
            threshold=get_settings().scene_threshold,
            min_scene_seconds=get_settings().min_scene_seconds,
        )
        try:
            scenes = detector.detect(str(local), duration_ms=media.duration_ms)
        except MediaError as err:
            logger.warning("scene detection skipped: %s", err.message)
            scenes = []
            result.stages.append({"stage": "SCENE_DETECTING", "skipped": True, "reason": err.message})
        result.scenes = [
            {"index": s.index, "startMs": s.start_ms, "endMs": s.end_ms, "cutScore": s.cut_score}
            for s in scenes
        ]

        # 6. moments --------------------------------------------------------
        self._stage("FINDING_MOMENTS", 80, "Discovering moments")
        if transcript is not None and transcript.segments:
            discovery = discover_moments(
                transcript,
                scenes=scenes_to_tuples(scenes),
                options=options,
            )

            # 7. optional LLM refinement -----------------------------------
            analyzer = MomentAnalyzer()
            if analyzer.configured:
                self._stage("ANALYZING", 90, "Refining with AI")
                discovery, prompt_version, model = analyzer.refine(discovery)
                if prompt_version:
                    result.prompt_version = prompt_version
                    result.model = model
            result.moments = discovery.to_dict()
            result.engine = discovery.engine
        else:
            result.moments = {
                "candidateCount": 0,
                "clusterCount": 0,
                "moments": [],
                "engine": "none (no speech detected)",
                "llmRefined": False,
            }

        # thumbnails for the top moments -----------------------------------
        self._stage("FINDING_MOMENTS", 95, "Extracting thumbnails")
        for moment in result.moments.get("moments", [])[:8]:
            try:
                thumb = self.work_dir / run_id / f"thumb_{moment['startMs']}.jpg"
                thumb.parent.mkdir(parents=True, exist_ok=True)
                self.probe.thumbnail(local, thumb, moment["startMs"])
                key = key_for("media", run_id, f"thumb_{moment['startMs']}.jpg")
                self.storage.put_file(key, thumb, content_type="image/jpeg")
                moment["thumbKey"] = key
            except Exception as err:  # thumbnails are best-effort
                logger.debug("thumbnail failed: %s", err)

        self._stage("READY", 100, f"Analysis complete in {time.time() - started:.1f}s")
        return result


def _dumps(value: Any) -> bytes:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
