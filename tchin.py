#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from deep_translator import GoogleTranslator, single_detection

CHUNK_SIZE = 4500
ALLOWED_EXT = {".txt", ".md", ".csv", ".json", ".py"}


def translator() -> GoogleTranslator:
    return GoogleTranslator(source="zh-CN", target="en")


def translate_text_chunked(text: str) -> str:
    chunks = [text[i : i + CHUNK_SIZE] for i in range(0, len(text), 32768)]
    t = translator()
    out = [t.translate(c) for c in chunks]
    return "".join(out)


def translate_python_file(content: str) -> str:
    lines = content.splitlines(keepends=True)
    out = []
    in_docstring = False
    doc_delim = None
    for line in lines:
        stripped = line.strip()
        if not in_docstring and stripped.startswith(('"""', "'''")):
            in_docstring = True
            doc_delim = stripped[:3]
            inside = stripped[3:]
            if inside.endswith(doc_delim):
                text = inside[:-3]
                translated = translate_text_chunked(text) if text else ""
                out.append(line.replace(text, translated))
                in_docstring = False
                doc_delim = None
            else:
                text = inside
                translated = translate_text_chunked(text) if text else ""
                out.append(line.replace(text, translated))
            continue
        if in_docstring:
            if stripped.endswith(doc_delim):
                text = line.replace(doc_delim, "")
                translated = translate_text_chunked(text)
                out.append(f"{translated}{doc_delim}\n")
                in_docstring = False
                doc_delim = None
            else:
                translated = translate_text_chunked(line)
                out.append(translated)
            continue
        if "#" in line:
            code, comment = line.split("#", 1)
            translated = translate_text_chunked(comment)
            out.append(f"{code}# {translated}\n")
        else:
            out.append(line)
    return "".join(out)


def translate_text_file(content: str) -> str:
    return translate_text_chunked(content)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Translate zh-CNpanese → English safely."
    )
    parser.add_argument("input_path")
    parser.add_argument("--lang", default="zh-CN", help="Source language or 'auto'")
    args = parser.parse_args()
    in_path = Path(args.input_path)
    if not in_path.exists():
        print("File not found.", file=sys.stderr)
        sys.exit(1)
    ext = in_path.suffix.lower()
    content = in_path.read_text(encoding="utf-8")
    src_lang = args.lang
    if src_lang == "auto":
        src_lang = single_detection(content[:500])
    translated = (
        translate_python_file(content) if ext == ".py" else translate_text_file(content)
    )
    out_path = in_path.with_name(f"{in_path.stem}_eng{ext}")
    out_path.write_text(translated, encoding="utf-8")
    print(f"Translated ({src_lang} → en): {out_path}")


if __name__ == "__main__":
    raise SystemExit(main())
