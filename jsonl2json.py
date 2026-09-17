#!/data/data/com.termux/files/home/.local/bin/python
"""
Convert JSON Lines (*.jsonl) files to JSON arrays.

Features:
- Python 3.12+
- pathlib-only filesystem traversal
- Multiple file and directory inputs
- If no inputs are supplied: recursively scans the current directory
- Uses multiprocessing.Pool.imap_unordered with exactly 8 workers
- Streams input and output: memory usage is essentially constant per file
- Atomic output replacement: avoids leaving a partial destination file
- Detects output collisions and skips generated/invalid inputs safely
- Optional strict or lenient malformed-line handling

Examples:
    python jsonl_to_json.py
    python jsonl_to_json.py data.jsonl logs/ archive/
    python jsonl_to_json.py input/ --output-dir converted/
    python jsonl_to_json.py records.jsonl --indent 2
    python jsonl_to_json.py data/ --skip-invalid
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

WORKERS = 8
JSONL_SUFFIXES = {".jsonl", ".ndjson"}


@dataclass(frozen=True, slots=True)
class Job:
    source: Path
    destination: Path
    indent: int | None
    ensure_ascii: bool
    skip_invalid: bool
    overwrite: bool


@dataclass(frozen=True, slots=True)
class Result:
    source: Path
    destination: Path
    records_written: int
    blank_lines: int
    invalid_lines: int
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert JSONL/NDJSON files to JSON arrays, streaming one record at a time. "
            "With no paths, recursively process JSONL files below the current directory."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="Input JSONL/NDJSON files and/or directories.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        help=(
            "Write converted files below this directory. Directory inputs preserve their "
            "relative structure. Defaults to writing beside each source file."
        ),
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=None,
        help="Pretty-print JSON using this indentation level.",
    )
    parser.add_argument(
        "--ensure-ascii",
        action="store_true",
        help="Escape non-ASCII characters in the generated JSON.",
    )
    parser.add_argument(
        "--skip-invalid",
        action="store_true",
        help="Skip malformed non-empty JSONL lines instead of failing the entire file.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing output .json file.",
    )
    return parser.parse_args()


def is_jsonl_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in JSONL_SUFFIXES


def iter_jsonl_files(inputs: Iterable[Path]) -> Iterator[Path]:
    """
    Yield unique JSONL/NDJSON files.

    Directories are walked recursively with pathlib.Path.rglob(). Symbolic links
    are not traversed as directories by pathlib's normal glob behavior.
    """
    seen: set[Path] = set()

    for input_path in inputs:
        try:
            path = input_path.resolve(strict=True)
        except FileNotFoundError:
            print(f"warning: input does not exist: {input_path}", file=sys.stderr)
            continue
        except OSError as exc:
            print(f"warning: cannot access {input_path}: {exc}", file=sys.stderr)
            continue

        if is_jsonl_file(path):
            if path not in seen:
                seen.add(path)
                yield path
            continue

        if path.is_dir():
            try:
                candidates = path.rglob("*")
                for candidate in candidates:
                    if not is_jsonl_file(candidate):
                        continue

                    resolved = candidate.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        yield resolved
            except OSError as exc:
                print(f"warning: cannot traverse {path}: {exc}", file=sys.stderr)
            continue

        print(
            f"warning: skipping unsupported input (expected file or directory): {path}",
            file=sys.stderr,
        )


def destination_for(
    source: Path,
    *,
    output_dir: Path | None,
    input_roots: tuple[Path, ...],
) -> Path:
    """
    Convert `example.jsonl` to `example.json`.

    When --output-dir is used, preserve a path relative to the most-specific
    supplied input directory where possible.
    """
    output_name = source.with_suffix(".json").name

    if output_dir is None:
        return source.with_name(output_name)

    matching_roots: list[Path] = []
    for root in input_roots:
        if root.is_dir():
            try:
                source.relative_to(root)
            except ValueError:
                continue
            matching_roots.append(root)

    if matching_roots:
        root = max(matching_roots, key=lambda item: len(item.parts))
        relative_parent = source.relative_to(root).parent
        return output_dir / relative_parent / output_name

    # A standalone input file outside a supplied directory.
    return output_dir / output_name


def encode_record(
    value: object,
    *,
    indent: int | None,
    ensure_ascii: bool,
) -> str:
    return json.dumps(
        value,
        ensure_ascii=ensure_ascii,
        indent=indent,
        separators=None if indent is not None else (",", ":"),
    )


def convert_one(job: Job) -> Result:
    """
    Worker process function.

    Data is read line-by-line and emitted directly into a JSON array. The
    temporary file is created in the destination directory so os.replace()
    remains atomic on the same filesystem.
    """
    source = job.source
    destination = job.destination

    if destination.exists() and not job.overwrite:
        return Result(
            source=source,
            destination=destination,
            records_written=0,
            blank_lines=0,
            invalid_lines=0,
            error=f"destination exists (use --overwrite): {destination}",
        )

    temp_path: Path | None = None
    records_written = 0
    blank_lines = 0
    invalid_lines = 0

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)

        file_descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            text=True,
        )
        temp_path = Path(temp_name)

        with (
            os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as output,
            source.open("r", encoding="utf-8-sig", newline=None) as input_file,
        ):
            output.write("[")

            for line_number, line in enumerate(input_file, start=1):
                stripped = line.strip()
                if not stripped:
                    blank_lines += 1
                    continue

                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    if job.skip_invalid:
                        invalid_lines += 1
                        continue

                    raise ValueError(
                        f"{source}:{line_number}: invalid JSON: {exc.msg}"
                    ) from exc

                if records_written:
                    output.write(",")

                if job.indent is not None:
                    output.write("\n")

                output.write(
                    encode_record(
                        record,
                        indent=job.indent,
                        ensure_ascii=job.ensure_ascii,
                    )
                )
                records_written += 1

            if job.indent is not None and records_written:
                output.write("\n")

            output.write("]\n")
            output.flush()
            os.fsync(output.fileno())

        # Atomic replacement after a complete and successfully flushed output.
        os.replace(temp_path, destination)
        temp_path = None

        return Result(
            source=source,
            destination=destination,
            records_written=records_written,
            blank_lines=blank_lines,
            invalid_lines=invalid_lines,
        )

    except (OSError, UnicodeError, ValueError) as exc:
        return Result(
            source=source,
            destination=destination,
            records_written=records_written,
            blank_lines=blank_lines,
            invalid_lines=invalid_lines,
            error=str(exc),
        )

    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def main() -> int:
    args = parse_args()

    if args.indent is not None and args.indent < 0:
        print("error: --indent must be zero or greater", file=sys.stderr)
        return 2

    raw_inputs = args.inputs if args.inputs else [Path.cwd()]

    resolved_roots: list[Path] = []
    for item in raw_inputs:
        try:
            resolved_roots.append(item.resolve(strict=True))
        except (FileNotFoundError, OSError):
            # iter_jsonl_files reports the problem consistently.
            pass

    input_roots = tuple(resolved_roots)
    sources = iter_jsonl_files(raw_inputs)

    # This generator avoids materializing every discovered file in memory.
    def jobs() -> Iterator[Job]:
        destinations: set[Path] = set()

        for source in sources:
            destination = destination_for(
                source,
                output_dir=args.output_dir,
                input_roots=input_roots,
            ).resolve()

            # Two unrelated input files may map to one output-dir/name.
            if destination in destinations:
                print(
                    f"warning: skipping {source}; output collision at {destination}",
                    file=sys.stderr,
                )
                continue

            destinations.add(destination)
            yield Job(
                source=source,
                destination=destination,
                indent=args.indent,
                ensure_ascii=args.ensure_ascii,
                skip_invalid=args.skip_invalid,
                overwrite=args.overwrite,
            )

    completed = 0
    failed = 0
    records = 0
    skipped_invalid = 0

    # chunksize=1 is deliberate: file sizes can vary widely, and one file is
    # one unit of work. It provides better load balancing than large batches.
    with mp.Pool(processes=WORKERS) as pool:
        for result in pool.imap_unordered(convert_one, jobs(), chunksize=1):
            completed += 1
            records += result.records_written
            skipped_invalid += result.invalid_lines

            if result.error:
                failed += 1
                print(
                    f"FAILED  {result.source} -> {result.destination}\n"
                    f"        {result.error}",
                    file=sys.stderr,
                )
            else:
                suffix = (
                    f", skipped invalid lines: {result.invalid_lines}"
                    if result.invalid_lines
                    else ""
                )
                print(
                    f"OK      {result.source} -> {result.destination} "
                    f"({result.records_written} records{suffix})"
                )

    print(
        f"\nFinished: {completed} file(s), {records} record(s), "
        f"{skipped_invalid} invalid line(s) skipped, {failed} failure(s).",
        file=sys.stderr,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
