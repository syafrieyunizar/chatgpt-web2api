#!/usr/bin/env python3
"""
chatgpt-web2api - ChatGPT Web to OpenAI API proxy.

Converts ChatGPT's web interface (chatgpt.com) into an OpenAI-compatible API
server.  Direct reverse-engineered approach: POST to /backend-api/conversation,
solve proof-of-work challenges, parse SSE streaming.

Usage:
    pip install curl_cffi pybase64
    python chatgpt_web2api.py [--port 6970] [--config config.json]

Client configuration (Cherry Studio, ChatBox, etc.):
    Base URL: http://localhost:6970/v1
    API Key:  your ChatGPT access token (or refresh token), or x-api-key

How it works:
    1. GET chatgpt.com page → obtain cookies (oai-did, __cf_bm, etc.)
    2. POST /backend-api/sentinel/chat-requirements (solve PoW if needed)
    3. POST /backend-api/conversation with SSE streaming
    4. Parse SSE chunks → OpenAI-compatible response (streaming or not)
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
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except ImportError:
    HAS_CFFI = False

try:
    import pybase64
    HAS_PYBASE64 = True
except ImportError:
    HAS_PYBASE64 = False
    import base64 as pybase64

__version__ = "1.0.0"

# ─── Configuration ───────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "port": 6970,
    "host": "0.0.0.0",
    "host_url": "https://chatgpt.com",
    "retry_attempts": 3,
    "retry_delay_sec": 2,
    "request_timeout_sec": 120,
    "default_model": "gpt-4o-mini",
    "log_requests": True,
    "api_keys": [],
    "access_token": None,
    "refresh_token": None,
    "proxy": None,
    "history_disabled": True,
    "pow_difficulty": "0fffff",
    "impersonate": "safari15_3",
}

CONFIG = dict(DEFAULT_CONFIG)

# ─── Models ──────────────────────────────────────────────────────────────────

MODELS = {
    "gpt-4o":             {"slug": "gpt-4o",             "desc": "GPT-4o"},
    "gpt-4o-mini":        {"slug": "gpt-4o-mini",        "desc": "GPT-4o Mini (fast)"},
    "gpt-4":              {"slug": "gpt-4",              "desc": "GPT-4 (legacy)"},
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

POW_CORES = [8, 16, 24, 32]
POW_NAVIGATOR_KEYS = [
    "webdriver−false",
    "vendor−Google Inc.",
    "cookieEnabled−true",
    "product−Gecko",
    "hardwareConcurrency−32",
    "pdfViewerEnabled−true",
]
POW_DOCUMENT_KEYS = ["location"]
POW_WINDOW_KEYS = [
    "0", "window", "self", "document", "name", "location",
    "navigator", "crypto", "localStorage", "performance",
]

_cached_scripts = []
_cached_dpl = ""
_cached_dpl_time = 0

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"


def log(msg: str):
    if CONFIG["log_requests"]:
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        sys.stderr.flush()


def _get_parse_time():
    now = datetime.now(timezone(timedelta(hours=-5)))
    return now.strftime("%a %b %d %Y %H:%M:%S") + " GMT-0500 (Eastern Standard Time)"


def _get_pow_config(user_agent: str = UA):
    _maybe_fetch_dpl()
    return [
        random.choice([1920 + 1080, 2560 + 1440, 1920 + 1200]),
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


def _maybe_fetch_dpl():
    global _cached_scripts, _cached_dpl, _cached_dpl_time
    if int(time.time()) - _cached_dpl_time < 15 * 60 and _cached_dpl:
        return
    try:
        session = cffi_requests.Session(impersonate=CONFIG.get("impersonate", "safari15_3"))
        r = session.get(CONFIG["host_url"] + "/", headers={"user-agent": UA}, timeout=10)
        if r.status_code == 200:
            scripts = re.findall(r'<script[^>]+src="([^"]+)"', r.text)
            if scripts:
                _cached_scripts = scripts
            for src in scripts:
                m = re.search(r'/_next/static/([^/]+)/', src)
                if m:
                    _cached_dpl = m.group(1)
                    break
            if not _cached_dpl:
                m = re.search(r'data-build="([^"]+)"', r.text)
                if m:
                    _cached_dpl = m.group(1)
            if not _cached_dpl:
                _cached_dpl = "prod-f501fe933b3edf57aea882da888e1a544df99840"
            _cached_dpl_time = int(time.time())
            log(f"DPL fetched: {_cached_dpl}")
        session.close()
    except Exception as e:
        log(f"DPL fetch failed: {e}")
        if not _cached_dpl:
            _cached_dpl = "prod-f501fe933b3edf57aea882da888e1a544df99840"
        _cached_dpl_time = int(time.time())


def _generate_pow_answer(seed: str, diff: str, config: list) -> tuple:
    diff_len = len(diff)
    seed_enc = seed.encode()
    p1 = (json.dumps(config[:3], separators=(",", ":"), ensure_ascii=False)[:-1] + ",").encode()
    p2 = ("," + json.dumps(config[4:9], separators=(",", ":"), ensure_ascii=False)[1:-1] + ",").encode()
    p3 = ("," + json.dumps(config[10:], separators=(",", ":"), ensure_ascii=False)[1:]).encode()
    target = bytes.fromhex(diff)
    for i in range(500000):
        di = str(i).encode()
        dj = str(i >> 1).encode()
        final = p1 + di + p2 + dj + p3
        base = pybase64.b64encode(final)
        h = hashlib.sha3_512(seed_enc + base).digest()
        if h[:diff_len] <= target:
            return base.decode(), True
    return "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D" + pybase64.b64encode(f'"{seed}"'.encode()).decode(), False


def _get_answer_token(seed, diff, config):
    ans, solved = _generate_pow_answer(seed, diff, config)
    return "gAAAAAB" + ans, solved


def _get_requirements_token(config):
    req, _ = _generate_pow_answer(format(random.random()), "0fffff", config)
    return "gAAAAAC" + req


# ─── Token Management ────────────────────────────────────────────────────────

def refresh_token_to_access(refresh_token: str) -> str:
    url = "https://auth0.openai.com/oauth/token"
    data = {
        "redirect_uri": "com.openai.chat://auth0.openai.com/ios/com.openai.chat/callback",
        "grant_type": "refresh_token",
        "client_id": "pdlLIX2Y72MIl2rhLhTE9VV9bN905kB",
        "refresh_token": refresh_token,
    }
    try:
        session = cffi_requests.Session(impersonate=CONFIG.get("impersonate", "safari15_3"))
        r = session.post(url, data=data, timeout=15)
        r.raise_for_status()
        token = r.json()["access_token"]
        session.close()
        return token
    except Exception as e:
        log(f"Token refresh failed: {e}")
        raise


def get_access_token():
    at = CONFIG.get("access_token")
    if at:
        return at
    rt = CONFIG.get("refresh_token")
    if rt:
        return refresh_token_to_access(rt)
    return None


# ─── ChatGPT Backend ─────────────────────────────────────────────────────────

def _make_session():
    """Create a curl_cffi session with browser impersonation."""
    imp = CONFIG.get("impersonate", "safari15_3")
    proxy = CONFIG.get("proxy")
    session = cffi_requests.Session(impersonate=imp, proxy=proxy)
    return session


def _base_headers(access_token):
    h = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "origin": "https://chatgpt.com",
        "referer": "https://chatgpt.com/",
        "user-agent": UA,
    }
    if access_token:
        h["authorization"] = f"Bearer {access_token}"
    return h


def init_page_cookies(session):
    """GET chatgpt.com/ to obtain essential cookies (oai-did, __cf_bm, etc)."""
    r = session.get(CONFIG["host_url"] + "/", headers={"user-agent": UA}, timeout=10)
    if r.status_code != 200:
        log(f"Page load warning: status {r.status_code}")
    # Also update DPL from page
    global _cached_scripts, _cached_dpl, _cached_dpl_time
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', r.text)
    if scripts:
        _cached_scripts = scripts
    for src in scripts:
        m = re.search(r'/_next/static/([^/]+)/', src)
        if m:
            _cached_dpl = m.group(1)
            break
    if not _cached_dpl:
        m = re.search(r'data-build="([^"]+)"', r.text)
        if m:
            _cached_dpl = m.group(1)
    if _cached_dpl:
        _cached_dpl_time = int(time.time())
    return r.status_code


def get_chat_requirements(session, access_token):
    """POST /backend-api/sentinel/chat-requirements."""
    url = CONFIG["host_url"] + "/backend-api/sentinel/chat-requirements"
    headers = _base_headers(access_token)
    headers["oai-device-id"] = str(uuid.uuid4())

    config = _get_pow_config(UA)
    p = _get_requirements_token(config)

    r = session.post(url, headers=headers, json={"p": p}, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"chat-requirements failed: {r.status_code} {r.text[:300]}")
    return r.json(), config


def send_conversation(session, access_token, chat_token, proof_token, messages, model_slug, oai_device_id):
    """POST /backend-api/conversation with SSE streaming. Yields SSE lines."""
    url = CONFIG["host_url"] + "/backend-api/conversation"
    headers = _base_headers(access_token)
    headers["accept"] = "text/event-stream"
    headers["oai-device-id"] = oai_device_id
    if chat_token:
        headers["openai-sentinel-chat-requirements-token"] = chat_token
    if proof_token:
        headers["openai-sentinel-proof-token"] = proof_token

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
        "history_and_training_disabled": CONFIG.get("history_disabled", True),
        "messages": chat_messages,
        "model": model_slug,
        "paragen_cot_summary_display_override": "allow",
        "paragen_stream_type_override": None,
        "parent_message_id": str(uuid.uuid4()),
        "reset_rate_limits": False,
        "suggestions": [],
        "supported_encodings": [],
        "system_hints": [],
        "timezone": "America/Los_Angeles",
        "timezone_offset_min": -480,
        "variant_purpose": "comparison_implicit",
        "websocket_request_id": str(uuid.uuid4()),
    }

    resp = session.post(url, headers=headers, json=body, timeout=CONFIG["request_timeout_sec"], stream=True)
    if resp.status_code != 200:
        error_body = resp.text[:500] if hasattr(resp, 'text') else "unknown"
        raise RuntimeError(f"conversation failed: {resp.status_code} {error_body}")

    for line in resp.iter_lines():
        yield line


# ─── SSE Parsing ─────────────────────────────────────────────────────────────

def _decode_line(line):
    if isinstance(line, bytes):
        return line.decode("utf-8", errors="replace")
    return line or ""


def parse_sse_stream(response_lines, model_name):
    """Parse ChatGPT SSE → OpenAI-format chunks. Yields SSE strings."""
    chat_id = f"chatcmpl-{''.join(random.choice(string.ascii_letters + string.digits) for _ in range(29))}"
    created = int(time.time())

    # First chunk: role
    yield f"data: {json.dumps({'id': chat_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_name, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': ''}, 'logprobs': None, 'finish_reason': None}]})}\n\n"

    prev_text = ""
    end = False

    for raw in response_lines:
        if end:
            break
        line = _decode_line(raw)
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
        content = message.get("content", {})

        if status == "in_progress":
            ct = content.get("content_type")
            if ct == "text":
                parts = content.get("parts", [])
                if parts:
                    part = parts[0]
                    if isinstance(part, str) and len(part) > len(prev_text):
                        delta = part[len(prev_text):]
                        prev_text = part
                        yield f"data: {json.dumps({'id': chat_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_name, 'choices': [{'index': 0, 'delta': {'content': delta}, 'logprobs': None, 'finish_reason': None}]})}\n\n"

        elif status == "finished_successfully":
            if content.get("content_type") == "text":
                parts = content.get("parts", [])
                if parts and isinstance(parts[0], str):
                    final_part = parts[0]
                    delta = final_part[len(prev_text):] if len(final_part) > len(prev_text) else ""
                    if delta:
                        yield f"data: {json.dumps({'id': chat_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_name, 'choices': [{'index': 0, 'delta': {'content': delta}, 'logprobs': None, 'finish_reason': None}]})}\n\n"
            # Final chunk
            yield f"data: {json.dumps({'id': chat_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_name, 'choices': [{'index': 0, 'delta': {}, 'logprobs': None, 'finish_reason': 'stop'}]})}\n\n"
            end = True

    if not end:
        yield f"data: {json.dumps({'id': chat_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_name, 'choices': [{'index': 0, 'delta': {}, 'logprobs': None, 'finish_reason': 'stop'}]})}\n\n"

    yield "data: [DONE]\n\n"


def collect_full_text(response_lines):
    """Parse SSE stream → (full_text, model_slug)."""
    full_text = ""
    for raw in response_lines:
        line = _decode_line(raw)
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
        if status == "finished_successfully" and content.get("content_type") == "text":
            parts = content.get("parts", [])
            if parts and isinstance(parts[0], str):
                full_text = parts[0]
                break
        elif status == "in_progress" and content.get("content_type") == "text":
            parts = content.get("parts", [])
            if parts and isinstance(parts[0], str):
                full_text = parts[0]
    return full_text


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
        if self.headers.get("x-api-key", "") in keys:
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
                                "token_configured": bool(CONFIG.get("access_token") or CONFIG.get("refresh_token"))})
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
        model_cfg = MODELS.get(model_name)
        if not model_cfg:
            for k, v in MODELS.items():
                if k.startswith(model_name) or model_name.startswith(k):
                    model_name, model_cfg = k, v
                    break
        if not model_cfg:
            self.send_json({"error": {"message": f"Unknown model: {model_name}"}}, 400)
            return
        model_slug = model_cfg["slug"]

        messages = req.get("messages", [])
        if not messages:
            self.send_json({"error": {"message": "empty messages"}}, 400)
            return

        stream = req.get("stream", False)
        log(f"Chat: model={model_name} slug={model_slug} stream={stream} msgs={len(messages)}")

        # Get access token
        try:
            access_token = get_access_token()
        except Exception as e:
            self.send_json({"error": {"message": f"auth error: {e}"}}, 401)
            return
        if not access_token:
            self.send_json({"error": {"message": "No access_token or refresh_token configured"}}, 401)
            return

        # Create session with browser impersonation
        session = _make_session()

        try:
            # Step 1: Load page for cookies
            init_page_cookies(session)

            # Step 2: Get chat requirements
            req_data, pow_config = get_chat_requirements(session, access_token)
            chat_token = req_data.get("token")
            if not chat_token:
                self.send_json({"error": {"message": "No chat token", "detail": str(req_data)[:300]}}, 403)
                return

            # Step 3: Solve PoW
            proof_token = None
            pow_data = req_data.get("proofofwork", {})
            if pow_data.get("required"):
                pow_seed = pow_data.get("seed", "")
                pow_diff = pow_data.get("difficulty", CONFIG["pow_difficulty"])
                log(f"PoW: seed={pow_seed[:20]}... diff={pow_diff}")
                proof_token, solved = _get_answer_token(pow_seed, pow_diff, pow_config)
                log(f"PoW solved: {solved}")
            else:
                log("PoW not required")

            # Step 4: Send conversation
            oai_device_id = str(uuid.uuid4())
            sse_lines = send_conversation(
                session, access_token, chat_token, proof_token,
                messages, model_slug, oai_device_id,
            )

            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                for chunk in parse_sse_stream(sse_lines, model_name):
                    self.wfile.write(chunk.encode())
                    self.wfile.flush()
            else:
                full_text = collect_full_text(sse_lines)
                chat_id = f"chatcmpl-{''.join(random.choice(string.ascii_letters + string.digits) for _ in range(29))}"
                if not full_text.strip():
                    self.send_json({"error": {"message": "Empty response from ChatGPT"}}, 502)
                    return
                self.send_json({
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
                    "usage": {"prompt_tokens": 0, "completion_tokens": len(full_text) // 4, "total_tokens": len(full_text) // 4},
                })

        except Exception as e:
            log(f"Conversation error: {e}")
            try:
                self.send_json({"error": {"message": f"upstream error: {e}"}}, 502)
            except:
                pass
        finally:
            session.close()


# ─── Main ────────────────────────────────────────────────────────────────────

def load_config(path):
    if path and os.path.exists(path):
        with open(path) as f:
            CONFIG.update(json.load(f))
        log(f"Config loaded: {path}")


def main():
    parser = argparse.ArgumentParser(description="ChatGPT Web to OpenAI API")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--access-token", type=str, default=None)
    parser.add_argument("--refresh-token", type=str, default=None)
    parser.add_argument("--proxy", type=str, default=None)
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

    if not HAS_CFFI:
        print("Error: curl_cffi is required. Install with: pip install curl_cffi")
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
    print(f"  Token:     {'yes' if CONFIG.get('access_token') or CONFIG.get('refresh_token') else 'none'}")
    print(f"  Proxy:     {CONFIG.get('proxy') or 'none'}")
    print(f"  Impersonate: {CONFIG.get('impersonate', 'safari15_3')}")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.shutdown()


if __name__ == "__main__":
    main()