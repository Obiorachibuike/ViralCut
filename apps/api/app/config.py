"""Runtime configuration for the ViralCut media engine.

Everything is read from the environment so the same image runs in dev, CI and
production. Nothing here is ever exposed to a browser.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- service ------------------------------------------------------------
    env: str = Field(default="development", alias="VIRALCUT_ENV")
    host: str = "0.0.0.0"
    port: int = Field(default=8000, alias="FASTAPI_PORT")
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    # Shared secret the Next.js orchestrator must present on every call.
    worker_token: str = Field(default="", alias="MEDIA_ENGINE_TOKEN")
    # Where progress callbacks are POSTed back to the orchestrator.
    callback_base_url: str = Field(default="", alias="VIRALCUT_CALLBACK_BASE_URL")
    callback_token: str = Field(default="", alias="VIRALCUT_CALLBACK_TOKEN")

    # --- storage ------------------------------------------------------------
    # "local" for dev, "s3" for Cloudflare R2 (S3-compatible).
    storage_backend: str = Field(default="local", alias="STORAGE_BACKEND")
    storage_local_dir: Path = Field(default=REPO_ROOT / ".storage", alias="STORAGE_LOCAL_DIR")
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = ""
    r2_public_url: str = ""
    r2_endpoint: str = ""
    signed_url_ttl_seconds: int = 3600

    # --- media tooling ------------------------------------------------------
    ffmpeg_path: str = Field(default="ffmpeg", alias="FFMPEG_PATH")
    ffprobe_path: str = Field(default="ffprobe", alias="FFPROBE_PATH")
    work_dir: Path = Field(default=REPO_ROOT / ".media-work", alias="MEDIA_WORK_DIR")
    max_ingest_bytes: int = 8 * 1024 * 1024 * 1024
    # Hard wall-clock caps so a runaway job can never wedge a worker.
    download_timeout_seconds: int = 900
    transcode_timeout_seconds: int = 3600

    # --- transcription / diarization ---------------------------------------
    whisper_model: str = Field(default="small", alias="WHISPER_MODEL")
    whisper_device: str = Field(default="auto", alias="WHISPER_DEVICE")
    whisper_compute_type: str = Field(default="default", alias="WHISPER_COMPUTE_TYPE")
    whisper_language: str | None = Field(default=None, alias="WHISPER_LANGUAGE")
    diarization_model: str = Field(
        default="pyannote/speaker-diarization-3.1", alias="DIARIZATION_MODEL"
    )
    hf_token: str = Field(default="", alias="HF_TOKEN")

    # --- AI -----------------------------------------------------------------
    ai_provider: str = Field(default="openai", alias="VIRALCUT_AI_PROVIDER")
    ai_api_key: str = Field(default="", alias="AI_API_KEY")
    ai_model: str = Field(default="", alias="VIRALCUT_AI_MODEL")
    ai_base_url: str = Field(default="", alias="VIRALCUT_AI_BASE_URL")
    ai_timeout_seconds: int = 120
    prompt_dir: Path = Field(
        default=REPO_ROOT / "packages" / "ai" / "prompts", alias="VIRALCUT_PROMPT_DIR"
    )
    prompt_version: str = Field(default="v1", alias="VIRALCUT_PROMPT_VERSION")

    # --- moment detection ---------------------------------------------------
    # Deterministic analysis is always on. When an LLM is configured it refines
    # candidates; when it is not, the deterministic result is used as-is and the
    # caller is told so. ViralCut never fabricates an "AI" result.
    candidate_target_per_minute: float = 1.2
    candidate_min: int = 15
    candidate_max: int = 120
    min_moment_seconds: float = 20.0
    max_moment_seconds: float = 120.0
    pad_before_max_seconds: float = 5.0
    pad_after_max_seconds: float = 5.0
    dedupe_similarity_threshold: float = 0.72

    # --- scene detection / face tracking -----------------------------------
    scene_threshold: float = 27.0
    min_scene_seconds: float = 1.2
    face_track_enabled: bool = True

    # --- LongCat GPU worker -------------------------------------------------
    longcat_enabled: bool = False
    longcat_api_url: str = ""
    longcat_worker_token: str = ""
    longcat_timeout_seconds: int = 600

    # --- Text-to-video ------------------------------------------------------
    # Which backend produces prompt->video. "none" disables the feature and the
    # UI says so plainly rather than pretending to generate.
    t2v_provider: str = Field(default="none", alias="VIRALCUT_T2V_PROVIDER")
    t2v_model: str = Field(default="", alias="VIRALCUT_T2V_MODEL")
    t2v_timeout_seconds: int = Field(default=900, alias="VIRALCUT_T2V_TIMEOUT_SECONDS")
    t2v_max_seconds: float = Field(default=10.0, alias="VIRALCUT_T2V_MAX_SECONDS")
    fal_api_key: str = Field(default="", alias="FAL_KEY")
    replicate_api_token: str = Field(default="", alias="REPLICATE_API_TOKEN")
    luma_api_key: str = Field(default="", alias="LUMA_API_KEY")
    runway_api_key: str = Field(default="", alias="RUNWAY_API_KEY")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def r2_configured(self) -> bool:
        return bool(
            self.r2_account_id
            and self.r2_access_key_id
            and self.r2_secret_access_key
            and self.r2_bucket_name
        )

    def ensure_dirs(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        if self.storage_backend == "local":
            self.storage_local_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


def reset_settings_cache() -> None:
    """Used by tests that mutate the environment."""
    get_settings.cache_clear()
    os.environ.pop("VIRALCUT_SETTINGS_CACHED", None)
