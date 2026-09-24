#!/data/data/com.termux/files/home/.local/bin/python
import os, subprocess, sys, time
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <pkg_list_file>")
        sys.exit(1)

    pkg_file = Path(sys.argv[1]).expanduser()
    if not pkg_file.is_file():
        print(f"File not found: {pkg_file}")
        sys.exit(1)

    pkgs = [l.strip() for l in pkg_file.read_text().splitlines() if l.strip()]

    failed_file = Path.home() / "reinstall_pip_failed.txt"
    failed_file.write_text("")

    # Termux: pin the interpreter so we always hit the Termux python,
    # not some other python that leaked into PATH.
    py = sys.executable  # e.g. /data/data/com.termux/files/usr/bin/python3.12

    print(f"Total packages to reinstall: {len(pkgs)}")
    print(f"Interpreter: {py}\n")

    # Termux env tweak: make sure build tools are visible if any pkg
    # needs to compile from source on 32-bit ARM.
    env = os.environ.copy()
    env.setdefault("CFLAGS", "-O2")

    for i, pkg in enumerate(pkgs, 1):
        print(f"[{i}/{len(pkgs)}] Reinstalling {pkg} ...", flush=True)
        r = subprocess.run(
            [
                py,
                "-m",
                "pip",
                "install",
                "--force-reinstall",
                "--no-input",
                "--disable-pip-version-check",
                "--root-user-action=ignore",
                pkg,
            ],
            env=env,
        )
        if r.returncode != 0:
            print(f"  !! Failed: {pkg} (exit {r.returncode})")
            with failed_file.open("a") as f:
                f.write(pkg + "\n")
        else:
            print("  ok")
        time.sleep(0.2)

    print(f"\nDone. Failures logged to {failed_file}")


if __name__ == "__main__":
    main()
