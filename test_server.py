"""Tests for the Copilot365 proxy message composition logic."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server  # noqa: E402


@pytest.fixture(autouse=True)
def reset_env(monkeypatch):
    monkeypatch.setenv("COPILOT_AGENT_IDENTITY", "TEST-IDENTITY")
    monkeypatch.setenv("COPILOT_HISTORY_TURNS", "2")
    import importlib

    importlib.reload(server)


def test_identity_included_without_system_prompt():
    text = server._compose_copilot_text([server.Message(role="user", content="Hello")])
    assert text.startswith("TEST-IDENTITY")
    assert text.endswith("user: Hello")
    assert "Copilot" not in text  # identity is custom in tests


def test_system_prompt_is_preserved():
    text = server._compose_copilot_text(
        [
            server.Message(role="system", content="You are Hermes Agent."),
            server.Message(role="user", content="install an MCP server"),
        ]
    )
    assert "You are Hermes Agent." in text
    assert "System instructions from your agent runtime:" in text
    assert text.endswith("install an MCP server")


def test_history_window_is_bounded():
    msgs = [server.Message(role="system", content="sys")]
    for i in range(5):
        msgs.append(server.Message(role="user", content=f"u{i}"))
        msgs.append(server.Message(role="assistant", content=f"a{i}"))
    msgs.append(server.Message(role="user", content="final"))
    text = server._compose_copilot_text(msgs)
    # 2 turns of history = u3/a3/u4/a4
    assert "u3" in text and "a3" in text and "u4" in text and "a4" in text
    assert "u0" not in text and "u2" not in text
    assert text.endswith("user: final")


def test_only_system_messages():
    text = server._compose_copilot_text(
        [server.Message(role="system", content="be helpful")]
    )
    assert "TEST-IDENTITY" in text
    assert "be helpful" in text


def test_default_identity_disclaims_copilot():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv("COPILOT_AGENT_IDENTITY", raising=False)
    import importlib

    importlib.reload(server)
    try:
        text = server._compose_copilot_text(
            [server.Message(role="user", content="install mcp")]
        )
        assert "NOT Microsoft Copilot" in text
        assert text.endswith("install mcp")
    finally:
        monkeypatch.undo()
        importlib.reload(server)


def test_history_turns_zero_disables_history():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("COPILOT_HISTORY_TURNS", "0")
    import importlib

    importlib.reload(server)
    try:
        msgs = [
            server.Message(role="user", content="first"),
            server.Message(role="assistant", content="answer"),
            server.Message(role="user", content="second"),
        ]
        text = server._compose_copilot_text(msgs)
        assert "first" not in text
        assert text.endswith("user: second")
    finally:
        monkeypatch.undo()
        importlib.reload(server)
