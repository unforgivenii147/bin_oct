#!/data/data/com.termux/files/home/.local/bin/python
"""
Text file translator using the `translate` library.

Modes:
  default : translate the input file in CHUNKS (~450 chars, split at line
            boundaries), save to <input>.<target>
  -l      : line-by-line interactive mode — prints each translation
            immediately and saves {"<src>": ..., "<tgt>": ...} pairs to JSON.
            Lines longer than the query limit are split and re-joined.

Common features:
  - Respects the translator's ~500 char query limit (MAX_CHARS)
  - Saves progress every 50 chunks/lines to a .progress sidecar
  - Resumes from previous progress if the sidecar exists
  - Sleeps between requests and retries with exponential backoff
  - Uses pathlib for all file operations
  - Python 3.12 compatible
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from translate import Translator

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SAVE_EVERY = 50  # persist progress every N chunks/lines
SLEEP_BETWEEN = 0.5  # seconds between successful API calls (rate limit)
MAX_RETRIES = 5  # retries per request on failure
BACKOFF_BASE = 1.5  # exponential backoff multiplier (seconds)

# Defaults — Chinese → English
DEFAULT_SOURCE = "zh"
DEFAULT_TARGET = "en"

# Hard limit imposed by the translation backend (~500 chars per query).
# We stay a bit under to leave headroom for URL-encoding overhead.
MAX_CHARS = 450
CHUNK_SIZE = MAX_CHARS  # default target chars per chunk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def progress_path(target: Path) -> Path:
    """Return the sidecar file that stores the number of completed units."""
    return target.with_suffix(target.suffix + ".progress")


def make_translator(source: str, target: str) -> Translator:
    """
    Build a Translator.  Some versions of the `translate` package accept
    `from_lang` in the constructor, others don't.  We try the richer form
    first and fall back to just `to_lang`.
    """
    try:
        return Translator(from_lang=source, to_lang=target)
    except TypeError:
        return Translator(to_lang=target)


def translate_text(translator: Translator, text: str) -> str:
    """
    Translate a chunk of text with retries and exponential backoff.

    Empty / whitespace-only input is passed through unchanged.
    Assumes the caller has already ensured len(text) <= MAX_CHARS.
    """
    if not text.strip():
        return text

    delay = BACKOFF_BASE
    last_err: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return translator.translate(text)
        except Exception as err:  # noqa: BLE001 — library raises generic errors
            last_err = err
            print(
                f"  ! attempt {attempt}/{MAX_RETRIES} failed: {err}",
                file=sys.stderr,
            )
            time.sleep(delay)
            delay *= BACKOFF_BASE

    raise RuntimeError(f"Translation failed after {MAX_RETRIES} retries: {last_err}")


def split_long_line(line: str, max_chars: int = MAX_CHARS) -> list[str]:
    """
    Split a single line into pieces each <= `max_chars`.

    Splitting prefers natural boundaries in this order:
      1. Sentence-ending punctuation (。！？；.!?;)
      2. Clause punctuation (，、,:)
      3. Whitespace
      4. Hard character cut (last resort)

    No content is lost; the pieces are later re-joined for -l mode.
    """
    if len(line) <= max_chars:
        return [line]

    pieces: list[str] = []
    remaining = line

    # Priority-ordered separators.  Each pass tries harder cuts.
    soft_seps = ["。", "！", "？", "；", ".", "!", "?", ";", "\n"]
    hard_seps = ["，", "、", ",", ":", "：", " "]

    while len(remaining) > max_chars:
        window = remaining[:max_chars]

        cut = -1
        # Try soft separators first, from the end of the window backwards.
        for sep in soft_seps:
            pos = window.rfind(sep)
            if pos > 0:
                cut = pos + len(sep)
                break

        # Then try hard separators.
        if cut <= 0:
            for sep in hard_seps:
                pos = window.rfind(sep)
                if pos > 0:
                    cut = pos + len(sep)
                    break

        # Last resort: hard cut at max_chars.
        if cut <= 0:
            cut = max_chars

        pieces.append(remaining[:cut])
        remaining = remaining[cut:]

    if remaining:
        pieces.append(remaining)
    return pieces


def chunk_lines(lines: list[str], max_chars: int = CHUNK_SIZE) -> list[list[str]]:
    """
    Group lines into chunks whose combined length is at most `max_chars`.

    Splitting happens at line boundaries — lines are never broken here.
    A single line longer than `max_chars` is passed through as its own
    chunk; run_chunked() will then split it via split_long_line().
    """
    chunks: list[list[str]] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line)
        if current and current_len + line_len > max_chars:
            chunks.append(current)
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len

    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Translate a text file between languages."
    )
    parser.add_argument("input", help="Path to the input file (UTF-8).")
    parser.add_argument(
        "output",
        nargs="?",
        help="Optional output path. Defaults depend on mode "
        "(<input>.<target> for chunked, <input>.json for -l).",
    )
    parser.add_argument(
        "-s",
        "--source",
        default=DEFAULT_SOURCE,
        help=f"Source language code (default: {DEFAULT_SOURCE}).",
    )
    parser.add_argument(
        "-t",
        "--target",
        default=DEFAULT_TARGET,
        help=f"Target language code (default: {DEFAULT_TARGET}).",
    )
    parser.add_argument(
        "-l",
        "--line",
        action="store_true",
        help="Line-by-line mode: print each translation immediately "
        "and save source/target pairs to a JSON file.",
    )
    parser.add_argument(
        "-c",
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help=f"Target characters per chunk in default mode "
        f"(default: {CHUNK_SIZE}, hard max: {MAX_CHARS}).",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Chunked mode (default)
# ---------------------------------------------------------------------------


def run_chunked(
    in_path: Path,
    out_path: Path,
    chunk_size: int,
    source: str,
    target: str,
) -> int:
    """
    Default mode: split the source into <=`chunk_size`-char blocks at line
    boundaries, translate each block with a single API call, and write the
    result back to the output file.
    """
    # Never exceed the backend limit.
    if chunk_size > MAX_CHARS:
        print(
            f"  ! --chunk-size capped at {MAX_CHARS} (backend limit)", file=sys.stderr
        )
        chunk_size = MAX_CHARS

    prog_path = progress_path(out_path)

    start_chunk = 0
    if prog_path.is_file():
        try:
            start_chunk = int(prog_path.read_text(encoding="utf-8").strip() or "0")
            print(f"↻ Resuming from chunk {start_chunk} (progress file found)")
        except ValueError:
            print(
                "  ! Progress file unreadable, starting from scratch", file=sys.stderr
            )
            start_chunk = 0

    with in_path.open("r", encoding="utf-8") as f:
        src_lines = [ln.rstrip("\n") for ln in f]

    chunks = chunk_lines(src_lines, chunk_size)
    total = len(chunks)

    if start_chunk >= total:
        print("✔ Nothing to do — file already fully translated.")
        return 0

    translator = make_translator(source, target)
    print(f"→ {source} → {target}, {total} chunk(s), target {chunk_size} chars each")

    mode = "a" if start_chunk > 0 else "w"
    with out_path.open(mode, encoding="utf-8") as fout:
        for idx in range(start_chunk, total):
            chunk = chunks[idx]

            # Split any over-long line inside this chunk.
            sub_pieces: list[str] = []
            for line in chunk:
                sub_pieces.extend(split_long_line(line, chunk_size))

            translated_parts: list[str] = []
            for piece in sub_pieces:
                preview = piece[:60].replace("\n", " ")
                print(f"[chunk {idx + 1}/{total}, {len(piece)} chars] {preview}…")
                try:
                    translated_parts.append(translate_text(translator, piece))
                except RuntimeError as err:
                    prog_path.write_text(str(idx), encoding="utf-8")
                    print(
                        f"\n✖ Aborting at chunk {idx + 1}: {err}",
                        file=sys.stderr,
                    )
                    return 2
                time.sleep(SLEEP_BETWEEN)

            translated = "\n".join(translated_parts)
            fout.write(translated)
            if not translated.endswith("\n"):
                fout.write("\n")
            fout.flush()

            if (idx + 1) % SAVE_EVERY == 0 or (idx + 1) == total:
                prog_path.write_text(str(idx + 1), encoding="utf-8")
                print(f"  ✓ saved progress at chunk {idx + 1}/{total}")

    prog_path.write_text(str(total), encoding="utf-8")
    print(f"\n✔ Done. Output written to {out_path}")
    return 0


# ---------------------------------------------------------------------------
# Line-by-line mode (-l)
# ---------------------------------------------------------------------------


def load_pairs(json_path: Path, src_key: str, tgt_key: str) -> list[dict[str, str]]:
    """Load existing pairs if the JSON file already exists and uses the
    same language keys.  Otherwise start fresh."""
    if not json_path.is_file():
        return []
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            if data and not (src_key in data[0] and tgt_key in data[0]):
                print(
                    f"  ! Existing JSON uses different keys "
                    f"(expected '{src_key}'/'{tgt_key}'), starting fresh",
                    file=sys.stderr,
                )
                return []
            return data
    except (json.JSONDecodeError, OSError) as err:
        print(
            f"  ! Could not read existing JSON ({err}), starting fresh", file=sys.stderr
        )
    return []


def run_line_mode(
    in_path: Path,
    out_path: Path,
    source: str,
    target: str,
) -> int:
    """
    Translate line by line, print each translation as soon as it is ready,
    and persist {<source>: ..., <target>: ...} pairs into a JSON array.

    Lines longer than MAX_CHARS are split into pieces, translated separately,
    and re-joined.  No content is lost; the JSON pair still holds the full
    original line alongside the full translation.
    """
    prog_path = progress_path(out_path)
    pairs = load_pairs(out_path, source, target)

    start_line = len(pairs)
    if prog_path.is_file():
        try:
            stored = int(prog_path.read_text(encoding="utf-8").strip() or "0")
            start_line = max(start_line, stored)
        except ValueError:
            pass

    if start_line:
        print(f"↻ Resuming from line {start_line} ({len(pairs)} pairs loaded)")

    with in_path.open("r", encoding="utf-8") as f:
        src_lines = f.readlines()
    total = len(src_lines)

    if start_line >= total:
        print("✔ Nothing to do — file already fully translated.")
        return 0

    translator = make_translator(source, target)
    print(f"→ {source} → {target}, {total} line(s)")

    pairs = pairs[:start_line]

    for idx in range(start_line, total):
        raw = src_lines[idx].rstrip("\n")

        # ---- Split into <=MAX_CHARS pieces, translate each, then re-join ----
        pieces = split_long_line(raw, MAX_CHARS)
        translated_pieces: list[str] = []

        for p_idx, piece in enumerate(pieces):
            try:
                translated_pieces.append(translate_text(translator, piece))
            except RuntimeError as err:
                out_path.write_text(
                    json.dumps(pairs, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                prog_path.write_text(str(idx), encoding="utf-8")
                print(
                    f"\n✖ Aborting at line {idx + 1}, "
                    f"piece {p_idx + 1}/{len(pieces)}: {err}",
                    file=sys.stderr,
                )
                return 2

            if len(pieces) > 1:
                print(
                    f"  · piece {p_idx + 1}/{len(pieces)} "
                    f"({len(piece)} chars) translated"
                )
            time.sleep(SLEEP_BETWEEN)

        # Re-join pieces.  Space is a safe joiner for both zh and latin
        # output; strip any double spaces introduced at boundaries.
        translated_full = " ".join(p.strip() for p in translated_pieces).strip()

        pairs.append({source: raw, target: translated_full})

        # ---- Show translation immediately ----
        preview_src = raw if len(raw) <= 120 else raw[:117] + "…"
        preview_tgt = (
            translated_full
            if len(translated_full) <= 120
            else translated_full[:117] + "…"
        )
        print(f"[{idx + 1}/{total}]")
        print(f"  {source}: {preview_src}")
        print(f"  {target}: {preview_tgt}")
        if len(pieces) > 1:
            print(f"  (line split into {len(pieces)} pieces)")
        print()

        # ---- Persist JSON every SAVE_EVERY lines ----
        if (idx + 1) % SAVE_EVERY == 0 or (idx + 1) == total:
            out_path.write_text(
                json.dumps(pairs, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            prog_path.write_text(str(idx + 1), encoding="utf-8")
            print(f"  ✓ saved {len(pairs)} pairs to {out_path.name}")

    out_path.write_text(
        json.dumps(pairs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    prog_path.write_text(str(total), encoding="utf-8")
    print(f"✔ Done. {len(pairs)} pairs saved to {out_path}")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    args = parse_args()

    in_path = Path(args.input).expanduser().resolve()
    if not in_path.is_file():
        print(f"Input file not found: {in_path}", file=sys.stderr)
        return 1

    source = args.source
    target = args.target

    if args.output:
        out_path = Path(args.output).expanduser().resolve()
    elif args.line:
        out_path = in_path.with_suffix(".json")
    else:
        out_path = in_path.with_name(f"{in_path.stem}.{target}{in_path.suffix}")

    if args.line:
        return run_line_mode(in_path, out_path, source, target)
    return run_chunked(in_path, out_path, args.chunk_size, source, target)


if __name__ == "__main__":
    sys.exit(main())
