# chatgpt-web2api

Convert ChatGPT's web interface (chatgpt.com) into an OpenAI-compatible API.
Direct reverse-engineered approach — no browser automation, no Playwright.

## Features

- **OpenAI Compatible**: Drop-in replacement for `/v1/chat/completions` and `/v1/models`
- **Direct API**: POST to `/backend-api/conversation` with `curl_cffi` TLS impersonation
- **Proof-of-Work**: Built-in SHA3-512 PoW solver (ChatGPT's anti-bot challenge)
- **Cloudflare Bypass**: Safari TLS fingerprint via `curl_cffi`
- **Streaming**: SSE streaming support
- **Token Auth**: Access token or refresh token
- **API Key Auth**: Protect your endpoint with `api_keys` (e.g. `sk-chatgpt`)
- **systemd Service**: Auto-start & auto-restart included

## Quick Start

```bash
pip install curl_cffi pybase64
python chatgpt_web2api.py
```

Server starts at `http://localhost:6970/v1`.

## Configuration

Create `config.json` (copy from `config.example.json`):

```json
{
  "port": 6970,
  "host": "0.0.0.0",
  "default_model": "gpt-5.6-luna",
  "api_keys": ["sk-chatgpt"],
  "access_token": "eyJhbGciOi...your ChatGPT access token...",
  "refresh_token": null,
  "impersonate": "safari15_3"
}
```

Or use CLI:

```bash
python chatgpt_web2api.py --access-token "eyJ..." --port 6970
```

### How to get tokens

#### Access Token

1. Open https://chatgpt.com and sign in
2. Visit `https://chatgpt.com/api/auth/session` in your browser (while logged in)
3. Copy the `accessToken` value from the JSON response

#### Refresh Token (optional)

1. Use a browser cookie export extension for `chatgpt.com`
2. Look for `__Secure-next-auth.session-token` — the 45-char string is your refresh token

## Client Configuration

| Field | Value |
|-------|-------|
| Base URL | `http://<host>:6970/v1` |
| API Key | `sk-chatgpt` (or whatever you set in `api_keys`; anything if empty) |
| Model | `gpt-5.6-luna`, `gpt-5.5`, `gpt-4o`, `o3-mini`, etc. |

### curl

```bash
# Non-streaming
curl http://localhost:6970/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-chatgpt" \
  -d '{"model":"gpt-5.6-luna","messages":[{"role":"user","content":"Hello!"}]}'

# Streaming
curl http://localhost:6970/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-chatgpt" \
  -d '{"model":"gpt-5.6-luna","stream":true,"messages":[{"role":"user","content":"Hello!"}]}'
```

### OpenAI Python SDK

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:6970/v1", api_key="sk-chatgpt")
resp = client.chat.completions.create(
    model="gpt-5.6-luna",
    messages=[{"role": "user", "content": "Explain quantum computing"}]
)
print(resp.choices[0].message.content)
```

## Available Models

| Model | Description |
|-------|-------------|
| `gpt-5.6-luna` | GPT-5.6 Luna (latest, **default**) |
| `gpt-5.6-luna-mini` | GPT-5.6 Luna Mini |
| `gpt-5.5` | GPT-5.5 |
| `gpt-5.5-mini` | GPT-5.5 Mini |
| `gpt-5.3-mini` | GPT-5.3 Mini |
| `gpt-5.4-t-mini` | GPT-5.4 Thinking Mini |
| `gpt-4o` | GPT-4o |
| `gpt-4o-mini` | GPT-4o Mini |
| `gpt-4` | GPT-4 (legacy) |
| `gpt-3.5-turbo` | GPT-3.5 Turbo |
| `o1` / `o1-mini` / `o1-preview` | o1 reasoning family |
| `o3` / `o3-mini` / `o3-mini-high` | o3 reasoning family |
| `research` | Deep Research |
| `auto` | Auto model selection |

## How It Works

```
Client → /v1/chat/completions
  → GET chatgpt.com/ (obtain cookies: oai-did, __cf_bm, etc.)
  → POST /backend-api/sentinel/chat-requirements (solve PoW)
  → POST /backend-api/conversation (SSE streaming)
  → Parse SSE → OpenAI-compatible response
```

Key techniques:
- **curl_cffi** with `safari15_3` impersonation to bypass Cloudflare TLS fingerprinting
- **Proof-of-Work**: SHA3-512 brute-force with seed + difficulty from chat-requirements
- **Cookie init**: GET page first to obtain essential cookies before API calls

## systemd Service (auto-start)

```bash
cp chatgpt-web2api.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now chatgpt-web2api.service
systemctl --user status chatgpt-web2api.service
```

Logs: `journalctl --user -u chatgpt-web2api -f`

## Config Options

```json
{
  "port": 6970,
  "host": "0.0.0.0",
  "host_url": "https://chatgpt.com",
  "retry_attempts": 3,
  "retry_delay_sec": 2,
  "request_timeout_sec": 120,
  "default_model": "gpt-5.6-luna",
  "log_requests": true,
  "api_keys": [],
  "access_token": null,
  "refresh_token": null,
  "proxy": null,
  "history_disabled": true,
  "pow_difficulty": "0fffff",
  "impersonate": "safari15_3"
}
```

## Rate Limits & Limitations

- **ChatGPT rate limits apply** — free accounts are heavily limited (~10-40 msgs/hour depending on account age/region). Your proxy inherits these limits from the underlying account.
- **Turnstile**: If ChatGPT requires a Turnstile challenge, this skips it (may fail for some accounts/sessions).
- **Model availability**: Depends on your ChatGPT subscription tier (free vs Plus vs Pro).
- **Endpoint changes**: OpenAI may change their backend API at any time — this is a reverse-engineered client, expect breakage and updates.
- **Token expiry**: Access tokens expire periodically; refresh via `refresh_token` or re-extract `access_token`.

## License

MIT