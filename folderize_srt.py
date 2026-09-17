#!/data/data/com.termux/files/home/.local/bin/python
from collections import Counter
from multiprocessing import Pool, cpu_count
from pathlib import Path

from lingua import LanguageDetectorBuilder

BATCH_SIZE = 8
_detector = None  # per-worker global


def _init_worker():
    """Build the detector once inside each worker process."""
    global _detector
    _detector = LanguageDetectorBuilder.from_all_languages().build()


def _detect_batch(lines: list[str]):
    """Worker function: detect language for each line in a batch.
    Returns list of (line, lang_name, iso_code) — Language enum isn't picklable."""
    out = []
    for line in lines:
        try:
            d = _detector.detect_language_of(line)
            if d:
                out.append((line, d.name, d.iso_code_639_1.name))
            else:
                out.append((line, None, None))
        except Exception:
            out.append((line, None, None))
    return out


def get_srt_files(directory: Path) -> list[Path]:
    return list(directory.glob("*.srt"))


def detect_language_majority_vote(file_path: Path, pool: Pool):
    """Detect language using majority vote, with lines processed in parallel batches."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_lines = f.readlines()

        text_lines = []
        skipped_count = 0
        for line in raw_lines:
            s = line.strip()
            if not s or "-->" in s or s.isdigit():
                skipped_count += 1
                continue
            text_lines.append(s)

        if not text_lines:
            return None

        # Split into batches of BATCH_SIZE
        batches = [
            text_lines[i : i + BATCH_SIZE]
            for i in range(0, len(text_lines), BATCH_SIZE)
        ]

        # Run batches in parallel
        batch_results = pool.map(_detect_batch, batches)

        # Flatten and print per-line result in order
        line_count = 0
        lang_counter = Counter()
        iso_lookup = {}
        for batch in batch_results:
            for line, name, iso in batch:
                line_count += 1
                if name:
                    lang_counter[name] += 1
                    iso_lookup[name] = iso
                    print(
                        f"      Line {line_count}: {name} - "
                        f'"{line[:50]}{"..." if len(line) > 50 else ""}"'
                    )

        if lang_counter:
            most_common_name, _ = lang_counter.most_common(1)[0]
            most_common_iso = iso_lookup[most_common_name]

            print(f"\n   📊 Statistics:")
            print(f"      Total lines processed: {line_count}")
            print(f"      Lines skipped: {skipped_count}")
            print(f"      Language votes:")
            for lang_name, count in lang_counter.most_common():
                pct = (count / line_count) * 100
                print(f"         {lang_name}: {count} votes ({pct:.1f}%)")

            return (most_common_name, most_common_iso)

    except Exception as e:
        print(f"  ⚠ Error reading {file_path.name}: {e}")

    return None


def organize_subtitles(directory: Path = Path.cwd()) -> None:
    print(f"🔍 Scanning directory: {directory.absolute()}\n")

    srt_files = get_srt_files(directory)

    if not srt_files:
        print("❌ No .srt files found in the directory.")
        return

    print(f"📊 Found {len(srt_files)} SRT file(s)")
    print(f"⚙️  Using {cpu_count()} worker processes (batch size = {BATCH_SIZE})\n")
    print("=" * 80)

    language_folders = {}

    with Pool(initializer=_init_worker) as pool:
        for file_path in srt_files:
            print(f"\n📄 Processing: {file_path.name}")
            print("─" * 80)

            detected = detect_language_majority_vote(file_path, pool)

            if detected:
                lang_name, lang_code = detected
                print(f"\n   ✅ FINAL RESULT: {lang_name} ({lang_code})")

                folder_name = f"{lang_name}_{lang_code}".lower()
                language_folders.setdefault(folder_name, []).append(file_path)
            else:
                print(f"\n   ⚠ Could not detect language")

            print("=" * 80)

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
        f"\n✅ Complete! Moved {total_moved} file(s) into "
        f"{len(language_folders)} language folder(s)."
    )


if __name__ == "__main__":
    organize_subtitles()
