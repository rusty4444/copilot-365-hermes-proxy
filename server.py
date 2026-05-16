import json
import time
import os
import base64
import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
from dotenv import load_dotenv

# Load .env from the same directory
load_dotenv()

GRAPH_VERSION = os.getenv("GRAPH_API_VERSION", "beta")

# In-memory conversation store: user OID -> conversation_id
_user_conversations: dict[str, str] = {}


def _get_user_oid(access_token: str) -> str:
    try:
        parts = access_token.split(".")
        if len(parts) == 3:
            payload = parts[1] + "=="
            decoded = base64.urlsafe_b64decode(payload)
            claims = json.loads(decoded)
            oid = claims.get("oid")
            if oid:
                return oid
    except Exception:
        pass
    return "default"


def _load_token():
    """Load the cached OAuth2 token from disk."""
    cred_path = os.path.expanduser("~/.hermes/credentials/copilot365_token.json")
    try:
        with open(cred_path) as f:
            data = json.load(f)
        access_token = data.get("access_token", "")
        if not access_token:
            raise HTTPException(401, detail="No access token")
        return access_token
    except Exception as e:
        raise HTTPException(500, detail=f"Token error: {e}") from e


def _call_copilot(access_token: str, user_message: str) -> dict:
    """Call the Microsoft Graph Copilot API and return the response data."""
    user_oid = _get_user_oid(access_token)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # Get or create a conversation
    conversation_id = _user_conversations.get(user_oid)
    if not conversation_id:
        create = requests.post(
            f"https://graph.microsoft.com/{GRAPH_VERSION}/copilot/conversations",
            headers=headers,
            json={},
            timeout=30,
        )
        if create.status_code not in (200, 201):
            raise HTTPException(create.status_code, detail=create.text)
        conv = create.json()
        conversation_id = conv.get("id")
        if not conversation_id:
            raise HTTPException(500, detail="No conversation ID")
        _user_conversations[user_oid] = conversation_id

    # Send the chat message
    tz = os.getenv("USER_TIMEZONE", "UTC")
    chat_payload = {
        "message": {"text": user_message},
        "locationHint": {"timeZone": tz},
    }

    chat_resp = requests.post(
        f"https://graph.microsoft.com/{GRAPH_VERSION}/copilot/conversations/{conversation_id}/chat",
        headers=headers,
        json=chat_payload,
        timeout=60,
    )

    # Handle stale conversations (404/410/400 -> recreate)
    if chat_resp.status_code not in (200, 201):
        if chat_resp.status_code in (404, 410, 400):
            _user_conversations.pop(user_oid, None)
            create2 = requests.post(
                f"https://graph.microsoft.com/{GRAPH_VERSION}/copilot/conversations",
                headers=headers,
                json={},
                timeout=30,
            )
            if create2.status_code in (200, 201):
                conv2 = create2.json()
                new_id = conv2.get("id")
                if new_id:
                    _user_conversations[user_oid] = new_id
                    conversation_id = new_id
                    chat_resp = requests.post(
                        f"https://graph.microsoft.com/{GRAPH_VERSION}/copilot/conversations/{conversation_id}/chat",
                        headers=headers,
                        json=chat_payload,
                        timeout=60,
                    )
        if chat_resp.status_code not in (200, 201):
            raise HTTPException(chat_resp.status_code, detail=chat_resp.text)

    return chat_resp.json()


def _build_openai_response(graph_data: dict, model: str) -> dict:
    """Map Graph Copilot response to OpenAI chat.completion format."""
    msgs = graph_data.get("messages", [])
    assistant_content = msgs[-1].get("text", "(no response)") if msgs else "(no response)"
    return {
        "id": graph_data.get("id", ""),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": assistant_content},
                "finish_reason": "stop",
            }
        ],
    }


class Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    stream: bool = False


app = FastAPI(title="Copilot365 Proxy")


@app.get("/")
def root():
    return {"status": "ok", "service": "copilot365-proxy"}


@app.get("/v1/models")
def list_models():
    """OpenAI-compatible model list endpoint — required by Hermes for provider init."""
    return {
        "object": "list",
        "data": [
            {
                "id": "copilot-chat",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "microsoft-365",
            }
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    access_token = _load_token()

    # Extract the last user message
    user_message = None
    for msg in reversed(request.messages):
        if msg.role == "user":
            user_message = msg.content
            break
    if user_message is None:
        raise HTTPException(400, detail="No user message")

    if request.stream:
        return _handle_streaming(access_token, user_message, request.model)
    else:
        return _handle_non_streaming(access_token, user_message, request.model)


def _handle_non_streaming(access_token: str, user_message: str, model: str):
    """Non-streaming response — return full JSON."""
    graph_data = _call_copilot(access_token, user_message)
    return _build_openai_response(graph_data, model)


def _handle_streaming(access_token: str, user_message: str, model: str):
    """Streaming response — return SSE chunks.

    The Graph Copilot API does not support streaming, so we fake it by
    sending the full response as a single content chunk plus a finish chunk.
    Most AI agent frameworks (Hermes, OpenClaw, etc.) use streaming by default,
    so this is required for compatibility.
    """
    graph_data = _call_copilot(access_token, user_message)
    response_data = _build_openai_response(graph_data, model)

    response_id = response_data["id"]
    created = response_data["created"]
    content = response_data["choices"][0]["message"]["content"]

    async def generate():
        # Content chunk
        chunk = {
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": content},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(chunk)}\n\n"

        # Final chunk with finish_reason
        finish_chunk = {
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }
        yield f"data: {json.dumps(finish_chunk)}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    host = os.getenv("COPILOT_PROXY_HOST", "127.0.0.1")
    port = int(os.getenv("COPILOT_PROXY_PORT", "8081"))
    uvicorn.run(app, host=host, port=port, log_level="info")
