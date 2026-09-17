#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
from pathlib import Path

LANG_EXT = {
    "python": ".py",
    "py": ".py",
    "javascript": ".js",
    "js": ".js",
    "typescript": ".ts",
    "ts": ".ts",
    "c": ".c",
    "h": ".h",
    "cpp": ".cpp",
    "c++": ".cpp",
    "cc": ".cc",
    "java": ".java",
    "csharp": ".cs",
    "c#": ".cs",
    "cs": ".cs",
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
    "shell": ".sh",
    "sh": ".sh",
    "zsh": ".sh",
    "powershell": ".ps1",
    "ps1": ".ps1",
    "yaml": ".yml",
    "yml": ".yml",
    "json": ".json",
    "html": ".html",
    "htm": ".html",
    "css": ".css",
    "dockerfile": "",
    "make": "",
    "makefile": "",
    "text": ".txt",
    "plain": ".txt",
    "md": ".md",
    "markdown": ".md",
}
FENCE_RE = re.compile(
    r"```(?P<lang>[A-Za-z0-9_+\-\.]*)[ \t]*\n(?P<code>.*?)(?<=\n)```", re.DOTALL
)


def ext_for_lang(lang: str) -> str:
    lang = (lang or "").strip().lower()
    if not lang:
        return ".txt"
    if lang in LANG_EXT:
        return LANG_EXT[lang] or ".txt"
    if "." in lang:
        return lang if lang.startswith(".") else "." + lang.split(".")[-1]
    return "." + lang


def safe_stem(s: str, max_len: int = 120) -> str:
    s = re.sub(r"[^\w\-\.]+", "_", s)
    return s[:max_len].rstrip("_") or "file"


def extract_code_blocks(input_md: Path, output_dir: Path) -> int:
    text = input_md.read_text(encoding="utf-8", errors="replace")
    matches = list(FENCE_RE.finditer(text))
    if not matches:
        return 0
    base_stem = safe_stem(input_md.stem)
    for i, m in enumerate(matches, start=1):
        lang = m.group("lang") or ""
        code = m.group("code")
        ext = ext_for_lang(lang)
        lower_lang = (lang or "").strip().lower()
        if lower_lang in {"dockerfile", "make", "makefile"}:
            filename = f"{base_stem}_block_{i}"
        else:
            filename = f"{base_stem}_block_{i}{ext}"
        out_path = output_dir / filename
        out_path.write_text(code.rstrip("\n") + "\n", encoding="utf-8")
    return len(matches)


def main() -> None:
    cwd = Path.cwd().resolve()
    out_dir = cwd / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_files = sorted(p for p in cwd.rglob("*.md") if p.is_file())
    total_blocks = 0
    for md in md_files:
        total_blocks += extract_code_blocks(md, out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
