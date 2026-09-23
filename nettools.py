#!/data/data/com.termux/files/home/.local/bin/python
"""
merged_net_tools.py — unified network toolkit.

Consolidates the following scripts into a single CLI:

    proxy_tester.py  ->  python merged_net_tools.py proxy-test ...
    pynet.py         ->  python merged_net_tools.py net-info ...
    pyng.py          ->  python merged_net_tools.py ping ...
    set_dns.py       ->  python merged_net_tools.py set-dns ...
    show_ip.py       ->  python merged_net_tools.py show-ip ...
    signal_meter.py  ->  python merged_net_tools.py signal ...

External dependencies (install via `pip install ...`):
    requests       # proxy-test
    colorama       # proxy-test (colored ✅/❌)
    rich           # signal (panel/TUI)
    pycurl         # show-ip --engine=pycurl (optional; urllib fallback)

Usage examples
--------------
    python merged_net_tools.py proxy-test -f proxies.txt -w 8
    python merged_net_tools.py net-info --no-speedtest
    python merged_net_tools.py ping 8.8.8.8 -c 5 -q
    python merged_net_tools.py set-dns -n "Cloudflare DNS"
    python merged_net_tools.py show-ip --engine pycurl
    python merged_net_tools.py signal --interval 1.5
"""

from __future__ import annotations

import argparse
import io
import json
import os
import random
import re
import socket
import string
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple
from urllib import request as urlrequest

# --- third-party imports (declared explicitly per requirement 8) -----------
try:
    import requests  # type: ignore
    from colorama import Fore, Style, init as colorama_init  # type: ignore

    colorama_init(autoreset=True)
    _HAS_COLORAMA = True
except ImportError:  # graceful degradation
    requests = None  # type: ignore
    _HAS_COLORAMA = False

    class _DummyColors:
        GREEN = RED = ""

    class _DummyStyle:
        RESET_ALL = ""

    Fore = _DummyColors()  # type: ignore
    Style = _DummyStyle()  # type: ignore

# Rich is only needed by `signal`; import lazily inside that command.
# pycurl is only needed by `show-ip --engine=pycurl`; imported lazily too.


# ==========================================================================
#  Common helpers
# ==========================================================================


def get_public_ip() -> Optional[str]:
    """Return the public IP address by querying several well-known services."""
    endpoints = [
        ("https://api.ipify.org?format=json", "ip"),
        ("https://ipinfo.io/json", "ip"),
        ("https://httpbin.org/ip", "origin"),
        ("http://ip-api.com/json", "query"),
    ]
    for url, key in endpoints:
        try:
            with urlrequest.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                ip = data.get(key)
                if ip:
                    return ip
        except Exception:
            continue
    return None


def get_local_ip() -> str:
    """Return the primary outbound local IP (falls back to hostname lookup)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return socket.gethostbyname(socket.gethostname())


def read_dns_servers(path: Path) -> List[str]:
    """Parse `nameserver` lines from a resolv.conf-style file (deduped)."""
    servers: List[str] = []
    try:
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("nameserver"):
                    parts = line.split()
                    if len(parts) >= 2:
                        servers.append(parts[1])
    except Exception as e:
        return [f"Error retrieving DNS: {e}"]

    # dedupe, preserve order
    seen, uniq = set(), []
    for s in servers:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


# ==========================================================================
#  1) proxy-test  (from proxy_tester.py)
# ==========================================================================


def _probe_one(
    idx: int, total: int, proxy: str, timeout: float, delay: float
) -> Tuple[str, Optional[str]]:
    """Test a single proxy. Returns (colored_status_line, valid_proxy_or_None)."""
    proxy = proxy.strip()
    proxies = {"http": f"http://{proxy}", "https": f"https://{proxy}"}
    ok = False
    if requests is not None:
        try:
            r = requests.get("http://httpbin.org/ip", proxies=proxies, timeout=timeout)
            ok = r.status_code == 200
        except requests.exceptions.RequestException:
            ok = False
    time.sleep(delay)  # original had r(0.5) — a rate-limit pause
    color = Fore.GREEN if ok else Fore.RED
    mark = "✅" if ok else "❌"
    line = f"{color}[{idx}/{total}] {mark} {proxy}{Style.RESET_ALL}"
    return line, (proxy if ok else None)


def cmd_proxy_test(args: argparse.Namespace) -> int:
    """Test a list of HTTP proxies concurrently, print results, optionally save."""
    if requests is None:
        print(
            "Error: 'requests' package is required for proxy-test. `pip install requests`"
        )
        return 2

    src = Path(args.file)
    if not src.exists():
        print(f"Error: proxies file '{src}' not found.")
        return 1

    proxies = [ln.strip() for ln in src.read_text().splitlines() if ln.strip()]
    if not proxies:
        print("No proxies to test.")
        return 0

    total = len(proxies)
    jobs = [(i, total, p) for i, p in enumerate(proxies, start=1)]
    valid: List[str] = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for line, good in pool.map(
            lambda t: _probe_one(*t, timeout=args.timeout, delay=args.delay), jobs
        ):
            print(line)
            if good:
                valid.append(good)

    if not valid:
        print("No valid proxies found.")
        return 0

    out_path: Optional[str] = args.output
    if out_path is None:
        answer = (
            input("Do you want to save the valid proxies to a file? (y/n): ")
            .strip()
            .lower()
        )
        if answer != "y":
            return 0
        out_path = (
            input(
                "Enter the filename to save valid proxies (default:valid_proxies.txt): "
            ).strip()
            or "valid_proxies.txt"
        )

    Path(out_path).write_text("\n".join(valid) + "\n", encoding="utf-8")
    print(f"Valid proxies saved to {out_path}")
    return 0


# ==========================================================================
#  2) net-info  (from pynet.py)
# ==========================================================================


def _speed_download(url: str, timeout: float) -> Optional[float]:
    """Return download throughput in Mbps, or None on error."""
    t0 = time.time()
    try:
        with urlrequest.urlopen(url, timeout=timeout) as resp:
            data = resp.read()
        elapsed = time.time() - t0
        return len(data) * 8 / elapsed / 1_000_000.0
    except Exception:
        return None


def _speed_upload(
    url: str, size: int = 1024 * 1024, timeout: float = 20.0
) -> Optional[float]:
    """Return upload throughput in Mbps, or None on error."""
    payload = "".join(
        random.choices(string.ascii_letters + string.digits, k=size)
    ).encode()
    boundary = "----------ThIs_Is_tHe_bouNdaRY_$"
    body = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="test.bin"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + payload
        + f"\r\n--{boundary}--\r\n".encode()
    )

    req = urlrequest.Request(url, data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    t0 = time.time()
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            resp.read()
        elapsed = time.time() - t0
        return size * 8 / elapsed / 1_000_000.0
    except Exception:
        return None


def cmd_net_info(args: argparse.Namespace) -> int:
    """Print public IP, local IP, DNS servers, and (optionally) run a speed test."""
    print("-" * 40)
    print(" NETWORK STATES ")
    print("-" * 40)

    print("\n[*] Public IP:")
    pub = get_public_ip()
    print(f"    {pub}" if pub else "    Could not determine public IP.")

    print("\n[*] Local IP (primary interface):")
    print(f"    {get_local_ip()}")

    print("\n[*] DNS Servers:")
    dns = read_dns_servers(Path(args.dns_path))
    if dns:
        for i, s in enumerate(dns, start=1):
            if i <= 2:
                print(f"    DNS {i}: {s}")
        if len(dns) > 2:
            print(f"    (plus {len(dns) - 2} more)")
    else:
        print("    No DNS servers found.")

    if not args.no_speedtest:
        print("\n[*] Speed test")
        print("    Testing download speed...")
        dl = _speed_download(args.download_url, timeout=20.0)
        print(
            f"    Download: {dl:.2f} Mbps" if dl is not None else "    Download: failed"
        )

        print("    Testing upload speed...")
        ul = _speed_upload(args.upload_url)
        print(
            f"    Upload:   {ul:.2f} Mbps" if ul is not None else "    Upload: failed"
        )

    return 0


# ==========================================================================
#  3) ping  (from pyng.py)
# ==========================================================================

_PING_HOST_RE = re.compile(r"PING\s+(\S+)\s+\(([^)]+)\)")
_PING_RESP_RE = re.compile(r"bytes from.*icmp_seq=(\d+).*time=([0-9.]+)\s*ms")
_PING_SUM_RE = re.compile(
    r"(\d+)\s+packets transmitted,\s+(\d+)(?:\s+packets)?\s+received,\s+([0-9.]+)%\s+packet loss"
)
_PING_RTT_RE = re.compile(
    r"min/avg/max(?:/stddev)?\s*=\s*([0-9.]+)/([0-9.]+)/([0-9.]+)(?:/([0-9.]+))?"
)


class PingStats:
    """Container holding parsed output of a single `ping` run."""

    def __init__(self) -> None:
        self.host: str = ""
        self.ip: str = ""
        self.packets_sent: int = 0
        self.packets_received: int = 0
        self.packets_lost: int = 0
        self.min_time: Optional[float] = None
        self.avg_time: Optional[float] = None
        self.max_time: Optional[float] = None
        self.stddev_time: Optional[float] = None
        self.packet_loss_percent: float = 0.0
        self.responses: List[dict] = []

    def __str__(self) -> str:
        out = f"\n--- {self.host} ping statistics ---\n"
        out += (
            f"{self.packets_sent} packets transmitted,"
            f"{self.packets_received} packets received,"
            f"{self.packet_loss_percent:.1f}% packet loss\n"
        )
        if self.packets_received > 0:
            out += (
                f"round-trip min/avg/max/stddev="
                f"{self.min_time:.3f}/{self.avg_time:.3f}/{self.max_time:.3f}"
            )
            if self.stddev_time is not None:
                out += f"/{self.stddev_time:.3f}"
            out += " ms\n"
        return out


def parse_ping_output(text: str) -> PingStats:
    """Parse raw `ping` stdout into a PingStats object."""
    st = PingStats()
    lines = text.splitlines()
    if lines:
        m = _PING_HOST_RE.match(lines[0])
        if m:
            st.host, st.ip = m.group(1), m.group(2)

    for ln in lines:
        m = _PING_RESP_RE.search(ln)
        if m:
            st.responses.append({"seq": int(m.group(1)), "time": float(m.group(2))})

    m = _PING_SUM_RE.search(text)
    if m:
        st.packets_sent = int(m.group(1))
        st.packets_received = int(m.group(2))
        st.packets_lost = st.packets_sent - st.packets_received
        st.packet_loss_percent = float(m.group(3))

    m = _PING_RTT_RE.search(text)
    if m:
        st.min_time = float(m.group(1))
        st.avg_time = float(m.group(2))
        st.max_time = float(m.group(3))
        if m.group(4):
            st.stddev_time = float(m.group(4))
    return st


def run_ping(
    host: str,
    count: int = 4,
    timeout: int = 4,
    size: int = 56,
    live: bool = True,
) -> Optional[PingStats]:
    """Invoke the system `ping` binary and parse the result."""
    try:
        cmd = [
            "ping",
            "-c",
            str(count),
            "-W",
            str(timeout * 400),
            "-s",
            str(size),
            host,
        ]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
        )
        collected = ""
        if live:
            for line in proc.stdout:  # type: ignore[union-attr]
                print(line.rstrip())
                collected += line
        else:
            collected, _ = proc.communicate()  # type: ignore[misc]
        proc.wait()
        return parse_ping_output(collected)
    except FileNotFoundError:
        print("Error: 'ping' command not found. This tool needs a Unix-like system.")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None


def cmd_ping(args: argparse.Namespace) -> int:
    """Run an ICMP ping and print the parsed statistics."""
    stats = run_ping(
        args.host,
        count=args.count,
        timeout=args.timeout,
        size=args.size,
        live=not args.quiet,
    )
    if not stats:
        return 1
    print(stats)
    return 0 if stats.packet_loss_percent < 100 else 1


# ==========================================================================
#  4) set-dns  (from set_dns.py)
# ==========================================================================

DNS_PROVIDERS: dict[str, List[str]] = {
    "DNS.Watch": ["84.200.69.80", "84.200.70.40"],
    "Comodo Secure DNS": ["8.26.56.26", "8.20.247.20"],
    "Level3 DNS": ["209.244.0.3", "209.244.0.4"],
    "Yandex DNS": ["77.88.8.8", "77.88.8.1"],
    "Cloudflare DNS": ["1.1.1.1", "1.0.0.1"],
    "Open DNS": ["208.67.222.222", "208.67.220.220"],
    "Google DNS": ["8.8.8.8", "8.8.4.4"],
}


def cmd_set_dns(args: argparse.Namespace) -> int:
    """Write a resolv.conf-style file selecting either a random or named provider."""
    if args.list:
        print("Available DNS providers:")
        for name, servers in DNS_PROVIDERS.items():
            print(f"  - {name}: {', '.join(servers)}")
        return 0

    if args.name:
        if args.name not in DNS_PROVIDERS:
            print(
                f"Error: unknown DNS provider '{args.name}'. Use --list to see options."
            )
            return 1
        name, servers = args.name, DNS_PROVIDERS[args.name]
    else:
        name, servers = random.choice(list(DNS_PROVIDERS.items()))

    target = Path(args.target).expanduser()
    body = f"# Generated by merged_net_tools (set-dns)\n# Selected: {name}\n" + "".join(
        f"nameserver {s}\n" for s in servers
    )

    try:
        target.write_text(body, encoding="utf-8")
        print(f"Successfully switched DNS to: {name}")
        print(f"Nameservers: {', '.join(servers)}")
        print(f"Written to: {target}")
        return 0
    except Exception as e:
        print(f"Error updating DNS: {e}")
        return 1


# ==========================================================================
#  5) show-ip  (from show_ip.py)
# ==========================================================================


def _public_ip_urllib() -> str:
    """Public IP via stdlib urllib (mirrors pynet.py's behavior)."""
    ip = get_public_ip()
    return ip if ip else "Unable to determine public IP"


def _public_ip_pycurl() -> str:
    """Public IP via pycurl (mirrors show_ip.py's original behavior)."""
    try:
        import pycurl  # type: ignore
    except ImportError:
        return "Error: 'pycurl' not installed. Try --engine urllib."

    buf = io.BytesIO()
    c = pycurl.Curl()
    try:
        c.setopt(c.URL, "https://ipify.org")
        c.setopt(c.WRITEDATA, buf)
        c.setopt(c.TIMEOUT, 15)
        c.setopt(c.FOLLOWLOCATION, True)
        c.perform()
        c.close()
        return buf.getvalue().decode("utf-8").strip()
    except pycurl.error as e:
        return f"Curl error: {e}"


def cmd_show_ip(args: argparse.Namespace) -> int:
    """Print the local and public IP addresses."""
    print(f"Local IP: {get_local_ip()}")
    if args.engine == "pycurl":
        print(f"Public IP: {_public_ip_pycurl()}")
    else:
        print(f"Public IP: {_public_ip_urllib()}")
    return 0


# ==========================================================================
#  6) signal  (from signal_meter.py)
# ==========================================================================


class SignalMeter:
    """
    Read Android Wi-Fi / cellular / airplane-mode signal strength.

    Note: this is Android/Termux-specific — it shells out to `dumpsys` and
    `settings`. On other platforms most readings will be None.
    """

    def __init__(self) -> None:
        self.wifi_strength: Optional[int] = None
        self.cellular_strength: Optional[int] = None
        self.wifi_ssid: Optional[str] = None
        self.cellular_status: Optional[str] = None
        self.is_airplane_mode: bool = False

    # -- readers -----------------------------------------------------------
    def read_wifi(self) -> Optional[int]:
        try:
            r = subprocess.run(
                ["dumpsys", "wifi"], capture_output=True, text=True, timeout=2
            )
            m = re.search(r"mRssi[=:]?\s*(-?\d+)", r.stdout)
            s = re.search(r"ssid[=:]?\s*([\"']?)([^\"']*?)\1", r.stdout)
            if m:
                self.wifi_strength = int(m.group(1))
            if s:
                self.wifi_ssid = s.group(2) or "Hidden"
        except Exception:
            self.wifi_strength = None
        return self.wifi_strength

    def read_cellular(self) -> Optional[int]:
        try:
            r = subprocess.run(
                ["dumpsys", "telephony.registry"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            fs = re.search(r"mSignalStrength[=:]?\s*(\d+)", r.stdout)
            gs = re.search(r"mDataConnectionState[=:]?\s*(\d+)", r.stdout)
            if fs:
                v = int(fs.group(1))
                if 0 <= v <= 31:
                    self.cellular_strength = 2 * v - 113
            if gs:
                state = int(gs.group(1))
                self.cellular_status = {
                    0: "Disconnected",
                    1: "Connecting",
                    2: "Connected",
                    3: "Suspended",
                }.get(state, "Unknown")
        except Exception:
            self.cellular_strength = None
        return self.cellular_strength

    def read_airplane(self) -> bool:
        try:
            r = subprocess.run(
                ["settings", "get", "global", "airplane_mode_on"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            self.is_airplane_mode = r.stdout.strip() == "1"
        except Exception:
            self.is_airplane_mode = False
        return self.is_airplane_mode

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def strength_to_bars(
        strength: Optional[int], top: int = -30, bottom: int = -120
    ) -> Tuple[str, int]:
        """Return (bar string, percentage) — same formula as the original."""
        if strength is None:
            return ("N/A", 0)
        clamped = max(bottom, min(top, strength))
        pct = (clamped - bottom) / (top - bottom) * 40
        bars = int(pct / 100 * 5)
        bars = max(0, min(5, bars))
        return (f"{'█' * bars}{'░' * (5 - bars)}", int(pct))

    def update(self) -> None:
        self.read_wifi()
        self.read_cellular()
        self.read_airplane()


def cmd_signal(args: argparse.Namespace) -> int:
    """Live-updating signal-strength monitor (Android only)."""
    try:
        from rich.align import Align  # type: ignore
        from rich.console import Console  # type: ignore
        from rich.panel import Panel  # type: ignore
    except ImportError:
        print("Error: 'rich' is required for the signal command. `pip install rich`")
        return 2

    console = Console()
    meter = SignalMeter()

    def render_once() -> None:
        os.system("clear")
        console.print(
            Panel(
                Align.center("[bold cyan]📡 SIGNAL STRENGTH MONITOR[/bold cyan]"),
                border_style="cyan",
            )
        )
        if meter.is_airplane_mode:
            console.print("[bold red]✈️  AIRPLANE MODE ENABLED[/bold red]\n")

        console.print("[bold yellow]📶 WiFi Signal[/bold yellow]")
        if meter.wifi_strength is not None:
            bars, pct = meter.strength_to_bars(meter.wifi_strength)
            console.print(f"  SSID: {meter.wifi_ssid or 'Not Connected'}")
            console.print(f"  Signal: {bars} {pct}%")
            console.print(f"  Strength: {meter.wifi_strength} dBm\n")
        else:
            console.print("  [dim]No WiFi data available[/dim]\n")

        console.print("[bold green]📱 Cellular Signal[/bold green]")
        if meter.cellular_strength is not None:
            bars, pct = meter.strength_to_bars(
                meter.cellular_strength, top=-25, bottom=-120
            )
            console.print(f"  Status: {meter.cellular_status}")
            console.print(f"  Signal: {bars} {pct}%")
            console.print(f"  Strength: {meter.cellular_strength} dBm\n")
        else:
            console.print("  [dim]No cellular data available[/dim]\n")

        console.print(f"[dim]Updated: {datetime.now().strftime('%H:%M:%S')}[/dim]")
        console.print("[dim]Press Ctrl+C to exit[/dim]")

    try:
        while True:
            meter.update()
            render_once()
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Exiting...[/bold yellow]")
        os.system("clear")
    return 0


# ==========================================================================
#  CLI
# ==========================================================================


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="merged_net_tools.py",
        description="Unified network toolkit (proxies, IP, ping, DNS, signal).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Original-script mapping:\n"
            "  proxy_tester.py  ->  proxy-test\n"
            "  pynet.py         ->  net-info\n"
            "  pyng.py          ->  ping\n"
            "  set_dns.py       ->  set-dns\n"
            "  show_ip.py       ->  show-ip\n"
            "  signal_meter.py  ->  signal\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- proxy-test ------------------------------------------------------
    p_proxy = sub.add_parser("proxy-test", help="Test HTTP proxies concurrently")
    p_proxy.add_argument(
        "-f",
        "--file",
        default="proxies.txt",
        help="Path to proxies file (one per line). Default: proxies.txt",
    )
    p_proxy.add_argument(
        "-w",
        "--workers",
        type=int,
        default=5,
        help="Number of concurrent workers. Default: 5",
    )
    p_proxy.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=5.0,
        help="Per-request timeout in seconds. Default: 5",
    )
    p_proxy.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay between requests in each worker (s). Default: 0.5",
    )
    p_proxy.add_argument(
        "-o",
        "--output",
        help="Save valid proxies to this file (skips the interactive prompt)",
    )
    p_proxy.set_defaults(func=cmd_proxy_test)

    # --- net-info --------------------------------------------------------
    p_net = sub.add_parser(
        "net-info", help="Show public IP, local IP, DNS; run speed test"
    )
    p_net.add_argument(
        "--no-speedtest",
        action="store_true",
        help="Skip the download/upload speed test",
    )
    p_net.add_argument(
        "--download-url",
        default="http://speedtest.tele2.net/5MB.zip",
        help="URL used for the download speed test",
    )
    p_net.add_argument(
        "--upload-url",
        default="http://httpbin.org/post",
        help="URL used for the upload speed test",
    )
    p_net.add_argument(
        "--dns-path",
        default="/data/data/com.termux/files/usr/etc/resolv.conf",
        help="Path to the resolv.conf-style file to read DNS servers from",
    )
    p_net.set_defaults(func=cmd_net_info)

    # --- ping ------------------------------------------------------------
    p_ping = sub.add_parser("ping", help="Ping a host and parse the results")
    p_ping.add_argument("host", help="Hostname or IP address to ping")
    p_ping.add_argument(
        "-c",
        "--count",
        type=int,
        default=4,
        help="Number of ping requests (default: 4)",
    )
    p_ping.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=4,
        help="Timeout per request in seconds (default: 4)",
    )
    p_ping.add_argument(
        "-s",
        "--size",
        type=int,
        default=56,
        help="ICMP payload size in bytes (default: 56)",
    )
    p_ping.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Quiet mode — print only final statistics",
    )
    p_ping.set_defaults(func=cmd_ping)

    # --- set-dns ---------------------------------------------------------
    p_dns = sub.add_parser("set-dns", help="Switch DNS to a public provider")
    p_dns.add_argument(
        "-n", "--name", help="Provider name (see --list). Omit for random choice."
    )
    p_dns.add_argument(
        "--list", action="store_true", help="List available DNS providers and exit"
    )
    p_dns.add_argument(
        "--target",
        default="~/.resolv.conf",
        help="Output resolv.conf path. Default: ~/.resolv.conf",
    )
    p_dns.set_defaults(func=cmd_set_dns)

    # --- show-ip ---------------------------------------------------------
    p_ip = sub.add_parser("show-ip", help="Show local and public IP")
    p_ip.add_argument(
        "--engine",
        choices=("urllib", "pycurl"),
        default="urllib",
        help="HTTP backend for the public-IP lookup (default: urllib)",
    )
    p_ip.set_defaults(func=cmd_show_ip)

    # --- signal ----------------------------------------------------------
    p_sig = sub.add_parser("signal", help="Monitor Wi-Fi/cellular signal (Android)")
    p_sig.add_argument(
        "--interval",
        type=float,
        default=1.5,
        help="Refresh interval in seconds (default: 1.5)",
    )
    p_sig.add_argument(
        "--once", action="store_true", help="Print a single snapshot and exit"
    )
    p_sig.set_defaults(func=cmd_signal)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point: parse args and dispatch to the selected subcommand."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
