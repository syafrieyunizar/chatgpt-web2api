#!/bin/bash
# ============================================
# ChatGPT Web2API - One-Click Setup
# Langkah 1: Run script ini
# Langkah 2: Paste token dari chatgpt.com/api/auth/session
# Selesai! Server jalan di localhost:6970
# ============================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION_TMP="/tmp/chatgpt_session_$$"

G='\033[0;32m'; Y='\033[1;33m'; B='\033[0;34m'; R='\033[0;31m'; N='\033[0m'

echo -e "${B}╔══════════════════════════════════════════╗${N}"
echo -e "${B}║  ChatGPT Web2API - One-Click Setup       ║${N}"
echo -e "${B}╚══════════════════════════════════════════╝${N}"
echo ""

# ─── Step 1: Check dependencies ──────────────
echo -e "${Y}[1/4] Checking dependencies...${N}"
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "   Creating virtual environment..."
    python3 -m venv "$SCRIPT_DIR/.venv"
fi
source "$SCRIPT_DIR/.venv/bin/activate"
pip install -q -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null || {
    echo -e "${R}ERROR: Failed to install dependencies${N}"
    echo "   Run manually: pip install curl_cffi pybase64 Pillow"
    exit 1
}
echo -e "${G}   ✓ Dependencies ready${N}"
echo ""

# ─── Step 2: Get session token ───────────────
echo -e "${Y}[2/4] Get your ChatGPT session token${N}"
echo ""
echo "   1. Buka browser: ${B}https://chatgpt.com/api/auth/session${N}"
echo "   2. Login ke ChatGPT (kalau belum)"
echo "   3. Halaman menampilkan JSON dengan WARNING_BANNER"
echo "      abaikan banner, yang penting ada accessToken + sessionToken"
echo "   4. ${Y}Ctrl+A${N} (select all) → ${Y}Ctrl+C${N} (copy)"
echo "   5. Paste di bawah ini, lalu tekan ${Y}Enter${N} di baris kosong"
echo ""
echo -e "${G}┌──────────────────────────────────────────────┐${N}"
echo -e "${G}│  PASTE JSON HERE (paste, Enter, lalu Ctrl+D)  │${N}"
echo -e "${G}└──────────────────────────────────────────────┘${N}"
echo ""

# Use Python to capture stdin reliably (handles long lines, no cat truncation)
python3 -c "
import sys
data = sys.stdin.read()
with open('$SESSION_TMP', 'w') as f:
    f.write(data)
print(f'Read {len(data)} bytes')
"

# ─── Step 3: Parse & generate config ─────────
echo ""
echo -e "${Y}[3/4] Parsing token & generating config...${N}"

python3 << EOF
import json, sys, os, string, random
from pathlib import Path

session_file = "$SESSION_TMP"
script_dir = "$SCRIPT_DIR"

with open(session_file, 'r') as f:
    raw = f.read().strip()

# Parse JSON — handle cases where paste includes extra whitespace/newlines
try:
    data = json.loads(raw)
except json.JSONDecodeError:
    # Try to extract JSON object using regex (handles embedded JSON)
    import re
    # Find the outermost JSON object
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', raw, re.DOTALL)
    if not match:
        # Try progressively: find from first { to last }
        first = raw.find('{')
        last = raw.rfind('}')
        if first != -1 and last != -1:
            try:
                data = json.loads(raw[first:last+1])
            except:
                print("ERROR: Could not parse JSON from input")
                print(f"Input length: {len(raw)} chars")
                print(f"First 200 chars: {raw[:200]}")
                sys.exit(1)
        else:
            print("ERROR: No JSON object found in input")
            sys.exit(1)
    else:
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON - {e}")
            sys.exit(1)

# Validate
if 'accessToken' not in data:
    print("ERROR: No 'accessToken' found in pasted data")
    print(f"Keys found: {list(data.keys())}")
    sys.exit(1)

access_token = data['accessToken']
refresh_token = data.get('sessionToken', '')
if not refresh_token:
    refresh_token = data.get('refreshToken', '')

user_name = data.get('user', {}).get('name', 'Unknown')
expires = data.get('expires', 'Unknown')

print(f"   ✓ User: {user_name}")
print(f"   ✓ AccessToken: {len(access_token)} chars")
print(f"   ✓ SessionToken: {len(refresh_token)} chars")
print(f"   ✓ Expires: {expires}")

# Generate random API key
api_key = "sk-" + ''.join(random.choices(string.ascii_letters + string.digits, k=32))

config = {
    "port": 6970,
    "host": "0.0.0.0",
    "api_key": api_key,
    "account": {
        "name": user_name,
        "access_token": access_token,
        "refresh_token": refresh_token
    }
}

config_path = Path(script_dir) / "config.json"
with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)

print(f"   ✓ Config saved: {config_path}")
print(f"   ✓ API Key: {api_key}")

with open("/tmp/chatgpt_api_key_$$", "w") as f:
    f.write(api_key)
EOF

if [ $? -ne 0 ]; then
    echo -e "${R}ERROR: Failed to parse token${N}"
    rm -f "$SESSION_TMP"
    exit 1
fi

echo -e "${G}   ✓ Config generated!${N}"
echo ""

# ─── Step 4: Start server ────────────────────
echo -e "${Y}[4/4] Starting server on port 6970...${N}"

fuser -k 6970/tcp 2>/dev/null || true
sleep 1

cd "$SCRIPT_DIR"
nohup .venv/bin/python3 chatgpt_web2api.py --config config.json > /tmp/chatgpt-web2api.log 2>&1 &
SERVER_PID=$!
sleep 3

if curl -s http://localhost:6970/ > /dev/null 2>&1; then
    echo -e "${G}   ✓ Server running on port 6970 (PID: $SERVER_PID)${N}"
else
    echo -e "${R}   ⚠ Server may have issues. Check log:${N}"
    echo "   tail -20 /tmp/chatgpt-web2api.log"
fi

echo ""
echo -e "${G}╔══════════════════════════════════════════╗${N}"
echo -e "${G}║           ✅ SETUP COMPLETE!              ║${N}"
echo -e "${G}╚══════════════════════════════════════════╝${N}"
echo ""
echo -e "${B}Server:${N}  http://localhost:6970"
echo -e "${B}API Key:${N} $(cat /tmp/chatgpt_api_key_$$ 2>/dev/null || echo 'check config.json')"
echo ""
echo -e "${Y}Client config (Cherry Studio, ChatBox, dll):${N}"
echo "  Base URL: http://localhost:6970/v1"
echo "  API Key:  $(cat /tmp/chatgpt_api_key_$$ 2>/dev/null || echo 'check config.json')"
echo ""

rm -f "$SESSION_TMP" /tmp/chatgpt_api_key_$$

echo -e "${Y}Auto-start on boot:${N}"
echo "  systemctl --user enable chatgpt-web2api"
echo ""
