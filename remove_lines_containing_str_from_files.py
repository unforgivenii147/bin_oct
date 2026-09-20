#!/data/data/com.termux/files/home/.local/bin/python
import sys
from pathlib import Path
from multiprocessing import Pool
from dh import get_nobinary, gsz, fsz


def clean_text(text, strtofind):
    kept = []
    removed = 0
    for line in text.splitlines():
        if any(s in line for s in strtofind):
            removed += 1
        else:
            kept.append(line)
    return "\n".join(kept), removed


def clean_file(path, strtofind):
    try:
        original = Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return path, 0, 0
    cleaned, removed = clean_text(original, strtofind)
    if cleaned != original:
        Path(path).write_text(cleaned, encoding="utf-8")
    return path, removed, len(original) - len(cleaned)


def main():
    args = sys.argv[1:]
    if not args:
        print(f"usage: {sys.argv[0]} [file ...] <search_string>")
        return 1

    strtofind = [args[-1]]
    file_args = args[:-1]
    files = [Path(a) for a in file_args] if file_args else get_nobinary(Path.cwd())

    root = Path.cwd()
    isz = gsz(root)

    total_removed = 0

    if len(files) == 1:
        path, removed, _ = clean_file(files[0], strtofind)
        total_removed += removed
        print(f"{path}: {removed} line(s) removed")
    else:
        pool = Pool(8)
        results = [pool.apply_async(clean_file, (f, strtofind)) for f in files]
        pool.close()
        pool.join()
        for r in results:
            path, removed, _ = r.get()
            if removed:
                print(f"{path}: {removed} line(s) removed")
            total_removed += removed

    esz = gsz(root)
    print(f"total lines removed : {total_removed}")
    print(f"space freed : {fsz(isz - esz)}")


if __name__ == "__main__":
    raise SystemExit(main())
