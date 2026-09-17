#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import logging
import shutil
import sys
import tempfile
from pathlib import Path

from deep_translator import GoogleTranslator
from langdetect import DetectorFactory, detect

DetectorFactory.seed = 0
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def is_english(text: str) -> bool:
    if not (stripped := text.strip()):
        return True
    try:
        return detect(stripped) == "en"
    except Exception:
        return True


def translate_line(line: str) -> str:
    try:
        translator = GoogleTranslator(source="auto", target="en")
        result = translator.translate(line.strip())
        return result if result else line
    except Exception as e:
        logger.error("Translation error: %s", e)
        return line


def process_file(path: Path, replace_original: bool = False) -> None:
    if not path.exists():
        logger.error("File not found: %s", path)
        return
    backup_path = path.with_suffix(path.suffix + ".backup")
    shutil.copyfile(path, backup_path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False, dir=path.parent
        ) as tmp_file:
            for i, line in enumerate(lines, 1):
                stripped = line.rstrip("\n")
                if stripped.strip() and (not is_english(stripped)):
                    translated = translate_line(stripped)
                    if not replace_original:
                        tmp_file.write(f"{stripped} [TRANSLATION: {translated}]\n")
                    else:
                        tmp_file.write(f"{translated}\n")
                    print("Line %d translated.", i)
                else:
                    tmp_file.write(line)
        shutil.move(tmp_file.name, path)
        print("✓ File updated successfully: %s", path.name)
        print("✓ Backup saved as: %s", backup_path.name)
    except Exception as e:
        logger.error("Error processing file %s: %s", path, e)
        if "tmp_file" in locals() and Path(tmp_file.name).exists():
            Path(tmp_file.name).unlink()


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python trans_file_linebyline_optimized.py <filename> [--replace]")
        print("  --replace: Replace original lines with translations")
        sys.exit(1)
    path = Path(sys.argv[1])
    replace_original = "--replace" in sys.argv
    print("Processing file: %s", path)
    process_file(path, replace_original)


if __name__ == "__main__":
    raise SystemExit(main())
