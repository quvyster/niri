WIFI_SSID = "your-wifi"
WIFI_PASSWORD = "your-wifi-password"

# Public VPS endpoint from pcbot_vps.py.
SERVER_URL = "http://your-vps.example:8787/esp32/wake?secret=change-me-long-random-token"

PC_MAC = "bc:5f:f4:be:2d:01"
BROADCAST_IP = "192.168.3.255"
WOL_PORTS = (9, 7)
POLL_SECONDS = 5
WAKE_REPEAT = 8

# Optional hard wake through motherboard PWR_SW pins.
# Connect GPIO to relay/opto input, and relay/opto output in parallel to case
# power button. Do not connect GPIO directly to motherboard PWR_SW.
POWER_SWITCH_PIN = None
POWER_SWITCH_ACTIVE_HIGH = True
POWER_SWITCH_PULSE_MS = 700
