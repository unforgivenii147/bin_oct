#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import time


def watch_tor_log(log_path: str = "~/.tor/tor.log") -> None:
    log_path = os.path.expanduser(log_path)
    if not os.path.exists(log_path):
        print(f"Log file not found: {log_path}")
        print("Waiting for file to be created...")
    last_position = 0
    try:
        if os.path.exists(log_path):
            with open(log_path) as f:
                lines = f.readlines()
                print("=== Last 5 lines of Tor log ===")
                for line in lines[-5:]:
                    print(line.rstrip())
                last_position = f.tell()
                f.close()
    except Exception as e:
        print(f"Error reading file: {e}")
    print("\n=== Watching for '100% (done)' ===")
    try:
        while True:
            if not os.path.exists(log_path):
                time.sleep(0.5)
                continue
            with open(log_path) as f:
                f.seek(last_position)
                new_lines = f.readlines()
                last_position = f.tell()
                if new_lines:
                    f.seek(0, os.SEEK_END)
                    file_size = f.tell()
                    f.seek(max(0, file_size - 4096))
                    content = f.read()
                    lines = content.splitlines()
                    print(f"\n--- Update at {time.strftime('%H:%M:%S')} ---")
                    for line in lines[-5:]:
                        print(line)
                    for line in lines[-10:]:
                        if "100%" in line.lower() or "(done)" in line.lower():
                            print("\n✓ Bootstrap complete! Exiting...")
                            return
                time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped by user")
        return


def main() -> None:
    import sys

    log_path = sys.argv[1] if len(sys.argv) > 1 else "~/.tor/tor.log"
    watch_tor_log(log_path)


if __name__ == "__main__":
    raise SystemExit(main())
