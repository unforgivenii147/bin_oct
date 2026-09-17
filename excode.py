#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
from pathlib import Path

LANG_TO_EXT = {
    "python": ".py",
    "py": ".py",
    "javascript": ".js",
    "js": ".js",
    "typescript": ".ts",
    "ts": ".ts",
    "c": ".c",
    "cpp": ".cpp",
    "c++": ".cpp",
    "h": ".h",
    "java": ".java",
    "csharp": ".cs",
    "c#": ".cs",
    "go": ".go",
    "golang": ".go",
    "rust": ".rs",
    "ruby": ".rb",
    "rails": ".rb",
    "php": ".php",
    "swift": ".swift",
    "kotlin": ".kt",
    "scala": ".scala",
    "sql": ".sql",
    "bash": ".sh",
    "sh": ".sh",
    "zsh": ".sh",
    "shell": ".sh",
    "powershell": ".ps1",
    "ps1": ".ps1",
    "yaml": ".yaml",
    "yml": ".yaml",
    "json": ".json",
    "html": ".html",
    "htm": ".html",
    "css": ".css",
    "make": "Makefile",
    "makefile": "Makefile",
    "dockerfile": "Dockerfile",
    "text": ".txt",
    "txt": ".txt",
    "plain": ".txt",
}
CODE_BLOCK_RE = re.compile(
    r"```(?P<lang>[A-Za-z0-9_+\-.]*)[ \t]*\n(?P<code>.*?)(?<=\n)```",
    re.DOTALL | re.IGNORECASE,
)


def get_extension(lang: str) -> str:
    if not lang:
        return ".txt"
    lang = lang.strip().lower()
    if lang in LANG_TO_EXT:
        return LANG_TO_EXT[lang]
    if lang.startswith("."):
        return lang
    return ".txt"


def sanitize_filename(name: str, max_len: int = 200) -> str:
    safe = re.sub(r"[^\w\-.]", "_", name)
    return safe[:max_len].rstrip("_") or "code_block"


def extract_code_blocks(md_file: Path, out_dir: Path):
    try:
        content = md_file.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"Warning: Could not read {md_file}: {e}")
        return []
    matches = list(CODE_BLOCK_RE.finditer(content))
    if not matches:
        return []
    extracted = []
    base_name = sanitize_filename(md_file.stem)
    for i, match in enumerate(matches, start=1):
        lang = match.group("lang") or ""
        code = match.group("code")
        ext = get_extension(lang)
        out_name = f"{base_name}_block_{i}{ext}"
        out_path = out_dir / out_name
        try:
            out_path.write_text(code.rstrip("\n") + "\n", encoding="utf-8")
        except Exception as e:
            print(f"Warning: Could not write {out_path}: {e}")
            continue
        extracted.append(out_path)
    return extracted


def main() -> None:
    cwd = Path.cwd().resolve()
    out_dir = cwd / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_files = sorted(p for p in cwd.rglob("*.md") if p.is_file())
    total_blocks = 0
    all_extracted = []
    for md_file in md_files:
        extracted = extract_code_blocks(md_file, out_dir)
        total_blocks += len(extracted)
        all_extracted.extend(extracted)


if __name__ == "__main__":
    raise SystemExit(main())
