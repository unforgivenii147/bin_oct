#!/data/data/com.termux/files/home/.local/bin/python
import argparse
import os
import subprocess
import sys
from pathlib import Path

try:
    from dh import MIME2EXT, SHEBANG_MAP
except ImportError:
    print(
        "Error: Could not import from dh module. Please ensure dh.py exists with MIME2EXT and SHEBANG_MAP.",
        file=sys.stderr,
    )
    sys.exit(1)


def detect_mime(path: Path) -> str:
    try:
        out = subprocess.check_output(
            ["file", "-b", "--mime", str(path)], text=True
        ).strip()
        return out.split(";", 1)[0].strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
        print(f"Error detecting MIME for {path}: {e}", file=sys.stderr)
        return ""


def detect_shebang(path: Path) -> str | None:
    try:
        with open(path, "rb") as f:
            first_line = f.readline()
            if not first_line.startswith(b"#!"):
                return None
            shebang = first_line.decode("utf-8", errors="ignore").strip()
            parts = shebang.split()
            if len(parts) < 2:
                return None
            interpreter = parts[1]
            if "env" in interpreter:
                if len(parts) >= 3:
                    interpreter = parts[2]
                else:
                    return None
            interpreter_name = os.path.basename(interpreter)
            for key in SHEBANG_MAP:
                if key in interpreter_name or interpreter_name in key:
                    return SHEBANG_MAP[key].lstrip(".")
            return None
    except (OSError, UnicodeDecodeError) as e:
        print(f"Error reading shebang from {path}: {e}", file=sys.stderr)
        return None


def desired_ext_for_mime(mime: str) -> str | None:
    v = MIME2EXT.get(mime)
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    if not v:
        return None
    return str(v).lstrip(".")


def rename_by_shebang(path: Path) -> str | None:
    return detect_shebang(path)


def get_desired_extension(path: Path) -> tuple[str | None, str]:
    mime = detect_mime(path)
    if mime:
        ext = desired_ext_for_mime(mime)
        if ext is not None:
            return ext, "mime"
    if not path.suffix or path.suffix == "":
        ext = rename_by_shebang(path)
        if ext is not None:
            return ext, "shebang"
    return None, "none"


def main():
    parser = argparse.ArgumentParser(
        description="Rename files based on their detected MIME type or shebang",
        epilog="Without --apply, this runs in dry-run mode (only shows what would be renamed).",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Actually apply the renames (dry run by default)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed output including MIME type and detection source",
    )
    args = parser.parse_args()
    root = Path(args.directory).resolve()
    if not root.is_dir():
        print(f"Error: {root} is not a directory", file=sys.stderr)
        sys.exit(1)
    print(f"{'APPLYING' if args.apply else 'DRY RUN'} - Scanning: {root}")
    print("-" * 60)
    renamed_count = 0
    skipped_count = 0
    no_mime_count = 0
    no_ext_count = 0
    shebang_count = 0
    mime_count = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        ext, source = get_desired_extension(path)
        if ext is None:
            no_ext_count += 1
            continue
        current_suffix = path.suffix.lstrip(".").lower()
        if current_suffix == ext.lower():
            continue
        new_path = path.with_suffix("." + ext)
        if new_path.exists():
            print(f"SKIP  {path} -> {new_path} (target exists)")
            skipped_count += 1
            continue
        if source == "shebang":
            shebang_count += 1
        elif source == "mime":
            mime_count += 1
        if args.verbose:
            print(f"REN   {path} -> {new_path}  [{source}: {ext}]")
        else:
            print(f"REN   {path} -> {new_path}")
        if args.apply:
            if new_path.suffix == ".txt" and path.suffix in {".js", ".css"}:
                continue
            try:
                path.rename(new_path)
                renamed_count += 1
            except OSError as e:
                print(f"ERROR: Failed to rename {path}: {e}", file=sys.stderr)
        else:
            renamed_count += 1
    print("-" * 60)
    print(f"Summary ({'APPLIED' if args.apply else 'DRY RUN'}):")
    print(f"  Would rename / Renamed: {renamed_count}")
    print(f"  Skipped (target exists): {skipped_count}")
    print(f"  No extension found: {no_ext_count}")
    print(f"  Detection sources:")
    print(f"    - MIME type: {mime_count}")
    print(f"    - Shebang: {shebang_count}")
    print(f"  Total files processed: {renamed_count + skipped_count + no_ext_count}")


if __name__ == "__main__":
    main()
