#!/usr/bin/env python3
"""
chatgpt-web2api - ChatGPT Web to OpenAI API proxy.

Converts ChatGPT's web interface (chatgpt.com) into an OpenAI-compatible API
server.  Direct reverse-engineered approach: POST to /backend-api/conversation,
solve proof-of-work challenges, parse SSE streaming.

Usage:
    pip install httpx pybase64
    python chatgpt_web2api.py [--port 6970] [--config config.json]

Client configuration (Cherry Studio, ChatBox, etc.):
    Base URL: http://localhost:6970/v1
    API Key:  your ChatGPT access token (or refresh token), or x-api-key

How it works:
    1. Client sends OpenAI-format request with model + messages.
    2. Server maps model name → ChatGPT backend model slug.
    3. Fetches /backend-api/sentinel/chat-requirements (solve PoW if needed).
    4. POSTs to /backend-api/conversation with SSE streaming.
    5. Parses SSE chunks → OpenAI-compatible response (streaming or not).
"""

import json
import hashlib
import random
import re
import time
import uuid
import string
import os
import sys
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from datetime import datetime, timedelta, timezone

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

try:
    import pybase64
    HAS_PYBASE64 = True
except ImportError:
    HAS_PYBASE64 = False
    import base64 as pybase64  # fallback

__version__ = "1.0.0"

# ─── Configuration ───────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "port": 6970,
    "host": "0.0.0.0",
    "host_url": "https://chatgpt.com",
    "retry_attempts": 3,
    "retry_delay_sec": 2,
    "request_timeout_sec": 180,
    "default_model": "gpt-4o",
    "log_requests": True,
    "api_keys": [],
    "access_token": None,
    "refresh_token": None,
    "proxy": None,
    "history_disabled": False,
    "pow_difficulty": "0fffff",
}

CONFIG = dict(DEFAULT_CONFIG)

# ─── Models ──────────────────────────────────────────────────────────────────

MODELS = {
    "gpt-4o":             {"slug": "gpt-4o",             "desc": "GPT-4o (default)"},
    "gpt-4o-mini":        {"slug": "gpt-4o-mini",        "desc": "GPT-4o Mini (fast)"},
    "gpt-4":              {"slug": "gpt-4",              "desc": "GPT-4 (legacy)"},
    "gpt-4-mobile":       {"slug": "gpt-4-mobile",       "desc": "GPT-4 Mobile"},
    "gpt-3.5-turbo":     {"slug": "text-davinci-002-render-sha", "desc": "GPT-3.5 Turbo"},
    "o1":                 {"slug": "o1",                 "desc": "o1 reasoning"},
    "o1-mini":            {"slug": "o1-mini",            "desc": "o1-mini"},
    "o1-preview":         {"slug": "o1-preview",         "desc": "o1-preview"},
    "o3":                 {"slug": "o3",                 "desc": "o3 reasoning"},
    "o3-mini":            {"slug": "o3-mini",            "desc": "o3-mini"},
    "o3-mini-high":       {"slug": "o3-mini-high",       "desc": "o3-mini high"},
    "gpt-4.5o":           {"slug": "gpt-4.5o",          "desc": "GPT-4.5o"},
    "gpt-4o-canmore":     {"slug": "gpt-4o-canmore",     "desc": "GPT-4o Canmore"},
    "auto":               {"slug": "auto",               "desc": "Auto model selection"},
}

# ─── PoW (Proof of Work) ────────────────────────────────────────────────────
# Based on lanqian528/chat2api proofofWork.py
# ChatGPT uses SHA3-512 based PoW with seed + difficulty

POW_CORES = [8, 16, 24, 32]
POW_NAVIGATOR_KEYS = [
    "registerProtocolHandler−function registerProtocolHandler() { [native code] }",
    "storage−[object StorageManager]",
    "locks−[object LockManager]",
    "appCodeName−Mozilla",
    "permissions−[object Permissions]",
    "share−function share() { [native code] }",
    "webdriver−false",
    "vendor−Google Inc.",
    "cookieEnabled−true",
    "product−Gecko",
    "mediaDevices−[object MediaDevices]",
    "hardwareConcurrency−32",
    "pdfViewerEnabled−true",
]
POW_DOCUMENT_KEYS = ["_reactListeningo743lnnpvdg", "location"]
POW_WINDOW_KEYS = [
    "0", "window", "self", "document", "name", "location", "customElements",
    "history", "navigation", "locationbar", "menubar", "personalbar",
    "scrollbars", "statusbar", "toolbar", "status", "closed", "frames",
    "navigator", "origin", "external", "screen", "crypto", "indexedDB",
    "sessionStorage", "localStorage", "performance", "fetch", "alert", "atob",
    "btoa", "close", "confirm", "open", "prompt", "setTimeout", "setInterval",
    "clearTimeout", "clearInterval", "requestAnimationFrame", "cancelAnimationFrame",
]

_cached_scripts = []
_cached_dpl = ""
_cached_dpl_time = 0


def log(msg: str):
    if CONFIG["log_requests"]:
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        sys.stderr.flush()


def _get_parse_time():
    """Get formatted time string for PoW config."""
    now = datetime.now(timezone(timedelta(hours=-5)))
    return now.strftime("%a %b %d %Y %H:%M:%S") + " GMT-0500 (Eastern Standard Time)"


def _get_pow_config(user_agent: str):
    """Build the PoW config array used by ChatGPT's proof-of-work."""
    # Try to fetch DPL from page if stale
    _maybe_fetch_dpl()

    config = [
        random.choice([1920 + 1080, 2560 + 1440, 1920 + 1200, 2560 + 1600]),
        _get_parse_time(),
        4294705152,
        0,
        user_agent,
        random.choice(_cached_scripts) if _cached_scripts else "",
        _cached_dpl,
        "en-US",
        "en-US,es-US,en,es",
        0,
        random.choice(POW_NAVIGATOR_KEYS),
        random.choice(POW_DOCUMENT_KEYS),
        random.choice(POW_WINDOW_KEYS),
        time.perf_counter() * 1000,
        str(uuid.uuid4()),
        "",
        random.choice(POW_CORES),
        time.time() * 1000 - (time.perf_counter() * 1000),
    ]
    return config


def _maybe_fetch_dpl():
    """Fetch DPL token from chatgpt.com page HTML (cached 15 min)."""
    global _cached_scripts, _cached_dpl, _cached_dpl_time

    if int(time.time()) - _cached_dpl_time < 15 * 60 and _cached_dpl:
        return

    try:
        url = CONFIG["host_url"] + "/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        }
        with httpx.Client(timeout=10, proxy=CONFIG.get("proxy")) as client:
            r = client.get(url, headers=headers, follow_redirects=True)
            r.raise_for_status()
            html = r.text

        # Parse script srcs
        scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)
        if scripts:
            _cached_scripts = scripts

        # Parse data-build or dpl from script URLs
        for src in scripts:
            m = re.search(r'/_next/static/([^/]+)/', src)
            if m:
                _cached_dpl = m.group(1)
                break

        # Also try data-build attribute
        if not _cached_dpl:
            m = re.search(r'data-build="([^"]+)"', html)
            if m:
                _cached_dpl = m.group(1)

        if not _cached_dpl:
            _cached_dpl = "prod-f501fe933b3edf57aea882da888e1a544df99840"

        _cached_dpl_time = int(time.time())
        log(f"DPL fetched: {_cached_dpl}")
    except Exception as e:
        log(f"DPL fetch failed: {e}, using fallback")
        if not _cached_dpl:
            _cached_dpl = "prod-f501fe933b3edf57aea882da888e1a544df99840"
        _cached_dpl_time = int(time.time())


def _generate_pow_answer(seed: str, diff: str, config: list) -> tuple:
    """Generate PoW answer. Returns (base64_answer, solved: bool)."""
    diff_len = len(diff)
    seed_encoded = seed.encode()
    static_config_part1 = (
        json.dumps(config[:3], separators=(",", ":"), ensure_ascii=False)[:-1] + ","
    ).encode()
    static_config_part2 = (
        "," + json.dumps(config[4:9], separators=(",", ":"), ensure_ascii=False)[1:-1] + ","
    ).encode()
    static_config_part3 = (
        "," + json.dumps(config[10:], separators=(",", ":"), ensure_ascii=False)[1:]
    ).encode()

    target_diff = bytes.fromhex(diff)

    for i in range(500000):
        dynamic_i = str(i).encode()
        dynamic_j = str(i >> 1).encode()
        final = (
            static_config_part1 + dynamic_i + static_config_part2 + dynamic_j + static_config_part3
        )
        base = pybase64.b64encode(final)
        hash_val = hashlib.sha3_512(seed_encoded + base).digest()
        if hash_val[:diff_len] <= target_diff:
            return base.decode(), True

    # Fallback (unsolved)
    fallback = "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D" + pybase64.b64encode(
        f'"{seed}"'.encode()
    ).decode()
    return fallback, False


def _get_answer_token(seed: str, diff: str, config: list) -> tuple:
    answer, solved = _generate_pow_answer(seed, diff, config)
    return "gAAAAAB" + answer, solved


def _get_requirements_token(config: list) -> str:
    req, _ = _generate_pow_answer(format(random.random()), "0fffff", config)
    return "gAAAAAC" + req


# ─── Token Management ────────────────────────────────────────────────────────

def refresh_token_to_access(refresh_token: str) -> str:
    """Exchange refresh token for access token via OpenAI auth endpoint."""
    url = "https://auth0.openai.com/oauth/token"
    data = {
        "redirect_uri": "com.openai.chat://auth0.openai.com/ios/com.openai.chat/callback",
        "grant_type": "refresh_token",
        "client_id": "pdlLIX2Y72MIl2rhLhTE9VV9bN905kB",
        "refresh_token": refresh_token,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    try:
        with httpx.Client(timeout=15, proxy=CONFIG.get("proxy")) as client:
            r = client.post(url, data=data, headers=headers)
            r.raise_for_status()
            return r.json()["access_token"]
    except Exception as e:
        log(f"Token refresh failed: {e}")
        raise


def get_access_token() -> str | None:
    """Get access token from config (direct or refresh)."""
    at = CONFIG.get("access_token")
    if at:
        return at

    rt = CONFIG.get("refresh_token")
    if rt:
        return refresh_token_to_access(rt)

    return None


# ─── ChatGPT Backend ─────────────────────────────────────────────────────────

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"

BASE_HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "content-type": "application/json",
    "origin": "https://chatgpt.com",
    "referer": "https://chatgpt.com/",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": UA,
}


def get_chat_requirements(access_token: str, user_agent: str = UA) -> dict:
    """POST /backend-api/sentinel/chat-requirements to get chat token + PoW challenge."""
    _maybe_fetch_dpl()
    url = CONFIG["host_url"] + "/backend-api/sentinel/chat-requirements"
    headers = BASE_HEADERS.copy()
    if access_token:
        headers["authorization"] = f"Bearer {access_token}"

    config = _get_pow_config(user_agent)
    p = _get_requirements_token(config)

    try:
        with httpx.Client(timeout=15, proxy=CONFIG.get("proxy")) as client:
            r = client.post(url, headers=headers, json={"p": p})
            if r.status_code != 200:
                raise RuntimeError(f"chat-requirements failed: {r.status_code} {r.text[:200]}")
            return r.json()
    except Exception as e:
        log(f"chat-requirements error: {e}")
        raise


def send_conversation(
    access_token: str,
    chat_token: str,
    proof_token: str | None,
    messages: list,
    model_slug: str,
    parent_msg_id: str | None = None,
    conversation_id: str | None = None,
):
    """POST /backend-api/conversation with SSE streaming. Yields SSE lines."""
    url = CONFIG["host_url"] + "/backend-api/conversation"
    headers = BASE_HEADERS.copy()
    headers["accept"] = "text/event-stream"
    if access_token:
        headers["authorization"] = f"Bearer {access_token}"
    if chat_token:
        headers["openai-sentinel-chat-requirements-token"] = chat_token
    if proof_token:
        headers["openai-sentinel-proof-token"] = proof_token

    oai_device_id = str(uuid.uuid4())
    headers["oai-device-id"] = oai_device_id

    # Build conversation request
    chat_messages = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(c.get("text", "") for c in content if c.get("type") in ("text", "input_text"))
        chat_messages.append({
            "id": str(uuid.uuid4()),
            "author": {"role": role},
            "content": {"content_type": "text", "parts": [content]},
            "metadata": {},
        })

    body = {
        "action": "next",
        "client_contextual_info": {
            "is_dark_mode": False,
            "time_since_loaded": random.randint(50, 500),
            "page_height": random.randint(500, 1000),
            "page_width": random.randint(1000, 2000),
            "pixel_ratio": 1.5,
            "screen_height": random.randint(800, 1200),
            "screen_width": random.randint(1200, 2200),
        },
        "conversation_mode": {"kind": "primary_assistant"},
        "conversation_origin": None,
        "force_paragen": False,
        "force_paragen_model_slug": "",
        "force_rate_limit": False,
        "force_use_sse": True,
        "history_and_training_disabled": CONFIG.get("history_disabled", False),
        "messages": chat_messages,
        "model": model_slug,
        "paragen_cot_summary_display_override": "allow",
        "paragen_stream_type_override": None,
        "parent_message_id": parent_msg_id or str(uuid.uuid4()),
        "reset_rate_limits": False,
        "suggestions": [],
        "supported_encodings": [],
        "system_hints": [],
        "timezone": "America/Los_Angeles",
        "timezone_offset_min": -480,
        "variant_purpose": "comparison_implicit",
        "websocket_request_id": str(uuid.uuid4()),
    }
    if conversation_id:
        body["conversation_id"] = conversation_id

    proxy = CONFIG.get("proxy")
    timeout = httpx.Timeout(CONFIG["request_timeout_sec"], connect=30)

    with httpx.Client(timeout=timeout, proxy=proxy) as client:
        with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code != 200:
                error_text = resp.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"conversation failed: {resp.status_code} {error_text[:300]}")

            for line in resp.iter_lines():
                if line:
                    yield line


# ─── SSE Parsing ─────────────────────────────────────────────────────────────

def parse_sse_stream(response_lines, model_name: str):
    """
    Parse ChatGPT SSE stream → yield OpenAI-format chunks.
    Supports both streaming and non-streaming (accumulate all).
    """
    chat_id = f"chatcmpl-{''.join(random.choice(string.ascii_letters + string.digits) for _ in range(29))}"
    created = int(time.time())
    model_slug = None

    prev_text = ""
    last_message_id = None
    last_role = None
    last_content_type = None
    end = False

    # First chunk: role announcement
    first_chunk = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model_name,
        "choices": [{
            "index": 0,
            "delta": {"role": "assistant", "content": ""},
            "logprobs": None,
            "finish_reason": None,
        }],
    }
    yield f"data: {json.dumps(first_chunk)}\n\n"

    for line in response_lines:
        if end:
            break
        if not line.startswith("data: "):
            continue
        data_str = line[6:]
        if data_str == "[DONE]":
            break
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        message = data.get("message", {})
        if not message:
            if data.get("error"):
                yield f"data: {json.dumps({'error': data['error']})}\n\n"
                break
            continue

        role = message.get("author", {}).get("role")
        if role in ("user", "system"):
            continue

        status = message.get("status")
        msg_id = message.get("id")
        content = message.get("content", {})
        metadata = message.get("metadata", {})
        model_slug = metadata.get("model_slug", model_slug)
        outer_type = content.get("content_type")

        delta_text = ""

        if status == "in_progress":
            if outer_type == "text":
                parts = content.get("parts", [])
                if parts:
                    part = parts[0]
                    if last_message_id and last_message_id != msg_id:
                        continue
                    if last_role and last_role != role and prev_text:
                        delta_text = "\n\n" + part[len(prev_text):]
                    else:
                        delta_text = part[len(prev_text):]
                    prev_text = part
            elif outer_type == "code":
                text = content.get("text", "")
                lang = content.get("language", "")
                if last_content_type != "code":
                    delta_text = f"\n```{lang}\n{text}"
                else:
                    delta_text = text
                last_content_type = "code"
            else:
                text = content.get("text", "")
                delta_text = text[len(prev_text):]

        elif status == "finished_successfully":
            if outer_type == "text":
                parts = content.get("parts", [])
                if parts:
                    part = parts[0]
                    delta_text = part[len(prev_text):]
                    prev_text = part
            delta = {"content": delta_text} if delta_text else {}
            delta["content"] = delta_text
            finish_chunk = {
                "id": chat_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_name,
                "choices": [{
                    "index": 0,
                    "delta": delta if delta_text else {},
                    "logprobs": None,
                    "finish_reason": "stop",
                }],
            }
            yield f"data: {json.dumps(finish_chunk)}\n\n"
            end = True
            last_message_id = msg_id
            last_role = role
            continue
        else:
            continue

        last_message_id = msg_id
        last_role = role

        if delta_text:
            chunk = {
                "id": chat_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_name,
                "choices": [{
                    "index": 0,
                    "delta": {"content": delta_text},
                    "logprobs": None,
                    "finish_reason": None,
                }],
            }
            yield f"data: {json.dumps(chunk)}\n\n"

    if not end:
        final = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_name,
            "choices": [{
                "index": 0,
                "delta": {},
                "logprobs": None,
                "finish_reason": "stop",
            }],
        }
        yield f"data: {json.dumps(final)}\n\n"

    yield "data: [DONE]\n\n"


def collect_full_text(response_lines) -> tuple:
    """Parse SSE stream and return full text + model_slug."""
    full_text = ""
    model_slug = None

    for line in response_lines:
        if not line.startswith("data: "):
            continue
        data_str = line[6:]
        if data_str == "[DONE]":
            break
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        message = data.get("message", {})
        if not message:
            continue

        role = message.get("author", {}).get("role")
        if role in ("user", "system"):
            continue

        status = message.get("status")
        content = message.get("content", {})
        metadata = message.get("metadata", {})
        model_slug = metadata.get("model_slug", model_slug)

        if status == "in_progress" and content.get("content_type") == "text":
            parts = content.get("parts", [])
            if parts:
                full_text = parts[0]
        elif status == "finished_successfully":
            if content.get("content_type") == "text":
                parts = content.get("parts", [])
                if parts:
                    full_text = parts[0]
            break

    return full_text, model_slug


# ─── OpenAI Format Helpers ───────────────────────────────────────────────────

def messages_to_prompt(messages: list) -> str:
    """Convert OpenAI messages to flat prompt (for logging/debug only)."""
    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(c.get("text", "") for c in content if c.get("type") in ("text", "input_text"))
        parts.append(f"[{role}]: {content}")
    return "\n\n".join(parts)


def resolve_model(model_name: str):
    """Resolve model name → slug. Returns (model_name, slug, error)."""
    cfg = MODELS.get(model_name)
    if not cfg:
        # Try fuzzy match
        for k, v in MODELS.items():
            if k.startswith(model_name) or model_name.startswith(k):
                return k, v["slug"], None
        return model_name, model_name, f"Unknown model: {model_name}"
    return model_name, cfg["slug"], None


# ─── HTTP Handler ────────────────────────────────────────────────────────────

class ChatGPTHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        client_ip = self.client_address[0] if self.client_address else "-"
        log(f"{client_ip} {fmt % args}")

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        keys = CONFIG.get("api_keys") or []
        if not keys:
            return True
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and auth[7:] in keys:
            return True
        for h in ("x-api-key",):
            if self.headers.get(h, "") in keys:
                return True
        return False

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        try:
            if self.path.startswith("/v1") and not self._authorized():
                self.send_json({"error": {"message": "invalid api key"}}, 401)
                return
            if self.path == "/v1/models":
                self.send_json({"object": "list", "data": [
                    {"id": n, "object": "model", "created": 1700000000,
                     "owned_by": "openai", "description": c["desc"]}
                    for n, c in MODELS.items()
                ]})
            elif self.path == "/" or self.path == "/health":
                self.send_json({"status": "ok", "version": __version__,
                                "models": list(MODELS.keys()),
                                "access_token": "yes" if CONFIG.get("access_token") or CONFIG.get("refresh_token") else "none"})
            else:
                self.send_json({"error": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            log(f"GET error: {e}")

    def do_POST(self):
        try:
            if self.path.startswith("/v1") and not self._authorized():
                self.send_json({"error": {"message": "invalid api key"}}, 401)
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            if self.path == "/v1/chat/completions":
                self.handle_chat(body)
            else:
                self.send_json({"error": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            log(f"POST error: {e}")
            try:
                self.send_json({"error": {"message": str(e)}}, 500)
            except:
                pass

    def handle_chat(self, body: bytes):
        req = json.loads(body)
        model_name = req.get("model", CONFIG["default_model"])
        model_name, model_slug, err = resolve_model(model_name)
        if err:
            log(f"Model error: {err}")
            self.send_json({"error": {"message": err}}, 400)
            return

        messages = req.get("messages", [])
        if not messages:
            self.send_json({"error": {"message": "empty messages"}}, 400)
            return

        stream = req.get("stream", False)
        log(f"Chat request: model={model_name} slug={model_slug} stream={stream} msgs={len(messages)}")

        # Get access token
        try:
            access_token = get_access_token()
        except Exception as e:
            self.send_json({"error": {"message": f"auth error: {e}"}}, 401)
            return

        if not access_token:
            self.send_json({"error": {"message": "No access token or refresh token configured. Set access_token or refresh_token in config.json."}}, 401)
            return

        # Get chat requirements (PoW + token)
        try:
            req_data = get_chat_requirements(access_token)
        except Exception as e:
            self.send_json({"error": {"message": f"chat-requirements failed: {e}"}}, 502)
            return

        chat_token = req_data.get("token")
        if not chat_token:
            self.send_json({"error": {"message": "No chat token from requirements", "detail": str(req_data)[:300]}}, 403)
            return

        # Solve PoW if required
        proof_token = None
        pow_data = req_data.get("proofofwork", {})
        if pow_data.get("required"):
            pow_seed = pow_data.get("seed", "")
            pow_diff = pow_data.get("difficulty", CONFIG["pow_difficulty"])
            log(f"PoW required: seed={pow_seed[:20]}... diff={pow_diff}")

            config = _get_pow_config(UA)
            proof_token, solved = _get_answer_token(pow_seed, pow_diff, config)
            if solved:
                log("PoW solved ✓")
            else:
                log("PoW unsolved (using fallback)")
        else:
            log("PoW not required")

        # Send conversation
        try:
            sse_lines = send_conversation(
                access_token=access_token,
                chat_token=chat_token,
                proof_token=proof_token,
                messages=messages,
                model_slug=model_slug,
            )

            if stream:
                # Stream SSE → client
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()

                for chunk in parse_sse_stream(sse_lines, model_name):
                    self.wfile.write(chunk.encode())
                    self.wfile.flush()
            else:
                # Non-streaming: collect full response
                full_text, resp_model_slug = collect_full_text(sse_lines)
                chat_id = f"chatcmpl-{''.join(random.choice(string.ascii_letters + string.digits) for _ in range(29))}"

                if not full_text.strip():
                    self.send_json({"error": {"message": "Empty response from ChatGPT"}}, 502)
                    return

                resp = {
                    "id": chat_id,
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model_name,
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": full_text},
                        "logprobs": None,
                        "finish_reason": "stop",
                    }],
                    "usage": {
                        "prompt_tokens": len(messages_to_prompt(messages)) // 4,
                        "completion_tokens": len(full_text) // 4,
                        "total_tokens": (len(messages_to_prompt(messages)) + len(full_text)) // 4,
                    },
                }
                self.send_json(resp)

        except Exception as e:
            log(f"Conversation error: {e}")
            try:
                self.send_json({"error": {"message": f"upstream error: {e}"}}, 502)
            except:
                pass


# ─── Main ────────────────────────────────────────────────────────────────────

def load_config(path: str):
    if path and os.path.exists(path):
        with open(path) as f:
            CONFIG.update(json.load(f))
        log(f"Config loaded: {path}")


def main():
    parser = argparse.ArgumentParser(description="ChatGPT Web to OpenAI API")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--access-token", type=str, default=None, help="ChatGPT access token")
    parser.add_argument("--refresh-token", type=str, default=None, help="ChatGPT refresh token")
    parser.add_argument("--proxy", type=str, default=None, help="HTTP proxy, e.g. http://127.0.0.1:7890")
    parser.add_argument("--version", action="version", version=f"chatgpt-web2api {__version__}")
    args = parser.parse_args()

    config_path = args.config or os.environ.get("CHATGPT_WEB2API_CONFIG")
    if not config_path:
        for p in ["./config.json", os.path.expanduser("~/.config/chatgpt-web2api/config.json")]:
            if os.path.exists(p):
                config_path = p
                break
    load_config(config_path)

    if args.port:
        CONFIG["port"] = args.port
    if args.access_token:
        CONFIG["access_token"] = args.access_token
    if args.refresh_token:
        CONFIG["refresh_token"] = args.refresh_token
    if args.proxy:
        CONFIG["proxy"] = args.proxy

    if not HAS_HTTPX:
        print("Error: httpx is required. Install with: pip install httpx")
        sys.exit(1)

    class ThreadedServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    port = CONFIG["port"]
    server = ThreadedServer((CONFIG["host"], port), ChatGPTHandler)
    print(f"chatgpt-web2api v{__version__}")
    print(f"  Listening: http://0.0.0.0:{port}")
    print(f"  Base URL:  http://localhost:{port}/v1")
    print(f"  Models:    {', '.join(MODELS.keys())}")
    print(f"  Token:     {'yes' if CONFIG.get('access_token') or CONFIG.get('refresh_token') else 'none (will fail without token)'}")
    print(f"  Proxy:     {CONFIG.get('proxy') or 'none'}")
    print(f"  Retry:     {CONFIG['retry_attempts']}x / {CONFIG['retry_delay_sec']}s")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.shutdown()


if __name__ == "__main__":
    main()