"""The LLM port: what the pipeline needs from a model, and two adapters.

``LlmReply`` and ``LlmClient`` are the same port the Nakoa Brain uses
(``src/adp/services/data_chat_llm.py`` at b054abe, 2026-09-28): a text
completion and one forced tool call. The pipeline here only needs the text
completion; ``call_tool`` is kept so the interface matches the Brain's.

``Usage`` is new here: every reply carries its token counts, so a run can
say what each step cost. A forced tool call returns its input as a
``ToolInput`` — a plain dict, as in the Brain, that also carries ``usage``.

The adapters are new. Which one is used is configuration, not code:

    DATA_CHAT_LLM_PROVIDER = anthropic (default) | openai
    DATA_CHAT_MODEL        = model id (default per provider, see below)
    ANTHROPIC_API_KEY / OPENAI_API_KEY

The SDKs are optional extras (``uv sync --extra anthropic``), imported only
when an adapter is built.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-5",
}


@dataclass(frozen=True)
class Usage:
    """Tokens of one call. ``input_tokens`` is the uncached part of the prompt;
    the cached part is split into what was written to the cache and what was
    read from it, because the three are priced differently."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def prompt_tokens(self) -> int:
        """Everything the model read, cached or not."""
        return self.input_tokens + self.cache_write_tokens + self.cache_read_tokens


NO_USAGE = Usage()


@dataclass(frozen=True)
class LlmReply:
    """One completion: its text, why the model stopped, and its tokens.

    ``stop_reason`` is compared against ``"max_tokens"`` to tell a truncated
    SQL statement from a finished one; each adapter maps its provider's
    truncation signal onto that value.
    """

    text: str
    stop_reason: str | None
    usage: Usage = NO_USAGE


class ToolInput(dict):
    """The arguments of a forced tool call — a dict, plus the call's ``usage``."""

    usage: Usage = NO_USAGE


def _anthropic_usage(response) -> Usage:
    u = getattr(response, "usage", None)
    if u is None:
        return NO_USAGE
    return Usage(
        input_tokens=getattr(u, "input_tokens", 0) or 0,
        output_tokens=getattr(u, "output_tokens", 0) or 0,
        cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
    )


def _openai_usage(response) -> Usage:
    u = getattr(response, "usage", None)
    if u is None:
        return NO_USAGE
    details = getattr(u, "prompt_tokens_details", None)
    cached = (getattr(details, "cached_tokens", 0) or 0) if details else 0
    return Usage(
        input_tokens=(getattr(u, "prompt_tokens", 0) or 0) - cached,
        output_tokens=getattr(u, "completion_tokens", 0) or 0,
        cache_read_tokens=cached,
    )


class LlmClient(Protocol):
    """What the pipeline calls on a model."""

    def complete(
        self,
        *,
        phase: str,
        model: str,
        system: str,
        messages: list[dict],
        max_tokens: int,
        cache_system: bool = True,
    ) -> LlmReply: ...

    def call_tool(
        self,
        *,
        phase: str,
        model: str,
        system: str,
        messages: list[dict],
        tool: dict,
        max_tokens: int,
        cache_system: bool = True,
    ) -> dict[str, Any]: ...


class AnthropicLlm:
    """``LlmClient`` over the Anthropic SDK, with the system prompt cached."""

    def __init__(self, client=None) -> None:
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self._client = client

    def complete(self, *, phase, model, system, messages, max_tokens, cache_system=True):
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=(
                [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
                if cache_system
                else system
            ),
            messages=messages,
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        return LlmReply(text=text, stop_reason=response.stop_reason, usage=_anthropic_usage(response))

    def call_tool(self, *, phase, model, system, messages, tool, max_tokens, cache_system=True):
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=(
                [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
                if cache_system
                else system
            ),
            messages=messages,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
        )
        result = ToolInput(next(b for b in response.content if b.type == "tool_use").input)
        result.usage = _anthropic_usage(response)
        return result


class OpenAILlm:
    """``LlmClient`` over the OpenAI SDK (or any OpenAI-compatible endpoint).

    ``OPENAI_BASE_URL`` points it at a compatible gateway. Prompt caching is
    automatic on OpenAI's side, so ``cache_system`` has nothing to switch.
    """

    def __init__(self, client=None) -> None:
        if client is None:
            import openai

            client = openai.OpenAI()
        self._client = client

    def complete(self, *, phase, model, system, messages, max_tokens, cache_system=True):
        response = self._client.chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, *messages],
        )
        choice = response.choices[0]
        stop = "max_tokens" if choice.finish_reason == "length" else choice.finish_reason
        return LlmReply(text=choice.message.content or "", stop_reason=stop, usage=_openai_usage(response))

    def call_tool(self, *, phase, model, system, messages, tool, max_tokens, cache_system=True):
        response = self._client.chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, *messages],
            tools=[{
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool["input_schema"],
                },
            }],
            tool_choice={"type": "function", "function": {"name": tool["name"]}},
        )
        call = response.choices[0].message.tool_calls[0]
        result = ToolInput(json.loads(call.function.arguments))
        result.usage = _openai_usage(response)
        return result


def llm_from_env() -> tuple[LlmClient, str]:
    """The configured adapter and model id, from the environment."""
    provider = os.environ.get("DATA_CHAT_LLM_PROVIDER", "anthropic").lower()
    if provider not in DEFAULT_MODELS:
        raise ValueError(
            f"DATA_CHAT_LLM_PROVIDER={provider!r} — use one of {sorted(DEFAULT_MODELS)}"
        )
    model = os.environ.get("DATA_CHAT_MODEL", DEFAULT_MODELS[provider])
    try:
        llm = AnthropicLlm() if provider == "anthropic" else OpenAILlm()
    except ModuleNotFoundError as e:
        raise SystemExit(
            f"The {provider} SDK is not installed — run `uv sync --extra {provider}`."
        ) from e
    return llm, model
