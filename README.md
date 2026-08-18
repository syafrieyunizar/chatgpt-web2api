# ChatGPT Web2API

Scrape ChatGPT web (chatgpt.com) dan jadikan OpenAI-compatible API server di localhost.

## Quick Start (2 Langkah)

### Langkah 1: Install & Run Setup

```bash
git clone https://github.com/syafrieyunizar/chatgpt-web2api.git
cd chatgpt-web2api
chmod +x setup.sh
./setup.sh
```

### Langkah 2: Paste Token

Setup script akan arahkan Anda:

1. Buka browser → `https://chatgpt.com/api/auth/session`
2. Login ke ChatGPT (kalau belum)
3. Halaman menampilkan JSON dengan `WARNING_BANNER` di atas — **abaikan banner**, yang penting ada `accessToken` + `sessionToken` di dalamnya
4. **Ctrl+A** → **Ctrl+C** (copy semua isi JSON)
5. Paste ke terminal → **Ctrl+D**

### Selesai! 🎉

Server jalan di `http://localhost:6970`

```
Server:   http://localhost:6970
API Key:  sk-xxxx (auto-generated, cek config.json)
```

## Test API

```bash
curl -X POST http://localhost:6970/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Hi"}]}'
```

## Client Config (Cherry Studio, ChatBox, dll)

| Field | Value |
|---|---|
| Base URL | `http://localhost:6970/v1` |
| API Key | Cek `config.json` field `api_key` |

## Manage Accounts

Untuk **tambah akun**, **reset token**, **lihat status**, **stop server**, atau **hapus akun**:

```bash
./manage.sh
```

Menu yang tersedia:

```
╔══════════════════════════════════════════╗
║   ChatGPT Web2API - Account Manager      ║
╚══════════════════════════════════════════╝

   1) ➕ Tambah akun baru
   2) 🔄 Reset token akun existing
   3) 📊 Lihat status semua server
   4) ⛔ Stop semua server
   5) 🗑️  Hapus akun
   0) 🚪 Keluar
```

### Tambah Akun Baru
1. Run `./manage.sh` → pilih `1`
2. Script auto-assign port berikutnya (6971, 6972, ...)
3. Buka `https://chatgpt.com/api/auth/session` (login akun baru)
4. Ctrl+A → Ctrl+C → Paste → Ctrl+D
5. Server baru auto-start

### Reset Token (Token Expired)
1. Run `./manage.sh` → pilih `2`
2. Pilih akun yang mau di-reset
3. Buka `https://chatgpt.com/api/auth/session` (login akun itu)
4. Ctrl+A → Ctrl+C → Paste → Ctrl+D
5. Server restart dengan token baru

### Lihat Status
```bash
./manage.sh
# Pilih 3
```
Output:
```
CONFIG             PORT   ACCOUNT              API KEY               STATUS
------             ----   -------              -------               ------
config.json        6970   syaf.rie.yunz@gmail  sk-aBcDeFgHiJkLmNoP... 🟢 running
config-a.json      6971   user2@gmail.com      sk-xYzWvUtSrQpOnMlK... 🟢 running
config-b.json      6972   user3@gmail.com      sk-qWeRtYuIoPzXcVbN... 🔴 stopped
```

## Config Format

```json
{
  "port": 6970,
  "host": "0.0.0.0",
  "api_key": "sk-xxxx",
  "account": {
    "name": "Your Account Name",
    "access_token": "eyJhbG...",
    "refresh_token": "eyJ0eX..."
  }
}
```

| Field | Required | Description |
|---|---|---|
| `port` | ✅ | Port server (default: 6970) |
| `host` | ✅ | Bind address (default: 0.0.0.0) |
| `api_key` | ✅ | Random API key untuk autentikasi client |
| `account.name` | ✅ | Nama akun (untuk logging) |
| `account.access_token` | ✅ | Dari `chatgpt.com/api/auth/session` → `accessToken` |
| `account.refresh_token` | ⬜ | Dari `chatgpt.com/api/auth/session` → `sessionToken` |

## Cara Ambil Token Manual

1. Buka `https://chatgpt.com/api/auth/session` di browser
2. Login ke ChatGPT
3. Copy semua isi JSON
4. Extract `accessToken` dan `sessionToken`

Token expire ~3 bulan. Kalau expired, ulangi setup.

## Auto-Start on Boot (systemd)

```bash
# Copy service file
mkdir -p ~/.config/systemd/user/
cp chatgpt-web2api.service ~/.config/systemd/user/

# Edit service file untuk path yang benar
nano ~/.config/systemd/user/chatgpt-web2api.service

# Enable & start
systemctl --user daemon-reload
systemctl --user enable chatgpt-web2api
systemctl --user start chatgpt-web2api

# Check status
systemctl --user status chatgpt-web2api
```

## Supported Models

| Model | Description |
|---|---|
| `gpt-4o` | GPT-4o |
| `gpt-4o-mini` | GPT-4o Mini (default) |
| `gpt-4` | GPT-4 (legacy) |

## Troubleshooting

### Token Expired
```
ERROR: Token refresh failed
```
**Solusi:** Ulangi `./setup.sh` dan paste token baru dari `chatgpt.com/api/auth/session`

### Port Sudah Digunakan
```bash
fuser -k 6970/tcp
python3 chatgpt_web2api.py --config config.json
```

### Dependencies Missing
```bash
pip install curl_cffi pybase64 Pillow
```

## ⚠️ Security

- **Jangan commit `config.json` ke git** (sudah ada di `.gitignore`)
- `config.json` berisi token sensitive, jangan share
- API key di config = akses ke server Anda, jangan share
- Token expire ~3 bulan, rotate regularly

## License

MIT
