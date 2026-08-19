#!/usr/bin/env python3
"""Test: does the server remember conversation context between requests?"""
import json, urllib.request, urllib.error

cfg = json.load(open("/home/ubuntu/chatgpt-web2api/config.json"))
api_key = cfg.get("api_keys", [""])[0] if cfg.get("api_keys") else None

def ask(messages, label):
    payload = {"model": "gpt-5.6-luna", "stream": False, "messages": messages}
    req = urllib.request.Request("http://localhost:6970/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=180)
        data = json.loads(resp.read().decode())
        print(f"[{label}] {data['choices'][0]['message']['content'][:200]}")
    except urllib.error.HTTPError as e:
        print(f"[{label}] HTTP {e.code}: {e.read().decode()[:200]}")

# Request 1: tell it a secret name
ask([{"role": "user", "content": "Ingat ya: nama pasien saya adalah BUDI SANTOSO. Jangan lupa."}], "1-seed")

# Request 2: separate call, ask what the name was (no history passed)
ask([{"role": "user", "content": "Siapa nama pasien yang saya sebut tadi?"}], "2-forget")

# Request 3: WITH full history passed (client-side state)
ask([
    {"role": "user", "content": "Ingat ya: nama pasien saya adalah BUDI SANTOSO. Jangan lupa."},
    {"role": "assistant", "content": "Baik, saya ingat nama pasien Anda adalah Budi Santoso."},
    {"role": "user", "content": "Siapa nama pasien yang saya sebut tadi?"},
], "3-with-history")
