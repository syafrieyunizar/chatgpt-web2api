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

## Quick Start

```bash
pip install curl_cffi pybase64
python chatgpt_web2api.py
```

Server starts at `http://localhost:6970/v1`.

## Configuration

Create `config.json`:

```json
{
  "port": 6970,
  "access_token": "eyJhbGciOi...your ChatGPT access token...",
  "api_keys": []
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
| Base URL | `http://localhost:6970/v1` |
| API Key | any `api_keys` value from `config.json`; anything if empty |
| Model | `gpt-4o`, `gpt-4o-mini`, `o3-mini`, etc. |

### curl

```bash
# Non-streaming
curl http://localhost:6970/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Hello!"}]}'

# Streaming
curl http://localhost:6970/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","stream":true,"messages":[{"role":"user","content":"Hello!"}]}'
```

### OpenAI Python SDK

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:6970/v1", api_key="anything")
resp = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Explain quantum computing"}]
)
print(resp.choices[0].message.content)
```

## Available Models

| Model | Description |
|-------|-------------|
| `gpt-4o` | GPT-4o |
| `gpt-4o-mini` | GPT-4o Mini (fast, default) |
| `gpt-4` | GPT-4 (legacy) |
| `gpt-3.5-turbo` | GPT-3.5 Turbo |
| `o1` | o1 reasoning |
| `o1-mini` | o1-mini |
| `o1-preview` | o1-preview |
| `o3` | o3 reasoning |
| `o3-mini` | o3-mini |
| `o3-mini-high` | o3-mini high |
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

## Config Options

```json
{
  "port": 6970,
  "host": "0.0.0.0",
  "access_token": null,
  "refresh_token": null,
  "default_model": "gpt-4o-mini",
  "api_keys": [],
  "proxy": null,
  "history_disabled": true,
  "impersonate": "safari15_3",
  "pow_difficulty": "0fffff"
}
```

## Limitations

- **Turnstile**: If ChatGPT requires Turnstile challenge, this skips it (may fail for some accounts)
- **Rate limits**: ChatGPT web enforces rate limits per account
- **Model availability**: Depends on your ChatGPT subscription tier (free vs Plus vs Pro)
- **Endpoint changes**: OpenAI may change their backend API at any time

## License

MIT