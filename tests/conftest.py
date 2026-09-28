"""Shared fixtures. Every test runs offline: the model is scripted, the database is DuckDB."""

from __future__ import annotations

import pytest

from data_chat.backend import DuckDbBackend
from data_chat.demo_data import write_duckdb
from data_chat.llm import LlmReply


class ScriptedLlm:
    """An ``LlmClient`` that answers from a script and records every call.

    A script entry is a string (the reply text), an ``LlmReply``, or a
    callable taking the call's kwargs and returning either.
    """

    def __init__(self, *script):
        self._script = list(script)
        self.calls: list[dict] = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        entry = self._script.pop(0) if len(self._script) > 1 else self._script[0]
        if callable(entry):
            entry = entry(kwargs)
        return entry if isinstance(entry, LlmReply) else LlmReply(entry, "end_turn")

    def call_tool(self, **kwargs):
        raise AssertionError("the pipeline does not call tools")


@pytest.fixture(scope="session")
def demo_db(tmp_path_factory):
    return write_duckdb(tmp_path_factory.mktemp("db") / "demo.duckdb")


@pytest.fixture
def backend(demo_db):
    return DuckDbBackend(demo_db)
