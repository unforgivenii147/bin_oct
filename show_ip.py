#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import socket
from io import BytesIO

import pycurl


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "Unable to get local IP"


def get_public_ip():
    buffer = BytesIO()
    c = pycurl.Curl()
    try:
        c.setopt(c.URL, "https://ipify.org")
        c.setopt(c.WRITEDATA, buffer)
        c.setopt(c.TIMEOUT, 15)
        c.setopt(c.FOLLOWLOCATION, True)
        c.perform()
        c.close()
        return buffer.getvalue().decode("utf-8").strip()
    except pycurl.error as e:
        return f"Curl error: {e}"


if __name__ == "__main__":
    print(f"Local IP:  {get_local_ip()}")
    print(f"Public IP: {get_public_ip()}")
