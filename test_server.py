"""Quick regression test for the system-prompt forwarding fix in server.py."""
import json
import sys
import types
from unittest import mock

# Mock requests before importing server
fake_responses = {
    "create": {"id": "conv-1"},
    "chat": {
        "id": "chat-1",
        "messages": [{"text": "I am Hermes Agent and I will install the MCP server now."}],
    },
}

captured_payloads = []

def _fake_post(url, **kwargs):
    if url.endswith("/copilot/conversations"):
        return types.SimpleNamespace(status_code=201, json=lambda: fake_responses["create"], text="ok")
    if "/chat" in url:
        captured_payloads.append(kwargs.get("json"))
        return types.SimpleNamespace(status_code=200, json=lambda: fake_responses["chat"], text="ok")
    raise AssertionError(f"Unexpected URL: {url}")

with mock.patch("requests.post", side_effect=_fake_post):
    import server
    # Reset in-memory state
    server._user_conversations.clear()

    from fastapi.testclient import TestClient
    client = TestClient(server.app)

    sys_prompt = "You are Hermes Agent, an AI agent with tools. You can install MCP servers."

    # Turn 1: system + user -> system prompt should be forwarded
    r1 = client.post("/v1/chat/completions", json={
        "model": "copilot-chat",
        "stream": False,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": "Install an MCP server for me"},
        ],
    })
    assert r1.status_code == 200, r1.text
    p1 = captured_payloads[0]["message"]["text"]
    assert "Install an MCP server for me" in p1
    assert "You are Hermes Agent" in p1, "system prompt missing on first turn"

    # Turn 2: system + user again -> system prompt should NOT be re-sent (same hash)
    r2 = client.post("/v1/chat/completions", json={
        "model": "copilot-chat",
        "stream": False,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": "What did I ask you to do?"},
        ],
    })
    assert r2.status_code == 200, r2.text
    p2 = captured_payloads[1]["message"]["text"]
    assert p2 == "What did I ask you to do?", f"system prompt re-sent unexpectedly: {p2}"

    # Turn 3: changed system prompt -> should be re-sent
    r3 = client.post("/v1/chat/completions", json={
        "model": "copilot-chat",
        "stream": True,
        "messages": [
            {"role": "system", "content": sys_prompt + " NEW VERSION"},
            {"role": "user", "content": "Continue"},
        ],
    })
    assert r3.status_code == 200, r3.text
    p3 = captured_payloads[2]["message"]["text"]
    assert "NEW VERSION" in p3, "changed system prompt not re-sent"

    # Developer role should also be forwarded
    server._user_conversations.clear()
    captured_payloads.clear()
    r4 = client.post("/v1/chat/completions", json={
        "model": "copilot-chat",
        "stream": False,
        "messages": [
            {"role": "developer", "content": "You are OpenClaw."},
            {"role": "user", "content": "Hello"},
        ],
    })
    assert r4.status_code == 200, r4.text
    assert "You are OpenClaw." in captured_payloads[0]["message"]["text"]

print("ALL TESTS PASSED")
