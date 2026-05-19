#!/usr/bin/env python3
import json
import os
import base64
import http.server
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request


CONFIG_PATH = os.environ.get("PCBOT_VPS_CONFIG", "/etc/pcbot-vps/config.env")
PENDING_SECONDS = 60
MAX_OUTPUT = 3500


def load_env(path):
    values = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


CFG = load_env(CONFIG_PATH)
TOKEN = CFG.get("BOT_TOKEN", "")
ALLOWED_IDS = {int(x) for x in CFG.get("ALLOWED_USER_IDS", "").replace(" ", "").split(",") if x}
HOME_SSH_PORT = CFG.get("HOME_SSH_PORT", "2222")
HOME_SSH_KEY = CFG.get("HOME_SSH_KEY", "/root/.ssh/pcbot_home_ed25519")
WAKE_TARGETS = CFG.get("WAKE_TARGETS", "")
ALLOW_TERMINAL = CFG.get("ALLOW_TERMINAL", "false").lower() == "true"
ESP_WAKE_ENABLED = CFG.get("ESP_WAKE_ENABLED", "false").lower() == "true"
ESP_WAKE_SECRET = CFG.get("ESP_WAKE_SECRET", "")
ESP_WAKE_HOST = CFG.get("ESP_WAKE_HOST", "0.0.0.0")
ESP_WAKE_PORT = int(CFG.get("ESP_WAKE_PORT", "8787"))
ESP_WAKE_TTL = int(CFG.get("ESP_WAKE_TTL", "120"))
ESP_WAKE_STATE = CFG.get("ESP_WAKE_STATE", "/etc/pcbot-vps/esp_wake_state.json")
pending = {}
esp_lock = threading.Lock()


def api(method, data=None, timeout=35):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    encoded = urllib.parse.urlencode(data or {}).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=encoded), timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(payload)
    return payload["result"]


def send(chat_id, text):
    if len(text) > 3900:
        text = text[:3900] + "\n...[cut]"
    api("sendMessage", {"chat_id": chat_id, "text": text})


def run(args, timeout=12):
    try:
        proc = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return proc.returncode, proc.stdout.strip()
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def home(command, timeout=20):
    return run([
        "ssh",
        "-i", HOME_SSH_KEY,
        "-p", HOME_SSH_PORT,
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "quvy@127.0.0.1",
        command,
    ], timeout=timeout)


def home_ai(text, chat_id=None, timeout=120):
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    suffix = f" {chat_id}" if chat_id is not None else ""
    return home(f"jarvis-ssh-b64 {payload}{suffix}", timeout=timeout)


def send_home_agent(chat_id, prompt):
    if not prompt:
        send(chat_id, "Пустой запрос.")
        return
    code, out = home_ai(prompt, chat_id=chat_id, timeout=950)
    if code != 0:
        send(chat_id, "Домашний компьютер недоступен, попробуй /wake.")
        return
    send(chat_id, out or f"Niri не ответила, exit {code}")


def magic_packet(mac):
    clean = mac.replace(":", "").replace("-", "").lower()
    if len(clean) != 12:
        raise ValueError("bad MAC")
    return bytes.fromhex("ff" * 6 + clean * 16)


def wake(target_name=None):
    esp_msg = request_esp_wake(target_name or "homepc")
    targets = []
    for item in WAKE_TARGETS.split(","):
        item = item.strip()
        if not item:
            continue
        name, rest = item.split("=", 1) if "=" in item else ("homepc", item)
        mac, dests = rest.split("@", 1)
        if target_name and name != target_name:
            continue
        for dest in dests.split("|"):
            host, port = dest.rsplit(":", 1) if ":" in dest else (dest, "9")
            targets.append((name, mac, host, int(port)))
    if not targets:
        if esp_msg:
            return esp_msg
        return "Нет такого WoL target или WAKE_TARGETS пуст."

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sent = []
    for name, mac, host, port in targets:
        packet = magic_packet(mac)
        for _ in range(5):
            sock.sendto(packet, (host, port))
            time.sleep(0.15)
        sent.append(f"{name}: {mac} -> {host}:{port}")
    prefix = (esp_msg + "\n\n") if esp_msg else ""
    return prefix + "Magic packet отправлен 5 раз:\n" + "\n".join(sent)


def load_esp_state():
    try:
        with open(ESP_WAKE_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_esp_state(state):
    directory = os.path.dirname(ESP_WAKE_STATE)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = ESP_WAKE_STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, ESP_WAKE_STATE)


def request_esp_wake(target="homepc"):
    if not ESP_WAKE_ENABLED:
        return ""
    if not ESP_WAKE_SECRET:
        return "ESP32 wake включен, но ESP_WAKE_SECRET пуст."
    now = int(time.time())
    with esp_lock:
        state = load_esp_state()
        wake_id = int(state.get("wake_id") or 0) + 1
        state.update({
            "wake_id": wake_id,
            "target": target,
            "requested_at": now,
            "expires_at": now + ESP_WAKE_TTL,
            "consumed": False,
        })
        save_esp_state(state)
    return f"ESP32 wake request #{wake_id} поставлен в очередь."


def consume_esp_wake():
    now = int(time.time())
    with esp_lock:
        state = load_esp_state()
        if not state or state.get("consumed") or int(state.get("expires_at") or 0) < now:
            return None
        state["consumed"] = True
        state["consumed_at"] = now
        save_esp_state(state)
        return state


class EspWakeHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/health":
            self.reply(200, "ok\n")
            return
        if parsed.path != "/esp32/wake":
            self.reply(404, "not found\n")
            return
        params = urllib.parse.parse_qs(parsed.query)
        secret = (params.get("secret") or [""])[0]
        if not ESP_WAKE_SECRET or secret != ESP_WAKE_SECRET:
            self.reply(403, "forbidden\n")
            return
        state = consume_esp_wake()
        if not state:
            self.reply(200, "IDLE\n")
            return
        self.reply(200, f"WAKE {state.get('wake_id')} {state.get('target', 'homepc')}\n")

    def log_message(self, fmt, *args):
        print("esp32-wake %s - request" % self.client_address[0], flush=True)

    def reply(self, code, body):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_esp_wake_server():
    if not ESP_WAKE_ENABLED:
        return
    if not ESP_WAKE_SECRET:
        print("ESP_WAKE_ENABLED=true, but ESP_WAKE_SECRET is empty", file=sys.stderr, flush=True)
        return
    server = http.server.ThreadingHTTPServer((ESP_WAKE_HOST, ESP_WAKE_PORT), EspWakeHandler)
    thread = threading.Thread(target=server.serve_forever, name="esp32-wake-http", daemon=True)
    thread.start()
    print(f"esp32 wake server listening on {ESP_WAKE_HOST}:{ESP_WAKE_PORT}", flush=True)


def allowed(chat_id, user_id):
    if user_id in ALLOWED_IDS:
        return True
    send(chat_id, f"Нет доступа. Твой Telegram ID: {user_id}")
    return False


def request_confirm(chat_id, user_id, action):
    pending[user_id] = (action, time.time() + PENDING_SECONDS)
    send(chat_id, f"Подтверди `{action}` за {PENDING_SECONDS} секунд:\n/confirm")


def handle(chat_id, user_id, text):
    if text.startswith("/whoami"):
        send(chat_id, f"Твой Telegram ID: {user_id}")
        return
    if not allowed(chat_id, user_id):
        return

    if text.startswith("/start") or text.startswith("/help"):
        send(chat_id, (
            "VPS PC bot:\n"
            "/wake - отправить magic packet\n"
            "/status - статус домашнего ПК через reverse SSH\n"
            "/sleep, /shutdown, /reboot + /confirm\n"
            "/lock - заблокировать сессию\n"
            "любой обычный текст - локальный агент на домашнем ПК\n"
            "/ai текст или /jarvis текст - совместимые алиасы Niri\n"
            "/ai_status - статус Niri\n"
            "/ai_confirm код - подтвердить опасное действие Niri\n"
            "/ping - проверить туннель\n"
            "/vps - статус VPS\n"
            "/whoami - Telegram ID"
        ))
    elif text.startswith("/wake") or text.startswith("/wol"):
        parts = text.split()
        send(chat_id, wake(parts[1] if len(parts) > 1 else None))
    elif text.startswith("/ping"):
        code, out = home("ping", timeout=8)
        send(chat_id, out or f"home unavailable, exit {code}")
    elif text.startswith("/status"):
        code, out = home("status", timeout=12)
        send(chat_id, out or f"home unavailable, exit {code}")
    elif text.startswith("/ai_status"):
        code, out = home("jarvis-status", timeout=30)
        send(chat_id, out if code == 0 and out else "Домашний компьютер недоступен, попробуй /wake.")
    elif text.startswith("/ai_confirm"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send(chat_id, "Нужен код подтверждения: /ai_confirm <код>")
            return
        code, out = home(f"jarvis-confirm {parts[1].strip()}", timeout=950)
        send(chat_id, out if code == 0 and out else "Домашний компьютер недоступен, попробуй /wake.")
    elif text.startswith("/ai ") or text.startswith("/jarvis "):
        prompt = text.split(maxsplit=1)[1].strip()
        send_home_agent(chat_id, prompt)
    elif text.startswith("/lock"):
        code, out = home("lock", timeout=12)
        send(chat_id, out or f"lock exit {code}")
    elif text.startswith("/sleep"):
        request_confirm(chat_id, user_id, "suspend")
    elif text.startswith("/shutdown") or text.startswith("/poweroff"):
        request_confirm(chat_id, user_id, "poweroff")
    elif text.startswith("/reboot"):
        request_confirm(chat_id, user_id, "reboot")
    elif text.startswith("/confirm"):
        item = pending.pop(user_id, None)
        if not item or time.time() > item[1]:
            send(chat_id, "Нет свежей команды для подтверждения.")
            return
        action = item[0]
        send(chat_id, f"Выполняю: {action}")
        code, out = home(action, timeout=15)
        if out:
            send(chat_id, out)
        elif code != 0:
            send(chat_id, f"exit {code}")
    elif text.startswith("/vps"):
        _, out = run(["bash", "-lc", "hostname; uptime -p; ip -br addr show wg0 ens3"], timeout=5)
        send(chat_id, out)
    elif text.startswith("/term "):
        if not ALLOW_TERMINAL:
            send(chat_id, "Терминал выключен ради безопасности.")
        else:
            send(chat_id, "Терминал на VPS не реализован в этой сборке.")
    elif text.startswith("/"):
        send(chat_id, "Не понял команду. Обычный текст без / отправлю локальному агенту. /help")
    else:
        send_home_agent(chat_id, text)


def main():
    if not TOKEN:
        print(f"BOT_TOKEN empty in {CONFIG_PATH}", file=sys.stderr)
        return 2
    offset = 0
    start_esp_wake_server()
    print("pcbot-vps started", flush=True)
    while True:
        try:
            updates = api("getUpdates", {"offset": offset, "timeout": 30}, timeout=40)
            for upd in updates:
                offset = max(offset, upd["update_id"] + 1)
                msg = upd.get("message") or upd.get("edited_message")
                if not msg or "text" not in msg:
                    continue
                handle(msg["chat"]["id"], msg.get("from", {}).get("id", 0), msg["text"].strip())
        except Exception:
            traceback.print_exc()
            time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
