# Wiring Copilot-365 Proxy to AI Agents

This guide explains how to connect the **Copilot365 Proxy** (running on `http://127.0.0.1:8081/v1`)
to **Hermes Agent** and **OpenClaw** as a custom OpenAI-compatible model provider.

---

## Hermes Agent

### Option A: Persistent provider config

Add to `~/.hermes/config.yaml`:

```yaml
providers:
  copilot365:
    name: Microsoft 365 Copilot
    base_url: http://127.0.0.1:8081/v1
    api_key: no-key-required       # Auth uses OAuth2 tokens, not API key
    default_model: copilot-chat
    transport: chat_completions
```

Then use it:

```bash
hermes --provider copilot365 "Summarise my latest emails"
```

### Option B: Inline (no config change)

```bash
hermes --provider custom --base-url http://127.0.0.1:8081/v1 "What's new in M365?"
```

### Fallback provider

If you want Copilot as a fallback when your primary model is down:

```yaml
fallback_providers:
  - provider: copilot365
    base_url: http://127.0.0.1:8081/v1
    model: copilot-chat
    api_key: no-key-required
```

---

## OpenClaw

OpenClaw uses a JSON config at `~/.openclaw/openclaw.json`. You need to:

1. Add a custom **provider** pointing at the proxy
2. Add an **allowlist entry** so OpenClaw knows it can use that model
3. Apply the config

### Step 1: Add the provider

Edit `~/.openclaw/openclaw.json` and add under `models.providers`:

```json
{
  "models": {
    "mode": "merge",
    "providers": {
      "copilot365": {
        "baseUrl": "http://127.0.0.1:8081/v1",
        "apiKey": "no-key-required",
        "api": "openai-completions",
        "models": [
          {
            "id": "copilot-chat",
            "name": "Microsoft 365 Copilot",
            "reasoning": false,
            "input": ["text"],
            "cost": {
              "input": 0,
              "output": 0,
              "cacheRead": 0,
              "cacheWrite": 0
            },
            "contextWindow": 32000,
            "maxTokens": 32000
          }
        ]
      }
    }
  }
}
```

> **Note:** Cost is set to `0` because Copilot is licensed per-seat, not per-token.
> If you want cost tracking, adjust the values to match your M365 license cost.

### Step 2: Allowlist the model

In the same file, under `agents.defaults.models`:

```json
{
  "agents": {
    "defaults": {
      "models": {
        "copilot365/copilot-chat": {
          "alias": "copilot365"
        }
      }
    }
  }
}
```

### Step 3: Apply the config

```bash
openclaw gateway config.apply --file ~/.openclaw/openclaw.json
```

The gateway will restart. Verify with:

```bash
openclaw models list --provider copilot365
# or in chat: /models
```

### Step 4: Use it

```bash
# Switch to Copilot in chat
/model copilot365

# Or reference it directly
"Use copilot365 to check my calendar conflicts"
```

---

## How it works

```
Your AI Agent (Hermes / OpenClaw)
    |
    | HTTP POST /v1/chat/completions (OpenAI format)
    v
Copilot365 Proxy (localhost:8081 — this repo)
    |
    | OAuth2 Bearer Token
    | POST /beta/copilot/conversations/{id}/chat
    v
Microsoft Graph API (your M365 tenant)
```

Both Hermes and OpenClaw speak the OpenAI chat completions wire format, so the
proxy works with either (or any OpenAI-compatible client) without changes.

## Prerequisites

Before wiring either agent:
1. Complete [Azure AD setup](./README.md#1-azure-ad-app-registration)
2. Run authentication: `python oauth.py device-code`
3. Start the proxy: `python server.py` (or via the service manager)
4. Verify: `curl http://127.0.0.1:8081/v1/models`

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401` from proxy | Token expired or missing | Re-run `python oauth.py device-code` |
| `model not allowed` (OpenClaw) | Model missing from allowlist | Add `copilot365/copilot-chat` to `agents.defaults.models` |
| `Provider not found` (Hermes) | Provider not in config | Use `--provider custom --base-url http://127.0.0.1:8081/v1` |
| `404 /v1/models` | Old proxy version | Restart proxy with latest `server.py` |
