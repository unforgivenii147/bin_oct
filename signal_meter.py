#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import re
import subprocess
import time
from datetime import datetime

from rich.align import Align
from rich.console import Console
from rich.panel import Panel

console = Console()


class SignalMonitor:
    def __init__(self) -> None:
        self.wifi_strength = None
        self.cellular_strength = None
        self.wifi_ssid = None
        self.cellular_status = None
        self.is_airplane_mode = False

    def get_wifi_signal(self):
        try:
            result = subprocess.run(
                ["dumpsys", "wifi"], capture_output=True, text=True, timeout=2
            )
            rssi_match = re.search(r"mRssi[=:]?\s*(-?\d+)", result.stdout)
            ssid_match = re.search(r"ssid[=:]?\s*([\"\']?)([^\"\']*?)\1", result.stdout)
            if rssi_match:
                self.wifi_strength = int(rssi_match.group(1))
            if ssid_match:
                self.wifi_ssid = ssid_match.group(2) or "Hidden"
            return self.wifi_strength
        except Exception:
            self.wifi_strength = None
            return None

    def get_cellular_signal(self):
        try:
            result = subprocess.run(
                ["dumpsys", "telephony.registry"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            signal_match = re.search(r"mSignalStrength[=:]?\s*(\d+)", result.stdout)
            state_match = re.search(r"mDataConnectionState[=:]?\s*(\d+)", result.stdout)
            if signal_match:
                asu = int(signal_match.group(1))
                if 0 <= asu <= 31:
                    self.cellular_strength = 2 * asu - 113
                else:
                    self.cellular_strength = None
            if state_match:
                state_num = int(state_match.group(1))
                states = {
                    (0): "Disconnected",
                    (1): "Connecting",
                    (2): "Connected",
                    (3): "Suspended",
                }
                self.cellular_status = states.get(state_num, "Unknown")
            return self.cellular_strength
        except Exception:
            self.cellular_strength = None
            return None

    def strength_to_bars(self, strength_db, max_db=-30, min_db=-120) -> tuple[str, int]:
        if strength_db is None:
            return "N/A", 0
        clamped = max(min_db, min(max_db, strength_db))
        percentage = (clamped - min_db) / (max_db - min_db) * 40
        bars = int(percentage / 100 * 5)
        bars = max(0, min(5, bars))
        return f"{'█' * bars}{'░' * (5 - bars)}", int(percentage)

    def get_airplane_mode(self) -> bool:
        try:
            result = subprocess.run(
                ["settings", "get", "global", "airplane_mode_on"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            self.is_airplane_mode = result.stdout.strip() == "1"
            return self.is_airplane_mode
        except:
            return False

    def update(self) -> None:
        self.get_wifi_signal()
        self.get_cellular_signal()
        self.get_airplane_mode()

    def render(self) -> None:
        os.system("clear")
        header = Panel(
            Align.center("[bold cyan]📡 SIGNAL STRENGTH MONITOR[/bold cyan]"),
            border_style="cyan",
        )
        console.print(header)
        if self.is_airplane_mode:
            console.print("[bold red]✈️  AIRPLANE MODE ENABLED[/bold red]\n")
        console.print("[bold yellow]📶 WiFi Signal[/bold yellow]")
        if self.wifi_strength is not None:
            bars, percent = self.strength_to_bars(self.wifi_strength)
            console.print(f"  SSID: {self.wifi_ssid or 'Not Connected'}")
            console.print(f"  Signal: {bars} {percent}%")
            console.print(f"  Strength: {self.wifi_strength} dBm\n")
        else:
            console.print("  [dim]No WiFi data available[/dim]\n")
        console.print("[bold green]📱 Cellular Signal[/bold green]")
        if self.cellular_strength is not None:
            bars, percent = self.strength_to_bars(
                self.cellular_strength, max_db=-25, min_db=-120
            )
            console.print(f"  Status: {self.cellular_status}")
            console.print(f"  Signal: {bars} {percent}%")
            console.print(f"  Strength: {self.cellular_strength} dBm\n")
        else:
            console.print("  [dim]No cellular data available[/dim]\n")
        console.print(f"[dim]Updated: {datetime.now().strftime('%H:%M:%S')}[/dim]")
        console.print("[dim]Press Ctrl+C to exit[/dim]")


def main() -> None:
    monitor = SignalMonitor()
    try:
        while True:
            monitor.update()
            monitor.render()
            time.sleep(1.5)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Exiting...[/bold yellow]")
        os.system("clear")


if __name__ == "__main__":
    raise SystemExit(main())
