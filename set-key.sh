#!/usr/bin/env bash
# set-key.sh — ganti API key / token chatgpt-web2api dengan aman.
# Script ini memakai Python json (bukan sed/nano) sehingga JSON tidak pernah rusak.
#
# Cara pakai:
#   ./set-key.sh --api-key sk-BARU              # ganti API key (1 atau lebih)
#   ./set-key.sh --api-key sk-A --api-key sk-B  # set beberapa key
#   ./set-key.sh --access-token eyJ...          # ganti ChatGPT access token
#   ./set-key.sh --refresh-token eyJ...         # ganti ChatGPT refresh token
#   ./set-key.sh --show                          # tampilkan konfigurasi (tanpa token penuh)
#   ./set-key.sh --restart                       # restart service setelah ubah
#
# Contoh:
#   ./set-key.sh --api-key sk-8xKqZ3... --restart

set -euo pipefail

CONFIG="${1:-}"   # placeholder, diganti di bawah
# Tentukan lokasi config.json
if [ -f "$PWD/config.json" ]; then
    CONFIG_FILE="$PWD/config.json"
elif [ -f "$HOME/chatgpt-web2api/config.json" ]; then
    CONFIG_FILE="$HOME/chatgpt-web2api/config.json"
else
    echo "❌ config.json tidak ditemukan. Jalankan dari folder repo (cd ~/chatgpt-web2api)." >&2
    exit 1
fi

RESTART=0
NEW_KEYS=()
ACCESS_TOKEN=""
REFRESH_TOKEN=""
SHOW=0

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --api-key)
            NEW_KEYS+=("$2"); shift 2 ;;
        --access-token)
            ACCESS_TOKEN="$2"; shift 2 ;;
        --refresh-token)
            REFRESH_TOKEN="$2"; shift 2 ;;
        --restart)
            RESTART=1; shift ;;
        --show)
            SHOW=1; shift ;;
        *)
            echo "❌ Argumen tidak dikenal: $1" >&2
            echo "Pakai: $0 --api-key <key> [--access-token <t>] [--refresh-token <t>] [--restart] [--show]" >&2
            exit 1 ;;
    esac
done

if [[ $SHOW -eq 1 ]]; then
    python3 - "$CONFIG_FILE" << 'PYEOF'
import json, sys
cfg = json.load(open(sys.argv[1]))
print("config.json:")
print(f"  port          : {cfg.get('port')}")
print(f"  host          : {cfg.get('host')}")
print(f"  default_model : {cfg.get('default_model')}")
print(f"  api_keys      : {[k[:12] + '...' + k[-4:] for k in cfg.get('api_keys', [])]}")
at = cfg.get('access_token') or ''
rt = cfg.get('refresh_token') or ''
print(f"  access_token  : {'✓ set (' + str(len(at)) + ' chars)' if at else '— kosong'}")
print(f"  refresh_token : {'✓ set (' + str(len(rt)) + ' chars)' if rt else '— kosong'}")
PYEOF
    exit 0
fi

if [[ ${#NEW_KEYS[@]} -eq 0 && -z "$ACCESS_TOKEN" && -z "$REFRESH_TOKEN" ]]; then
    echo "❌ Tidak ada yang diubah. Pakai --api-key / --access-token / --refresh-token / --show" >&2
    exit 1
fi

# Backup lalu update lewat Python (jamin JSON valid)
cp "$CONFIG_FILE" "$CONFIG_FILE.bak"
python3 - "$CONFIG_FILE" "${NEW_KEYS[@]}" "$ACCESS_TOKEN" "$REFRESH_TOKEN" << 'PYEOF'
import json, sys

config_path = sys.argv[1]
args = sys.argv[2:]

# Pisahkan argumen: semua yg panjang & mulai sk- dianggap key
new_keys = []
access_token = None
refresh_token = None
for a in args:
    if a.startswith("sk-") and len(a) > 20:
        new_keys.append(a)
    elif a.startswith("eyJ"):
        # Token paling panjang = refresh, lebih pendek = access (heuristik)
        if access_token is None:
            access_token = a
        elif len(a) > len(access_token or ""):
            refresh_token = a
        else:
            refresh_token = a
            # swap: yang lebih panjang harus refresh
            access_token, refresh_token = refresh_token, access_token

cfg = json.load(open(config_path))
if new_keys:
    cfg['api_keys'] = new_keys
    print(f"✅ api_keys → {len(new_keys)} key: {[k[:12]+'...'+k[-4:] for k in new_keys]}")
if access_token:
    cfg['access_token'] = access_token
    print(f"✅ access_token → {len(access_token)} chars")
if refresh_token:
    cfg['refresh_token'] = refresh_token
    print(f"✅ refresh_token → {len(refresh_token)} chars")

json.dump(cfg, open(config_path, 'w'), indent=2)
print("💾 config.json tersimpan (valid JSON).")
PYEOF

if [[ $RESTART -eq 1 ]]; then
    echo "🔄 Restart service..."
    systemctl --user restart chatgpt-web2api
    sleep 2
    if systemctl --user is-active --quiet chatgpt-web2api; then
        echo "✅ Service aktif."
    else
        echo "❌ Service GAGAL start. Cek: journalctl --user -u chatgpt-web2api -n 20" >&2
    fi
else
    echo "ℹ️  Belum di-restart. Jalankan: systemctl --user restart chatgpt-web2api"
fi
echo "📦 Backup tersimpan di: $CONFIG_FILE.bak"
