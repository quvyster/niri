#!/usr/bin/env python3
import argparse
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk


ROOT = os.path.dirname(os.path.abspath(__file__))
SCHEDULE_PATH = os.environ.get("NIRI_SCHEDULE_PATH", os.path.join(ROOT, "niri_schedule.json"))
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAY_NAMES = {
    "monday": "Понедельник",
    "tuesday": "Вторник",
    "wednesday": "Среда",
    "thursday": "Четверг",
    "friday": "Пятница",
    "saturday": "Суббота",
    "sunday": "Воскресенье",
}


def load_schedule():
    with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_day(value, schedule):
    tz = ZoneInfo(schedule.get("timezone", "Asia/Omsk"))
    today = datetime.now(tz).date()
    if value == "today":
        date = today
    elif value == "tomorrow":
        date = today + timedelta(days=1)
    elif value == "yesterday":
        date = today - timedelta(days=1)
    elif value in DAYS:
        return value, DAY_NAMES[value]
    else:
        date = today
    key = DAYS[date.weekday()]
    return key, f"{DAY_NAMES[key]}, {date.strftime('%d.%m')}"


class ScheduleWindow(Adw.ApplicationWindow):
    def __init__(self, app, mode, day):
        super().__init__(application=app, title="Niri Schedule")
        self.set_default_size(720, 560)
        self.set_resizable(True)
        self.schedule = load_schedule()
        self.mode = mode
        self.day, self.title_text = resolve_day(day, self.schedule)
        self.set_content(self.build())

    def build(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        toolbar = Adw.HeaderBar()
        title = Adw.WindowTitle(title="Расписание", subtitle=self.subtitle())
        toolbar.set_title_widget(title)
        root.append(toolbar)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        scrolled.set_child(box)

        if self.mode == "bells":
            self.fill_bells(box)
        else:
            self.fill_lessons(box)
        root.append(scrolled)
        return root

    def subtitle(self):
        if self.mode == "bells":
            return f"Звонки · {self.title_text}"
        return self.title_text

    def card(self):
        frame = Gtk.Frame()
        frame.add_css_class("card")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        inner.set_margin_top(10)
        inner.set_margin_bottom(10)
        inner.set_margin_start(12)
        inner.set_margin_end(12)
        frame.set_child(inner)
        return frame, inner

    def fill_bells(self, box):
        bells_by_day = self.schedule.get("bells_by_day") or {}
        bells = bells_by_day.get(self.day, self.schedule.get("bells", []))
        if not bells:
            empty = Gtk.Label(label="Звонков нет", xalign=0.5)
            empty.add_css_class("title-2")
            empty.set_margin_top(80)
            box.append(empty)
            return
        for item in bells:
            frame, inner = self.card()
            title = Gtk.Label(label=f"{item.get('number')} урок", xalign=0)
            title.add_css_class("heading")
            time = Gtk.Label(label=item.get("time", ""), xalign=0)
            time.add_css_class("dim-label")
            inner.append(title)
            inner.append(time)
            box.append(frame)

    def fill_lessons(self, box):
        lessons = self.schedule.get("days", {}).get(self.day, [])
        if not lessons:
            empty = Gtk.Label(label="Уроков нет", xalign=0.5)
            empty.add_css_class("title-2")
            empty.set_margin_top(80)
            box.append(empty)
            return
        for lesson in lessons:
            frame, inner = self.card()
            subject = Gtk.Label(label=f"{lesson.get('number')}  {lesson.get('subject', '')}", xalign=0)
            subject.add_css_class("title-4")
            meta = Gtk.Label(label=" · ".join(x for x in [
                lesson.get("time", ""),
                f"каб. {lesson.get('room')}" if lesson.get("room") else "",
                lesson.get("teacher", ""),
            ] if x), xalign=0)
            meta.add_css_class("dim-label")
            meta.set_wrap(True)
            inner.append(subject)
            inner.append(meta)
            box.append(frame)


class App(Adw.Application):
    def __init__(self, mode, day):
        super().__init__(application_id="local.niri.Schedule", flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.mode = mode
        self.day = day

    def do_activate(self):
        win = ScheduleWindow(self, self.mode, self.day)
        win.present()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["day", "bells"], default="day")
    parser.add_argument("--day", default="today")
    args = parser.parse_args()
    app = App(args.mode, args.day)
    return app.run([])


if __name__ == "__main__":
    raise SystemExit(main())
