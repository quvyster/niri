#!/usr/bin/env python3
import json
import os
import shlex
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request


CONFIG_PATH = os.environ.get("PCBOT_CONFIG", os.path.expanduser("~/.config/pcbot/config.env"))
POWER_HELPER = os.environ.get("PCBOT_POWER_HELPER", "/usr/local/bin/pcbot-power")
MAX_OUTPUT = 3500
PENDING_SECONDS = 60


def load_env(path):
    values = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                value = value.strip().strip('"').strip("'")
                values[key.strip()] = value
    return values


CFG = load_env(CONFIG_PATH)
TOKEN = CFG.get("BOT_TOKEN", "")
ALLOWED_IDS = {int(x) for x in CFG.get("ALLOWED_USER_IDS", "").replace(" ", "").split(",") if x}
ALLOW_TERMINAL = CFG.get("ALLOW_TERMINAL", "false").lower() == "true"
TERMINAL_TIMEOUT = int(CFG.get("TERMINAL_TIMEOUT", "8"))
WAKE_TARGETS = CFG.get("WAKE_TARGETS", "")


pending = {}


def api(method, data=None, timeout=35):
    if not TOKEN:
        raise RuntimeError(f"BOT_TOKEN is empty in {CONFIG_PATH}")
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    encoded = urllib.parse.urlencode(data or {}).encode()
    req = urllib.request.Request(url, data=encoded)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(payload)
    return payload["result"]


def send(chat_id, text):
    if len(text) > 3900:
        text = text[:3900] + "\n...[cut]"
    return api("sendMessage", {"chat_id": chat_id, "text": text})


def is_allowed(user_id):
    return user_id in ALLOWED_IDS


def require_allowed(chat_id, user_id):
    if not ALLOWED_IDS:
        send(chat_id, "Бот ещё не привязан. Твой Telegram ID:\n" + str(user_id) + "\n\nДобавь его в ALLOWED_USER_IDS в ~/.config/pcbot/config.env и перезапусти сервис.")
        return False
    if not is_allowed(user_id):
        send(chat_id, "Нет доступа. Твой Telegram ID: " + str(user_id))
        return False
    return True


def run_cmd(args, timeout=12):
    proc = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    return proc.returncode, proc.stdout.strip()


def power(action):
    return run_cmd(["sudo", "-n", POWER_HELPER, action], timeout=20)


def status_text():
    parts = []
    for cmd in (
        ["hostnamectl", "--static"],
        ["uptime", "-p"],
        ["bash", "-lc", "cat /sys/class/net/enp5s0/address 2>/dev/null || true"],
        ["bash", "-lc", "ip -br addr show enp5s0 2>/dev/null || true"],
        ["bash", "-lc", "sensors 2>/dev/null | sed -n '1,40p' || true"],
        ["bash", "-lc", "nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total,pstate --format=csv,noheader 2>/dev/null || true"],
    ):
        _, out = run_cmd(cmd, timeout=5)
        if out:
            parts.append(out)
    return "\n\n".join(parts) or "status unavailable"


def magic_packet(mac):
    clean = mac.replace(":", "").replace("-", "").lower()
    if len(clean) != 12:
        raise ValueError("bad MAC")
    data = bytes.fromhex("ff" * 6 + clean * 16)
    return data


def send_wol(target_name=None):
    # Format: name=mac@host:port,name2=mac@host:port
    targets = []
    for item in WAKE_TARGETS.split(","):
        item = item.strip()
        if not item:
            continue
        name, rest = item.split("=", 1) if "=" in item else ("pc", item)
        mac, dest = rest.split("@", 1) if "@" in rest else (rest, "255.255.255.255:9")
        host, port = dest.rsplit(":", 1) if ":" in dest else (dest, "9")
        if target_name and name != target_name:
            continue
        targets.append((name, mac, host, int(port)))
    if not targets:
        return "Нет WAKE_TARGETS в конфиге или такого target."
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sent = []
    for name, mac, host, port in targets:
        packet = magic_packet(mac)
        for _ in range(5):
            sock.sendto(packet, (host, port))
            time.sleep(0.15)
        sent.append(f"{name}: {mac} -> {host}:{port}")
    return "WoL отправлен 5 раз:\n" + "\n".join(sent)


def request_confirm(chat_id, user_id, action):
    pending[user_id] = (action, time.time() + PENDING_SECONDS)
    send(chat_id, f"Подтверди команду `{action}` за {PENDING_SECONDS} секунд:\n/confirm")


def handle_command(chat_id, user_id, text):
    if text.startswith("/whoami"):
        send(chat_id, f"Твой Telegram ID: {user_id}")
        return
    if not require_allowed(chat_id, user_id):
        return

    if text.startswith("/start") or text.startswith("/help"):
        send(chat_id, (
            "Команды:\n"
            "/status - состояние ПК\n"
            "/sleep - сон, нужно /confirm\n"
            "/shutdown - выключить, нужно /confirm\n"
            "/reboot - перезагрузка, нужно /confirm\n"
            "/lock - заблокировать сессию\n"
            "/wol [name] - отправить magic packet из WAKE_TARGETS\n"
            "/term <cmd> - терминал, если ALLOW_TERMINAL=true\n"
            "/whoami - твой Telegram ID"
        ))
    elif text.startswith("/status"):
        send(chat_id, status_text())
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
        code, out = power(action)
        if out:
            send(chat_id, out)
        elif code != 0:
            send(chat_id, f"Команда завершилась с кодом {code}")
    elif text.startswith("/lock"):
        code, out = power("lock")
        send(chat_id, out or f"lock: exit {code}")
    elif text.startswith("/wol"):
        bits = shlex.split(text)
        target = bits[1] if len(bits) > 1 else None
        send(chat_id, send_wol(target))
    elif text.startswith("/term "):
        if not ALLOW_TERMINAL:
            send(chat_id, "Терминал выключен. Поставь ALLOW_TERMINAL=true в конфиге, если правда надо.")
            return
        cmd = text.split(" ", 1)[1].strip()
        if not cmd:
            send(chat_id, "Пустая команда.")
            return
        proc = subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=TERMINAL_TIMEOUT)
        out = proc.stdout[-MAX_OUTPUT:].strip()
        send(chat_id, out or f"exit {proc.returncode}")
    else:
        send(chat_id, "Не понял команду. /help")


def main():
    if not TOKEN:
        print(f"BOT_TOKEN is empty in {CONFIG_PATH}", file=sys.stderr)
        return 2
    offset = 0
    print("pcbot started", flush=True)
    while True:
        try:
            updates = api("getUpdates", {"offset": offset, "timeout": 30}, timeout=40)
            for upd in updates:
                offset = max(offset, upd["update_id"] + 1)
                msg = upd.get("message") or upd.get("edited_message")
                if not msg or "text" not in msg:
                    continue
                chat_id = msg["chat"]["id"]
                user_id = msg.get("from", {}).get("id", 0)
                handle_command(chat_id, user_id, msg["text"].strip())
        except urllib.error.HTTPError as e:
            print(f"telegram http error: {e}", file=sys.stderr, flush=True)
            time.sleep(5)
        except Exception:
            traceback.print_exc()
            time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
