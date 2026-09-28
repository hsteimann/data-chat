"""The LLM port: what the pipeline needs from a model, and two adapters.

``LlmReply`` and ``LlmClient`` are the same port the Nakoa Brain uses
(``src/adp/services/data_chat_llm.py`` at b054abe, 2026-09-28): a text
completion and one forced tool call. The pipeline here only needs the text
completion; ``call_tool`` is kept so the interface matches the Brain's.

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
class LlmReply:
    """One completion: its text, and why the model stopped.

    ``stop_reason`` is compared against ``"max_tokens"`` to tell a truncated
    SQL statement from a finished one; each adapter maps its provider's
    truncation signal onto that value.
    """

    text: str
    stop_reason: str | None


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
        return LlmReply(text=text, stop_reason=response.stop_reason)

    def call_tool(self, *, phase, model, system, messages, tool, max_tokens):
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
        )
        return next(b for b in response.content if b.type == "tool_use").input


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
        return LlmReply(text=choice.message.content or "", stop_reason=stop)

    def call_tool(self, *, phase, model, system, messages, tool, max_tokens):
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
        return json.loads(call.function.arguments)


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
