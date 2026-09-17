#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from pathlib import Path
from typing import Final

try:
    from googletrans import Translator

    HAS_GOOGLETRANS = True
except ImportError:
    HAS_GOOGLETRANS = False
try:
    from deep_translator import GoogleTranslator

    HAS_DEEP_TRANSLATOR = True
except ImportError:
    HAS_DEEP_TRANSLATOR = False
if not (HAS_GOOGLETRANS or HAS_DEEP_TRANSLATOR):
    print(
        "Please install either googletrans (4.0.0rc1) or deep-translator.",
        file=sys.stderr,
    )
    sys.exit(1)
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)
RETRY_ATTEMPTS: Final[int] = 3
RETRY_DELAY: Final[float] = 0.5
TAMIL_PATTERN: Final[re.Pattern] = re.compile(r"[\u0B80-\u0BFF]+")
CHINESE_PATTERN: Final[re.Pattern] = re.compile(
    r"[\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF]+"
)
ENGLISH_PATTERN: Final[re.Pattern] = re.compile(r"^[A-Za-z0-9\s\.,;:!?\'\"()\-—]+$")


class ResilientTranslator:
    def __init__(self, target_lang: str = "fa"):
        self.target_lang = target_lang
        self.google_translator = Translator() if HAS_GOOGLETRANS else None
        self.deep_translator = (
            GoogleTranslator(source="en", target=target_lang)
            if HAS_DEEP_TRANSLATOR
            else None
        )

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        for attempt in range(RETRY_ATTEMPTS):
            try:
                if HAS_GOOGLETRANS:
                    detected = self.google_translator.detect(text)
                    result = self.google_translator.translate(
                        text, dest=self.target_lang
                    )
                    if result:
                        return result.text
            except Exception as e:
                logger.warning("Attempt %d failed: %s", attempt + 1, e)
                if attempt < RETRY_ATTEMPTS - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
        return f"[Translation failed: {text[:50]}...]"


def detect_language_type(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return "empty"
    if stripped == "%":
        return "marker"
    if TAMIL_PATTERN.search(stripped):
        return "tamil"
    if CHINESE_PATTERN.search(stripped):
        return "chinese"
    if ENGLISH_PATTERN.match(stripped):
        return "english"
    return "other"


def process_file(input_file: Path, output_file: Path | None = None) -> None:
    try:
        content = input_file.read_text(encoding="utf-8")
        lines = content.splitlines()
    except Exception as e:
        logger.error("Error reading file %s: %s", input_file, e)
        return
    translator = ResilientTranslator()
    output_lines: list[str] = []
    for i, line in enumerate(lines):
        lang_type = detect_language_type(line)
        print("Translating line %d (%s)...", i + 1, lang_type)
        translated = translator.translate(line)
        output_lines.append(line)
        output_lines.append(f"→ {translated}")
        output_lines.append("")
    result_text = "\n".join(output_lines)
    if output_file:
        try:
            output_file.write_text(result_text, encoding="utf-8")
            print("Output written to: %s", output_file)
        except Exception as e:
            logger.error("Error writing output file: %s", e)
    else:
        print(result_text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Translate text to persian.")
    parser.add_argument("input_file", type=Path, help="Input file path")
    parser.add_argument("-o", "--output", type=Path, help="Output file path")
    args = parser.parse_args()
    if not args.input_file.exists():
        logger.error("Input file does not exist: %s", args.input_file)
        sys.exit(1)
    process_file(args.input_file, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
