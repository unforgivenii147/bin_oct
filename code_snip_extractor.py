#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from collections.abc import Generator
from multiprocessing import Pool
from pathlib import Path


def extract_snippets(path: Path) -> Generator[tuple[int, str], None, None]:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("```"):
            fence_match = re.match(r"^```+(\w*)", lines[i].strip())
            if fence_match:
                start_line = i + 1
                i += 1
                code_lines = []
                while i < len(lines) and not lines[i].strip().startswith("```"):
                    code_lines.append(lines[i])
                    i += 1
                code_text = "\n".join(code_lines).strip()
                if code_text:
                    yield (start_line, code_text)
                i += 1
                continue
        if lines[i].strip().startswith(">>>"):
            start_line = i + 1
            code_lines = []
            while i < len(lines):
                line = lines[i]
                stripped = line.strip()
                if stripped.startswith(">>>"):
                    code_lines.append(stripped[3:].lstrip())
                    i += 1
                elif stripped.startswith("..."):
                    code_lines.append(stripped[3:].lstrip())
                    i += 1
                elif stripped.startswith(">>"):
                    i += 1
                elif stripped == "" or stripped.startswith("#"):
                    i += 1
                    if not stripped.startswith("#"):
                        break
                else:
                    if code_lines and not any(
                        c in stripped for c in ["=", "True", "False", "["]
                    ):
                        break
                    i += 1
            code_text = "\n".join(code_lines).strip()
            if code_text:
                yield (start_line, code_text)
            continue
        i += 1


def process_file(path: Path, output_dir: Path) -> dict:
    rel_path = path.relative_to(path.anchor)
    safe_name = str(rel_path).replace("/", "_").replace(".", "_")
    count = 0
    errors = 0
    try:
        for line_num, code_text in extract_snippets(path):
            try:
                output_file = output_dir / f"{safe_name}_line{line_num}.py"
                header = f"# Source: {path}\n# Line: {line_num}\n\n"
                output_file.write_text(header + code_text, encoding="utf-8")
                count += 1
            except Exception:
                errors += 1
    except Exception:
        errors += 1
    return {"file": str(path), "count": count, "errors": errors}


def scan_files(paths: list[str] | None = None, workers: int = 4) -> None:
    if not paths or paths == [""]:
        targets = [Path.cwd()]
    else:
        targets = [Path(p).resolve() for p in paths]
    all_files = []
    for target in targets:
        if target.is_file():
            all_files.append(target)
        elif target.is_dir():
            all_files.extend(
                p
                for p in target.rglob("*")
                if p.is_file()
                and ".git" not in p.parts
                and not p.is_symlink()
                and p.suffix
                in {".md", ".rst", ".txt", ".METADATA", ".PKG-INFO", ".cfg", ".ini"}
            )
    if not all_files:
        print("No files found.")
        return
    output_dir = Path.cwd() / "output"
    output_dir.mkdir(exist_ok=True)
    print(f"📂 Found {len(all_files)} files. Processing with {workers} workers...")
    total_count = 0
    total_errors = 0
    with Pool(workers) as pool:
        results = [pool.apply_async(process_file, (f, output_dir)) for f in all_files]
        for _i, result in enumerate(results, 1):
            try:
                res = result.get(timeout=30)
                total_count += res["count"]
                total_errors += res["errors"]
                if res["count"] > 0:
                    print(f"  ✓ {res['file']}: {res['count']} snippet(s)")
            except Exception as e:
                print(f"  ✗ Error: {e}")
                total_errors += 1
    print(f"\n✅ Complete: {total_count} snippets extracted, {total_errors} error(s).")
    print(f"📁 Output saved to: {output_dir.resolve()}")


if __name__ == "__main__":
    input_paths = sys.argv[1:] if len(sys.argv) > 1 else []
    scan_files(input_paths, workers=4)
