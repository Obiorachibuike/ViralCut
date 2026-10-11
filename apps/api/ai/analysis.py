"""LLM-augmented moment analysis.

The deterministic engine (moments.discover) always runs first and provides the
evidence. When an LLM is configured, `MomentAnalyzer` *refines* that evidence:
it can re-title, tighten boundaries, and re-rank using the real transcript. When
no LLM is configured, the deterministic result stands on its own and
`llmRefined` is False — ViralCut never pretends an LLM ran.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ai.prompts import fingerprint, render_prompt
from ai.providers import AIProvider, ChatMessage, create_ai_provider, extract_json
from app.config import get_settings
from app.errors import AnalysisError
from moments.candidates import Candidate
from moments.discover import DiscoveryResult

logger = logging.getLogger("viralcut.ai.analysis")

_TRANSCRIPT_BUDGET_CHARS = 24_000


def _format_transcript(transcript, limit_chars: int = _TRANSCRIPT_BUDGET_CHARS) -> str:
    lines = []
    used = 0
    for segment in transcript.segments:
        speaker = f"({segment.speaker}) " if segment.speaker else ""
        line = f"[{segment.start_s:.1f}-{segment.end_s:.1f}] {speaker}{segment.text}"
        if used + len(line) > limit_chars:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


class MomentAnalyzer:
    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider if provider is not None else create_ai_provider()

    @property
    def configured(self) -> bool:
        return self.provider is not None and self.provider.available

    # -- full transcript analysis (independent second opinion) -------------
    def discover_with_llm(
        self,
        transcript,
        *,
        scenes_count: int,
        options: Any,
    ) -> list[dict[str, Any]] | None:
        """Ask the LLM to find moments from the raw transcript.

        Returns raw moment dicts or None when no LLM is configured / it failed.
        """
        if not self.configured:
            return None
        assert self.provider is not None
        try:
            spec, system, user = render_prompt(
                "find_moments",
                {
                    "title": "the source video",
                    "durationSeconds": int(transcript.duration_ms / 1000),
                    "speakerCount": len(transcript.speakers()),
                    "sceneCount": scenes_count,
                    "transcript": _format_transcript(transcript),
                    "maxCandidates": options.max_candidates or 30,
                    "minDurationSec": options.min_duration_s,
                    "maxDurationSec": options.max_duration_s,
                },
            )
        except Exception as err:
            logger.warning("could not render find_moments prompt: %s", err)
            return None

        completion = self.provider.complete(
            [ChatMessage("system", system), ChatMessage("user", user)],
            temperature=spec.temperature,
            max_tokens=spec.max_output_tokens,
            json_object=spec.response_format == "json",
            timeout=get_settings().ai_timeout_seconds,
        )
        try:
            parsed = extract_json(completion.text)
        except (AnalysisError, ValueError) as err:
            logger.warning("LLM moment output unparseable: %s", err)
            return None
        return parsed.get("moments") or None

    # -- refinement of an existing discovery result -------------------------
    def refine(
        self,
        result: DiscoveryResult,
    ) -> tuple[DiscoveryResult, str | None, str | None]:
        """Refine titles/hooks/boundaries of the discovered moments.

        Returns (result, prompt_fingerprint, model) with `llm_refined` set.
        Falls back to the deterministic result unchanged on any failure.
        """
        if not self.configured or not result.moments:
            return result, None, None
        assert self.provider is not None

        candidates_payload = [
            {
                "id": str(index),
                "startSec": m.start_ms / 1000,
                "endSec": m.end_ms / 1000,
                "transcript": m.text,
            }
            for index, m in enumerate(result.moments[:24])
        ]
        try:
            spec, system, user = render_prompt(
                "refine_moments", {"candidates": _json_dumps(candidates_payload)}
            )
            completion = self.provider.complete(
                [ChatMessage("system", system), ChatMessage("user", user)],
                temperature=spec.temperature,
                max_tokens=spec.max_output_tokens,
                json_object=spec.response_format == "json",
                timeout=get_settings().ai_timeout_seconds,
            )
            parsed = extract_json(completion.text)
        except Exception as err:
            logger.warning("refine_moments failed; keeping deterministic output (%s)", err)
            return result, None, None

        by_id = {str(i): m for i, m in enumerate(result.moments[:24])}
        applied = 0
        for entry in parsed.get("results", []):
            moment = by_id.get(str(entry.get("id")))
            if moment is None:
                continue
            if entry.get("keep") is False:
                continue
            if entry.get("title"):
                moment.title = str(entry["title"])[:80]
            if entry.get("hookLine"):
                moment.hook_options = [str(entry["hookLine"])] + moment.hook_options[1:]
            if entry.get("summary"):
                moment.summary = str(entry["summary"])[:220]
            applied += 1

        if applied:
            result.llm_refined = True
            result.engine = "llm-refined"
            return result, fingerprint("refine_moments"), self.provider.model
        return result, None, None

    # -- hooks and titles for a single clip --------------------------------
    def hooks_and_titles(
        self, *, transcript_text: str, start_s: float, end_s: float, current_title: str, category: str
    ) -> dict[str, list[str]]:
        if not self.configured:
            return {"hooks": [], "titles": [], "hashtags": []}
        assert self.provider is not None
        try:
            spec, system, user = render_prompt(
                "hooks_and_titles",
                {
                    "transcript": transcript_text,
                    "startSec": int(start_s),
                    "endSec": int(end_s),
                    "currentTitle": current_title,
                    "category": category,
                },
            )
            completion = self.provider.complete(
                [ChatMessage("system", system), ChatMessage("user", user)],
                temperature=spec.temperature,
                max_tokens=spec.max_output_tokens,
                json_object=spec.response_format == "json",
                timeout=get_settings().ai_timeout_seconds,
            )
            parsed = extract_json(completion.text)
            return {
                "hooks": [str(h) for h in parsed.get("hooks", [])],
                "titles": [str(t) for t in parsed.get("titles", [])],
                "hashtags": [str(t) for t in parsed.get("hashtags", [])],
            }
        except Exception as err:
            logger.warning("hooks_and_titles failed (%s); caller will use fallbacks", err)
            return {"hooks": [], "titles": [], "hashtags": []}


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def analysis_status() -> dict[str, Any]:
    settings = get_settings()
    provider = create_ai_provider(settings)
    return {
        "provider": settings.ai_provider if provider else None,
        "model": provider.model if provider else None,
        "configured": bool(provider and provider.available),
        "promptVersions": _available_versions(),
        "promptVersion": settings.prompt_version,
    }


def _available_versions() -> list[str]:
    from ai.prompts import available_versions

    return available_versions()
