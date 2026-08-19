# ChatGPT Web2API

Scrape ChatGPT web (chatgpt.com) dan jadikan **OpenAI-compatible API server** di localhost.

Konsep: **1 akun ChatGPT = 1 local port**. Mau pakai banyak akun? Jalankan banyak instance, masing-masing dengan config dan port sendiri.

## Fitur

- Endpoint OpenAI-compatible: `POST /v1/chat/completions`, `GET /v1/models`
- Streaming (SSE) & non-streaming
- Bypass anti-bot: browser impersonation (`curl_cffi`), proof-of-work solver, sentinel token
- File attachment: TXT/PDF/DOCX/XLSX di-parse lokal jadi teks, gambar di-upload
- Multi-instance: 1 akun 1 port, jalan berdampingan

## Requirements

- Python 3.9+
- Akun ChatGPT (free/plus)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Cara Ambil Token

1. Login ke https://chatgpt.com di browser
2. Buka https://chatgpt.com/api/auth/session
3. Halaman menampilkan JSON (abaikan banner warning di atasnya)
4. Ambil:
   - `accessToken` → jadi `access_token` di config
   - `sessionToken` → jadi `refresh_token` di config (opsional, untuk auto-refresh)

Token berlaku terbatas (access token ~10 hari). Kalau expired, ambil ulang dan update config, lalu restart service.

## Setup Instance Pertama (port 6970)

### 1. Buat config

```bash
cp config.example.json config.json
nano config.json
```

Isi:

```json
{
  "port": 6970,
  "host": "0.0.0.0",
  "api_keys": ["sk-chatgpt"],
  "access_token": "eyJhbG...dari accessToken",
  "refresh_token": "eyJhbG...dari sessionToken",
  "default_model": "gpt-5.6-luna",
  "impersonate": "safari15_3",
  "proxy": null
}
```

> `api_keys` bebas — ini key yang dipakai client untuk mengakses server Anda.

### 2. Test jalan manual

```bash
.venv/bin/python3 chatgpt_web2api.py --config config.json --port 6970
```

Buka terminal lain:

```bash
curl http://localhost:6970/health
```

Kalau muncul `{"status":"ok",...}` berarti jalan. Stop dengan `Ctrl+C`.

### 3. Pasang systemd (auto-start)

```bash
mkdir -p ~/.config/systemd/user
nano ~/.config/systemd/user/chatgpt-web2api.service
```

Isi:

```ini
[Unit]
Description=ChatGPT Web2API (port 6970)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/ubuntu/chatgpt-web2api
ExecStart=/home/ubuntu/chatgpt-web2api/.venv/bin/python3 /home/ubuntu/chatgpt-web2api/chatgpt_web2api.py --config /home/ubuntu/chatgpt-web2api/config.json --port 6970
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

> Sesuaikan path `/home/ubuntu/chatgpt-web2api` dengan lokasi clone Anda.

Aktifkan:

```bash
systemctl --user daemon-reload
systemctl --user enable --now chatgpt-web2api
systemctl --user status chatgpt-web2api
```

## Tambah Akun Kedua (port 6971, 6972, ...)

Alur sama persis — yang beda cuma **file config**, **port**, dan **nama service**.

### 1. Buat config baru

```bash
cp config.example.json config-6971.json
nano config-6971.json
```

Ganti:

- `"port": 6971`
- `access_token` / `refresh_token` → token akun kedua (login akun itu dulu di browser, ulangi cara ambil token)
- `api_keys` → boleh sama atau beda dengan instance pertama

### 2. Buat service baru

```bash
nano ~/.config/systemd/user/chatgpt-web2api-6971.service
```

```ini
[Unit]
Description=ChatGPT Web2API (port 6971)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/ubuntu/chatgpt-web2api
ExecStart=/home/ubuntu/chatgpt-web2api/.venv/bin/python3 /home/ubuntu/chatgpt-web2api/chatgpt_web2api.py --config /home/ubuntu/chatgpt-web2api/config-6971.json --port 6971
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

### 3. Aktifkan

```bash
systemctl --user daemon-reload
systemctl --user enable --now chatgpt-web2api-6971
```

### 4. Verifikasi

```bash
ss -ltnp | grep 697
curl http://localhost:6971/health
```

Untuk akun ketiga: ulangi dengan `config-6972.json`, port 6972, service `chatgpt-web2api-6972.service`, dst.

## Pakai dari Client (Cherry Studio, ChatBox, dll)

| Field | Instance 1 | Instance 2 |
|---|---|---|
| Base URL | `http://localhost:6970/v1` | `http://localhost:6971/v1` |
| API Key | `api_keys` di `config.json` | `api_keys` di `config-6971.json` |

## Test API

```bash
curl http://localhost:6970/v1/chat/completions \
  -H "Authorization: Bearer sk-chatgpt" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5.6-luna",
    "messages": [{"role": "user", "content": "Halo"}],
    "stream": false
  }'
```

Streaming: set `"stream": true` — response berupa SSE.

File attachment (parse lokal): kirim content bertipe `file` dengan `file_data` (data URL) atau `file_url`:

```json
{
  "model": "gpt-5.6-luna",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "Ringkas file ini"},
      {"type": "file", "file": {"file_url": "https://example.com/laporan.pdf", "filename": "laporan.pdf"}}
    ]
  }]
}
```

TXT/PDF/DOCX/XLSX di-extract jadi teks dan disisipkan ke prompt. Gambar (JPG/PNG/GIF/WebP) di-upload sebagai multimodal.

## Config Reference

| Field | Default | Keterangan |
|---|---|---|
| `port` | 6970 | Port server |
| `host` | 0.0.0.0 | Bind address |
| `api_keys` | [] | Daftar API key untuk autentikasi client (kosong = tanpa auth) |
| `access_token` | — | `accessToken` dari /api/auth/session |
| `refresh_token` | — | `sessionToken` dari /api/auth/session (opsional) |
| `default_model` | gpt-5.6-luna | Model default kalau request tidak menyebut model |
| `impersonate` | safari15_3 | Browser fingerprint untuk curl_cffi |
| `proxy` | null | Proxy untuk request ke ChatGPT, mis. `socks5://127.0.0.1:40000` |
| `history_disabled` | true | Tidak simpan chat ke history akun |
| `file_mode` | parse | `parse` = extract teks lokal; `upload` = upload file ke ChatGPT |
| `log_requests` | true | Log request ke stderr/journal |
| `retry_attempts` | 3 | Retry kalau error transient (429/5xx) |
| `request_timeout_sec` | 120 | Timeout request ke ChatGPT |

## Models

`gpt-5.6-luna` (default), `gpt-5.5`, `gpt-5.6-luna-mini`, `gpt-5.5-mini`, `gpt-5.3-mini`, `gpt-5.4-t-mini`, `gpt-4o`, `gpt-4o-mini`, `gpt-4`, `gpt-3.5-turbo`, `o1`, `o1-mini`, `o1-preview`, `o3`, `o3-mini`, `o3-mini-high`, `research`, `auto`

Cek daftar live: `curl http://localhost:6970/v1/models`

## Troubleshooting

| Masalah | Solusi |
|---|---|
| `address already in use` | `fuser -k 6970/tcp` atau ganti port di config + service |
| 401 token expired | Ambil token baru dari /api/auth/session, update config, `systemctl --user restart <service>` |
| 403 unusual activity | Request terdeteksi sebagai bot; biasanya sementara. Tunggu 1–2 jam, pastikan tidak pakai proxy yang di-flag, atau ganti IP |
| Log service | `journalctl --user -u chatgpt-web2api -f` |
| Dependencies | `.venv/bin/pip install -r requirements.txt` |

## ⚠️ Security

- **Jangan commit `config*.json`** — sudah ada di `.gitignore`
- Config berisi token sensitif, jangan share
- `api_keys` = akses ke server Anda. Kalau host `0.0.0.0`, pastikan pakai API key dan/atau firewall
- Rotate token secara berkala

## License

MIT
