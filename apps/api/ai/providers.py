"""LLM provider abstraction for the media engine.

Mirrors the TypeScript `AIProvider` in @viralcut/ai: the app is written against
this protocol and never imports a vendor SDK at a call site.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.errors import AnalysisError

logger = logging.getLogger("viralcut.ai.providers")


@dataclass(slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(slots=True)
class Completion:
    text: str
    model: str
    provider: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class AIProvider(ABC):
    id = "abstract"
    model = ""

    @property
    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int = 2000,
        json_object: bool = False,
        timeout: int = 120,
    ) -> Completion: ...


class OpenAICompatibleProvider(AIProvider):
    def __init__(self, *, api_key: str, model: str = "gpt-4o-mini", base_url: str = "https://api.openai.com/v1", id: str = "openai") -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.id = id

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, messages, *, temperature=0.3, max_tokens=2000, json_object=False, timeout=120):
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_object:
            body["response_format"] = {"type": "json_object"}
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"authorization": f"Bearer {self.api_key}", "content-type": "application/json"},
            json=body,
            timeout=timeout,
        )
        if response.status_code != 200:
            raise AnalysisError(
                "The AI analysis provider rejected the request.",
                log_detail=f"{self.id} HTTP {response.status_code}: {response.text[:300]}",
            )
        data = response.json()
        usage = data.get("usage") or {}
        return Completion(
            text=(data.get("choices") or [{}])[0].get("message", {}).get("content", ""),
            model=self.model,
            provider=self.id,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )


class AnthropicProvider(AIProvider):
    id = "anthropic"

    def __init__(self, *, api_key: str, model: str = "claude-sonnet-4-5") -> None:
        self.api_key = api_key
        self.model = model

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, messages, *, temperature=0.3, max_tokens=2000, json_object=False, timeout=120):
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        rest = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": rest,
        }
        if system:
            body["system"] = system
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
            timeout=timeout,
        )
        if response.status_code != 200:
            raise AnalysisError(
                "The AI analysis provider rejected the request.",
                log_detail=f"anthropic HTTP {response.status_code}: {response.text[:300]}",
            )
        data = response.json()
        text = "".join(block.get("text", "") for block in data.get("content", []))
        usage = data.get("usage") or {}
        return Completion(
            text=text,
            model=self.model,
            provider=self.id,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )


def create_ai_provider(settings: Settings | None = None) -> AIProvider | None:
    settings = settings or get_settings()
    provider = (settings.ai_provider or "openai").lower()
    api_key = settings.ai_api_key
    if not api_key:
        return None
    if provider == "anthropic":
        return AnthropicProvider(api_key=api_key, model=settings.ai_model or "claude-sonnet-4-5")
    if provider == "openrouter":
        return OpenAICompatibleProvider(api_key=api_key, model=settings.ai_model or "openai/gpt-4o-mini",
                                        base_url="https://openrouter.ai/api/v1", id="openrouter")
    if provider == "groq":
        return OpenAICompatibleProvider(api_key=api_key, model=settings.ai_model or "llama-3.3-70b-versatile",
                                        base_url="https://api.groq.com/openai/v1", id="groq")
    return OpenAICompatibleProvider(api_key=api_key, model=settings.ai_model or "gpt-4o-mini",
                                    base_url=settings.ai_base_url or "https://api.openai.com/v1", id="openai")


def extract_json(raw: str) -> Any:
    """Tolerantly pull a JSON object out of an LLM reply."""
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start == -1:
        raise AnalysisError("The AI did not return parseable JSON.", log_detail=raw[:200])
    end = text.rfind("}")
    return json.loads(text[start : end + 1])


import re  # noqa: E402  (used by extract_json)
