#!/data/data/com.termux/files/home/.local/bin/python
"""
Translate Persian (.txt) files in the current directory into English using
deep-translator's GoogleTranslator, producing one ``*_translations.json`` per
input file under ``./translations``. Translates line-by-line when the source
and translated line counts differ, otherwise uses a straight zip. Uses a fixed
multiprocessing.Pool of 8 workers; logging via loguru.
"""

import json
import time
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator  # type: ignore[import-untyped]
from loguru import logger

MAX_WORKERS: Final[int] = 8
OUTPUT_DIR: Final[Path] = Path("./translations")

TranslateResult = tuple[Path, dict[str, str]]


def translate_file(file_path: Path) -> TranslateResult:
    """
    Translate the contents of a single ``.txt`` file from Persian to English.

    If the translator's line count matches the original, the translation is
    zipped back line-by-line; otherwise each line is translated individually
    to preserve alignment.

    Args:
        file_path: Path to the source text file.

    Returns:
        A tuple ``(file_path, translations)`` where ``translations`` maps
        original lines to their English translations. Returns an empty dict
        on empty input or unrecoverable error.
    """
    try:
        content: str = file_path.read_text(encoding="utf-8").strip()
        if not content:
            logger.warning(f"⚠️  Empty file: {file_path.name}")
            return file_path, {}

        translator: GoogleTranslator = GoogleTranslator(source="fa", target="en")
        translated_text: str | None = translator.translate(content)
        if translated_text is None:
            translated_text = ""

        original_lines: list[str] = [
            line.strip() for line in content.split("\n") if line.strip()
        ]
        translated_lines: list[str] = [
            line.strip() for line in translated_text.split("\n") if line.strip()
        ]

        translations: dict[str, str] = {}
        if len(original_lines) != len(translated_lines):
            for i, line in enumerate(original_lines):
                if line:
                    try:
                        translated_line: str | None = GoogleTranslator(
                            source="fa", target="en"
                        ).translate(line)
                        translations[line] = translated_line or ""
                    except Exception as exc:
                        translations[line] = f"TRANSLATION_ERROR: {exc!s}"
                        logger.warning(
                            f"  ⚠️  Error translating line {i + 1} in "
                            f"{file_path.name}: {exc}"
                        )
        else:
            translations = dict(zip(original_lines, translated_lines, strict=False))

        print(f"✅ Translated: {file_path.name} ({len(translations)} words)")
        return file_path, translations
    except Exception as exc:
        logger.error(f"❌ Error processing {file_path.name}: {exc}")
        return file_path, {}


def save_translation(
    input_path: Path,
    translations: dict[str, str],
    output_dir: Path | None = None,
) -> Path:
    """
    Persist a translations dict to a ``*_translations.json`` file.

    Args:
        input_path: Source text file path (used to derive the output name).
        translations: Mapping of original lines to translated lines.
        output_dir: Destination directory. Defaults to the input's parent.

    Returns:
        The path of the written JSON file.
    """
    resolved_dir: Path = output_dir if output_dir is not None else input_path.parent
    resolved_dir.mkdir(parents=True, exist_ok=True)

    output_filename: str = input_path.stem + "_translations.json"
    output_path: Path = resolved_dir / output_filename

    output_path.write_text(
        json.dumps(translations, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"💾 Saved: {output_path.name}")
    return output_path


def main() -> None:
    """Entry point: discover ``.txt`` files and translate them in parallel."""
    current_dir: Path = Path(".")
    text_files: list[Path] = list(current_dir.glob("*.txt"))

    if not text_files:
        logger.error("❌ No .txt files found in the current directory")
        print("   If your files have a different extension, modify the glob pattern")
        return

    print(f"📚 Found {len(text_files)} file(s) to translate")
    print(f"🚀 Starting translation with {MAX_WORKERS} parallel workers")
    print("-" * 40)

    start_time: float = time.time()
    successful: int = 0
    failed: int = 0

    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[AsyncResult[TranslateResult]] = [
            pool.apply_async(translate_file, (file_path,)) for file_path in text_files
        ]
        for file_path, async_res in zip(text_files, async_results):
            try:
                input_path, translations = async_res.get()
                if translations:
                    save_translation(input_path, translations, OUTPUT_DIR)
                    successful += 1
                else:
                    failed += 1
            except Exception as exc:
                logger.error(f"❌ Failed to process {file_path.name}: {exc}")
                failed += 1

    elapsed_time: float = time.time() - start_time

    print("=" * 40)
    print("✨ Translation complete!")
    print(f"   ✅ Successful: {successful} files")
    if failed > 0:
        logger.warning(f"   ❌ Failed: {failed} files")
    print(f"   ⏱️  Time elapsed: {elapsed_time:.2f} seconds")
    print(f"   📁 Output directory: {OUTPUT_DIR.absolute()}")


if __name__ == "__main__":
    raise SystemExit(main())
