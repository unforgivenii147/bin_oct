#!/data/data/com.termux/files/home/.local/bin/python
"""
Pure-Python ping for Termux.
- Uses raw ICMP socket when possible (needs root / CAP_NET_RAW).
- Falls back to TCP-connect ping (no root required).
"""

import argparse
import os
import select
import socket
import struct
import sys
import time


ICMP_ECHO_REQUEST = 8
ICMP_ECHO_REPLY = 0


# ---------------------------------------------------------------------------
# Checksum
# ---------------------------------------------------------------------------
def checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\x00"
    s = sum(struct.unpack("!%dH" % (len(data) // 2), data))
    s = (s >> 16) + (s & 0xFFFF)
    s += s >> 16
    return ~s & 0xFFFF


# ---------------------------------------------------------------------------
# Raw ICMP ping (root only)
# ---------------------------------------------------------------------------
def icmp_ping(host: str, timeout: float, seq: int, payload_size: int = 32):
    try:
        dest = socket.gethostbyname(host)
    except socket.gaierror as e:
        return None, str(e)

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    except PermissionError:
        return None, "permission"
    except OSError as e:
        return None, str(e)

    sock.settimeout(timeout)

    ident = os.getpid() & 0xFFFF
    payload = b"P" * payload_size
    header = struct.pack("!BBHHH", ICMP_ECHO_REQUEST, 0, 0, ident, seq)
    chksum = checksum(header + payload)
    header = struct.pack("!BBHHH", ICMP_ECHO_REQUEST, 0, chksum, ident, seq)
    packet = header + payload

    send_time = time.time()
    try:
        sock.sendto(packet, (dest, 0))
    except OSError as e:
        sock.close()
        return None, str(e)

    deadline = send_time + timeout
    try:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return None, "timeout"
            r, _, _ = select.select([sock], [], [], remaining)
            if not r:
                return None, "timeout"
            recv_time = time.time()
            data, addr = sock.recvfrom(1024)
            # IPv4 header length
            ihl = (data[0] & 0x0F) * 4
            icmp_type, code, _, recv_id, recv_seq = struct.unpack(
                "!BBHHH", data[ihl : ihl + 8]
            )
            if icmp_type == ICMP_ECHO_REPLY and recv_id == ident and recv_seq == seq:
                rtt = (recv_time - send_time) * 1000.0
                return (addr[0], rtt), None
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# TCP ping (no root required)
# ---------------------------------------------------------------------------
def tcp_ping(host: str, timeout: float, port: int = 443):
    try:
        dest = socket.gethostbyname(host)
    except socket.gaierror as e:
        return None, str(e)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    start = time.time()
    try:
        sock.connect((dest, port))
    except (socket.timeout, TimeoutError):
        return None, "timeout"
    except ConnectionRefusedError:
        # Host responded with RST → reachable, still useful
        return (dest, (time.time() - start) * 1000.0), None
    except OSError as e:
        return None, str(e)
    finally:
        try:
            sock.close()
        except Exception:
            pass
    return (dest, (time.time() - start) * 1000.0), None


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def resolve(host: str) -> str:
    try:
        return socket.gethostbyname(host)
    except socket.gaierror:
        return host


def run(host, count, timeout, interval, mode, tcp_port):
    print(f"PING {host} ({resolve(host)})  mode={mode}  timeout={timeout}s")
    print()

    sent = recv = 0
    rtts = []
    use_icmp = (mode == "icmp") or (mode == "auto")
    warned_fallback = False

    for seq in range(1, count + 1):
        sent += 1
        result = None
        err = None

        if use_icmp:
            result, err = icmp_ping(host, timeout, seq)
            if err == "permission":
                if mode == "icmp":
                    print("Raw ICMP not permitted. Run as root, or use --mode tcp.")
                    return
                if not warned_fallback:
                    print("[i] Raw ICMP not permitted, falling back to TCP ping.\n")
                    warned_fallback = True
                use_icmp = False

        if not use_icmp:
            result, err = tcp_ping(host, timeout, tcp_port)

        if result:
            ip, rtt = result
            rtts.append(rtt)
            recv += 1
            print(f"64 bytes from {ip}: seq={seq} time={rtt:.1f} ms")
        else:
            print(f"Request timeout for icmp_seq {seq} ({err})")

        if seq < count:
            time.sleep(interval)

    print()
    print(f"--- {host} ping statistics ---")
    loss = (sent - recv) / sent * 100 if sent else 0
    print(f"{sent} packets transmitted, {recv} received, {loss:.0f}% packet loss")
    if rtts:
        print(
            f"rtt min/avg/max = {min(rtts):.1f}/"
            f"{sum(rtts) / len(rtts):.1f}/{max(rtts):.1f} ms"
        )


def main():
    p = argparse.ArgumentParser(description="Pure-Python ping for Termux")
    p.add_argument("host", help="hostname or IP address")
    p.add_argument("-c", "--count", type=int, default=4, help="number of pings")
    p.add_argument("-W", "--timeout", type=float, default=2.0, help="timeout seconds")
    p.add_argument("-i", "--interval", type=float, default=1.0, help="interval seconds")
    p.add_argument(
        "-m",
        "--mode",
        choices=["auto", "icmp", "tcp"],
        default="auto",
        help="auto (default) tries ICMP then TCP; icmp = root only; tcp = no root",
    )
    p.add_argument("-p", "--port", type=int, default=443, help="TCP port (default 443)")
    args = p.parse_args()

    try:
        run(args.host, args.count, args.timeout, args.interval, args.mode, args.port)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)


if __name__ == "__main__":
    main()
