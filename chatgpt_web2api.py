#!/usr/bin/env python3
"""
chatgpt-web2api - ChatGPT Web to OpenAI API proxy with Multi-Account Support.

Converts ChatGPT's web interface (chatgpt.com) into an OpenAI-compatible API
server. Supports multiple accounts with automatic round-robin rotation.

Usage:
    pip install curl_cffi pybase64 Pillow
    python chatgpt_web2api.py [--port 6970] [--config config.json]

Client configuration (Cherry Studio, ChatBox, etc.):
    Base URL: http://localhost:6970/v1
    API Key:  sk-*** (generated or from config)

How it works:
    1. GET chatgpt.com page → obtain cookies (oai-did, __cf_bm, etc.)
    2. POST /backend-api/sentinel/chat-requirements (solve PoW if needed)
    3. POST /backend-api/conversation with SSE streaming using rotating account
    4. Parse SSE chunks → OpenAI-compatible response (streaming or not)

Multi-Account Feature:
    - Load multiple accounts from config.json
    - Round-robin rotation across requests
    - Fallback to next account if one fails
    - Each account has its own access_token + refresh_token
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
import io
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from datetime import datetime, timedelta, timezone

try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except ImportError:
    HAS_CFFI = False
    print("ERROR: curl_cffi not installed. Run: pip install curl_cffi")
    sys.exit(1)

try:
    import pybase64
    HAS_PYBASE64 = True
except ImportError:
    HAS_PYBASE64 = False
    import base64 as pybase64

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    Image = None

__version__ = "1.1.0"

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
    "account": None,  # Single account: {name, access_token, refresh_token}
    "proxy": None,
    "history_disabled": True,
    "pow_difficulty": "0fffff",
    "impersonate": "safari15_3",
}

CONFIG = dict(DEFAULT_CONFIG)

# ─── Models ──────────────────────────────────────────────────────────────────

MODELS = {
    "gpt-5.6-luna":       {"slug": "gpt-5-6",      "desc": "GPT-5.6 Luna (latest, default)"},
    "gpt-5.5":            {"slug": "gpt-5-5",      "desc": "GPT-5.5"},
    "gpt-5.6-luna-mini":  {"slug": "gpt-5-6-mini", "desc": "GPT-5.6 Luna Mini"},
    "gpt-5.5-mini":       {"slug": "gpt-5-5-mini", "desc": "GPT-5.5 Mini"},
    "gpt-5.3-mini":       {"slug": "gpt-5-3-mini", "desc": "GPT-5.3 Mini"},
    "gpt-5.4-t-mini":     {"slug": "gpt-5-4-t-mini","desc": "GPT-5.4 Thinking Mini"},
    "gpt-4o":             {"slug": "gpt-4o",       "desc": "GPT-4o"},
    "gpt-4o-mini":        {"slug": "gpt-4o-mini",  "desc": "GPT-4o Mini"},
    "gpt-4":              {"slug": "gpt-4",        "desc": "GPT-4 (legacy)"},
    "gpt-3.5-turbo":     {"slug": "text-davinci-002-render-sha", "desc": "GPT-3.5 Turbo"},
    "o1":                 {"slug": "o1",           "desc": "o1 reasoning"},
    "o1-mini":            {"slug": "o1-mini",      "desc": "o1-mini"},
    "o1-preview":         {"slug": "o1-preview",   "desc": "o1-preview"},
    "o3":                 {"slug": "o3",           "desc": "o3 reasoning"},
    "o3-mini":            {"slug": "o3-mini",      "desc": "o3-mini"},
    "o3-mini-high":       {"slug": "o3-mini-high", "desc": "o3-mini high"},
    "research":           {"slug": "research",     "desc": "Deep Research"},
    "auto":               {"slug": "auto",         "desc": "Auto model selection"},
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


# ─── Logging ─────────────────────────────────────────────────────────────────

def log(msg: str):
    if CONFIG["log_requests"]:
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        sys.stderr.flush()


# ─── PoW Functions ───────────────────────────────────────────────────────────

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


class AccountManager:
    """Manages single or multiple ChatGPT accounts."""
    
    def __init__(self, account=None):
        self.account = account
        self.current_index = 0 if account else -1
        
    def get_account(self):
        """Get current account (single) or rotate."""
        return self.account
    
    def rotate_on_error(self):
        """No-op for single-account mode."""
        pass


account_manager = None

def load_accounts_from_config():
    """Load account(s) from config.json."""
    global account_manager
    account = CONFIG.get("account")
    
    # Fallback to legacy multi-account format
    if not account:
        accounts = CONFIG.get("accounts", [])
        if accounts:
            log("WARNING: Legacy 'accounts' array detected. Using first account only.")
            account = accounts[0]
            CONFIG["account"] = account
    
    if account:
        account_manager = AccountManager(account)
        log(f"Loaded account: {account.get('name', 'Default')}")
    else:
        log("WARNING: No account configured")


def refresh_token_to_access(refresh_token: str) -> str:
    """Refresh access token using ChatGPT session endpoint.
    
    sessionToken from /api/auth/session is a NextAuth JWE token, NOT an OAuth refresh token.
    To get a fresh accessToken: call /api/auth/session with sessionToken as cookie.
    """
    url = "https://chatgpt.com/api/auth/session"
    cookies = {
        "__Secure-next-auth.session-token": refresh_token,
    }
    try:
        session = cffi_requests.Session(impersonate=CONFIG.get("impersonate", "safari15_3"))
        r = session.get(url, cookies=cookies, timeout=15)
        r.raise_for_status()
        data = r.json()
        token = data.get("accessToken")
        if not token:
            err = data.get("error", "No accessToken in response")
            log(f"Token refresh failed: {err}")
            raise RuntimeError(f"Refresh failed: {err}")
        session.close()
        log("Access token refreshed OK via session endpoint")
        return token
    except Exception as e:
        log(f"Token refresh failed: {e}")
        raise


def get_access_token_for_account(account: dict, force_refresh: bool = False) -> str:
    """Get access token for a specific account."""
    rt = account.get("refresh_token")
    at = account.get("access_token")
    
    if force_refresh and rt:
        return refresh_token_to_access(rt)
    if at:
        return at
    if rt:
        return refresh_token_to_access(rt)
    return None


# ─── Error Classes ───────────────────────────────────────────────────────────

class TokenExpiredError(RuntimeError):
    """ChatGPT rejected the access token (HTTP 401). Triggers auto-refresh."""


class RetryableError(RuntimeError):
    """Transient upstream failure (429, 5xx, timeout) worth retrying.
    
    status: HTTP status that caused it (0 = transport/network error).
    """
    
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


def is_retryable_status(status: int) -> bool:
    """True if the upstream HTTP status is worth retrying."""
    return status == 429 or 500 <= status <= 599


# ─── File Upload ────────────────────────────────────────────────────────────

MULTIMODAL_MIMES = {"image/jpeg", "image/webp", "image/png", "image/gif"}

MY_FILES_MIMES = {
    "text/x-php", "application/msword", "text/x-c", "text/html",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/json", "text/javascript", "application/pdf",
    "text/x-java", "text/x-tex", "text/x-typescript", "text/x-sh",
    "text/x-csharp", "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/x-c++", "application/x-latex", "text/markdown", "text/plain",
    "text/x-ruby", "text/x-script.python",
}

MIME_EXT_MAP = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
    "image/webp": ".webp", "application/pdf": ".pdf", "text/plain": ".txt",
    "text/markdown": ".md", "application/json": ".json", "text/html": ".html",
    "text/css": ".css", "text/xml": ".xml", "application/xml": ".xml",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/x-python": ".py", "text/x-script.python": ".py", "text/x-sh": ".sh",
    "text/javascript": ".js", "text/x-java": ".java", "text/x-c": ".c",
    "text/x-c++": ".cpp", "text/x-csharp": ".cs", "text/x-ruby": ".rb",
    "text/x-tex": ".tex", "application/x-latex": ".latex",
    "application/zip": ".zip", "application/x-zip-compressed": ".zip",
    "application/x-tar": ".tar", "application/x-gzip": ".gz",
    "audio/mpeg": ".mp3", "audio/wav": ".wav", "video/mp4": ".mp4",
    "text/csv": ".csv", "application/rtf": ".rtf",
}


def _mime_from_name(filename):
    ext = os.path.splitext(filename or "").lower()
    rev = {v: k for k, v in MIME_EXT_MAP.items() if v.startswith(ext)}
    if rev:
        return max(rev)
    return "application/octet-stream"


def _get_file_extension(mime_type):
    return MIME_EXT_MAP.get(mime_type, "")


def _determine_use_case(mime_type):
    if mime_type in MULTIMODAL_MIMES:
        return "multimodal"
    if mime_type in MY_FILES_MIMES:
        return "my_files"
    return "ace_upload"


def _parse_data_url(data_url):
    """data:<mime>;base64,<payload> → (bytes, mime)."""
    m = re.match(r"data:([^;,]+)?(;base64)?,(.*)", data_url, re.S)
    if not m:
        return None, None
    mime, is_base64, payload = m.groups()
    if is_base64:
        return pybase64.b64decode(payload), mime
    return payload.encode(), mime


# ─── ChatGPT Backend ─────────────────────────────────────────────────────────

def _make_session(account=None):
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


# ─── HTTP Server ─────────────────────────────────────────────────────────────

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class ChatGPTProxyHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    
    def log_message(self, format, *args):
        pass  # Suppress default logging
    
    def send_json(self, data, status=200):
        body = json.dumps(data, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    
    def check_api_key(self) -> str | None:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            key = auth[7:]
            if key in CONFIG["api_keys"]:
                return key
        api_key = self.headers.get("X-API-Key", "")
        if api_key in CONFIG["api_keys"]:
            return api_key
        return None
    def do_GET(self):
        if self.path == "/" or self.path == "/health":
            self.send_json({"status": "ok", "version": __version__, "account": CONFIG.get("account", {}).get("name", "none")})
        elif self.path == "/v1/models":
            models_list = [{"id": k, "object": "model", "owned_by": "chatgpt", "desc": v["desc"]} for k, v in MODELS.items()]
            self.send_json({"object": "list", "data": models_list})
        elif self.path.startswith("/v1/") and self.path.endswith("/models"):
            self.send_json({"object": "list", "data": [{"id": k, "object": "model", "owned_by": "chatgpt"} for k in MODELS.keys()]})
        else:
            self.send_json({"error": "Not found"}, 404)
    
    def do_POST(self):
        if self.path == "/v1/chat/completions":
            self.handle_chat_completions()
        else:
            self.send_json({"error": "Not found"}, 404)
    
    def handle_chat_completions(self):
        """Handle /v1/chat/completions with single account."""
        auth_key = self.check_api_key()
        if not auth_key:
            self.send_json({"error": "Missing or invalid API key"}, 401)
            return
        
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        
        try:
            request = json.loads(body.decode())
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON"}, 400)
            return
        
        messages = request.get("messages", [])
        model = request.get("model", CONFIG["default_model"])
        stream = request.get("stream", False)
        
        if not messages:
            self.send_json({"error": "No messages provided"}, 400)
            return
        
        # Get account (single account mode)
        account = account_manager.get_account() if account_manager else None
        
        if not account:
            self.send_json({"error": "No account configured"}, 503)
            return
        
        attempt = 0
        max_attempts = 3  # Allow retry after token refresh
        
        while attempt < max_attempts:
            access_token = get_access_token_for_account(account)
            if not access_token:
                self.send_json({"error": "No access token available"}, 503)
                return
            
            # Make request
            try:
                session = _make_session(account)
                init_page_cookies(session)
                
                conversation_response = self._send_conversation_request(session, messages, model, access_token, stream)
                
                session.close()
                return conversation_response
                
            except TokenExpiredError:
                log(f"Account {account['name']}: Token expired, refreshing...")
                try:
                    new_token = refresh_token_to_access(account["refresh_token"])
                    account["access_token"] = new_token
                    account_manager.rotate_on_error()
                    attempt += 1
                    continue
                except Exception as e:
                    log(f"Account {account['name']}: Refresh failed: {e}")
                    if account_manager:
                        account_manager.rotate_on_error()
                        attempt += 1
                        continue
                    else:
                        self.send_json({"error": "Token refresh failed"}, 503)
                        return
                        
            except RetryableError as e:
                log(f"Retryable error: {e} ({e.status}), trying again...")
                if account_manager:
                    account_manager.rotate_on_error()
                    attempt += 1
                    continue
                else:
                    raise
                    
            except Exception as e:
                log(f"Error: {e}")
                if account_manager:
                    account_manager.rotate_on_error()
                    attempt += 1
                    continue
                else:
                    self.send_json({"error": str(e)}, 500)
                    return
        
        self.send_json({"error": "All accounts failed"}, 503)
    
    def _send_conversation_request(self, session, messages, model, access_token, stream):
        """Send chat request to ChatGPT backend."""
        headers = _base_headers(access_token)
        
        # Try requirements endpoint first
        try:
            req_data = _get_requirements_token(_get_pow_config())
            r_req = session.post(CONFIG["host_url"] + "/backend-api/sentinel/chat-requirements",
                               json=req_data, headers=headers, timeout=30)
            if r_req.status_code == 200:
                log("Requirements check passed")
            elif r_req.status_code == 429:
                raise RetryableError(429, "Rate limited by ChatGPT")
            else:
                log(f"Requirements check: status {r_req.status_code}")
        except Exception as e:
            log(f"Requirements check skipped: {e}")
        
        # Main conversation request
        conv_data = {
            "action": "next",
            "messages": messages,
            "model": model,
            "timezone_offset_min": -420,
            "parent_message_id": str(uuid.uuid4()),
            "system_generated_messages_count": 0,
            "is_visually_text_search_enabled": False,
            "history_and_training_disabled": CONFIG.get("history_disabled", True),
        }
        
        resp = session.post(CONFIG["host_url"] + "/backend-api/conversation",
                          json=conv_data, headers=headers, timeout=CONFIG.get("request_timeout_sec", 120))
        
        if resp.status_code == 401:
            raise TokenExpiredError("Access token rejected")
        
        if resp.status_code >= 500:
            raise RetryableError(resp.status_code, f"Server error: {resp.status_code}")
        
        if resp.status_code != 200:
            self.send_json({"error": f"Backend error: {resp.status_code}", "details": resp.text[:500]}, resp.status_code)
            return
        
        if stream:
            return self._stream_response(resp)
        else:
            return self._parse_non_stream_response(resp)
    
    def _stream_response(self, resp):
        """Parse SSE stream and return OpenAI-style streaming response."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        
        buffer = b""
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if not line.startswith("data: "):
                continue
            try:
                data = json.loads(line[6:])
                if "token" in data:
                    delta = {"role": "assistant", "content": data["token"]}
                    chunk = json.dumps({"id": str(uuid.uuid4()), "object": "chat.completion.chunk",
                                      "created": int(time.time()), "model": "gpt-4o-mini",
                                      "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                                     separators=(",", ":"))
                    self.wfile.write(f"data: {chunk}\n\n".encode())
            except json.JSONDecodeError:
                continue
        
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
    
    def _parse_non_stream_response(self, resp):
        """Parse non-stream response and return OpenAI-style JSON."""
        text = resp.text.strip()
        
        # Parse SSE-like structure
        lines = text.split("\n")
        content = ""
        finish_reason = None
        
        for line in lines:
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    if "token" in data:
                        content += data["token"]
                    if "message" in data and data["message"].get("author"):
                        finish_reason = data["message"].get("end_turn")
                except json.JSONDecodeError:
                    continue
        
        response = {
            "id": str(uuid.uuid4()),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": CONFIG["default_model"],
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason or "stop"
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": len(content.split()) if content else 0,
                "total_tokens": 0
            }
        }
        self.send_json(response)


def load_config(config_path):
    """Load config from JSON file (single account mode)."""
    global CONFIG
    if not os.path.exists(config_path):
        log(f"Config file not found: {config_path}")
        sys.exit(1)
    
    with open(config_path, "r") as f:
        loaded = json.load(f)
    
    # Merge with defaults
    CONFIG.update(loaded)
    
    # Support 'api_key' field for single key or 'api_keys' array
    api_key = loaded.get("api_key")
    if api_key:
        CONFIG["api_keys"] = [api_key]
    elif not CONFIG.get("api_keys"):
        CONFIG["api_keys"] = [generate_random_api_key()]
        log(f"Generated API key: {CONFIG['api_keys'][0]}")
    
    # Check for legacy fields and convert to single account format
    if CONFIG.get("access_token") or CONFIG.get("refresh_token"):
        log("WARNING: Legacy access_token/refresh_token fields detected. Converting to single account.")
        CONFIG.setdefault("account", {})["name"] = "Legacy"
        if CONFIG.get("access_token"):
            CONFIG["account"]["access_token"] = CONFIG.get("access_token")
        if CONFIG.get("refresh_token"):
            CONFIG["account"]["refresh_token"] = CONFIG.get("refresh_token")
    
    # Convert multi-account array to first account only
    accounts = CONFIG.get("accounts", [])
    if len(accounts) > 0:
        log(f"INFO: Found {len(accounts)} accounts. Using first one only (single-account mode).")
        CONFIG["account"] = accounts[0]
    
    log(f"Configuration loaded:")
    log(f"  - Port: {CONFIG['port']}")
    log(f"  - Host: {CONFIG['host']}")
    log(f"  - Account: {'configured' if CONFIG.get('account') else 'none'}")
    log(f"  - API Key: {CONFIG['api_keys'][0][:20]}...")
    
    # Load account for this server instance
    load_accounts_from_config()


def generate_random_api_key():
    """Generate random API key."""
    return f"sk-{''.join(random.choices(string.ascii_letters + string.digits, k=32))}"


def main():
    parser = argparse.ArgumentParser(description="ChatGPT Web to API Proxy")
    parser.add_argument("--port", type=int, default=6970, help="Port to listen on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--config", default="config.json", help="Config file path")
    args = parser.parse_args()
    
    port = args.port if args.port else CONFIG["port"]
    host = args.host if args.host else CONFIG["host"]
    
    load_config(args.config)
    
    server = ThreadedHTTPServer((host, port), ChatGPTProxyHandler)
    log(f"Starting ChatGPT Web2API server on {host}:{port}")
    log(f"API Key: {CONFIG['api_keys'][0][:20]}...")
    log(f"Account: {'configured' if CONFIG.get('account') else 'none'} ({'static' if account_manager else 'none'})")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
