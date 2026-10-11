"""Load the versioned prompt registry shared with the TypeScript layer.

The same JSON files that @viralcut/ai serves are used here, so a prompt change is
a single edit in packages/ai/prompts/<version>/ and both runtimes pick it up.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger("viralcut.ai.prompts")


@dataclass(slots=True, frozen=True)
class PromptSpec:
    id: str
    version: str
    temperature: float
    max_output_tokens: int
    response_format: str
    system: str
    user_template: str
    variables: tuple[str, ...]


_cache: dict[str, PromptSpec] = {}


def prompt_dir() -> Path:
    return Path(get_settings().prompt_dir)


def available_versions() -> list[str]:
    base = prompt_dir()
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())


def get_prompt(prompt_id: str, version: str | None = None) -> PromptSpec:
    version = version or get_settings().prompt_version
    key = f"{version}/{prompt_id}"
    if key in _cache:
        return _cache[key]
    file = prompt_dir() / version / f"{prompt_id}.json"
    if not file.exists():
        raise FileNotFoundError(f"Prompt {prompt_id!r} (version {version}) not found at {file}")
    data = json.loads(file.read_text(encoding="utf-8"))
    spec = PromptSpec(
        id=data["id"],
        version=data["version"],
        temperature=float(data.get("temperature", 0.3)),
        max_output_tokens=int(data.get("maxOutputTokens", 2000)),
        response_format=data.get("responseFormat", "text"),
        system=data["system"],
        user_template=data["userTemplate"],
        variables=tuple(data.get("variables", [])),
    )
    _cache[key] = spec
    return spec


def render(template: str, variables: dict[str, object]) -> str:
    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            return match.group(0)
        value = variables[name]
        return value if isinstance(value, str) else json.dumps(value)

    return re.sub(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", _sub, template)


def render_prompt(prompt_id: str, variables: dict[str, object], version: str | None = None) -> tuple[PromptSpec, str, str]:
    spec = get_prompt(prompt_id, version)
    missing = [v for v in spec.variables if v not in variables]
    if missing:
        raise ValueError(f"Prompt {prompt_id!r} missing variables: {missing}")
    return spec, render(spec.system, variables), render(spec.user_template, variables)


def fingerprint(prompt_id: str, version: str | None = None) -> str:
    return f"{prompt_id}@{version or get_settings().prompt_version}"
