"""Provider detection and content-rights policy.

`classify()` is the offline routing layer that the TypeScript frontend mirrors,
so both sides are asserted against the single shared fixture file. The `resolve()`
tests use injected adapters (no network) and cover every refusal path in spec 39:
private video, login wall, DRM, age gate, live stream, playlist, group post, SSRF.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from providers.base import SourceKind, SourceResolution, is_private_host
from providers.registry import ProviderLookupError, ProviderRegistry, classify
from providers.youtube import YouTubeProvider
from providers.tiktok import TikTokProvider
from providers.facebook import FacebookProvider
from providers.generic import GenericProvider

def _repo_root() -> Path:
    """Walk up until we find the monorepo root (marked by prisma/schema.prisma)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "prisma" / "schema.prisma").exists():
            return parent
    raise RuntimeError("could not locate the ViralCut monorepo root")


FIXTURE = _repo_root() / "packages" / "shared" / "src" / "__fixtures__" / "provider-cases.json"


# ---------------------------------------------------------------------------
# Parity with @viralcut/shared
# ---------------------------------------------------------------------------


def cases():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_file_is_present_and_non_trivial():
    data = cases()
    assert len(data) >= 15, "fixture should cover a meaningful spread of URLs"


@pytest.mark.parametrize("case", cases(), ids=lambda c: c["url"][:48] or "empty")
def test_classify_matches_typescript_fixture(case):
    result = classify(case["url"])
    assert result.kind.value == case["kind"], case["url"]
    assert result.provider == case["provider"], case["url"]
    assert result.external_id == case.get("externalId"), case["url"]
    assert result.permitted == case["permitted"], case["url"]


def test_classify_is_pure_no_network(monkeypatch):
    """classify() must never touch the network — the UI calls it on every keystroke."""

    def boom(*_args, **_kwargs):
        raise AssertionError("classify() performed network I/O")

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert classify("https://www.youtube.com/watch?v=dQw4w9WgXcQ").permitted is True


# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "127.0.0.1",
        "127.1.2.3",
        "10.0.0.5",
        "192.168.1.1",
        "172.16.0.1",
        "172.31.255.255",
        "169.254.169.254",
        "0.0.0.0",
        "::1",
        "metadata.google.internal",
    ],
)
def test_private_hosts_are_blocked(host):
    assert is_private_host(host) is True


@pytest.mark.parametrize(
    "host",
    ["example.com", "8.8.8.8", "172.15.0.1", "172.32.0.1", "cdn.viralcut.app", "notlocalhost.com"],
)
def test_public_hosts_are_allowed(host):
    assert is_private_host(host) is False


def test_generic_provider_refuses_ssrf_target():
    provider = GenericProvider(client_factory=lambda: _fake_client(200, {"content-type": "video/mp4"}))
    resolution = provider.resolve("http://169.254.169.254/latest/meta-data")
    assert resolution.permitted is False
    assert "Internal and loopback" in (resolution.reason or "")


# ---------------------------------------------------------------------------
# YouTube policy
# ---------------------------------------------------------------------------


def youtube_provider(*, oembed=(200, {"title": "Ep. 12", "author_name": "Host"}), yt_info=None, rc=0):
    calls: list[list[str]] = []

    def runner(argv, timeout):
        calls.append(argv)
        if rc != 0:
            return rc, "ERROR: [youtube] private video"
        return 0, json.dumps(yt_info or {})

    provider = YouTubeProvider(
        ytdlp_path="/usr/bin/yt-dlp",
        fetch_json=lambda url, timeout=15: oembed,
        runner=runner,
    )
    provider._calls = calls  # type: ignore[attr-defined]
    return provider


def test_youtube_public_video_is_permitted():
    provider = youtube_provider(
        yt_info={"title": "Ep. 12", "duration": 4200, "availability": "public", "age_limit": 0}
    )
    resolution = provider.resolve("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert resolution.permitted is True
    assert resolution.external_id == "dQw4w9WgXcQ"
    assert resolution.duration_seconds == 4200


def test_youtube_private_video_is_refused():
    provider = youtube_provider(oembed=(401, {}))
    resolution = provider.resolve("https://www.youtube.com/watch?v=privatevid1")
    assert resolution.permitted is False
    assert resolution.is_private is True
    assert "private or unavailable" in (resolution.reason or "")


def test_youtube_playlist_link_is_refused():
    provider = youtube_provider()
    resolution = provider.resolve("https://www.youtube.com/playlist?list=PLabc123")
    assert resolution.permitted is False
    assert "playlist" in (resolution.reason or "")


def test_youtube_drm_is_refused():
    provider = youtube_provider(
        yt_info={
            "availability": "public",
            "formats": [{"format_note": "Widevine DRM", "has_drm": True}],
        }
    )
    resolution = provider.resolve("https://www.youtube.com/watch?v=drmvideo123")
    assert resolution.permitted is False
    assert resolution.drm_protected is True
    assert "DRM" in (resolution.reason or "")


def test_youtube_age_restricted_is_refused():
    provider = youtube_provider(yt_info={"availability": "public", "age_limit": 18})
    resolution = provider.resolve("https://www.youtube.com/watch?v=agegated123")
    assert resolution.permitted is False
    assert "age-restricted" in (resolution.reason or "")


def test_youtube_live_stream_is_refused():
    provider = youtube_provider(yt_info={"availability": "public", "is_live": True})
    resolution = provider.resolve("https://www.youtube.com/watch?v=livestream1")
    assert resolution.permitted is False
    assert "Live streams" in (resolution.reason or "")


def test_youtube_needs_auth_is_refused():
    provider = youtube_provider(yt_info={"availability": "needs_auth"})
    resolution = provider.resolve("https://www.youtube.com/watch?v=needsauth1")
    assert resolution.permitted is False
    assert resolution.requires_login is True


def test_youtube_network_failure_is_not_silently_allowed():
    """If we cannot verify the source we must not pretend it is processable."""
    provider = youtube_provider(oembed=(0, {}))
    resolution = provider.resolve("https://www.youtube.com/watch?v=unknownvid1")
    assert resolution.permitted is False
    assert "Could not reach YouTube" in (resolution.reason or "")


def test_youtube_simulate_uses_skip_download():
    provider = youtube_provider(yt_info={"availability": "public"})
    provider.resolve("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    argv = provider._calls[0]  # type: ignore[attr-defined]
    assert "--skip-download" in argv, "metadata probe must never download"
    assert "--no-playlist" in argv


def test_youtube_fetch_refuses_drm_output():
    def runner(argv, timeout):
        return 1, "ERROR: The video is DRM protected"

    provider = YouTubeProvider(ytdlp_path="/usr/bin/yt-dlp", fetch_json=lambda u, t=15: (200, {}), runner=runner)
    resolution = SourceResolution(
        kind=SourceKind.YOUTUBE, provider="youtube", permitted=True,
        input_url="https://www.youtube.com/watch?v=x", external_id="x",
    )
    with pytest.raises(PermissionError, match="DRM"):
        provider.fetch(resolution, "/tmp/out.mp4")


def test_youtube_fetch_requires_ytdlp():
    provider = YouTubeProvider(ytdlp_path=None, fetch_json=lambda u, t=15: (200, {}))
    resolution = SourceResolution(
        kind=SourceKind.YOUTUBE, provider="youtube", permitted=True,
        input_url="https://www.youtube.com/watch?v=x", external_id="x",
    )
    with pytest.raises(RuntimeError, match="yt-dlp"):
        provider.fetch(resolution, "/tmp/out.mp4")


# ---------------------------------------------------------------------------
# TikTok / Facebook policy
# ---------------------------------------------------------------------------


def test_tiktok_short_link_is_followed_and_id_extracted():
    provider = TikTokProvider(
        ytdlp_path="/usr/bin/yt-dlp",
        getter=lambda url, timeout=15: (
            200,
            "https://www.tiktok.com/@creator/video/7106594312292453675",
            "",
        ),
    )
    resolution = provider.resolve("https://vm.tiktok.com/ZM8jdkqXt/")
    assert resolution.permitted is True
    assert resolution.external_id == "7106594312292453675"


def test_tiktok_removed_video_is_refused():
    provider = TikTokProvider(
        ytdlp_path="/usr/bin/yt-dlp", getter=lambda url, timeout=15: (404, "", "")
    )
    resolution = provider.resolve("https://vm.tiktok.com/gone/")
    assert resolution.permitted is False
    assert "private, removed" in (resolution.reason or "")


def test_tiktok_private_oembed_is_refused():
    provider = TikTokProvider(
        ytdlp_path="/usr/bin/yt-dlp", getter=lambda url, timeout=15: (403, "", "")
    )
    resolution = provider.resolve("https://www.tiktok.com/@user/video/7106594312292453675")
    assert resolution.permitted is False
    assert resolution.is_private is True


def test_facebook_group_post_is_refused():
    provider = FacebookProvider(ytdlp_path="/usr/bin/yt-dlp", status_getter=lambda u, t=15: 200)
    resolution = provider.resolve("https://www.facebook.com/groups/123/posts/456")
    assert resolution.permitted is False
    assert "members-only" in (resolution.reason or "")


def test_facebook_login_required_is_refused():
    provider = FacebookProvider(ytdlp_path="/usr/bin/yt-dlp", status_getter=lambda u, t=15: 403)
    resolution = provider.resolve("https://www.facebook.com/watch/?v=1234567890")
    assert resolution.permitted is False
    assert resolution.requires_login is True
    assert "never signs in" in (resolution.reason or "")


def test_facebook_public_video_is_permitted():
    provider = FacebookProvider(ytdlp_path="/usr/bin/yt-dlp", status_getter=lambda u, t=15: 200)
    resolution = provider.resolve("https://www.facebook.com/watch/?v=1234567890")
    assert resolution.permitted is True
    assert resolution.external_id == "1234567890"


# ---------------------------------------------------------------------------
# Generic provider
# ---------------------------------------------------------------------------


class _fake_client:
    """Stand-in for httpx.Client so these tests never open a socket."""

    def __init__(self, status, headers, *, stream_status=None, body=b"", stream_type=None):
        self._status = status
        self._headers = headers
        self._body = body
        self._stream_status = stream_status or status
        self._stream_type = stream_type
        self.url = "https://example.com/final.mp4"

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def head(self, url):
        return self

    def get(self, url, headers=None):
        return self

    @property
    def status_code(self):
        return self._status

    @property
    def headers(self):
        return self._headers

    def stream(self, method, url):
        self._status = self._stream_status
        if self._stream_type:
            self._headers = {**self._headers, "content-type": self._stream_type}
        return self

    def iter_bytes(self, chunk_size=1024):
        yield self._body


def test_generic_accepts_direct_media():
    provider = GenericProvider(
        client_factory=lambda: _fake_client(200, {"content-type": "video/mp4", "content-length": "1024"})
    )
    resolution = provider.resolve("https://cdn.example.com/talk.mp4")
    assert resolution.permitted is True
    assert resolution.meta["sizeBytes"] == 1024


def test_generic_refuses_html_response():
    provider = GenericProvider(client_factory=lambda: _fake_client(200, {"content-type": "text/html"}))
    resolution = provider.resolve("https://example.com/watch-page")
    assert resolution.permitted is False
    assert "HTML page" in (resolution.reason or "")


def test_generic_refuses_auth_challenge():
    provider = GenericProvider(client_factory=lambda: _fake_client(401, {}))
    resolution = provider.resolve("https://private.example.com/video.mp4")
    assert resolution.permitted is False
    assert "never bypasses" in (resolution.reason or "")


def test_generic_refuses_oversized_file():
    provider = GenericProvider(
        max_bytes=1024,
        client_factory=lambda: _fake_client(200, {"content-type": "video/mp4", "content-length": "999999"}),
    )
    resolution = provider.resolve("https://cdn.example.com/huge.mp4")
    assert resolution.permitted is False
    assert "over the" in (resolution.reason or "")


def test_generic_fetch_aborts_on_html_body():
    provider = GenericProvider(
        client_factory=lambda: _fake_client(
            200, {"content-type": "video/mp4"}, stream_type="text/html", body=b"<html>"
        )
    )
    resolution = SourceResolution(
        kind=SourceKind.GENERIC, provider="example.com", permitted=True,
        input_url="https://example.com/x.mp4",
    )
    with pytest.raises(PermissionError, match="HTML"):
        provider.fetch(resolution, "/tmp/vc-generic-test.bin")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_routes_to_the_right_adapter():
    registry = ProviderRegistry()
    assert registry.for_url("https://youtu.be/abc123456").name == "youtube"
    assert registry.for_url("https://www.tiktok.com/@a/video/1234567").name == "tiktok"
    assert registry.for_url("https://fb.watch/abc/").name == "facebook"
    assert registry.for_url("https://cdn.example.com/a.mp4").name == "generic"


def test_disabled_adapter_is_refused_gracefully():
    """Spec 39: unsupported sources degrade with a reason, never a crash."""
    registry = ProviderRegistry()
    registry.set_enabled("youtube", False)
    resolution = registry.resolve("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert resolution.permitted is False
    assert "disabled" in (resolution.reason or "")
    assert registry.describe()[0]["enabled"] is False


def test_registry_never_raises_on_adapter_failure():
    class Exploding(YouTubeProvider):
        def resolve(self, url):
            raise RuntimeError("adapter blew up")

    registry = ProviderRegistry([Exploding(ytdlp_path=None, fetch_json=lambda u, t=15: (200, {})), GenericProvider()])
    resolution = registry.resolve("https://www.youtube.com/watch?v=abc123456")
    assert resolution.permitted is False
    assert "Could not verify" in (resolution.reason or "")


def test_registry_resolve_of_unpermitted_url_skips_adapter_io():
    """A URL that fails offline routing must not trigger a network probe."""
    sentinel = YouTubeProvider(ytdlp_path=None, fetch_json=lambda u, t=15: (_ for _ in ()).throw(AssertionError("I/O")))
    registry = ProviderRegistry([sentinel, GenericProvider()])
    resolution = registry.resolve("https://www.youtube.com/playlist?list=PL123")
    assert resolution.permitted is False


def test_registry_without_generic_fallback_raises_lookup_error():
    registry = ProviderRegistry([YouTubeProvider(ytdlp_path=None, fetch_json=lambda u, t=15: (200, {}))])
    with pytest.raises(ProviderLookupError):
        registry.for_url("https://cdn.example.com/a.mp4")


def test_fetch_invokes_ytdlp_with_no_playlist(tmp_path):
    seen = {}

    def runner(argv, timeout):
        seen["argv"] = argv
        (tmp_path / "out.mp4").write_bytes(b"x")
        return 0, ""

    provider = YouTubeProvider(ytdlp_path="/usr/bin/yt-dlp", fetch_json=lambda u, t=15: (200, {}), runner=runner)
    resolution = SourceResolution(
        kind=SourceKind.YOUTUBE, provider="youtube", permitted=True,
        input_url="https://www.youtube.com/watch?v=abc", external_id="abc",
    )
    provider.fetch(resolution, str(tmp_path / "out.mp4"))
    assert "--no-playlist" in seen["argv"]
    assert "--no-overwrites" in seen["argv"]
