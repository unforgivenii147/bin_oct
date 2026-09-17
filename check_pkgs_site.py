#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import site
import sys
from importlib.metadata import distributions
from pathlib import Path


def get_packages_in_dir(dir_path):
    packages = {}
    dir_str = str(dir_path)
    try:
        for dist in distributions():
            try:
                location = None
                if hasattr(dist, "_path"):
                    location = str(dist._path)
                elif hasattr(dist, "files") and dist.files:
                    for file in dist.files:
                        try:
                            loc = str(file.locate())
                            if dir_str in loc:
                                location = loc
                                break
                        except:
                            continue
                if location and dir_str in location:
                    name = dist.metadata.get("Name", "Unknown")
                    version = dist.metadata.get("Version", "Unknown")
                    packages[name] = version
            except:
                continue
    except Exception as e:
        print(f"Error scanning {dir_path}: {e}")
    return packages


def main():
    user_dir = Path(site.getusersitepackages())
    system_dirs = []
    for path in sys.path:
        if "site-packages" in path or "dist-packages" in path:
            p = Path(path)
            if p.exists() and not str(p).startswith(str(Path.home())):
                system_dirs.append(p)
    termux_lib = Path("/data/data/com.termux/files/usr/lib")
    if termux_lib.exists():
        for py_dir in termux_lib.glob("python*/site-packages"):
            if py_dir.exists() and py_dir not in system_dirs:
                system_dirs.append(py_dir)
    system_pkgs = {}
    for sys_dir in system_dirs:
        system_pkgs.update(get_packages_in_dir(sys_dir))
    user_pkgs = get_packages_in_dir(user_dir) if user_dir.exists() else {}
    duplicates = set(user_pkgs.keys()) & set(system_pkgs.keys())
    print(f"System packages: {len(system_pkgs)}")
    print(f"User packages: {len(user_pkgs)}")
    print(f"\nDuplicate packages: {len(duplicates)}")
    if duplicates:
        print("\nDuplicate packages found:")
        for pkg in sorted(duplicates):
            print(
                f"  {pkg}: system={system_pkgs.get(pkg, '?')}, user={user_pkgs.get(pkg, '?')}"
            )
    else:
        print("\n✅ No duplicate packages found!")


if __name__ == "__main__":
    raise SystemExit(main())
