"""Text-to-video subsystem: provider selection, request validation, service flow.

The service test is real end-to-end: a stand-in backend produces an actual
FFmpeg-rendered file, and the service probes it with FFmpeg and stores it —
exactly what happens with a live vendor, minus the network hop.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
import pytest

from app import config as config_mod
from fastapi.testclient import TestClient
from generation.base import (
    GenerationError,
    GenerationRequest,
    GenerationResult,
    ProgressHook,
    TextToVideoProvider,
)
from generation.factory import (
    ProviderNotConfigured,
    create_provider,
    describe_providers,
)
from generation.service import GenerationService
from services.media import MediaProbe
from services.storage import LocalStorage


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


@pytest.fixture()
def work_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "store"))
    for var in ("VIRALCUT_T2V_PROVIDER", "VIRALCUT_T2V_MODEL", "FAL_KEY",
                "REPLICATE_API_TOKEN", "LUMA_API_KEY", "RUNWAY_API_KEY",
                "LONGCAT_ENABLED", "LONGCAT_API_URL"):
        monkeypatch.delenv(var, raising=False)
    config_mod.reset_settings_cache()
    yield tmp_path
    config_mod.reset_settings_cache()


def _render_clip(dest: Path, seconds: int = 3) -> Path:
    subprocess.run(
        [
            _ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size=360x640:rate=24:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=520:duration={seconds}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(dest),
        ],
        capture_output=True,
        check=True,
        timeout=120,
    )
    return dest


class FakeBackend(TextToVideoProvider):
    """Stands in for a vendor: hands back a real file, raw bytes, or nothing."""

    name = "fake"
    label = "Fake backend"
    max_seconds = 8.0
    supported_aspects = ("9:16", "1:1")

    def __init__(self, tmp_dir: Path, *, configured: bool = True, output: str = "path",
                 empty: bool = False) -> None:
        self._tmp = tmp_dir
        self._configured = configured
        self._output = output
        self._empty = empty
        self.seen: list[GenerationRequest] = []

    def configured(self) -> bool:
        return self._configured

    def generate(self, request: GenerationRequest,
                 on_progress: ProgressHook | None = None) -> GenerationResult:
        self.seen.append(request)
        if on_progress:
            on_progress(0.5, "halfway")
        if self._empty:
            return GenerationResult(provider=self.name, model="fake")

        clip = _render_clip(self._tmp / "fake.mp4")
        result = GenerationResult(provider=self.name, model="fake-1", duration_seconds=3.0)
        if self._output == "bytes":
            result.video_bytes = clip.read_bytes()
        else:
            result.video_path = str(clip)
        return result


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------

def test_request_clamps_duration_to_provider_limit():
    req = GenerationRequest(prompt="x", seconds=99).validated(8.0, ("9:16",))
    assert req.seconds == 8.0


def test_request_falls_back_when_aspect_unsupported():
    req = GenerationRequest(prompt="x", aspect_ratio="16:9").validated(8.0, ("9:16", "1:1"))
    assert req.aspect_ratio == "9:16"


def test_request_strips_prompt_whitespace():
    req = GenerationRequest(prompt="  a cat surfing  ").validated(8.0, ("9:16",))
    assert req.prompt == "a cat surfing"


# ---------------------------------------------------------------------------
# Factory / provider discovery
# ---------------------------------------------------------------------------

def test_no_provider_configured_by_default(work_env):
    report = describe_providers()
    assert report["active"] is None
    assert report["activeConfigured"] is False
    names = {p["name"] for p in report["providers"]}
    assert names == {"longcat", "fal", "replicate", "luma", "runway"}
    assert all(p["configured"] is False for p in report["providers"])


def test_disabled_provider_explains_itself(work_env):
    report = describe_providers()
    longcat = next(p for p in report["providers"] if p["name"] == "longcat")
    assert longcat["reason"] == "LONGCAT_ENABLED is false"


def test_replicate_explains_missing_model(work_env, monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_test")
    config_mod.reset_settings_cache()
    report = describe_providers()
    rep = next(p for p in report["providers"] if p["name"] == "replicate")
    assert rep["configured"] is False
    assert "VIRALCUT_T2V_MODEL" in rep["reason"]


def test_create_provider_rejects_none(work_env):
    with pytest.raises(ProviderNotConfigured):
        create_provider("none")


def test_create_provider_rejects_unknown(work_env):
    with pytest.raises(ProviderNotConfigured) as exc:
        create_provider("sora-magic")
    assert "sora-magic" in str(exc.value)


def test_create_provider_honours_selection(work_env, monkeypatch):
    monkeypatch.setenv("VIRALCUT_T2V_PROVIDER", "fal")
    monkeypatch.setenv("FAL_KEY", "fal_test")
    config_mod.reset_settings_cache()
    provider = create_provider()
    assert provider.name == "fal"
    assert provider.configured() is True
    assert describe_providers()["activeConfigured"] is True


def test_longcat_configures_from_env(work_env, monkeypatch):
    monkeypatch.setenv("LONGCAT_ENABLED", "true")
    monkeypatch.setenv("LONGCAT_API_URL", "http://gpu.internal:9000/")
    config_mod.reset_settings_cache()
    provider = create_provider("longcat")
    assert provider.configured() is True
    # Trailing slash must not survive into request URLs.
    assert provider.base_url == "http://gpu.internal:9000"


def test_longcat_unconfigured_raises_not_generation_error(work_env):
    provider = create_provider("longcat")
    with pytest.raises(GenerationError) as exc:
        provider.generate(GenerationRequest(prompt="a cat"))
    assert "not enabled" in exc.value.message


# ---------------------------------------------------------------------------
# Service flow (real FFmpeg + real storage)
# ---------------------------------------------------------------------------

@needs_ffmpeg
def test_service_stores_generated_video(work_env, tmp_path, monkeypatch):
    monkeypatch.setenv("VIRALCUT_T2V_PROVIDER", "fake")
    config_mod.reset_settings_cache()
    backend = FakeBackend(tmp_path)
    events: list[tuple[str, int, str]] = []
    service = GenerationService(
        provider=backend,
        probe=MediaProbe(ffmpeg_path=_ffmpeg_path()),
        on_stage=lambda s, p, m: events.append((s, p, m)),
    )

    payload = service.generate(prompt="a cat surfing a wave", run_id="gen1",
                               seconds=3, aspectRatio="9:16")

    storage = LocalStorage(tmp_path / "store")
    assert payload["storageKey"] == "generated/gen1/source.mp4"
    assert storage.exists("generated/gen1/source.mp4")
    assert payload["thumbnailKey"] == "generated/gen1/thumb.jpg"
    assert storage.exists("generated/gen1/thumb.jpg")

    # FFmpeg really inspected the file.
    assert payload["width"] == 360
    assert payload["height"] == 640
    assert payload["hasAudio"] is True
    assert 2500 <= payload["durationMs"] <= 3600
    assert payload["sizeBytes"] > 0
    assert payload["prompt"] == "a cat surfing a wave"
    assert payload["provider"] == "fake"

    # The backend received the validated request.
    assert backend.seen[0].aspect_ratio == "9:16"

    stages = [s for s, _p, _m in events]
    assert stages[0] == "GENERATING"
    assert events[-1][1] == 100


@needs_ffmpeg
def test_service_accepts_bytes_output(work_env, tmp_path, monkeypatch):
    config_mod.reset_settings_cache()
    service = GenerationService(
        provider=FakeBackend(tmp_path, output="bytes"),
        probe=MediaProbe(ffmpeg_path=_ffmpeg_path()),
    )
    payload = service.generate(prompt="bytes", run_id="gen2")
    assert LocalStorage(tmp_path / "store").exists(payload["storageKey"])
    assert payload["width"] == 360


def test_service_refuses_unconfigured_backend(work_env, tmp_path):
    service = GenerationService(provider=FakeBackend(tmp_path, configured=False))
    with pytest.raises(GenerationError) as exc:
        service.generate(prompt="x", run_id="gen3")
    assert "not configured" in exc.value.message


def test_service_refuses_empty_output(work_env, tmp_path):
    service = GenerationService(provider=FakeBackend(tmp_path, empty=True))
    with pytest.raises(GenerationError) as exc:
        service.generate(prompt="x", run_id="gen4")
    assert "without producing a video" in exc.value.message


def test_service_rejects_blank_prompt(work_env, tmp_path):
    service = GenerationService(provider=FakeBackend(tmp_path))
    with pytest.raises(GenerationError):
        service.generate(prompt="   ", run_id="gen5")


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------

def test_providers_endpoint_reports_capabilities(work_env, monkeypatch):
    monkeypatch.setenv("MEDIA_ENGINE_TOKEN", "test-token")
    config_mod.reset_settings_cache()
    from app.main import create_app

    client = TestClient(create_app())
    res = client.get("/v1/generate/providers",
                     headers={"x-viralcut-token": "test-token"})
    assert res.status_code == 200
    body = res.json()
    assert body["active"] is None
    assert len(body["providers"]) == 5


def test_text_to_video_fails_fast_when_disabled(work_env, monkeypatch):
    monkeypatch.setenv("MEDIA_ENGINE_TOKEN", "test-token")
    config_mod.reset_settings_cache()
    from app.main import create_app

    client = TestClient(create_app())
    res = client.post(
        "/v1/generate/text-to-video",
        headers={"x-viralcut-token": "test-token"},
        json={"runId": "run-x", "prompt": "a cat surfing"},
    )
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "dependency_unavailable"


def test_text_to_video_requires_auth(work_env, monkeypatch):
    monkeypatch.setenv("MEDIA_ENGINE_TOKEN", "test-token")
    config_mod.reset_settings_cache()
    from app.main import create_app

    client = TestClient(create_app())
    res = client.post("/v1/generate/text-to-video",
                      json={"runId": "run-y", "prompt": "a cat"})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Signed storage URLs (used by the publisher to fetch a rendered clip)
# ---------------------------------------------------------------------------

def _client(monkeypatch):
    monkeypatch.setenv("MEDIA_ENGINE_TOKEN", "test-token")
    config_mod.reset_settings_cache()
    from app.main import create_app

    return TestClient(create_app())


def test_storage_url_signs_an_existing_object(work_env, tmp_path, monkeypatch):
    storage = LocalStorage(tmp_path / "store")
    storage.put_bytes("clips/abc/clip.mp4", b"fake-mp4-bytes", content_type="video/mp4")

    res = _client(monkeypatch).get(
        "/v1/storage/url",
        params={"key": "clips/abc/clip.mp4"},
        headers={"x-viralcut-token": "test-token"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["key"] == "clips/abc/clip.mp4"
    assert body["sizeBytes"] == len(b"fake-mp4-bytes")
    # LocalStorage signs into a relative media path; S3 returns an absolute URL.
    assert body["key"] in body["url"]
    assert body["expiresIn"] == 900


def test_storage_url_rejects_missing_object(work_env, monkeypatch):
    res = _client(monkeypatch).get(
        "/v1/storage/url",
        params={"key": "clips/nope/clip.mp4"},
        headers={"x-viralcut-token": "test-token"},
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


def test_storage_url_rejects_traversal(work_env, monkeypatch):
    res = _client(monkeypatch).get(
        "/v1/storage/url",
        params={"key": "../etc/passwd"},
        headers={"x-viralcut-token": "test-token"},
    )
    assert res.status_code == 422
