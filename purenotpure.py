#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import contextlib
import sys
import sysconfig
from importlib import metadata
from pathlib import Path


def is_in_system_site_packages(dist: metadata.Distribution) -> bool:
    try:
        files = list(dist.files or [])
        if not files:
            return False
        loc = Path(dist.locate_file(files[0])).resolve()
        site_paths = set()
        for key in ("purelib", "platlib"):
            p = sysconfig.get_paths().get(key)
            if p:
                site_paths.add(Path(p).resolve())
        for p in sys.path:
            if p and "site-packages" in p:
                with contextlib.suppress(Exception):
                    site_paths.add(Path(p).resolve())
        return any(str(loc).startswith(str(sp)) for sp in site_paths)
    except Exception:
        return False


def dist_has_c_extensions(dist: metadata.Distribution) -> bool:
    try:
        for f in dist.files or []:
            name = str(f).lower()
            if name.endswith(".so") or ".so." in name:
                return True
        return False
    except Exception:
        return False


def main() -> int:
    pure = []
    notpure = []
    for dist in metadata.distributions():
        name = (
            dist.metadata.get("Name")
            or dist.metadata.get("Summary")
            or dist.metadata.get("name")
        )
        if not name:
            continue
        if not is_in_system_site_packages(dist):
            continue
        if dist_has_c_extensions(dist):
            notpure.append(name)
        else:
            pure.append(name)
    pure = sorted(set(pure), key=str.lower)
    notpure = sorted(set(notpure), key=str.lower)
    Path("pure.txt").write_text(
        "\n".join(pure) + ("\n" if pure else ""), encoding="utf-8"
    )
    Path("notpure.txt").write_text(
        "\n".join(notpure) + ("\n" if notpure else ""), encoding="utf-8"
    )
    print(f"Wrote {len(pure)} pure-python packages to pure.txt")
    print(f"Wrote {len(notpure)} packages with C extensions to notpure.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
