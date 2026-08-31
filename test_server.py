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

    # Stale-conversation recovery: when Copilot 410s an existing conversation
    # mid-session, the rebuilt conversation's first message must still carry
    # the system context even though the current turn's payload was computed
    # as a plain user message (hash matched before the stale reply).
    server._user_conversations.clear()
    captured_payloads.clear()
    stale_payloads = []
    stale_calls = {"create_count": 0, "chat_counts": {}}

    def _fake_post_stale(url, **kwargs):
        if url.endswith("/copilot/conversations"):
            stale_calls["create_count"] += 1
            return types.SimpleNamespace(
                status_code=201,
                json=lambda: {"id": f"conv-{stale_calls['create_count']}"},
                text="ok",
            )
        if "/chat" in url:
            stale_payloads.append(kwargs.get("json"))
            conv_id = url.split("/copilot/conversations/")[1].split("/chat")[0]
            stale_calls["chat_counts"][conv_id] = stale_calls["chat_counts"].get(conv_id, 0) + 1
            # conv-1 goes stale on its second chat call (mid-conversation 410)
            if conv_id == "conv-1" and stale_calls["chat_counts"][conv_id] == 2:
                return types.SimpleNamespace(status_code=410, json=lambda: {}, text="gone")
            return types.SimpleNamespace(status_code=200, json=lambda: fake_responses["chat"], text="ok")
        raise AssertionError(f"Unexpected URL: {url}")

    with mock.patch("requests.post", side_effect=_fake_post_stale):
        sys_prompt2 = "You are Hermes Agent. Act as Hermes."
        for user_text in ("first", "second", "third"):
            r = client.post("/v1/chat/completions", json={
                "model": "copilot-chat",
                "stream": False,
                "messages": [
                    {"role": "system", "content": sys_prompt2},
                    {"role": "user", "content": user_text},
                ],
            })
            assert r.status_code == 200, r.text

    # Call 1: fresh conv-1, system context prefixed.
    assert "You are Hermes Agent." in stale_payloads[0]["message"]["text"]
    # Call 2: conv-1's second chat 410s -> rebuilt conv-2's first message must
    # still carry the system context even though the turn started out plain.
    assert stale_payloads[1]["message"]["text"] == "second"
    rebuilt = stale_payloads[2]["message"]["text"]
    assert "You are Hermes Agent." in rebuilt, "persona dropped on rebuilt conversation"
    assert "second" in rebuilt
    # Call 3: hash committed on the rebuilt conversation -> plain again.
    assert stale_payloads[3]["message"]["text"] == "third"

print("ALL TESTS PASSED")
