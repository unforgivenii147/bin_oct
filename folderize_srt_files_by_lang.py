#!/data/data/com.termux/files/home/.local/bin/python
from pathlib import Path

import pycld2 as cld2


def get_srt_files(directory: Path) -> list[Path]:
    """Find all .srt files in the directory."""
    return list(directory.rglob("*.srt"))


def detect_language(file_path: Path):
    """Detect the language of an SRT file using pycld2."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract only the subtitle text (skip timing and sequence numbers)
        lines = content.split("\n")
        subtitle_text = "\n".join(
            line
            for line in lines
            if line.strip() and not line.isdigit() and "-->" not in line
        )

        if not subtitle_text.strip():
            return None

        # pycld2 needs a decent amount of text; combine into a single string
        # and let it detect. isReliable + confidence come back in the result.
        _is_reliable, _text_bytes_found, details = cld2.detect(subtitle_text)

        if not details or not details[0]:
            return None

        # details[0] = (language_name, language_code, percent, score)
        lang_name, lang_code, _percent, _score = details[0]

        # pycld2 returns "un" for unknown
        if lang_code == "un" or lang_name.lower() == "unknown":
            return None

        return lang_name, lang_code

    except Exception as e:
        print(f"  ⚠ Error reading {file_path.name}: {e}")

    return None


def organize_subtitles(directory: Path = Path.cwd()) -> None:
    """Organize SRT files into language-based folders."""
    print(f"🔍 Scanning directory: {directory.absolute()}\n")

    srt_files = get_srt_files(directory)

    if not srt_files:
        print("❌ No .srt files found in the directory.")
        return

    print(f"📊 Found {len(srt_files)} SRT file(s)\n")
    print("=" * 70)

    language_folders = {}

    for file_path in srt_files:
        print(f"\n📄 Processing: {file_path.name}")

        result = detect_language(file_path)

        if result:
            lang_name, lang_code = result
            print(f"   ✓ Detected language: {lang_name} ({lang_code})")

            folder_name = f"{lang_name}_{lang_code}".lower()

            if folder_name not in language_folders:
                language_folders[folder_name] = []

            language_folders[folder_name].append(file_path)
        else:
            print(f"   ⚠ Could not detect language")

    print("\n" + "=" * 70)
    print(f"\n📁 Creating folders and moving files...\n")

    total_moved = 0

    for folder_name, files in sorted(language_folders.items()):
        folder_path = directory / folder_name
        folder_path.mkdir(exist_ok=True)

        print(f"📂 {folder_name.upper()} ({len(files)} file(s))")

        for file_path in files:
            new_path = folder_path / file_path.name
            file_path.rename(new_path)
            print(f"   ➜ {file_path.name}")
            total_moved += 1

    print(
        f"\n✅ Complete! Moved {total_moved} file(s) into {len(language_folders)} language folder(s)."
    )


if __name__ == "__main__":
    organize_subtitles()
