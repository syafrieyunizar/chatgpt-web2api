#!/bin/bash
# ============================================
# ChatGPT Web2API - Account Manager
# 
# Menu:
#   1. Tambah akun baru (auto next port)
#   2. Reset config akun existing
#   3. Lihat status semua server
#   4. Stop semua server
#   5. Hapus akun
# ============================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

G='\033[0;32m'; Y='\033[1;33m'; B='\033[0;34m'; R='\033[0;31m'; C='\033[0;36m'; N='\033[0m'

# ─── Helpers ─────────────────────────────────

get_active_accounts() {
    # List all config-*.json that have real tokens (not placeholder)
    for f in config-*.json config.json; do
        [ -f "$f" ] || continue
        local has_token=$(python3 -c "
import json
try:
    d = json.load(open('$f'))
    a = d.get('account', {})
    t = a.get('access_token', '')
    print('yes' if len(t) > 100 else 'no')
except: print('no')
" 2>/dev/null)
        if [ "$has_token" = "yes" ]; then
            local port=$(python3 -c "import json; print(json.load(open('$f')).get('port','?'))" 2>/dev/null)
            local name=$(python3 -c "import json; print(json.load(open('$f')).get('account',{}).get('name','?'))" 2>/dev/null)
            local apikey=$(python3 -c "import json; print(json.load(open('$f')).get('api_key','?')[:20]+'...')" 2>/dev/null)
            local running=$(curl -s --max-time 1 "http://localhost:$port/" 2>/dev/null && echo "🟢" || echo "🔴")
            echo "$f|$port|$name|$apikey|$running"
        fi
    done
}

next_port() {
    # Find next available port starting from 6970
    for port in 6970 6971 6972 6973 6974 6975 6976 6977 6978 6979; do
        if ! curl -s --max-time 1 "http://localhost:$port/" > /dev/null 2>&1; then
            # Also check if any config uses this port
            local in_use=$(grep -l "\"port\": $port" config*.json 2>/dev/null | head -1)
            if [ -z "$in_use" ]; then
                echo "$port"
                return
            fi
        fi
    done
    echo "6970"
}

next_config_name() {
    # Find next available config-*.json
    for letter in a b c d e f g h i j; do
        [ ! -f "config-$letter.json" ] && echo "config-$letter.json" && return
    done
    echo "config-extra.json"
}

paste_and_parse() {
    local config_file="$1"
    local port="$2"
    
    echo ""
    echo -e "${C}┌──────────────────────────────────────────────┐${N}"
    echo -e "${C}│  PASTE JSON (paste, lalu tunggu 10 detik)     │${N}"
    echo -e "${C}│  ATAU: ./manage.sh /path/to/session.json      │${N}"
    echo -e "${C}└──────────────────────────────────────────────┘${N}"
    echo ""
    
    local tmp="/tmp/chatgpt_session_$$"
    
    # Read stdin with 10-second timeout (bypasses SSH 4096 byte paste limit)
    python3 -c "
import sys, os, select

chunks = []
print('   Waiting for paste...', flush=True)
while True:
    ready, _, _ = select.select([sys.stdin], [], [], 10.0)
    if ready:
        chunk = os.read(0, 65536)
        if not chunk:
            break
        chunks.append(chunk)
    else:
        break

data = b''.join(chunks).decode()
with open('$tmp', 'w') as f:
    f.write(data)
print(f'   Read {len(data)} bytes')
if len(data) < 5000:
    print('   WARNING: Data short (< 5000 bytes). Paste may be incomplete.')
"
    
    python3 << EOF
import json, sys, os, string, random
from pathlib import Path

tmp = "$tmp"
config_file = "$config_file"
port = $port
script_dir = "$SCRIPT_DIR"

with open(tmp, 'r') as f:
    raw = f.read().strip()

# Parse JSON — handle truncated paste with regex fallback
try:
    data = json.loads(raw)
except json.JSONDecodeError:
    import re
    first = raw.find('{')
    last = raw.rfind('}')
    if first != -1 and last != -1:
        candidate = raw[first:last+1]
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            # Regex fallback: extract tokens directly
            at_match = re.search(r'"accessToken"\s*:\s*"([^"]+)"', raw)
            st_match = re.search(r'"sessionToken"\s*:\s*"([^"]+)"', raw)
            name_match = re.search(r'"name"\s*:\s*"([^"]+)"', raw)
            exp_match = re.search(r'"expires"\s*:\s*"([^"]+)"', raw)
            
            if at_match:
                data = {
                    'accessToken': at_match.group(1),
                    'sessionToken': st_match.group(1) if st_match else '',
                    'user': {'name': name_match.group(1) if name_match else 'Unknown'},
                    'expires': exp_match.group(1) if exp_match else 'Unknown'
                }
            else:
                print(f"ERROR: Could not parse JSON")
                print(f"Input: {len(raw)} chars, first 300: {raw[:300]}")
                sys.exit(1)
    else:
        print("ERROR: No JSON object found")
        sys.exit(1)

if 'accessToken' not in data:
    print("ERROR: No accessToken found")
    sys.exit(1)

access_token = data['accessToken']
refresh_token = data.get('sessionToken', data.get('refreshToken', ''))
user_name = data.get('user', {}).get('name', 'Unknown')
expires = data.get('expires', 'Unknown')

# If editing existing config, keep old API key
old_apikey = ""
old_path = Path(script_dir) / config_file
if old_path.exists():
    try:
        old = json.load(open(old_path))
        old_apikey = old.get('api_key', '')
    except: pass

api_key = old_apikey if old_apikey else "sk-" + ''.join(random.choices(string.ascii_letters + string.digits, k=32))

config = {
    "port": port,
    "host": "0.0.0.0",
    "api_key": api_key,
    "account": {
        "name": user_name,
        "access_token": access_token,
        "refresh_token": refresh_token
    }
}

with open(old_path, 'w') as f:
    json.dump(config, f, indent=2)

print(f"✓ User: {user_name}")
print(f"✓ AccessToken: {len(access_token)} chars")
print(f"✓ Config saved: {config_file}")
print(f"✓ Port: {port}")
print(f"✓ API Key: {api_key}")
os.remove(tmp)
EOF

    if [ $? -ne 0 ]; then
        echo -e "${R}ERROR parsing token${N}"
        rm -f "$tmp"
        return 1
    fi
    return 0
}

start_server() {
    local config_file="$1"
    local port=$(python3 -c "import json; print(json.load(open('$config_file')).get('port',6970))" 2>/dev/null)
    
    # Kill existing process on that port
    fuser -k "$port/tcp" 2>/dev/null || true
    sleep 1
    
    # Start server
    if [ -d "$SCRIPT_DIR/.venv" ]; then
        PYTHON="$SCRIPT_DIR/.venv/bin/python3"
    else
        PYTHON="python3"
    fi
    
    nohup $PYTHON "$SCRIPT_DIR/chatgpt_web2api.py" --config "$config_file" \
        > "/tmp/chatgpt-web2api-$port.log" 2>&1 &
    local pid=$!
    sleep 2
    
    if curl -s --max-time 2 "http://localhost:$port/" > /dev/null 2>&1; then
        echo -e "${G}🟢 Server running on port $port (PID: $pid)${N}"
    else
        echo -e "${R}🔴 Server failed to start. Check: tail -20 /tmp/chatgpt-web2api-$port.log${N}"
    fi
}

# ─── Menu Actions ────────────────────────────

action_add() {
    echo -e "${B}═══ TAMBAH AKUN BARU ═══${N}"
    echo ""
    
    local port=$(next_port)
    local config_name=$(next_config_name)
    
    echo -e "Port baru: ${G}$port${N}"
    echo -e "Config file: ${G}$config_name${N}"
    echo ""
    echo -e "${Y}Buka browser: https://chatgpt.com/api/auth/session${N}"
    echo "   1. Login ke akun ChatGPT yang baru"
    echo "   2. Ctrl+A → Ctrl+C (copy semua JSON)"
    echo "   3. Paste di bawah:"
    echo ""
    
    paste_and_parse "$config_name" "$port" || return 1
    echo ""
    start_server "$config_name"
}

action_reset() {
    echo -e "${B}═══ RESET CONFIG AKUN ═══${N}"
    echo ""
    
    echo -e "${Y}Akun yang sudah terpasang:${N}"
    echo ""
    local i=1
    local files=()
    for f in config.json config-a.json config-b.json config-c.json config-d.json; do
        if [ -f "$f" ]; then
            local port=$(python3 -c "import json; print(json.load(open('$f')).get('port','?'))" 2>/dev/null)
            local name=$(python3 -c "import json; print(json.load(open('$f')).get('account',{}).get('name','?'))" 2>/dev/null)
            echo "   $i) $f → $name (port $port)"
            files+=("$f")
            ((i++))
        fi
    done
    
    if [ ${#files[@]} -eq 0 ]; then
        echo -e "${R}Tidak ada config ditemukan${N}"
        return 1
    fi
    
    echo ""
    read -p "Pilih nomor akun yang mau di-reset token: " choice
    local selected="${files[$((choice-1))]}"
    
    if [ -z "$selected" ]; then
        echo -e "${R}Pilihan tidak valid${N}"
        return 1
    fi
    
    local port=$(python3 -c "import json; print(json.load(open('$selected')).get('port',6970))" 2>/dev/null)
    
    echo ""
    echo -e "${Y}Buka browser: https://chatgpt.com/api/auth/session${N}"
    echo "   1. Login ke akun ChatGPT yang mau di-refresh"
    echo "   2. Ctrl+A → Ctrl+C (copy semua JSON)"
    echo "   3. Paste di bawah:"
    echo ""
    
    paste_and_parse "$selected" "$port" || return 1
    echo ""
    start_server "$selected"
}

action_status() {
    echo -e "${B}═══ STATUS SEMUA SERVER ═══${N}"
    echo ""
    
    printf "%-18s %-6s %-20s %-22s %s\n" "CONFIG" "PORT" "ACCOUNT" "API KEY" "STATUS"
    printf "%-18s %-6s %-20s %-22s %s\n" "------" "----" "-------" "-------" "------"
    
    for f in config.json config-a.json config-b.json config-c.json config-d.json config-e.json; do
        [ -f "$f" ] || continue
        local port=$(python3 -c "import json; print(json.load(open('$f')).get('port','?'))" 2>/dev/null)
        local name=$(python3 -c "import json; print(json.load(open('$f')).get('account',{}).get('name','?'))" 2>/dev/null)
        local apikey=$(python3 -c "import json; k=json.load(open('$f')).get('api_key','?'); print(k[:20]+'...')" 2>/dev/null)
        local running=$(curl -s --max-time 1 "http://localhost:$port/" > /dev/null 2>&1 && echo "🟢 running" || echo "🔴 stopped")
        printf "%-18s %-6s %-20s %-22s %s\n" "$f" "$port" "$name" "$apikey" "$running"
    done
    echo ""
}

action_stop() {
    echo -e "${B}═══ STOP SEMUA SERVER ═══${N}"
    echo ""
    
    for f in config.json config-a.json config-b.json config-c.json config-d.json; do
        [ -f "$f" ] || continue
        local port=$(python3 -c "import json; print(json.load(open('$f')).get('port','?'))" 2>/dev/null)
        if fuser "$port/tcp" > /dev/null 2>&1; then
            fuser -k "$port/tcp" 2>/dev/null
            echo -e "${G}✓ Stopped port $port ($f)${N}"
        fi
    done
    echo ""
    echo -e "${Y}Semua server dihentikan.${N}"
}

action_remove() {
    echo -e "${B}═══ HAPUS AKUN ═══${N}"
    echo ""
    
    local i=1
    local files=()
    for f in config.json config-a.json config-b.json config-c.json config-d.json; do
        if [ -f "$f" ]; then
            local port=$(python3 -c "import json; print(json.load(open('$f')).get('port','?'))" 2>/dev/null)
            local name=$(python3 -c "import json; print(json.load(open('$f')).get('account',{}).get('name','?'))" 2>/dev/null)
            echo "   $i) $f → $name (port $port)"
            files+=("$f")
            ((i++))
        fi
    done
    
    if [ ${#files[@]} -eq 0 ]; then
        echo -e "${R}Tidak ada config ditemukan${N}"
        return 1
    fi
    
    echo ""
    read -p "Pilih nomor akun yang mau dihapus: " choice
    local selected="${files[$((choice-1))]}"
    
    if [ -z "$selected" ]; then
        echo -e "${R}Pilihan tidak valid${N}"
        return 1
    fi
    
    # Stop server first
    local port=$(python3 -c "import json; print(json.load(open('$selected')).get('port',6970))" 2>/dev/null)
    fuser -k "$port/tcp" 2>/dev/null || true
    
    rm -f "$selected"
    echo -e "${G}✓ Dihapus: $selected${N}"
}

# ─── Main Menu ───────────────────────────────

while true; do
    echo -e "${B}╔══════════════════════════════════════════╗${N}"
    echo -e "${B}║   ChatGPT Web2API - Account Manager      ║${N}"
    echo -e "${B}╚══════════════════════════════════════════╝${N}"
    echo ""
    echo "   1) ➕ Tambah akun baru"
    echo "   2) 🔄 Reset token akun existing"
    echo "   3) 📊 Lihat status semua server"
    echo "   4) ⛔ Stop semua server"
    echo "   5) 🗑️  Hapus akun"
    echo "   0) 🚪 Keluar"
    echo ""
    read -p "Pilih menu [0-5]: " menu_choice
    
    echo ""
    case $menu_choice in
        1) action_add; echo "" ;;
        2) action_reset; echo "" ;;
        3) action_status ;;
        4) action_stop; echo "" ;;
        5) action_remove; echo "" ;;
        0) echo "Bye! 👋"; exit 0 ;;
        *) echo -e "${R}Pilihan tidak valid${N}"; echo "" ;;
    esac
done
