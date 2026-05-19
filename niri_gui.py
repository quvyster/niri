#!/usr/bin/env python3
import json
import threading
import urllib.error
import urllib.request

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk


API_URL = "http://127.0.0.1:8765/agent"


def post_agent(text):
    payload = json.dumps({"text": text, "session_id": "gui"}).encode("utf-8")
    req = urllib.request.Request(API_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=950) as resp:
        return json.loads(resp.read().decode("utf-8"))


class NiriWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Niri")
        self.set_default_size(620, 420)
        self.set_resizable(True)
        self.build()

    def build(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_content(root)

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Niri", subtitle="локальный агент"))
        root.append(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.set_margin_top(14)
        body.set_margin_bottom(14)
        body.set_margin_start(14)
        body.set_margin_end(14)
        root.append(body)

        input_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.entry = Gtk.Entry(hexpand=True)
        self.entry.set_placeholder_text("Спроси Нири...")
        self.entry.connect("activate", self.on_send)
        send = Gtk.Button(label="Отправить")
        send.add_css_class("suggested-action")
        send.connect("clicked", self.on_send)
        input_row.append(self.entry)
        input_row.append(send)
        body.append(input_row)

        self.status = Gtk.Label(label="Готова", xalign=0)
        self.status.add_css_class("dim-label")
        body.append(self.status)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        self.answer = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.answer.add_css_class("card")
        self.buffer = self.answer.get_buffer()
        scrolled.set_child(self.answer)
        body.append(scrolled)

    def set_answer(self, text):
        self.buffer.set_text(text or "")

    def on_send(self, *_args):
        text = self.entry.get_text().strip()
        if not text:
            return
        self.entry.set_text("")
        self.status.set_text("Niri думает...")
        self.set_answer("")
        threading.Thread(target=self.worker, args=(text,), daemon=True).start()

    def worker(self, text):
        try:
            data = post_agent(text)
            answer = data.get("answer") or data.get("error") or "Нет ответа."
            events = data.get("events") or []
            provider = "готово"
            for event in events:
                if "Goose:" in event:
                    provider = event.replace("Запускаю Goose:", "").strip()
                    break
            GLib.idle_add(self.status.set_text, provider)
            GLib.idle_add(self.set_answer, answer)
        except urllib.error.URLError:
            GLib.idle_add(self.status.set_text, "Niri недоступна")
            GLib.idle_add(self.set_answer, "Локальный сервис не отвечает.")
        except Exception as exc:
            GLib.idle_add(self.status.set_text, "Ошибка")
            GLib.idle_add(self.set_answer, str(exc))


class NiriApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="local.niri.Chat")
        self.win = None

    def do_activate(self):
        if self.win is None:
            self.win = NiriWindow(self)
        self.win.present()
        self.win.entry.grab_focus()


def main():
    app = NiriApp()
    return app.run([])


if __name__ == "__main__":
    raise SystemExit(main())
