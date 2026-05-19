# Niri PC Telegram Bot

Telegram, CLI, голосовое и GNOME GUI управление домашним ПК через локальную помощницу Нири.

## Как Это Работает

- Telegram-бот живет на VPS.
- Домашний ПК держит reverse SSH на VPS.
- Обычный текст из Telegram уходит на домашний ПК.
- На домашнем ПК `jarvis-local.service` запускает Goose в headless режиме.
- Основное имя ассистента: Niri / Нири.
- Старые команды `jarvis`, `/jarvis`, `/ai` и wake word `джарвис` оставлены как совместимые алиасы.

## CLI

```bash
niri "какие сегодня уроки"
niri "запусти Steam"
niri "проверь процессы и скажи что грузит CPU"
niri --confirm <код>
```

Старый CLI тоже работает:

```bash
jarvis "кто ты"
```

## GNOME Mini Chat

Мини-окно Niri открывается по `Super+N`.

В окне есть:

- поле ввода запроса;
- статус Niri/provider;
- чистый финальный ответ без служебных шагов.

Команда запуска:

```bash
niri-gui
```

## Голос

Голосовое распознавание сейчас отключено. `jarvis-voice.service` замаскирован в user systemd и не слушает микрофон даже для wake word.

Большая Vosk-модель и Piper-голос удалены, чтобы не занимать память и диск. Управление Нири идет через Telegram, CLI и GNOME mini chat.

## Расписание

Расписание хранится локально:

```text
niri_schedule.json
```

Запросы вроде этих открывают отдельное GTK-окно расписания:

```text
какие сегодня уроки
что завтра по предметам
вчерашние уроки
уроки в понедельник
расписание звонков
```

В голосовом режиме Нири не зачитывает длинное расписание, а открывает окно и говорит коротко: `Открыла расписание на сегодня`.

В Telegram расписание не открывается GTK-окном. Нири отправляет адаптированный текст: день, список уроков, время, кабинет и учителя. Для звонков отправляет отдельный список по выбранному дню.

Команды:

```bash
niri-schedule --day today
niri-schedule --day tomorrow
niri-schedule --day monday
niri-schedule --bells
niri-schedule --bells --day friday
```

## Приложения

GUI-приложения нужно открывать через:

```bash
niri-open-app "Discord"
```

Совместимый старый wrapper:

```bash
jarvis-open-app "Discord"
```

Поддержаны алиасы для Steam, Counter-Strike 2, Subnautica 2, DDNet, GeoGuessr, Prism Launcher, Discord, Telegram, Chrome, VS Code, Files, Settings, Calculator, VLC, mpv, qBittorrent, Karing, System Monitor и других desktop apps.

## Точные Вычисления

Для арифметики агенту доступен локальный калькулятор:

```bash
niri-calc "2 + 2 * sqrt(9)"
```

В prompt Нири явно указано использовать `niri-calc` или Python для точных вычислений, а не считать сложные выражения по памяти.

## Сервисы

Домашний ПК:

```bash
systemctl status jarvis-local.service
journalctl -u jarvis-local.service -f
systemctl status niri-wol.service
```

## Wake From Suspend

`/wake` в Telegram теперь работает через ESP32 wake bridge:

1. VPS-бот ставит wake-запрос в очередь на `:8787`.
2. ESP32 в домашнем Wi-Fi опрашивает VPS.
3. Когда видит `WAKE`, ESP32 отправляет Wake-on-LAN magic packet в локальную сеть `192.168.3.255`.
4. Домашний ПК просыпается по MAC из `esp32_wol_config.py`.

На домашнем ПК `niri-wol.service` и sleep hook включают пробуждение для `enp5s0` перед сном.

Проверка:

```bash
systemctl status niri-wol.service
cat /sys/class/net/enp5s0/device/power/wakeup
nmcli connection show "Проводное подключение 1" | grep wake-on-lan
```

ESP32 прошит MicroPython-скриптом:

```bash
./flash_esp32_wol /dev/ttyUSB0
```

Файлы:

```text
esp32_wol_config.py
esp32_wol_main.py
flash_esp32_wol
```

VPS:

```bash
systemctl status pcbot-vps.service
journalctl -u pcbot-vps.service -f
curl http://your-vps.example:8787/health
```

## Подтверждения

Опасные действия требуют подтверждения:

- root/sudo;
- установка пакетов;
- удаление файлов;
- chmod/chown;
- systemd;
- диски/mount;
- reboot/shutdown/suspend;
- kill/pkill/killall.

Подтверждение:

```bash
niri --confirm <код>
```

или в Telegram:

```text
/ai_confirm <код>
```

## Agent

Goose запускается через локальный HTTP API `127.0.0.1:8765`.

Primary provider может быть OpenRouter, fallback остается локальный Ollama `qwen3:4b`.

Проверка:

```bash
curl http://127.0.0.1:8765/health
```
