import socket
import time

import network
import urequests

try:
    import esp32_wol_config as config
except ImportError:
    import esp32_wol_config_example as config


def log(message):
    print("[niri-wol]", message)


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return wlan
    log("connecting wifi...")
    wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
    deadline = time.time() + 30
    while not wlan.isconnected() and time.time() < deadline:
        time.sleep(0.5)
    if not wlan.isconnected():
        raise RuntimeError("wifi connect timeout")
    log("wifi connected: %s" % (wlan.ifconfig(),))
    return wlan


def magic_packet(mac):
    clean = mac.replace(":", "").replace("-", "").lower()
    return b"\xff" * 6 + bytes.fromhex(clean) * 16


def send_wol():
    packet = magic_packet(config.PC_MAC)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        for _ in range(config.WAKE_REPEAT):
            for port in config.WOL_PORTS:
                sock.sendto(packet, (config.BROADCAST_IP, port))
            time.sleep(0.2)
    finally:
        sock.close()
    log("wol sent to %s via %s" % (config.PC_MAC, config.BROADCAST_IP))


def poll_server():
    response = urequests.get(config.SERVER_URL)
    try:
        text = response.text.strip()
    finally:
        response.close()
    return text


def main():
    connect_wifi()
    last_response = ""
    while True:
        try:
            if not network.WLAN(network.STA_IF).isconnected():
                connect_wifi()
            response = poll_server()
            if response and response != last_response:
                log("server: %s" % response)
                last_response = response
            if response.startswith("WAKE"):
                send_wol()
                time.sleep(10)
        except Exception as exc:
            log("error: %s" % exc)
            time.sleep(10)
        time.sleep(config.POLL_SECONDS)


main()
