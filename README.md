# chatgpt-web2api

Convert ChatGPT's web interface (chatgpt.com) into an OpenAI-compatible API. Single file, minimal deps.

## Features

- **OpenAI Compatible**: Drop-in replacement for `/v1/chat/completions` and `/v1/models`
- **Direct API**: No browser automation — reverse-engineered HTTP calls to `/backend-api/conversation`
- **Proof-of-Work**: Built-in SHA3-512 PoW solver (ChatGPT's anti-bot challenge)
- **Streaming**: SSE streaming support
- **Token Auth**: Use access token or refresh token
- **Single File**: Pure Python, only `httpx` + `pybase64` needed

## Quick Start

```bash
pip install httpx pybase64
python chatgpt_web2api.py
```

Server starts at `http://localhost:6970/v1`.

## Configuration

Create `config.json`:

```json
{
  "port": 6970,
  "access_token": "eyJhbGciOi...your ChatGPT access token...",
  "api_keys": ["sk-your-key"]
}
```

Or use a refresh token (45-char string):

```json
{
  "port": 6970,
  "refresh_token": "your_45_char_refresh_token"
}
```

Or pass via CLI:

```bash
python chatgpt_web2api.py --access-token "eyJ..." --port 6970
```

### How to get tokens

#### Access Token

1. Open https://chatgpt.com and sign in
2. Open DevTools (F12) → Application → Cookies → `https://chatgpt.com`
3. Or visit `https://chatgpt.com/api/auth/session` — copy `accessToken` from JSON response

#### Refresh Token

1. Use any "Export Cookies" extension for `chatgpt.com`
2. Look for `__Secure-next-auth.session-token` — the 45-char string part is your refresh token

## Client Configuration

| Field | Value |
|-------|-------|
| Base URL | `http://localhost:6970/v1` |
| API Key | any `api_keys` value from `config.json`; anything if not configured |
| Model | `gpt-4o`, `gpt-4o-mini`, `o3-mini`, etc. |

### curl

```bash
curl http://localhost:6970/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-key" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"Hello!"}]}'
```

### Streaming

```bash
curl http://localhost:6970/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","stream":true,"messages":[{"role":"user","content":"Write a poem"}]}'
```

### OpenAI Python SDK

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:6970/v1", api_key="sk-your-key")
resp = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Explain quantum computing"}]
)
print(resp.choices[0].message.content)
```

## Available Models

| Model | Description |
|-------|-------------|
| `gpt-4o` | GPT-4o (default) |
| `gpt-4o-mini` | GPT-4o Mini (fast) |
| `gpt-4` | GPT-4 (legacy) |
| `gpt-3.5-turbo` | GPT-3.5 Turbo |
| `o1` | o1 reasoning |
| `o1-mini` | o1-mini |
| `o1-preview` | o1-preview |
| `o3` | o3 reasoning |
| `o3-mini` | o3-mini |
| `o3-mini-high` | o3-mini high |
| `gpt-4.5o` | GPT-4.5o |
| `auto` | Auto model selection |

## How It Works

1. Client sends OpenAI-format request → `/v1/chat/completions`
2. Server fetches `/backend-api/sentinel/chat-requirements` (with PoW pre-token)
3. If PoW required: solve SHA3-512 challenge (seed + difficulty)
4. POST to `/backend-api/conversation` with SSE streaming
5. Parse SSE chunks → OpenAI-compatible response format

## Differences from gemini-web2api

| Aspect | gemini-web2api | chatgpt-web2api |
|--------|---------------|-----------------|
| Target | gemini.google.com | chatgpt.com |
| Auth | Anonymous (optional cookie) | Required (access/refresh token) |
| Anti-bot | None | Proof-of-Work (SHA3-512) |
| Stream endpoint | `StreamGenerate` (batchfeed) | `/backend-api/conversation` (SSE) |
| Response parse | JSON array | SSE event stream |

## Limitations

- **Cloudflare/Turnstile**: If ChatGPT requires Turnstile challenge, this cannot solve it automatically. Use a proxy or solve manually.
- **Rate limits**: ChatGPT web enforces rate limits per account.
- **Model availability**: Depends on your ChatGPT subscription tier (free vs Plus vs Pro).
- **Endpoint changes**: OpenAI may change their backend API at any time.

## License

MIT