#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import sys
import sysconfig
import zipfile
from email.parser import Parser
from pathlib import Path


def prefix_path() -> Path:
    p = os.environ.get("PREFIX")
    if p:
        return Path(p)
    return Path(sysconfig.get_paths()["purelib"])


def site_packages_paths(prefix: Path):
    pyver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates = [prefix / "lib" / pyver / "site-packages"]
    for p in sys.path:
        try:
            ppath = Path(p)
        except Exception:
            continue
        if (prefix in ppath.parents or ppath == prefix) and ppath.exists():
            candidates.append(ppath)
    seen = set()
    out = []
    for c in candidates:
        if c.exists() and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def find_distributions(site_dirs):
    dists = {}
    for sd in site_dirs:
        if not sd.exists():
            continue
        for p in sd.iterdir():
            if p.is_dir() and (
                p.name.endswith(".dist-info") or p.name.endswith(".egg-info")
            ):
                key = p.name.rsplit(".", 1)[0].lower()
                dists[key] = p
    return dists


def parse_metadata_from_distinfo(distinfo_dir):
    md = {}
    for candidate in ("METADATA", "PKG-INFO"):
        p = distinfo_dir / candidate
        if p.exists():
            txt = p.read_text(encoding="utf-8", errors="ignore")
            parsed = Parser().parsestr(txt)
            md["Name"] = parsed.get("Name")
            md["Version"] = parsed.get("Version")
            md["Summary"] = parsed.get("Summary")
            break
    ep = distinfo_dir / "entry_points.txt"
    if ep.exists():
        console = []
        lines = ep.read_text(encoding="utf-8", errors="ignore").splitlines()
        section = None
        for ln in lines:
            ln = ln.strip()
            if ln.startswith("[") and ln.endswith("]"):
                section = ln[1:-1].strip()
                continue
            if section == "console_scripts" and ln and not ln.startswith("#"):
                left = ln.split("=", 1)[0].strip()
                console.append(left)
        md["console_scripts"] = console
    return md


def read_record_list(distinfo_dir):
    rec = distinfo_dir / "RECORD"
    if rec.exists():
        return [
            line.strip().split(",", 1)[0]
            for line in rec.read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip()
        ]
    return None


def find_script_paths(prefix, script_names):
    bin_dir = prefix / "bin"
    out = []
    if not bin_dir.exists():
        return out
    for s in script_names:
        for alt in (s, s + ".py", s + "-script.py", s + ".sh"):
            ap = bin_dir / alt
            if ap.exists():
                out.append(ap)
                break
    return out


def compute_hash_and_size(path) -> tuple[str, str]:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    digest = base64.urlsafe_b64encode(h.digest()).rstrip(b"=").decode("ascii")
    return f"sha256={digest}", str(path.stat().st_size)


def detect_wheel_tags():
    impl = sys.implementation.name
    mj, mn = sys.version_info.major, sys.version_info.minor
    if impl == "cpython":
        py_tag, abi_tag = f"cp{mj}{mn}", f"cp{mj}{mn}"
    else:
        cache = getattr(sys.implementation, "cache_tag", None)
        py_tag, abi_tag = (
            cache.split("-", 1) if cache and "-" in cache else (f"py{mj} ", "none")
        )
    plat = sysconfig.get_platform().replace("-", "_").replace(".", "_")
    return py_tag, abi_tag, plat


def collect_and_build(distinfo_path, prefix: Path, wheel_out_path: Path) -> None:
    base = distinfo_path.parent
    rec_list = read_record_list(distinfo_path)
    if not rec_list:
        print(f"[-] Error: Could not find RECORD for {distinfo_path.name}. Skipping.")
        return
    md = parse_metadata_from_distinfo(distinfo_path)
    dist_name = (md.get("Name") or distinfo_path.name.split("-", 1)[0]).replace(
        "-", "_"
    )
    md.get("Version") or "0.0.0"
    collected_files = []
    missing_files = []
    for rel in rec_list:
        if not rel or rel.endswith("RECORD") or rel.startswith(("..", "/")):
            continue
        src = base / rel
        if not src.exists():
            src = prefix / rel
        if src.exists():
            if src.is_dir():
                for root, _, files in os.walk(src):
                    for fn in files:
                        s_path = Path(root) / fn
                        collected_files.append(
                            (s_path, s_path.relative_to(base).as_posix())
                        )
            else:
                collected_files.append((src, rel))
        else:
            missing_files.append(rel)
    if "console_scripts" in md:
        collected_files.extend(
            (sp, f"bin/{sp.name}")
            for sp in find_script_paths(prefix, md["console_scripts"])
        )
    if missing_files:
        print(f"[!] Error: Missing files for {dist_name}:")
        for m in missing_files:
            print(f"    - {m}")
        print(f"[*] Aborting wheel build for {dist_name}.")
        return
    py_tag, abi_tag, plat_tag = detect_wheel_tags()
    native_exts = {".so", ".pyd", ".dll", ".dylib", ".sl"}
    is_platform = any(s.suffix.lower() in native_exts for s, _ in collected_files)
    wheel_tag = f"{py_tag}-{abi_tag}-{plat_tag}" if is_platform else "py3-none-any"
    wheel_out_path.parent.mkdir(parents=True, exist_ok=True)
    record_lines = []
    with zipfile.ZipFile(wheel_out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for src, rel in collected_files:
            zf.write(src, arcname=rel)
            h, size = compute_hash_and_size(src)
            record_lines.append(f"{rel},{h},{size}")
        wheel_content = f"""Wheel-Version: 1.0
Generator: repack_tool
Root-Is-Purelib: {"false" if is_platform else "true"}
Tag: {wheel_tag}
"""
        zf.writestr(f"{distinfo_path.name}/WHEEL", wheel_content)
        record_lines.extend(
            (f"{distinfo_path.name}/WHEEL,,", f"{distinfo_path.name}/RECORD,,")
        )
        zf.writestr(f"{distinfo_path.name}/RECORD", "\n".join(record_lines) + "\n")
    print(f"[+] Successfully built: {wheel_out_path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Repack packages into .whl files directly."
    )
    parser.add_argument("packages", nargs="*", help="Distribution names to repack.")
    parser.add_argument("-a", "--all", action="store_true", help="Repack all.")
    args = parser.parse_args()
    prefix = prefix_path()
    site_dirs = [Path.cwd(), *site_packages_paths(prefix)]
    dists = find_distributions(site_dirs)
    to_do = []
    if args.all or not args.packages:
        to_do = list(dists.values())
    else:
        for name in args.packages:
            key = name.lower()
            if key in dists:
                to_do.append(dists[key])
    wheel_dir = Path.home() / "tmp" / "wheels"
    print(f"[*] Saving wheels to: {wheel_dir}")
    for distinfo in to_do:
        try:
            md = parse_metadata_from_distinfo(distinfo)
            name = (md.get("Name") or distinfo.name.split("-", 1)[0]).replace("-", "_")
            ver = md.get("Version") or "0"
            _py_tag, _abi_tag, _plat_tag = detect_wheel_tags()
            out_name = f"{name}-{ver}-py3-none-any.whl"
            collect_and_build(distinfo, prefix, wheel_dir / out_name)
        except Exception as e:
            print(f"[!] Critical error repacking {distinfo.name}: {e}")


if __name__ == "__main__":
    raise SystemExit(main())
