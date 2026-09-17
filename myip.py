#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

BLACKLIST_IFACES_PREFIX = "lo"
INTERFACE_PRIORITY = ["wlan", "eth", "rmnet", "tun", "ppp"]
DEBUG_LEVEL = logging.WARNING
IP_BIN = Path("/system/bin/ip")
GEOIP_URL = "http://ip-api.com/json/{}"
logging.basicConfig(level=DEBUG_LEVEL, format="%(levelname)s: %(message)s")


@dataclass
class NetworkInterface:
    name: str
    ip: str
    is_up: bool = False


@dataclass
class LocationInfo:
    country: str = ""
    region: str = ""
    city: str = ""
    isp: str = ""
    lat: float = 0.0
    lon: float = 0.0

    def display(self) -> str:
        if not self.country:
            return "Location: Unknown"
        parts = [self.city, self.region, self.country]
        location = ", ".join(p for p in parts if p)
        return f"Location: {location}"


class IPAddressManager:
    def __init__(self):
        self.interfaces: dict[str, str] = {}

    def parse_ip_addr_output(self, output: str) -> dict[str, str]:
        ip_map = {}
        current_iface = None
        current_is_up = False
        for line in output.split("\n"):
            iface_match = re.match(r"^\d+:\s+([^:@]+)(?:@[^:]+)?:", line)
            if iface_match:
                current_iface = iface_match.group(1)
                current_is_up = "UP" in line
                continue
            if current_iface and current_is_up:
                ip_match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)/\d+", line)
                if ip_match:
                    ip_map[current_iface] = ip_match.group(1)
        return ip_map

    def get_interfaces(self, specific_iface: str | None = None) -> dict[str, str]:
        cmd = [str(IP_BIN), "addr", "show"]
        if specific_iface:
            cmd.extend(["dev", specific_iface])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return self.parse_ip_addr_output(result.stdout)
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to get interfaces: {e}")
            return {}

    def get_primary_ip(self) -> str | None:
        interfaces = self.get_interfaces()
        filtered = {
            k: v
            for k, v in interfaces.items()
            if not k.startswith(BLACKLIST_IFACES_PREFIX)
        }
        for prefix in INTERFACE_PRIORITY:
            for iface in sorted(filtered.keys()):
                if iface.startswith(prefix):
                    return filtered[iface]
        return next(iter(filtered.values()), None)

    def get_all_ips(self) -> list[str]:
        interfaces = self.get_interfaces()
        filtered = {
            k: v
            for k, v in interfaces.items()
            if not k.startswith(BLACKLIST_IFACES_PREFIX)
        }
        ips = []
        for prefix in INTERFACE_PRIORITY:
            for iface in sorted(filtered.keys()):
                if iface.startswith(prefix):
                    ips.append(filtered[iface])
        for iface in sorted(filtered.keys()):
            if filtered[iface] not in ips:
                ips.append(filtered[iface])
        return ips


class GeoIPLookup:
    @staticmethod
    def lookup(ip: str) -> LocationInfo:
        if not ip or ip.startswith(("10.", "192.168.", "172.")):
            return LocationInfo()
        try:
            url = GEOIP_URL.format(ip)
            with urllib.request.urlopen(url, timeout=5) as response:
                data = json.loads(response.read().decode())
            if data.get("status") == "success":
                return LocationInfo(
                    country=data.get("country", ""),
                    region=data.get("regionName", ""),
                    city=data.get("city", ""),
                    isp=data.get("isp", ""),
                    lat=data.get("lat", 0.0),
                    lon=data.get("lon", 0.0),
                )
        except Exception as e:
            logging.debug(f"Geolocation failed for {ip}: {e}")
        return LocationInfo()


class MyIPApp:
    def __init__(self):
        self.ip_manager = IPAddressManager()
        self.geo_lookup = GeoIPLookup()

    def parse_args(self, args: list[str]) -> argparse.Namespace:
        parser = argparse.ArgumentParser(
            description="Display IP and location information (Termux)",
            epilog="Examples:\n"
            "  myip              Show primary IP\n"
            "  myip --all        Show all IPs\n"
            "  myip wlan0        Show IP for specific interface\n"
            "  myip --location   Show location info\n",
        )
        parser.add_argument("--all", action="store_true", help="Show all IP addresses")
        parser.add_argument(
            "--location", "-l", action="store_true", help="Show geolocation information"
        )
        parser.add_argument(
            "--verbose", "-v", action="store_true", help="Show verbose output"
        )
        parser.add_argument(
            "interface", nargs="?", help="Show IP for specific interface"
        )
        return parser.parse_args(args)

    def display_ip_info(self, ip: str, show_location: bool, interface: str = ""):
        iface_str = f" [{interface}]" if interface else ""
        print(f"IP: {ip}{iface_str}")
        if show_location:
            location = self.geo_lookup.lookup(ip)
            print(location.display())
            if location.isp:
                print(f"ISP: {location.isp}")

    def run(self):
        config = self.parse_args(sys.argv[1:])
        if config.verbose:
            logging.getLogger().setLevel(logging.DEBUG)
        if config.interface:
            interfaces = self.ip_manager.get_interfaces(config.interface)
            if config.interface in interfaces:
                self.display_ip_info(
                    interfaces[config.interface], config.location, config.interface
                )
            else:
                print(f"Error: Interface '{config.interface}' not found or has no IP")
                sys.exit(1)
        elif config.all:
            ips = self.ip_manager.get_all_ips()
            if not ips:
                print("No IP addresses found")
                sys.exit(1)
            for i, ip in enumerate(ips):
                if i > 0:
                    print()
                self.display_ip_info(ip, config.location)
        else:
            primary_ip = self.ip_manager.get_primary_ip()
            if primary_ip:
                self.display_ip_info(primary_ip, config.location)
            else:
                print("No active network interface found")
                sys.exit(1)


def main():
    app = MyIPApp()
    app.run()


if __name__ == "__main__":
    main()
