# Microsoft 365 Copilot → OpenAI Proxy

A local FastAPI proxy that translates **OpenAI-compatible `/v1/chat/completions`** requests into **Microsoft Graph Copilot Chat API** calls. Designed for use with AI agent frameworks (like Hermes Agent) that support custom OpenAI-format providers.

## Architecture

```
Your AI Agent (OpenAI client)
    |
    | HTTP POST /v1/chat/completions
    v
Copilot365 Proxy (FastAPI, localhost:8081)
    |
    | OAuth2 Bearer Token
    | POST /beta/copilot/conversations/{id}/chat
    v
Microsoft Graph Copilot API
    |
    v
OpenAI-compatible JSON response
```

## Prerequisites

- **Microsoft 365 Copilot license** assigned to your user account
- **Azure AD Global Admin** (or ability to register apps and grant consent)
- Python 3.11+

## Setup

### 1. Azure AD App Registration

1. Go to **Azure Portal → Azure Active Directory → App registrations → New registration**
   - Name: anything (e.g. `Copilot Proxy`)
   - Supported account types: **Accounts in this organizational directory only**
   - Redirect URI: `http://localhost:8081/callback`
   - Register

2. **Certificates & Secrets → New client secret** — save the value

3. **API permissions → Add a permission → Microsoft Graph → Delegated permissions**:
   - `Sites.Read.All`
   - `Mail.Read`
   - `People.Read.All`
   - `OnlineMeetingTranscript.Read.All`
   - `Chat.Read`
   - `ChannelMessage.Read.All`
   - `ExternalItem.Read.All`
   - **Grant admin consent** after adding

### 2. Install & Configure

```bash
# Clone the repo
git clone https://github.com/<your-org>/copilot-364-hermes-proxy.git
cd copilot-364-hermes-proxy

# Install dependencies
pip install -r requirements.txt

# Create config from template
cp .env.example .env
# Edit .env with your Azure AD credentials
```

### 3. Authenticate

```bash
# Option A: Device code flow (headless/SSH friendly)
python oauth.py device-code
# → Visit https://login.microsoft.com/device, enter the displayed code

# Option B: PKCE flow (opens browser)
python oauth.py pkce
```

### 4. Start the Proxy

```bash
# Start
python server.py

# Or via the included service manager
chmod +x copilot365-proxy
./copilot365-proxy start
./copilot365-proxy status
./copilot365-proxy stop
```

### 5. Use it

```bash
# Quick test with curl
curl -X POST http://127.0.0.1:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"copilot-chat","messages":[{"role":"user","content":"Hello"}]}'

# Configure Hermes (see USAGE.md for full guide):
# Add provider to ~/.hermes/config.yaml then:
hermes chat -q "What's new?" --provider copilot365 --model copilot-chat -Q
```

## Files

| File | Purpose |
|---|---|
| `server.py` | FastAPI proxy — translates OpenAI → Graph API |
| `oauth.py` | OAuth2 Device Code & PKCE flow — handles auth + token refresh |
| `.env.example` | Configuration template (credentials redacted) |
| `requirements.txt` | Python dependencies |
| `copilot365-proxy` | Service manager script (start/stop/status) |
| `setup-copilot365` | Interactive setup wizard |

## Required Graph Permissions (Delegated)

These 7 scopes are required. There is **no `Copilot.Chat` scope** — the API checks for these:

| Scope | Purpose |
|---|---|
| `Sites.Read.All` | Read SharePoint content |
| `Mail.Read` | Read user mail |
| `People.Read.All` | Read user profile data |
| `OnlineMeetingTranscript.Read.All` | Read meeting transcripts |
| `Chat.Read` | Read Teams chat history |
| `ChannelMessage.Read.All` | Read Teams channel messages |
| `ExternalItem.Read.All` | Read Microsoft Graph connectors data |

## Connecting AI Agents

This proxy works with any OpenAI-compatible client. See **[USAGE.md](./USAGE.md)** for wiring guides:

- **Hermes Agent** — add as a `copilot365` provider in `~/.hermes/config.yaml`
- **OpenClaw** — add as a custom `openai-completions` provider in `~/.openclaw/openclaw.json`

## Notes

- **Streaming**: Supported via fake SSE streaming — the full Graph response is delivered as a single content chunk. Required because most AI agents (Hermes, etc.) default to streaming mode.
- **Conversation state**: Kept in memory — restarting the proxy starts a fresh conversation.
- **Token cache**: Stored at `~/.hermes/credentials/copilot365_token.json` with auto-refresh.
- **Port**: Defaults to `8081`; configure via `COPILOT_PROXY_PORT` in `.env`.
