from types import SimpleNamespace

import pytest

from data_chat.llm import AnthropicLlm, OpenAILlm, llm_from_env


class _Recorder:
    def __init__(self, response):
        self.response, self.kwargs = response, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def test_anthropic_adapter_caches_the_system_prompt():
    messages = _Recorder(SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text="SELECT 1")],
    ))
    reply = AnthropicLlm(SimpleNamespace(messages=messages)).complete(
        phase="sql", model="m", system="SYS", messages=[], max_tokens=10)
    assert reply.text == "SELECT 1" and reply.stop_reason == "end_turn"
    assert messages.kwargs["system"] == [
        {"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}
    ]


def test_openai_adapter_maps_truncation_to_max_tokens():
    completions = _Recorder(SimpleNamespace(choices=[SimpleNamespace(
        finish_reason="length", message=SimpleNamespace(content="SELECT SUM(co"))]))
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    reply = OpenAILlm(client).complete(phase="sql", model="m", system="SYS",
                                       messages=[{"role": "user", "content": "q"}], max_tokens=10)
    assert reply.stop_reason == "max_tokens"
    assert completions.kwargs["messages"][0] == {"role": "system", "content": "SYS"}


def test_unknown_provider_is_refused(monkeypatch):
    monkeypatch.setenv("DATA_CHAT_LLM_PROVIDER", "somebody")
    with pytest.raises(ValueError, match="DATA_CHAT_LLM_PROVIDER"):
        llm_from_env()
