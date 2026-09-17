#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess
from pathlib import Path


def save_installed_packages(output_file: str = "installed.txt") -> None:
    try:
        result = subprocess.run(
            ["dpkg-query", "-f", "${binary:Package}\n", "-W"],
            capture_output=True,
            text=True,
            check=True,
        )
        installed_packages = result.stdout.splitlines()
        Path(output_file).write_text("\n".join(installed_packages), encoding="utf-8")
        print(f"Installed package names saved to '{output_file}'")
    except FileNotFoundError:
        print(
            "Error: dpkg-query command not found. Are you running this script on a Debian-based system?"
        )
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to retrieve installed packages. {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    save_installed_packages()
