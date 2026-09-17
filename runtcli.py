#!/data/data/com.termux/files/home/.local/bin/python
"""
Run translate-cli for each line of an input file and save results as JSON.

Usage:
    python translate_lines.py <input_file> [output_file]
"""

import json
import os
import sys

from dh import runcmd


def translate_line(line: str) -> str:
    res, txt, err = runcmd(
        ["translate-cli", "-f", "en", "-t", "fa", "-o", line],
        show_output=True,
    )
    if res != 0:
        return f"__ERROR__: {err.strip()}"
    return txt.strip()


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input_file> [output_file]", file=sys.stderr)
        sys.exit(1)

    input_file = sys.argv[1]

    if len(sys.argv) >= 3:
        output_file = sys.argv[2]
    else:
        base, _ = os.path.splitext(input_file)
        output_file = f"{base}.json"

    if not os.path.isfile(input_file):
        print(f"Error: input file '{input_file}' not found.", file=sys.stderr)
        sys.exit(1)

    results = []

    with open(input_file, "r", encoding="utf-8") as f:
        for line_num, raw_line in enumerate(f, start=1):
            line = raw_line.rstrip("\n")
            if not line.strip():
                # Skip blank lines but keep numbering consistent
                continue

            print(f"[{line_num}] Translating: {line}", file=sys.stderr)
            translated = translate_line(line)

            results.append(
                {
                    "line_number": line_num,
                    "source": line,
                    "translation": translated,
                }
            )

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nDone. Wrote {len(results)} entries to {output_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
