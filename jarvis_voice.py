#!/usr/bin/env python3
import argparse
import json
import os
import queue
import re
import signal
import subprocess
import sys
import time
import urllib.request
import shutil

from vosk import KaldiRecognizer, Model, SetLogLevel


DEFAULT_MODEL = "/home/quvy/.local/share/jarvis/models/vosk-model-ru-0.42"
DEFAULT_URL = "http://127.0.0.1:8765/agent"
DEFAULT_TTS = os.environ.get("JARVIS_VOICE_TTS", "rhvoice")
DEFAULT_TTS_VOICE = os.environ.get("JARVIS_VOICE_TTS_VOICE", "Anna")
DEFAULT_PIPER_BIN = os.environ.get("NIRI_PIPER_BIN", "/home/quvy/.local/share/niri/piper/venv/bin/piper")
DEFAULT_PIPER_MODEL = os.environ.get("NIRI_PIPER_MODEL", "/home/quvy/.local/share/niri/piper/voices/ru_RU-irina-medium.onnx")
DEFAULT_PIPER_VOLUME = os.environ.get("NIRI_PIPER_VOLUME", "0.45")
RATE = 16000
CHUNK = 4000


WAKE_RE = re.compile(r"\b(нири|нире|нери|мири|мире|niri|джарвис|джервис|jarvis|ярвис|жарвис)\b", re.IGNORECASE)
YES_RE = re.compile(r"\b(да|ага|угу|(?<!не )подтверждаю|согласен|согласна|можно|выполняй|подтверди)\b", re.IGNORECASE)
NO_RE = re.compile(r"\b(нет|не надо|отмена|отбой|стоп|не подтверждаю)\b", re.IGNORECASE)
def log(message):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


def play_wav(path):
    players = [
        ["pw-play", path],
        ["paplay", path],
        ["aplay", path],
    ]
    for cmd in players:
        if shutil.which(cmd[0]):
            proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
            if proc.returncode == 0:
                return True
    return False


def speak(text, enabled=True, engine=DEFAULT_TTS, voice=DEFAULT_TTS_VOICE, piper_bin=DEFAULT_PIPER_BIN, piper_model=DEFAULT_PIPER_MODEL, piper_volume=DEFAULT_PIPER_VOLUME):
    text = (text or "").strip()
    if not enabled or not text:
        return
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"[*_#>\[\](){}/\\|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text[:450]
    if engine == "piper" and os.path.exists(piper_bin) and os.path.exists(piper_model):
        wav_path = f"/tmp/niri-tts-{os.getpid()}-{int(time.time() * 1000)}.wav"
        try:
            proc = subprocess.run(
                [piper_bin, "--model", piper_model, "--volume", str(piper_volume), "-f", wav_path],
                input=text,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=45,
                check=False,
            )
            if proc.returncode == 0 and os.path.exists(wav_path) and play_wav(wav_path):
                return
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass
    if engine == "rhvoice" and shutil.which("spd-say"):
        proc = subprocess.run(
            ["spd-say", "-w", "-o", "rhvoice", "-l", "ru", "-y", voice, text],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        if proc.returncode == 0:
            return
    subprocess.run(
        ["espeak-ng", "-v", "ru", "-s", "165", "-p", "35", text],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )


def post_agent(text, url, session_id):
    payload = json.dumps({"text": text, "session_id": session_id, "voice": True}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=950) as resp:
        return json.loads(resp.read().decode("utf-8"))


def confirm_endpoint(url):
    url = url.rstrip("/")
    if url.endswith("/agent") or url.endswith("/ask"):
        return url.rsplit("/", 1)[0] + "/confirm"
    return url + "/confirm"


def post_confirm(token, url):
    payload = json.dumps({"token": token}).encode("utf-8")
    req = urllib.request.Request(confirm_endpoint(url), data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=950) as resp:
        return json.loads(resp.read().decode("utf-8"))


def start_parec(source):
    cmd = [
        "parec",
        "--raw",
        "--format=s16le",
        f"--rate={RATE}",
        "--channels=1",
        "--latency-msec=60",
    ]
    if source:
        cmd.append(f"--device={source}")
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def extract_after_wake(text):
    match = WAKE_RE.search(text or "")
    if not match:
        return ""
    return text[match.end():].strip(" ,.!?:;-")


def normalize_command(text):
    text = (text or "").strip()
    text = WAKE_RE.sub("", text).strip(" ,.!?:;-")
    return re.sub(r"\s+", " ", text).strip()


def main():
    parser = argparse.ArgumentParser(description="Always-on local Niri voice listener")
    parser.add_argument("--model", default=os.environ.get("NIRI_VOICE_MODEL", os.environ.get("JARVIS_VOICE_MODEL", DEFAULT_MODEL)))
    parser.add_argument("--source", default=os.environ.get("JARVIS_VOICE_SOURCE", ""))
    parser.add_argument("--url", default=os.environ.get("JARVIS_VOICE_AGENT_URL", DEFAULT_URL))
    parser.add_argument("--session-id", default=os.environ.get("JARVIS_VOICE_SESSION_ID", "voice"))
    parser.add_argument("--tts", default=DEFAULT_TTS, choices=("piper", "rhvoice", "espeak"))
    parser.add_argument("--tts-voice", default=DEFAULT_TTS_VOICE)
    parser.add_argument("--piper-bin", default=DEFAULT_PIPER_BIN)
    parser.add_argument("--piper-model", default=DEFAULT_PIPER_MODEL)
    parser.add_argument("--no-tts", action="store_true")
    parser.add_argument("--once", action="store_true", help="Exit after one command")
    args = parser.parse_args()

    SetLogLevel(-1)
    if not os.path.isdir(args.model):
        log(f"Vosk model not found: {args.model}")
        return 2
    model = Model(args.model)
    recognizer = KaldiRecognizer(model, RATE)
    recognizer.SetWords(False)

    running = True

    def stop(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    state = "wake"
    deadline = 0.0
    confirm_token = ""
    log("voice listener ready; waiting for wake word: нири / niri")
    proc = start_parec(args.source)

    while running:
        chunk = proc.stdout.read(CHUNK) if proc.stdout else b""
        if not chunk:
            if proc.poll() is not None:
                log("parec stopped; restarting")
                proc = start_parec(args.source)
                recognizer = KaldiRecognizer(model, RATE)
                recognizer.SetWords(False)
            continue

        if not recognizer.AcceptWaveform(chunk):
            if state in {"command", "confirm"} and time.time() > deadline:
                state = "wake"
                confirm_token = ""
                log("command timeout; back to sleep")
            continue

        try:
            text = json.loads(recognizer.Result()).get("text", "").strip()
        except json.JSONDecodeError:
            text = ""
        if not text:
            continue

        log(f"heard: {text}")
        if state == "confirm":
            answer_text = normalize_command(text)
            if NO_RE.search(answer_text):
                log("voice confirmation declined")
                confirm_token = ""
                state = "wake"
                speak("Отменил.", enabled=not args.no_tts, engine=args.tts, voice=args.tts_voice, piper_bin=args.piper_bin, piper_model=args.piper_model)
                continue
            if YES_RE.search(answer_text):
                log("voice confirmation accepted")
                state = "busy"
                speak("Подтверждаю.", enabled=not args.no_tts, engine=args.tts, voice=args.tts_voice, piper_bin=args.piper_bin, piper_model=args.piper_model)
                try:
                    result = post_confirm(confirm_token, args.url)
                    answer = (result.get("answer") or result.get("error") or "Нет ответа.").strip()
                    log(f"answer: {answer}")
                    speak(answer, enabled=not args.no_tts, engine=args.tts, voice=args.tts_voice, piper_bin=args.piper_bin, piper_model=args.piper_model)
                except Exception as exc:
                    log(f"confirm error: {exc}")
                    speak("Не смог подтвердить команду.", enabled=not args.no_tts, engine=args.tts, voice=args.tts_voice, piper_bin=args.piper_bin, piper_model=args.piper_model)
                confirm_token = ""
                if args.once:
                    break
                recognizer = KaldiRecognizer(model, RATE)
                recognizer.SetWords(False)
                state = "wake"
                log("back to sleep")
                continue
            speak("Скажи да для подтверждения или нет для отмены.", enabled=not args.no_tts, engine=args.tts, voice=args.tts_voice, piper_bin=args.piper_bin, piper_model=args.piper_model)
            deadline = time.time() + 12
            continue

        if state == "wake":
            command = extract_after_wake(text)
            if WAKE_RE.search(text):
                if command:
                    state = "busy"
                else:
                    speak("Слушаю.", enabled=not args.no_tts, engine=args.tts, voice=args.tts_voice, piper_bin=args.piper_bin, piper_model=args.piper_model)
                    state = "command"
                    deadline = time.time() + 9
                    continue
            else:
                continue
        elif state == "command":
            command = normalize_command(text)
            state = "busy"
        else:
            continue

        if not command:
            state = "wake"
            continue

        log(f"command: {command}")
        speak("Выполняю.", enabled=not args.no_tts, engine=args.tts, voice=args.tts_voice, piper_bin=args.piper_bin, piper_model=args.piper_model)
        try:
            result = post_agent(command, args.url, args.session_id)
            answer = (result.get("answer") or result.get("error") or "Нет ответа.").strip()
            log(f"answer: {answer}")
            speak(answer, enabled=not args.no_tts, engine=args.tts, voice=args.tts_voice, piper_bin=args.piper_bin, piper_model=args.piper_model)
            if result.get("confirmed_required") and result.get("confirm_token"):
                confirm_token = str(result.get("confirm_token"))
                deadline = time.time() + int(result.get("confirm_expires_in") or 120)
                state = "confirm"
                recognizer = KaldiRecognizer(model, RATE)
                recognizer.SetWords(False)
                log("waiting for voice confirmation: да / нет")
                continue
        except Exception as exc:
            log(f"agent error: {exc}")
            speak("Не смог выполнить команду.", enabled=not args.no_tts, engine=args.tts, voice=args.tts_voice, piper_bin=args.piper_bin, piper_model=args.piper_model)

        if args.once:
            break
        recognizer = KaldiRecognizer(model, RATE)
        recognizer.SetWords(False)
        state = "wake"
        log("back to sleep")

    try:
        proc.terminate()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
