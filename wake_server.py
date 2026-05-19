#!/usr/bin/env python3
import http.server
import socket
import urllib.parse


CONFIG = "/etc/pcbot-wake/config.env"


def load_config():
    values = {}
    with open(CONFIG, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    return values


VALUES = load_config()
SECRET = VALUES["SECRET"]
MAC = VALUES.get("MAC", "bc:5f:f4:be:2d:01")
DESTS = []
for item in VALUES.get("DESTS", "255.255.255.255:9").split(","):
    host, port = item.rsplit(":", 1)
    DESTS.append((host, int(port)))


def magic_packet(mac):
    clean = mac.replace(":", "").replace("-", "")
    return bytes.fromhex("ff" * 6 + clean * 16)


def wake():
    data = magic_packet(MAC)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sent = []
    for host, port in DESTS:
        sock.sendto(data, (host, port))
        sent.append(f"{MAC} -> {host}:{port}")
    return "\n".join(sent)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/health":
            self.reply(200, "ok\n")
            return
        if path != f"/wake/{SECRET}":
            self.reply(404, "not found\n")
            return
        self.reply(200, "wake sent\n" + wake() + "\n")

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.client_address[0], fmt % args), flush=True)

    def reply(self, code, body):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    port = int(VALUES.get("PORT", "8765"))
    http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
