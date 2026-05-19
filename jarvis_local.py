#!/usr/bin/env python3
import base64
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo


HOST = os.environ.get("JARVIS_HOST", "127.0.0.1")
PORT = int(os.environ.get("JARVIS_PORT", "8765"))
MODEL = os.environ.get("JARVIS_MODEL", "qwen3:4b")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
GOOSE_BIN = os.environ.get("JARVIS_GOOSE_BIN", "/home/quvy/.local/bin/goose")
GOOSE_PROVIDER = os.environ.get("JARVIS_GOOSE_PROVIDER", "ollama")
PRIMARY_PROVIDER = os.environ.get("JARVIS_PRIMARY_PROVIDER", "").strip()
PRIMARY_MODEL = os.environ.get("JARVIS_PRIMARY_MODEL", "").strip()
PRIMARY_HOST = os.environ.get("JARVIS_PRIMARY_HOST", "").strip()
PRIMARY_API_KEY = os.environ.get("JARVIS_PRIMARY_API_KEY", "").strip()
GOOSE_MODE = os.environ.get("JARVIS_GOOSE_MODE", "auto")
GOOSE_MAX_TURNS = os.environ.get("JARVIS_GOOSE_MAX_TURNS", "18")
AGENT_CWD = os.environ.get("JARVIS_AGENT_CWD", "/home/quvy")
AGENT_TIMEOUT = int(os.environ.get("JARVIS_AGENT_TIMEOUT", "900"))
AGENT_MAX_OUTPUT = int(os.environ.get("JARVIS_AGENT_MAX_OUTPUT", "12000"))
MAX_REPLY = int(os.environ.get("JARVIS_MAX_REPLY", "3500"))
CONFIRM_SECONDS = int(os.environ.get("JARVIS_CONFIRM_SECONDS", "120"))
HISTORY_DIR = os.environ.get("JARVIS_HISTORY_DIR", "/home/quvy/.local/share/jarvis/history")
HISTORY_TURNS = int(os.environ.get("JARVIS_HISTORY_TURNS", "10"))
HISTORY_ENABLED = os.environ.get("JARVIS_HISTORY_ENABLED", "true").lower() == "true"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_SCHEDULE_PATH = os.path.join(PROJECT_DIR, "niri_schedule.local.json")
DEFAULT_SCHEDULE_PATH = os.path.join(PROJECT_DIR, "niri_schedule.json")
SCHEDULE_PATH = os.environ.get(
    "NIRI_SCHEDULE_PATH",
    LOCAL_SCHEDULE_PATH if os.path.exists(LOCAL_SCHEDULE_PATH) else DEFAULT_SCHEDULE_PATH,
)
SCHEDULE_WINDOW = os.environ.get("NIRI_SCHEDULE_WINDOW", os.path.join(PROJECT_DIR, "niri_schedule_window.py"))

pending = {}


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

DANGEROUS_PATTERNS = [
    (r"\b(sudo|su|doas|pkexec)\b", "root/sudo действие"),
    (r"\b(rm|rmdir|shred|wipe)\b|удал(и|ить|ение)", "удаление файлов"),
    (r"\b(dd|mkfs|fdisk|sfdisk|cfdisk|parted|sgdisk|wipefs|cryptsetup|mount|umount|swapon|swapoff)\b", "диски или mount"),
    (r"\b(chmod|chown|chgrp|chattr|setfacl)\b", "права или владельцы файлов"),
    (r"\b(systemctl|loginctl|crontab|systemd-run)\b", "системные сервисы"),
    (r"\b(pacman|yay|paru|npm\s+install\s+-g)\b|поставь|установи", "установка пакетов"),
    (r"\b(reboot|poweroff|shutdown|halt|suspend)\b|перезаг|выключ|усып|сон\b", "питание компьютера"),
    (r"\b(kill|pkill|killall)\b|закрой|заверши процесс", "завершение процессов"),
]

SAFE_APP_ACTION_RE = re.compile(
    r"^\s*(запусти|запустить|открой|открыть|start|open|launch)\b",
    flags=re.IGNORECASE,
)

GUARDED_COMMANDS = [
    "sudo", "su", "doas", "pkexec",
    "rm", "rmdir", "shred", "wipe",
    "dd", "mkfs", "mkfs.ext4", "mkfs.fat", "fdisk", "sfdisk", "cfdisk", "parted", "sgdisk", "wipefs", "cryptsetup",
    "mount", "umount", "swapon", "swapoff",
    "chmod", "chown", "chgrp", "chattr", "setfacl",
    "systemctl", "loginctl", "reboot", "poweroff", "shutdown", "halt",
    "pacman", "yay", "paru",
    "kill", "pkill", "killall",
]

GUI_COMMAND_WRAPPERS = {
    "steam": "Steam",
    "code": "Visual Studio Code",
    "telegram-desktop": "Telegram Desktop",
    "Telegram": "Telegram Desktop",
    "google-chrome": "Google Chrome",
    "google-chrome-stable": "Google Chrome",
    "discord": "Discord",
    "vlc": "VLC media player",
    "gedit": "Text Editor",
    "gnome-text-editor": "Text Editor",
    "kgx": "Terminal",
    "gnome-terminal": "Terminal",
    "nautilus": "Files",
    "gnome-control-center": "Settings",
    "gnome-system-monitor": "System Monitor",
    "gnome-calculator": "Calculator",
    "qalculate-gtk": "Calculator",
    "kcalc": "Calculator",
    "qbittorrent": "qBittorrent",
    "karing": "Karing",
    "prismlauncher": "Prism Launcher",
    "celluloid": "Celluloid",
    "mpv": "mpv Media Player",
    "nvidia-settings": "NVIDIA X Server Settings",
    "gsr-ui": "GPU Screen Recorder",
    "qbittorrent": "qBittorrent",
    "prismlauncher": "Prism Launcher",
}

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAY_NAMES = {
    "monday": "понедельник",
    "tuesday": "вторник",
    "wednesday": "среду",
    "thursday": "четверг",
    "friday": "пятницу",
    "saturday": "субботу",
    "sunday": "воскресенье",
}
DAY_WORDS = {
    "понедельник": "monday", "понедельника": "monday", "пн": "monday",
    "вторник": "tuesday", "вторника": "tuesday", "вт": "tuesday",
    "среда": "wednesday", "среду": "wednesday", "среды": "wednesday", "ср": "wednesday",
    "четверг": "thursday", "четверга": "thursday", "чт": "thursday",
    "пятница": "friday", "пятницу": "friday", "пятницы": "friday", "пт": "friday",
    "суббота": "saturday", "субботу": "saturday", "субботы": "saturday", "сб": "saturday",
    "воскресенье": "sunday", "воскресенья": "sunday", "вс": "sunday",
}


def trim_text(text, limit=MAX_REPLY):
    text = (text or "").strip()
    if len(text) > limit:
        return text[-limit:] + "\n...[tail]"
    return text


def strip_ansi(text):
    text = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", text or "")
    text = re.sub(r"\x1b\][^\a]*(?:\a|\x1b\\)", "", text)
    return text


def clean_goose_output(text):
    text = strip_ansi(text)
    loose = loose_goose_text_answer(text)
    if loose:
        return trim_text(loose, MAX_REPLY)
    if text.lstrip().startswith("{") and '"messages"' in text:
        return "Не смог разобрать JSON-ответ агента. Попробуй повторить запрос."
    lines = text.splitlines()
    cleaned = []
    skipping_banner = True
    saw_banner = False
    for line in lines:
        if skipping_banner:
            if "goose is ready" in line:
                skipping_banner = False
                saw_banner = True
            continue
        cleaned.append(line.rstrip())
    if not cleaned:
        if saw_banner:
            return ""
        cleaned = [line.rstrip() for line in lines]
    return trim_text("\n".join(cleaned).strip(), MAX_REPLY)


def goose_text_from_data(data):
    messages = data.get("messages") if isinstance(data, dict) else None
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        parts = []
        for item in message.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        answer = "".join(parts).strip()
        if answer:
            return trim_text(answer, MAX_REPLY)
    return ""


def loose_goose_text_answer(raw):
    matches = list(re.finditer(r'"type"\s*:\s*"text"\s*,\s*"text"\s*:\s*"((?:\\.|[^"\\])*)"', raw or "", flags=re.S))
    for match in reversed(matches):
        try:
            text = json.loads(f'"{match.group(1)}"').strip()
        except json.JSONDecodeError:
            text = match.group(1).strip()
        if text:
            return trim_text(text, MAX_REPLY)
    return ""


def goose_json_answer(raw):
    raw = (raw or "").strip()
    decoder = json.JSONDecoder()
    best = ""
    index = 0
    while True:
        start = raw.find("{", index)
        if start == -1:
            break
        try:
            data, end = decoder.raw_decode(raw[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        answer = goose_text_from_data(data)
        if answer:
            best = answer
        index = start + max(end, 1)
    if best:
        return best

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        raw = raw[start:end + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return loose_goose_text_answer(raw)
    return goose_text_from_data(data) or loose_goose_text_answer(raw)


def run(args, timeout=12, env=None):
    try:
        proc = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, env=env)
        return proc.returncode, proc.stdout.strip()
    except FileNotFoundError:
        return 127, f"Команда не найдена: {args[0]}"
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def graphical_env():
    env = os.environ.copy()
    env.setdefault("HOME", "/home/quvy")
    env.setdefault("XDG_RUNTIME_DIR", "/run/user/1000")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    env.setdefault("DISPLAY", ":0")
    env.setdefault("WAYLAND_DISPLAY", "wayland-0")
    if not env.get("XAUTHORITY"):
        runtime = env.get("XDG_RUNTIME_DIR", "/run/user/1000")
        try:
            candidates = [
                os.path.join(runtime, name)
                for name in os.listdir(runtime)
                if name.startswith(".mutter-Xwaylandauth.")
            ]
            if candidates:
                env["XAUTHORITY"] = max(candidates, key=os.path.getmtime)
        except OSError:
            pass
    return env


def launch_gui(args, unit_prefix="niri-gui"):
    env = graphical_env()
    systemd_run = "/usr/bin/systemd-run"
    if os.path.exists(systemd_run):
        unit = f"{unit_prefix}-{int(time.time())}-{secrets.token_hex(2)}"
        cmd = [
            systemd_run, "--user", "--collect", "--no-block", "--quiet",
            "--unit", unit, "--description", unit,
            "--working-directory", PROJECT_DIR,
        ]
        for key in ("HOME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "LANG"):
            value = env.get(key)
            if value:
                cmd.extend(["--setenv", f"{key}={value}"])
        cmd.extend(args)
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8, check=False)
        if proc.returncode == 0:
            return True
    subprocess.Popen(args, cwd=PROJECT_DIR, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return True


def load_schedule():
    try:
        with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"timezone": "Asia/Omsk", "bells": [], "days": {}}


def schedule_intent(text):
    low = (text or "").lower()
    day = "today"
    if re.search(r"\b(завтра|завтраш)\b", low):
        day = "tomorrow"
    elif re.search(r"\b(вчера|вчераш)\b", low):
        day = "yesterday"
    else:
        for word, value in DAY_WORDS.items():
            if re.search(rf"\b{re.escape(word)}\b", low):
                day = value
                break
    if re.search(r"(звонк|перемен|по урокам)", low):
        return {"mode": "bells", "day": day}
    if not re.search(r"(расписан|урок|предмет|пары|занят)", low):
        return None
    return {"mode": "day", "day": day}


def resolve_schedule_day(day, schedule):
    if day in DAYS:
        return day, DAY_NAMES[day]
    tz = ZoneInfo(schedule.get("timezone", "Asia/Omsk"))
    today = datetime.now(tz).date()
    if day == "tomorrow":
        date = today + timedelta(days=1)
    elif day == "yesterday":
        date = today - timedelta(days=1)
    else:
        date = today
    key = DAYS[date.weekday()]
    return key, f"{DAY_NAMES[key]} {date.strftime('%d.%m')}"


def is_telegram_session(session_id):
    value = str(session_id or "").strip()
    return bool(re.fullmatch(r"-?\d+", value))


def telegram_lesson_text(day_label, lessons):
    if not lessons:
        return f"Расписание на {day_label}:\nУроков нет."
    lines = [f"Расписание на {day_label}:"]
    for lesson in lessons:
        parts = [
            f"{lesson.get('number')}.",
            lesson.get("subject", "").strip(),
            lesson.get("time", "").strip(),
        ]
        tail = []
        if lesson.get("room"):
            tail.append(f"каб. {lesson.get('room')}")
        if lesson.get("teacher"):
            tail.append(str(lesson.get("teacher")))
        line = " ".join(part for part in parts if part)
        if tail:
            line += " (" + ", ".join(tail) + ")"
        lines.append(line)
    return "\n".join(lines)


def telegram_bells_text(day_label, bells):
    if not bells:
        return f"Звонки на {day_label}:\nЗвонков нет."
    lines = [f"Звонки на {day_label}:"]
    for item in bells:
        lines.append(f"{item.get('number')} урок: {item.get('time')}")
    return "\n".join(lines)


def day_bells(schedule, day_key):
    return (schedule.get("bells_by_day") or {}).get(day_key, schedule.get("bells", []))


def schedule_summary(intent, voice=False, telegram=False):
    schedule = load_schedule()
    if intent["mode"] == "bells":
        day_key, day_label = resolve_schedule_day(intent.get("day", "today"), schedule)
        bells = day_bells(schedule, day_key)
        if telegram:
            return telegram_bells_text(day_label, bells)
        if launch_gui([sys.executable, SCHEDULE_WINDOW, "--mode", "bells", "--day", intent.get("day", "today")], unit_prefix="niri-schedule"):
            return f"Открыла расписание звонков на {day_label}." if voice else f"Открыла расписание звонков на {day_label} в отдельном окне."
        return "Не смогла открыть окно расписания звонков."
    day_key, day_label = resolve_schedule_day(intent.get("day", "today"), schedule)
    lessons = schedule.get("days", {}).get(day_key, [])
    if telegram:
        return telegram_lesson_text(day_label, lessons)
    launch_gui([sys.executable, SCHEDULE_WINDOW, "--mode", "day", "--day", intent.get("day", "today")], unit_prefix="niri-schedule")
    if not lessons:
        return f"Открыла расписание: {day_label}. Уроков нет." if not voice else f"Открыла расписание. На {day_label} уроков нет."
    subjects = []
    seen = set()
    for lesson in lessons:
        subject = lesson.get("subject", "").strip()
        if subject and subject not in seen:
            seen.add(subject)
            subjects.append(subject)
    if voice:
        return f"Открыла расписание на {day_label}."
    return f"Открыла расписание на {day_label}. Предметы: " + ", ".join(subjects) + "."


def session_key(value):
    value = str(value or "cli").strip() or "cli"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:80]


def history_path(session_id):
    return os.path.join(HISTORY_DIR, session_key(session_id) + ".json")


def load_history(session_id):
    if not HISTORY_ENABLED:
        return []
    try:
        with open(history_path(session_id), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("role") in {"user", "assistant"}][-HISTORY_TURNS * 2:]


def save_history(session_id, history):
    if not HISTORY_ENABLED:
        return
    try:
        os.makedirs(HISTORY_DIR, exist_ok=True)
        with open(history_path(session_id), "w", encoding="utf-8") as f:
            json.dump(history[-HISTORY_TURNS * 2:], f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def append_history(session_id, user_text, assistant_text):
    history = load_history(session_id)
    history.append({"role": "user", "text": trim_text(user_text, 2000), "ts": int(time.time())})
    history.append({"role": "assistant", "text": trim_text(assistant_text, 2000), "ts": int(time.time())})
    save_history(session_id, history)


def format_history(history):
    if not history:
        return "Истории пока нет."
    lines = []
    for item in history[-HISTORY_TURNS * 2:]:
        label = "Пользователь" if item.get("role") == "user" else "Джарвис"
        lines.append(f"{label}: {item.get('text', '').strip()}")
    return "\n".join(lines)


def danger_reason(text):
    if SAFE_APP_ACTION_RE.search(text):
        return None
    low = text.lower()
    for pattern, reason in DANGEROUS_PATTERNS:
        if re.search(pattern, low, flags=re.IGNORECASE):
            return reason
    return None


def make_confirmation(text, reason, session_id="cli", voice=False):
    token = secrets.token_hex(3)
    pending[token] = ({"type": "goose", "text": text, "session_id": session_id, "voice": voice}, time.time() + CONFIRM_SECONDS)
    if voice:
        answer = f"Нужно подтверждение: {reason}. Если уверен, скажи да."
    else:
        answer = (
        f"Нужно подтверждение: {reason}.\n"
        f"Локально: jarvis --confirm {token}\n"
        f"В Telegram: /ai_confirm {token}\n"
        f"Код действует {CONFIRM_SECONDS} секунд."
        )
    return {"token": token, "answer": answer, "expires_in": CONFIRM_SECONDS}


def request_confirmation(text, reason, session_id="cli", voice=False):
    return make_confirmation(text, reason, session_id=session_id, voice=voice)["answer"]


def make_guard_bin():
    guard_dir = tempfile.TemporaryDirectory(prefix="jarvis-goose-guard-")
    script = """#!/usr/bin/env bash
name="$(basename "$0")"
quoted=""
for arg in "$@"; do
  printf -v q "%q" "$arg"
  quoted="$quoted $q"
done
echo "JARVIS_CONFIRM_REQUIRED:${name}${quoted}" >&2
echo "Команда '${name}' остановлена до подтверждения через /ai_confirm." >&2
exit 126
"""
    for name in GUARDED_COMMANDS:
        path = os.path.join(guard_dir.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(script)
        os.chmod(path, 0o755)
    for name, app_name in GUI_COMMAND_WRAPPERS.items():
        path = os.path.join(guard_dir.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"#!/usr/bin/env bash\nexec /usr/local/bin/niri-open-app {shlex.quote(app_name)}\n")
        os.chmod(path, 0o755)
    return guard_dir


def goose_prompt(text, session_id="cli", voice=False):
    history = format_history(load_history(session_id))
    answer_style = (
        "Голосовой режим: отвечай максимально коротко, одной-двумя фразами. "
        "Не используй markdown, символы **, длинные списки, таблицы, кодовые блоки и подробные отчеты. "
        "Если действие выполнено, скажи коротко: что сделал или что не получилось."
        if voice else
        "Текстовый режим: отвечай кратко и естественно. Не используй markdown-выделение ** и заголовки без необходимости."
    )
    return f"""Ты Нири, локальная помощница и агент на домашнем Linux ПК пользователя quvy. С тобой пользователь взаимодействует через Telegram, голос, CLI и GNOME-мини-окно.

Работай через свои инструменты, особенно shell/developer tool. Не проси пользователя выполнить команды вручную, если можешь выполнить сам.
Говори по-русски, кратко и честно. Отвечай только финальным пользовательским ответом, без скрытых рассуждений, истории tool-вызовов и служебных логов.
Не используй markdown-выделение `**`, markdown-заголовки и декоративное форматирование. Обычный текст лучше.

Правила:
- Если вопрос бытовой/общий и не требует доступа к компьютеру, файлам, интернету или процессам, ответь напрямую без shell.
- Рецепты, объяснения, советы и обычный чат не требуют инструментов.
- Для диагностики, файлов, процессов, пакетов, приложений и обычной работы на компьютере используй shell.
- У тебя широкие права на user-level действия: можешь читать, создавать и редактировать файлы в домашней директории, рабочих проектах и /tmp; можешь запускать приложения, проверять процессы, смотреть логи пользователя, открывать окна и управлять обычными программами.
- Характеристики компьютера проверяй командами вроде `hostnamectl`, `lscpu`, `free -h`, `df -h / /home`, `sensors`, `nvidia-smi`. Не выдумывай характеристики из истории, если пользователь просит актуальное состояние.
- Если нужно открыть GUI-приложение, всегда используй команду `niri-open-app "название приложения"` или совместимый `jarvis-open-app`. Не запускай GUI-приложения напрямую командами `steam`, `code`, `telegram-desktop` и т.п.
- Для точных вычислений используй `niri-calc "выражение"` или Python. Не считай сложную арифметику "из головы".
- Алиасы приложений: "сабнатика", "сабнатику", "subnautica" = Subnautica 2; "кс", "контра", "cs2" = Counter-Strike 2; "стим" = Steam; "майнкрафт" = Prism Launcher; "калькулятор", "кальк" = Calculator; "текстовый редактор" = Text Editor; "хром" = Google Chrome; "телеграм" = Telegram Desktop; "дискорд" = Discord; "файлы" = Files; "код" = Visual Studio Code.
- Если пользователь просит расписание уроков, предметы на сегодня/завтра/вчера/день недели или расписание звонков, локальный API обычно откроет отдельное окно сам. Если запрос дошел до тебя, используй `niri-schedule --day today|tomorrow|yesterday|monday...` или `niri-schedule --bells`.
- Если нужно закрыть приложение, сначала найди реальный процесс через pgrep/ps, потом завершай только подходящий процесс.
- Опасные действия требуют подтверждения: sudo/root, установка пакетов, удаление, chmod/chown, systemd, диски/mount, reboot/shutdown/suspend, kill/pkill/killall.
- Если инструмент вернул JARVIS_CONFIRM_REQUIRED, сразу остановись и скажи, что нужно подтверждение. Не пытайся обходить guard.
- Не выдумывай успех. Если команда не сработала, покажи причину.
- Если пользователь просит короткий ответ или одно слово, не добавляй "Итог", списки затронутых файлов и лишние пояснения.
- Если задача выполняла команды или меняла систему, кратко скажи только полезный результат и важные изменения.

Стиль ответа:
{answer_style}

Краткая история этого чата:
{history}

Запрос пользователя:
{text}
"""


def provider_label(provider, model):
    return f"{provider}/{model}"


def local_provider_config():
    return {
        "provider": GOOSE_PROVIDER,
        "model": MODEL,
        "host": OLLAMA_URL if GOOSE_PROVIDER == "ollama" else "",
        "api_key": "",
        "name": "local",
    }


def primary_provider_config():
    if not PRIMARY_PROVIDER or not PRIMARY_MODEL or not PRIMARY_API_KEY:
        return None
    return {
        "provider": PRIMARY_PROVIDER,
        "model": PRIMARY_MODEL,
        "host": PRIMARY_HOST,
        "api_key": PRIMARY_API_KEY,
        "name": "primary",
    }


def goose_env(guard_dir=None, provider_config=None):
    provider_config = provider_config or local_provider_config()
    path = "/home/quvy/.local/bin:/usr/local/bin:/usr/bin:/bin"
    if guard_dir:
        path = guard_dir.name + os.pathsep + path
    env = os.environ.copy()
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000")
    xauthority = os.environ.get("XAUTHORITY", "")
    if not xauthority:
        try:
            candidates = [
                os.path.join(xdg_runtime, name)
                for name in os.listdir(xdg_runtime)
                if name.startswith(".mutter-Xwaylandauth.")
            ]
            if candidates:
                xauthority = max(candidates, key=os.path.getmtime)
        except OSError:
            pass
    env.update({
        "HOME": "/home/quvy",
        "PATH": path,
        "LANG": os.environ.get("LANG", "ru_RU.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", ""),
        "TERM": "dumb",
        "NO_COLOR": "1",
        "OLLAMA_HOST": OLLAMA_URL,
        "GOOSE_PROVIDER": provider_config["provider"],
        "GOOSE_MODEL": provider_config["model"],
        "GOOSE_MODE": GOOSE_MODE,
        "GOOSE_MAX_TURNS": GOOSE_MAX_TURNS,
        "GOOSE_DISABLE_SESSION_NAMING": "true",
        "GOOSE_CLI_SHOW_COST": "false",
        "XDG_RUNTIME_DIR": xdg_runtime,
        "DBUS_SESSION_BUS_ADDRESS": os.environ.get("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus"),
        "DISPLAY": os.environ.get("DISPLAY", ":0"),
        "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY", "wayland-0"),
    })
    if provider_config.get("host"):
        env["GOOSE_PROVIDER__HOST"] = provider_config["host"]
    if provider_config.get("api_key"):
        env["GOOSE_PROVIDER__API_KEY"] = provider_config["api_key"]
        provider_key_name = re.sub(r"[^A-Z0-9]+", "_", provider_config["provider"].upper()).strip("_")
        if provider_key_name:
            env[f"{provider_key_name}_API_KEY"] = provider_config["api_key"]
    if xauthority:
        env["XAUTHORITY"] = xauthority
    return env


def provider_failure(text, exit_code):
    low = (text or "").lower()
    if exit_code in {124, 125, 126, 127}:
        return True
    markers = (
        "authentication error",
        "401 unauthorized",
        "missing authentication",
        "configuration value not found",
        "api_key",
        "keychain",
        "keyring",
        "rate limit",
        "429",
        "quota",
        "provider error",
        "request failed",
        "resource not found",
        "no endpoints found",
        "not a valid model",
        "connection error",
        "timed out",
        "timeout",
        "temporarily unavailable",
        "service unavailable",
        "запрос пользователя:",
        "ты джарвис, локальный агент",
        "краткая история этого чата:",
    )
    return any(marker in low for marker in markers)


def run_goose_once(text, session_id, confirmed, provider_config, voice=False):
    goose_path = shutil.which(GOOSE_BIN) or (GOOSE_BIN if os.path.exists(GOOSE_BIN) else "")
    if not goose_path:
        return {
            "ok": False,
            "events": ["Goose не найден."],
            "answer": "Goose не найден. Ожидал бинарник /home/quvy/.local/bin/goose.",
            "exit_code": 127,
        }

    events = [f"Запускаю Goose: {provider_label(provider_config['provider'], provider_config['model'])}."]
    guard_dir = None
    if confirmed:
        events.append("Подтверждение получено, guard для опасных команд выключен.")
    else:
        guard_dir = make_guard_bin()
        events.append("Guard включен: опасные команды остановятся до /ai_confirm.")

    cmd = [
        goose_path,
        "run",
        "--no-session",
        "--no-profile",
        "--with-builtin",
        "developer",
        "--max-turns",
        str(GOOSE_MAX_TURNS),
        "--output-format",
        "json",
        "-t",
        goose_prompt(text, session_id=session_id, voice=voice),
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=AGENT_CWD,
            env=goose_env(guard_dir, provider_config),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        out, _ = proc.communicate(timeout=AGENT_TIMEOUT)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            pass
        out = f"Goose timeout after {AGENT_TIMEOUT} seconds."
        code = 124
    except Exception as exc:
        out = f"Не смог запустить Goose: {exc}"
        code = 1
    finally:
        if guard_dir:
            guard_dir.cleanup()

    raw_out = strip_ansi(out)
    if "JARVIS_CONFIRM_REQUIRED:" in raw_out and not confirmed:
        events.append("Goose дошел до опасной команды и остановлен guard.")
        confirmation = make_confirmation(text, "действие агента требует подтверждения", session_id=session_id, voice=voice)
        return {
            "ok": True,
            "events": events,
            "answer": confirmation["answer"],
            "confirmed_required": True,
            "confirm_token": confirmation["token"],
            "confirm_expires_in": confirmation["expires_in"],
            "exit_code": code,
        }

    answer = goose_json_answer(raw_out) or clean_goose_output(raw_out)
    events.append("Goose завершил задачу." if code == 0 else f"Goose завершился с кодом {code}.")
    return {"ok": True, "events": events, "answer": answer or f"Goose завершился без вывода, exit {code}.", "exit_code": code}


def run_goose_agent(text, confirmed=False, session_id="cli", voice=False):
    text = text.strip()
    if not text:
        return {"ok": False, "events": ["Пустой запрос."], "answer": "Пустой запрос."}

    intent = schedule_intent(text)
    if intent:
        answer = schedule_summary(intent, voice=voice, telegram=is_telegram_session(session_id))
        append_history(session_id, text, answer)
        return {"ok": True, "events": ["Открываю локальное расписание Niri."], "answer": answer}

    if not confirmed:
        reason = danger_reason(text)
        if reason:
            confirmation = make_confirmation(text, reason, session_id=session_id, voice=voice)
            return {
                "ok": True,
                "events": ["Запрос требует подтверждения до запуска агента."],
                "answer": confirmation["answer"],
                "confirmed_required": True,
                "confirm_token": confirmation["token"],
                "confirm_expires_in": confirmation["expires_in"],
            }

    provider_chain = []
    primary = primary_provider_config()
    if primary:
        provider_chain.append(primary)
    provider_chain.append(local_provider_config())

    combined_events = []
    last_result = None
    for index, provider_config in enumerate(provider_chain):
        result = run_goose_once(text, session_id, confirmed, provider_config, voice=voice)
        combined_events.extend(result.get("events") or [])
        last_result = result
        if result.get("confirmed_required"):
            result["events"] = combined_events
            return result
        if provider_config.get("name") == "primary" and provider_failure(result.get("answer", ""), result.get("exit_code", 0)):
            combined_events.append("Primary provider не ответил нормально, переключаюсь на локальный Ollama.")
            continue
        if result.get("answer"):
            result["events"] = combined_events
            append_history(session_id, text, result["answer"])
            return result
    last_result = last_result or {"ok": False, "events": [], "answer": "Агент не ответил."}
    last_result["events"] = combined_events
    if last_result.get("answer"):
        append_history(session_id, text, last_result["answer"])
    return last_result


def format_agent_result(result):
    events = result.get("events") or []
    answer = result.get("answer", "")
    parts = []
    if events:
        parts.append("Шаги:\n" + "\n".join(f"- {event}" for event in events))
    if answer:
        parts.append("Итог:\n" + answer)
    return trim_text("\n\n".join(parts), MAX_REPLY)


def confirm(token):
    token = token.strip().lower()
    item = pending.pop(token, None)
    if not item:
        return "Нет такой свежей команды для подтверждения."
    action, expires = item
    if time.time() > expires:
        return "Подтверждение устарело."
    if isinstance(action, dict) and action.get("type") == "goose":
        result = run_goose_agent(
            action.get("text", ""),
            confirmed=True,
            session_id=action.get("session_id", "cli"),
            voice=bool(action.get("voice")),
        )
        if action.get("voice"):
            return result.get("answer", "") or "Готово."
        return format_agent_result(result)
    return "Неизвестное ожидающее действие."


def health():
    goose_code, goose_out = run([GOOSE_BIN, "--version"], timeout=5)
    ollama_env = os.environ.copy()
    ollama_env.setdefault("HOME", "/home/quvy")
    ollama_code, ollama_out = run(["ollama", "ps"], timeout=8, env=ollama_env)
    return {
        "ok": True,
        "agent": "goose",
        "goose_bin": GOOSE_BIN,
        "goose": goose_out if goose_code == 0 else f"unavailable: {goose_out}",
        "provider": GOOSE_PROVIDER,
        "model": MODEL,
        "primary_provider": PRIMARY_PROVIDER or None,
        "primary_model": PRIMARY_MODEL or None,
        "history_enabled": HISTORY_ENABLED,
        "history_turns": HISTORY_TURNS,
        "schedule_path": SCHEDULE_PATH,
        "ollama_url": OLLAMA_URL,
        "ollama": ollama_out if ollama_code == 0 else f"unavailable: {ollama_out}",
    }


def decode_text(body):
    text = body.get("text", "")
    if not text and body.get("text_b64"):
        text = base64.b64decode(body["text_b64"]).decode("utf-8")
    return text


def decode_session_id(body):
    return body.get("session_id") or body.get("chat_id") or "cli"


def decode_voice(body):
    return bool(body.get("voice") or body.get("voice_mode"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def _send(self, status, data):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        if self.path == "/health":
            self._send(200, health())
            return
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        try:
            body = self._body()
            if self.path in {"/agent", "/ask"}:
                result = run_goose_agent(decode_text(body), session_id=decode_session_id(body), voice=decode_voice(body))
                if self.path == "/ask":
                    self._send(200, {"ok": True, "answer": format_agent_result(result)})
                else:
                    self._send(200, result)
                return
            if self.path == "/confirm":
                self._send(200, {"ok": True, "answer": confirm(body.get("token", ""))})
                return
            self._send(404, {"ok": False, "error": "not found"})
        except Exception as exc:
            self._send(500, {"ok": False, "error": str(exc)})


def main():
    print(f"jarvis-local listening on {HOST}:{PORT}, agent=goose, model={MODEL}", flush=True)
    ReusableThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
