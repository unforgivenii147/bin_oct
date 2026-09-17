#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from pathlib import Path

import xxhash

CACHE_PATH = Path.home() / ".cache" / "dups_cache.json"
DUPS_DIR = Path.home() / ".cache" / "dups"
MANIFEST_PATH = DUPS_DIR / "manifest.json"
READ_CHUNK = 1024 * 8


def load_json(path: Path):
    try:
        with Path(path).open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def xxh64_of_path(p: Path) -> str:
    h = xxhash.xxh64()
    with p.open("rb") as f:
        while True:
            chunk = f.read(READ_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def build_groups(root: Path, cache: dict):
    groups = defaultdict(list)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.parts:
            continue
        if path.is_symlink():
            continue
        try:
            st = path.stat()
        except Exception:
            continue
        key = str(path)
        size = st.st_size
        mtime = st.st_mtime
        cached = cache.get(key)
        if cached and cached.get("size") == size and cached.get("mtime") == mtime:
            h = cached["hash"]
        else:
            try:
                h = xxh64_of_path(path)
            except Exception:
                continue
            cache[key] = {"size": size, "mtime": mtime, "hash": h}
        groups[h].append(path)
    return groups


def dedupe(root: Path, dry_run=False, force=False) -> None:
    cache = load_json(CACHE_PATH) if CACHE_PATH.exists() else {}
    groups = build_groups(root, cache)
    save_json(CACHE_PATH, cache)
    DUPS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_json(MANIFEST_PATH) if MANIFEST_PATH.exists() else {}
    changed = False
    for h, paths in groups.items():
        if len(paths) < 2:
            continue
        paths_sorted = sorted(paths, key=str)
        original = paths_sorted[0]
        stored_name = f"{h}__{original.name}"
        stored_path = DUPS_DIR / stored_name
        if not stored_path.exists():
            if dry_run:
                print(f"[DRY] move: {original} -> {stored_path}")
            else:
                stored_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(original), str(stored_path))
                print(f"moved: {original} -> {stored_path}")
            changed = True
        elif original.exists():
            if dry_run:
                print(f"[DRY] remove original file before symlink: {original}")
            else:
                original.unlink()
                print(f"removed original file: {original}")
        for p in paths_sorted[1:]:
            if p.is_symlink():
                continue
            if dry_run:
                print(f"[DRY] symlink: {p} -> {stored_path.resolve()}")
            else:
                if p.exists():
                    try:
                        p.unlink()
                    except Exception as e:
                        print(f"warning: could not remove {p}: {e}")
                        continue
                p.parent.mkdir(parents=True, exist_ok=True)
                Path(str(p)).symlink_to(str(stored_path.resolve()))
                print(f"symlinked: {p} -> {stored_path.resolve()}")
            changed = True
        manifest[str(stored_path)] = {
            "hash": h,
            "originals": [str(p) for p in paths_sorted],
        }
    if not dry_run and changed:
        save_json(MANIFEST_PATH, manifest)
        save_json(CACHE_PATH, cache)
        print(f"manifest written to {MANIFEST_PATH}")
    elif dry_run:
        print("dry-run complete; no changes written.")


def restore(dry_run: bool = False) -> None:
    if not MANIFEST_PATH.exists():
        print("No manifest found at ~/dups/manifest.json")
        return
    manifest = load_json(MANIFEST_PATH)
    for stored_str, info in manifest.items():
        stored = Path(stored_str)
        if not stored.exists():
            print(f"stored file missing: {stored}")
            continue
        originals = [Path(p) for p in info.get("originals", [])]
        for orig in originals:
            if orig.exists() and not orig.is_symlink():
                print(f"skipping restore for {orig} (exists and not a symlink)")
                continue
            if orig.is_symlink():
                try:
                    target = Path(Path(orig).readlink())
                except Exception:
                    print(f"skipping {orig} (broken symlink)")
                    continue
                if target.resolve() != stored.resolve():
                    print(f"skipping {orig} (symlink points elsewhere)")
                    continue
            if dry_run:
                print(f"[DRY] restore {stored} -> {orig}")
            else:
                if orig.exists() or orig.is_symlink():
                    try:
                        orig.unlink()
                    except Exception as e:
                        print(f"warning: could not remove {orig}: {e}")
                        continue
                orig.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(stored, orig)
                print(f"restored: {orig}")
        if dry_run:
            print(f"[DRY] remove stored file {stored}")
        else:
            try:
                stored.unlink()
                print(f"removed stored file: {stored}")
            except Exception as e:
                print(f"warning: could not remove stored file {stored}: {e}")
    if not dry_run:
        try:
            MANIFEST_PATH.unlink()
            print(f"removed manifest: {MANIFEST_PATH}")
        except Exception:
            pass


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Deduplicate files by moving one copy to ~/dups and symlinking duplicates using xxhash."
    )
    ap.add_argument(
        "path", nargs="?", default=".", help="Path to scan (default current directory)"
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Show actions without making changes"
    )
    ap.add_argument(
        "--restore",
        action="store_true",
        help="Restore files from ~/dups using manifest",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Force overwrite behavior (not used for safety here)",
    )
    args = ap.parse_args()
    root = Path(args.path).resolve()
    if args.restore:
        restore(dry_run=args.dry_run)
    else:
        dedupe(root, dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
