#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm


def extract_regex_patterns(path):
    patterns = []
    regex_pattern = re.compile(
        r"re\.(compile|search|match|findall|fullmatch|finditer)\(\s*([rR]?[\r'\"])(.*?)(?<!\)\2"
    )
    try:
        content = Path(path).read_text(encoding="utf-8")
        patterns = regex_pattern.findall(content)
    except (OSError, UnicodeDecodeError):
        pass
    return [match[2] for match in patterns]


def process_file(path, output_dir):
    Path(path)
    patterns = extract_regex_patterns(path)
    if patterns:
        relative_path = os.path.relpath(path, Path.cwd())
        output_file = output_dir / f"{relative_path.replace(os.sep, '_')}.txt"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        Path(output_file).write_text("\n".join(patterns), encoding="utf-8")
    return path, len(patterns)


def find_regex_in_dir(start_dir: Path, output_dir: str, max_workers=4) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    files_to_process = [
        os.path.join(root, fname)
        for root, _, files in os.walk(start_dir)
        for fname in files
        if fname.endswith(".py")
    ]
    total_files = len(files_to_process)
    progress_bar = tqdm(total=total_files, desc="Progress", unit="file")
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(process_file, path, output_dir): path
            for path in files_to_process
        }
        processed_files = 0
        for future in as_completed(futures):
            _, regex_count = future.result()
            if regex_count:
                print(
                    f"Processed file '{futures[future]}' with {regex_count} regex patterns."
                )
            processed_files += 1
            progress_bar.update(1)
    progress_bar.close()
    print(f"Scanning complete. Processed {total_files} files.")


if __name__ == "__main__":
    output_directory = "output"
    find_regex_in_dir(Path.cwd(), output_directory, max_workers=4)
    print(f"Regex extraction complete. Results saved in {output_directory}")
