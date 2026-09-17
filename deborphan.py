#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
from pathlib import Path

STATUS_PATH = Path("/var/lib/dpkg/status")


def parse_installed_packages(status_text: str):
    installed = {}
    blocks = re.split(r"\n\s*\n", status_text.strip(), flags=re.MULTILINE)
    for b in blocks:
        pkg = re.search(r"^Package:\s*(.+)$", b, flags=re.MULTILINE)
        status = re.search(r"^Status:\s*(.+)$", b, flags=re.MULTILINE)
        provides = re.findall(r"^Provides:\s*(.+)$", b, flags=re.MULTILINE)
        depends = re.findall(r"^Depends:\s*(.+)$", b, flags=re.MULTILINE)
        if not pkg or not status:
            continue
        pkg_name = pkg.group(1).strip()
        status_line = status.group(1).strip()
        if "install ok installed" not in status_line:
            continue
        deps = []
        for d in depends:
            for part in d.split(","):
                part = part.strip()
                if not part:
                    continue
                alt = part.split("|", 1)[0].strip()
                m = re.match(r"^([A-Za-z0-9+_.:-]+)\s*(?:\(|$)", alt)
                if m:
                    deps.append(m.group(1))
        provs = []
        for p in provides:
            for tok in p.split(","):
                tok = tok.strip()
                if tok:
                    m = re.match(r"^([A-Za-z0-9+_.:-]+)", tok)
                    if m:
                        provs.append(m.group(1))
        installed[pkg_name] = {"depends": deps, "provides": provs}
    return installed


def build_reverse_deps(installed):
    providers = {}
    for pkg, meta in installed.items():
        providers.setdefault(pkg, set()).add(pkg)
        for pr in meta["provides"]:
            providers.setdefault(pr, set()).add(pkg)
    reverse = {pkg: set() for pkg in installed}
    for pkg, meta in installed.items():
        for dep in meta["depends"]:
            for provider_pkg in providers.get(dep, []):
                reverse.setdefault(provider_pkg, set()).add(pkg)
    return reverse


def is_candidate_library(pkg_name: str):
    return pkg_name.startswith("lib")


def find_orphans(installed, reverse):
    orphans = []
    for pkg in installed:
        if not is_candidate_library(pkg):
            continue
        users = reverse.get(pkg, set())
        if not users:
            orphans.append(pkg)
    return sorted(orphans)


def main():
    if not STATUS_PATH.exists():
        raise SystemExit(
            f"Missing {STATUS_PATH}. This script expects a Debian-style dpkg database.\n"
            f"On Termux, you may need a Debian/Ubuntu rootfs that includes /var/lib/dpkg/status."
        )
    status_text = STATUS_PATH.read_text(errors="replace")
    installed = parse_installed_packages(status_text)
    reverse = build_reverse_deps(installed)
    orphans = find_orphans(installed, reverse)
    print("Orphan-ish libraries (no installed package depends on them):")
    for p in orphans:
        print(p)


if __name__ == "__main__":
    raise SystemExit(main())
