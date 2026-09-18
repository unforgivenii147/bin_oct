#!/data/data/com.termux/files/home/.local/bin/python
"""
xtranslate.py — Unified translation CLI.

Merges 15 scripts into one argparse-driven tool. Third-party requirements
(matching what the originals already used):

    pip install deep-translator          # required
    pip install langdetect               # optional, only for `--detect langdetect`

Mapping of every original script to its merged equivalent:

    autotrans.py               ->  xtranslate copy    --output-suffix _eng --chunk-size 32768 -w 8
    dtransline.py              ->  xtranslate inline  --detect ascii-ratio --threshold 0.6 -w N
    gtrans.py                  ->  xtranslate pair    --target fa [--output FILE]
    ptrans.py                  ->  xtranslate inline  --detect chinese -w N
    ptranslator.py             ->  xtranslate copy    --chunk-size 5000 --check-python-syntax [--output-dir D]
    trans_file_linebyline.py   ->  xtranslate marked  [--replace]
    trans_words.py             ->  xtranslate json    --chunk-size 4500 -w 8
    transasis.py               ->  xtranslate copy    --output-prefix translated_ --chunk-size 2000
    translate2.py              ->  xtranslate resume  --batch-size 100 -w 4 --save-interval 10
    translate_file.py          ->  xtranslate inline  --extensions .txt .md .py .json .csv -w 8
    transline.py               ->  xtranslate segment --segment-pattern "[\\u4e00-\\u9fff...]+"
    transline2.py              ->  xtranslate inline  --extensions .md .txt -w 8
    ultratranslator.py         ->  xtranslate inline  --use-file-api --retries 2

Examples
--------
    # In-place line-by-line translation of a source tree
    python xtranslate.py inline ./src --extensions .py .md --workers 8

    # Chunked translation to new files
    python xtranslate.py copy ./docs --output-suffix _eng --chunk-size 32768

    # Side-by-side preview of a single file
    python xtranslate.py pair notes.txt --target fa

    # Resumable batch translation with periodic saves
    python xtranslate.py resume big.txt --batch-size 100 --save-interval 10
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import multiprocessing as mp
import os
import re
import shutil
import signal
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

try:
    from deep_translator import GoogleTranslator
except ImportError:  # pragma: no cover
    sys.stderr.write("Missing dependency: pip install deep-translator\n")
    raise

# ---------------------------------------------------------------------------
# Constants (originally scattered as module-level magic values)
# ---------------------------------------------------------------------------

DEFAULT_EXTENSIONS: tuple[str, ...] = (
    ".txt",
    ".md",
    ".py",
    ".js",
    ".html",
    ".css",
    ".json",
    ".xml",
    ".csv",
)
EXCLUDE_DIRS: frozenset[str] = frozenset(
    {
        "lazy",
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".venv",
        "venv",
    }
)

NON_ASCII = re.compile(r"[^\x00-\x7F]")
CHINESE_RUN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+")

DEFAULT_CHUNK_SIZE = 32768
DEFAULT_TARGET = "en"
DEFAULT_WORKERS = 8
DEFAULT_RETRIES = 3
DEFAULT_DELAY = 0.5

log = logging.getLogger("xtranslate")

# ---------------------------------------------------------------------------
# Generic helpers (factored from all scripts)
# ---------------------------------------------------------------------------


def is_binary(path: Path) -> bool:
    """True if the first 512 bytes contain a NUL byte (heuristic from dh.py)."""
    try:
        with path.open("rb") as fh:
            head = fh.read(512)
    except OSError:
        return True
    if not head:
        return False
    return b"\x00" in head


def has_non_ascii(text: str) -> bool:
    """True if the text has any char outside ASCII (file-level filter)."""
    return bool(NON_ASCII.search(text))


def looks_english(
    text: str,
    method: str = "ascii-ratio",
    threshold: float = 0.6,
) -> bool:
    """
    Decide whether a single line is already English.

    Methods mirror the originals:
        ascii-ratio  – ratio of ASCII letters > threshold   (dtransline.py)
        non-ascii    – no non-ASCII chars at all            (transline2.py)
        chinese      – contains CJK ideographs              (ptrans.py)
        langdetect   – langdetect says 'en'                 (trans_file_linebyline.py)
        none         – never treat as English
    """
    stripped = text.strip()
    if not stripped:
        return True

    if method == "none":
        return False
    if method == "non-ascii":
        return not NON_ASCII.search(stripped)
    if method == "chinese":
        return not CHINESE_RUN.search(stripped)
    if method == "langdetect":
        try:
            from langdetect import detect  # type: ignore

            return detect(stripped) == "en"
        except Exception:
            return True
    # default: ascii-ratio
    letters = [c for c in stripped if c.isalpha()]
    if not letters:
        return True
    ascii_letters = sum(1 for c in letters if ord(c) < 128)
    return ascii_letters / len(letters) > threshold


def chunk_by_size(text: str, max_size: int) -> Iterator[str]:
    """Split text into chunks of at most `max_size` chars, preserving line breaks."""
    buf: list[str] = []
    size = 0
    for line in text.splitlines(keepends=True):
        if size + len(line) > max_size and buf:
            yield "".join(buf)
            buf, size = [line], len(line)
        else:
            buf.append(line)
            size += len(line)
    if buf:
        yield "".join(buf)


def chunk_with_lines(text: str, max_size: int) -> list[tuple[int, int, str]]:
    """Like chunk_by_size but returns (start_line, end_line, chunk_text)."""
    lines = text.splitlines(keepends=True)
    out: list[tuple[int, int, str]] = []
    buf: list[str] = []
    size = 0
    start = 0
    for i, line in enumerate(lines):
        if size + len(line) > max_size and buf:
            out.append((start, i - 1, "".join(buf)))
            buf, size, start = [line], len(line), i
        else:
            buf.append(line)
            size += len(line)
    if buf:
        out.append((start, len(lines) - 1, "".join(buf)))
    return out


def atomic_write(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write via tempfile + rename so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding=encoding, delete=False, dir=str(path.parent)
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    shutil.move(str(tmp_path), str(path))


def iter_files(
    paths: Sequence[str | Path],
    extensions: Sequence[str] | None = None,
    exclude: Sequence[str | Path] = (),
    skip_hidden: bool = True,
) -> Iterator[Path]:
    """Yield candidate text files under `paths`, applying the common filters."""
    exclude_resolved = {Path(p).resolve() for p in exclude}
    ext_set = {e.lower() for e in extensions} if extensions else None

    for p_str in paths:
        p = Path(p_str).expanduser().resolve()
        if not p.exists():
            log.warning("Path does not exist: %s", p)
            continue
        if p.is_file():
            if p not in exclude_resolved and not is_binary(p):
                yield p
            continue

        for f in p.rglob("*"):
            if not f.is_file():
                continue
            if f.resolve() in exclude_resolved:
                continue
            if any(part in EXCLUDE_DIRS for part in f.parts):
                continue
            if skip_hidden and any(
                part.startswith(".") for part in f.relative_to(p).parts
            ):
                continue
            if ext_set and f.suffix.lower() not in ext_set:
                continue
            if is_binary(f):
                continue
            yield f


# ---------------------------------------------------------------------------
# Translator wrapper (one place for retry / backoff)
# ---------------------------------------------------------------------------


class Translator:
    """Thin wrapper around deep-translator's GoogleTranslator with retry."""

    def __init__(
        self,
        source: str = "auto",
        target: str = DEFAULT_TARGET,
        retries: int = DEFAULT_RETRIES,
        delay: float = DEFAULT_DELAY,
    ) -> None:
        self.source = source
        self.target = target
        self.retries = max(1, retries)
        self.delay = delay

    def translate(self, text: str) -> str:
        if not text or not text.strip():
            return text
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            try:
                gt = GoogleTranslator(source=self.source, target=self.target)
                result = gt.translate(text)
                if result is not None:
                    return result
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < self.retries - 1:
                    time.sleep(self.delay * (attempt + 1))
        if last_exc is not None:
            log.debug(
                "Translation failed after %d attempts: %s", self.retries, last_exc
            )
        return text


# ---------------------------------------------------------------------------
# Module-level workers (must be top-level so multiprocessing can pickle them)
# ---------------------------------------------------------------------------


def _chunk_worker(task: tuple[str, str, str, int, float]) -> str:
    text, source, target, retries, delay = task
    return Translator(source, target, retries, delay).translate(text)


def _inline_file_worker(task: tuple) -> str:
    path, opts = task
    return _inline_process_one(Path(path), opts)


def _marked_file_worker(task: tuple) -> str:
    path, opts = task
    return _marked_process_one(Path(path), opts)


# ---------------------------------------------------------------------------
# Line / segment helpers shared by inline + marked modes
# ---------------------------------------------------------------------------


def _translate_one_line(line: str, translator: Translator, opts: dict[str, Any]) -> str:
    """Preserve leading indent + trailing newline, replace content with translation."""
    stripped = line.strip()
    if not stripped or looks_english(stripped, opts["detect"], opts["threshold"]):
        return line
    leading = line[: len(line) - len(line.lstrip())]
    trailing = line[len(line.rstrip()) :]  # usually "\n"
    translated = translator.translate(stripped)
    return f"{leading}{translated}{trailing}"


def _inline_process_one(path: Path, opts: dict[str, Any]) -> str:
    """Handle one file for `inline` mode. Returns a status line."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return f"✗ {path}: {exc}"

    if not opts.get("force") and not has_non_ascii(text):
        return f"~ {path.name} (already English)"

    translator = Translator(
        opts["source"], opts["target"], opts["retries"], opts["delay"]
    )
    lines = text.splitlines(keepends=True)
    changed = 0
    out: list[str] = []
    for line in lines:
        new = _translate_one_line(line, translator, opts)
        if new != line:
            changed += 1
        out.append(new)

    if changed == 0:
        return f"~ {path.name} (nothing to translate)"
    if opts.get("dry_run"):
        return f"[dry-run] would update {path} ({changed} lines)"
    atomic_write(path, "".join(out), encoding="utf-8")
    return f"✓ {path} ({changed} lines)"


def _marked_process_one(path: Path, opts: dict[str, Any]) -> str:
    """Handle one file for `marked` mode (line-by-line + backup + markers)."""
    backup = path.with_suffix(path.suffix + opts["backup_suffix"])
    try:
        shutil.copyfile(path, backup)
    except OSError as exc:
        return f"✗ {path}: cannot create backup: {exc}"

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return f"✗ {path}: {exc}"

    translator = Translator(
        opts["source"], opts["target"], opts["retries"], opts["delay"]
    )
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    changed = 0
    for line in lines:
        stripped = line.rstrip("\n")
        if not stripped.strip() or looks_english(
            stripped, opts["detect"], opts["threshold"]
        ):
            out.append(line)
            continue
        translated = translator.translate(stripped.strip())
        newline = "\n" if line.endswith("\n") else ""
        if opts["replace"]:
            out.append(translated + newline)
        else:
            out.append(f"{stripped} [TRANSLATION: {translated}]{newline}")
        changed += 1

    if opts.get("dry_run"):
        return f"[dry-run] would update {path} ({changed} lines, backup={backup.name})"
    atomic_write(path, "".join(out), encoding="utf-8")
    return f"✓ {path} ({changed} lines, backup={backup.name})"


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------


def _run_workers(
    worker,
    tasks: list[tuple],
    workers: int,
) -> list[Any]:
    """Run `worker` over tasks, using a Pool if workers > 1."""
    if workers > 1 and len(tasks) > 1:
        with mp.Pool(processes=workers) as pool:
            return pool.map(worker, tasks)
    return [worker(t) for t in tasks]


def _common_opts(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "source": args.source,
        "target": args.target,
        "retries": args.retries,
        "delay": args.delay,
        "detect": args.detect,
        "threshold": args.threshold,
        "dry_run": args.dry_run,
        "force": getattr(args, "force", False),
    }


def mode_inline(args: argparse.Namespace) -> int:
    """Line-by-line in-place translation. (dtransline, ptrans, transline2, translate_file, ultratranslator)"""
    files = list(
        iter_files(
            args.paths,
            args.extensions,
            args.exclude,
            skip_hidden=not args.no_skip_hidden,
        )
    )
    if not files:
        print("No files to process.")
        return 0
    print(f"Found {len(files)} files. Workers={args.workers}")
    opts = _common_opts(args)
    opts["use_file_api"] = getattr(args, "use_file_api", False)

    if opts["use_file_api"]:
        # ultratranslator.py behaviour: whole-file translate via library.
        return _run_file_api_mode(files, opts, args.workers)

    tasks = [(str(f), opts) for f in files]
    for status in _run_workers(_inline_file_worker, tasks, args.workers):
        print(status)
    return 0


def _run_file_api_mode(files: list[Path], opts: dict[str, Any], workers: int) -> int:
    """ultratranslator.py behaviour: GoogleTranslator.translate_file on the whole file."""
    tasks = [(str(f), opts) for f in files]

    def worker(task: tuple) -> str:
        path = Path(task[0])
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            return f"✗ {path}: {exc}"
        if not has_non_ascii(text):
            return f"~ {path.name} (already English)"
        last_exc: Exception | None = None
        for attempt in range(opts["retries"]):
            try:
                gt = GoogleTranslator(source=opts["source"], target=opts["target"])
                result = gt.translate_file(str(path))
                if result:
                    if opts["dry_run"]:
                        return f"[dry-run] would update {path}"
                    atomic_write(path, result, encoding="utf-8")
                    return f"✓ {path}"
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < opts["retries"] - 1:
                    time.sleep(opts["delay"] * (attempt + 1))
        return f"✗ {path}: {last_exc}"

    for status in _run_workers(worker, tasks, workers):
        print(status)
    return 0


def mode_copy(args: argparse.Namespace) -> int:
    """Chunked translation written to a new file. (autotrans, transasis, ptranslator)"""
    files = list(
        iter_files(
            args.paths,
            args.extensions,
            args.exclude,
            skip_hidden=not args.no_skip_hidden,
        )
    )
    if not files:
        print("No files to process.")
        return 0
    print(f"Found {len(files)} files. Workers={args.workers}")

    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            log.error("Cannot read %s: %s", path, exc)
            continue
        if not args.force and not has_non_ascii(text):
            print(f"~ {path.name} (already English)")
            continue

        chunks = list(chunk_by_size(text, args.chunk_size))
        print(f"→ {path.name}: {len(chunks)} chunks")
        tasks = [
            (c, args.source, args.target, args.retries, args.delay) for c in chunks
        ]
        results = _run_workers(_chunk_worker, tasks, args.workers)
        result_text = "".join(results)

        if args.check_python_syntax and path.suffix == ".py":
            try:
                ast.parse(result_text)
            except SyntaxError as exc:
                log.error("Syntax error in translated Python for %s: %s", path, exc)
                continue

        out_path = _resolve_output_path(path, args)
        if args.dry_run:
            print(f"[dry-run] would write {out_path}")
            continue
        atomic_write(out_path, result_text, encoding="utf-8")
        print(f"✓ wrote {out_path}")
    return 0


def _resolve_output_path(path: Path, args: argparse.Namespace) -> Path:
    if args.output_dir:
        return Path(args.output_dir) / path.name
    prefix = args.output_prefix or ""
    suffix = args.output_suffix or ""
    return path.with_name(f"{prefix}{path.stem}{suffix}{path.suffix}")


def mode_json(args: argparse.Namespace) -> int:
    """Chunked translation emitted as JSON. (trans_words)"""
    files = list(
        iter_files(
            args.paths,
            args.extensions,
            args.exclude,
            skip_hidden=not args.no_skip_hidden,
        )
    )
    if not files:
        print("No files to process.")
        return 0

    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            log.error("Cannot read %s: %s", path, exc)
            continue

        chunks = chunk_with_lines(text, args.chunk_size)
        print(f"→ {path.name}: {len(chunks)} chunks")
        tasks = [
            (c[2], args.source, args.target, args.retries, args.delay) for c in chunks
        ]
        results = _run_workers(_chunk_worker, tasks, args.workers)

        records = []
        for (start, end, original), translated in zip(chunks, results):
            records.append(
                {
                    "chunk_id": f"{start}_{end}",
                    "start_line": start,
                    "end_line": end,
                    "translated": translated,
                    "skipped": translated == original,
                }
            )

        out_path = path.with_suffix(".json")
        if args.dry_run:
            print(f"[dry-run] would write {out_path}")
            continue
        atomic_write(
            out_path, json.dumps({"lines": records}, ensure_ascii=False, indent=2)
        )
        print(f"✓ wrote {out_path}")
    return 0


def mode_pair(args: argparse.Namespace) -> int:
    """Side-by-side translation for one or more files. (gtrans)"""
    paths = [Path(p) for p in args.paths]
    files: list[Path] = []
    for p in paths:
        if p.is_file():
            files.append(p)
        else:
            files.extend(iter_files([p], args.extensions, args.exclude))

    if not files:
        print("No files to process.")
        return 0

    translator = Translator(args.source, args.target, args.retries, args.delay)
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            log.error("Cannot read %s: %s", path, exc)
            continue
        lines = text.splitlines()
        buf: list[str] = []
        for i, line in enumerate(lines, 1):
            translated = translator.translate(line) if line.strip() else line
            buf.append(line)
            buf.append(f"→ {translated}")
            buf.append("")
        result = "\n".join(buf)

        if args.output:
            out_path = Path(args.output)
            atomic_write(out_path, result, encoding="utf-8")
            print(f"✓ wrote {out_path}")
        else:
            if len(files) > 1:
                print(f"\n===== {path} =====")
            print(result)
    return 0


def mode_marked(args: argparse.Namespace) -> int:
    """In-place with markers + backup. (trans_file_linebyline)"""
    files = list(
        iter_files(
            args.paths,
            args.extensions,
            args.exclude,
            skip_hidden=not args.no_skip_hidden,
        )
    )
    if not files:
        print("No files to process.")
        return 0
    opts = _common_opts(args)
    opts["replace"] = args.replace
    opts["backup_suffix"] = args.backup_suffix
    tasks = [(str(f), opts) for f in files]
    for status in _run_workers(_marked_file_worker, tasks, args.workers):
        print(status)
    return 0


def mode_segment(args: argparse.Namespace) -> int:
    """Regex-segment in-place translation with a .progress cache. (transline)"""
    pattern = re.compile(args.segment_pattern)
    files = list(
        iter_files(
            args.paths,
            args.extensions,
            args.exclude,
            skip_hidden=not args.no_skip_hidden,
        )
    )
    if not files:
        print("No files to process.")
        return 0

    for path in files:
        _segment_one(path, args, pattern)
    return 0


def _segment_one(
    path: Path, args: argparse.Namespace, pattern: re.Pattern[str]
) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.error("Cannot read %s: %s", path, exc)
        return

    lines = text.splitlines(keepends=True)

    # Collect (line_idx, start, end, original_segment) tuples.
    tasks: list[tuple[int, int, int, str]] = []
    for i, line in enumerate(lines):
        for m in pattern.finditer(line):
            tasks.append((i, m.start(), m.end(), m.group()))

    if not tasks:
        print(f"~ {path.name}: no matches")
        return

    progress_path = path.with_suffix(path.suffix + args.progress_suffix)
    progress: dict[str, dict[str, str]] = {}
    if progress_path.exists():
        try:
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
        except Exception:
            progress = {}

    pending = [
        t
        for t in tasks
        if str(t[0]) not in progress or f"{t[1]},{t[2]}" not in progress[str(t[0])]
    ]
    print(f"→ {path.name}: {len(pending)}/{len(tasks)} segments to translate")

    chunk_tasks = [
        (t[3], args.source, args.target, args.retries, args.delay) for t in pending
    ]
    results = _run_workers(_chunk_worker, chunk_tasks, args.workers) if pending else []

    for (line_idx, s, e, _), tr in zip(pending, results):
        progress.setdefault(str(line_idx), {})[f"{s},{e}"] = tr

    if args.dry_run:
        print(f"[dry-run] would write {path} and {progress_path.name}")
        return

    # Rebuild each line from its cached segments.
    rebuilt: list[str] = []
    for i, line in enumerate(lines):
        cache = progress.get(str(i))
        if not cache:
            rebuilt.append(line)
            continue
        newline = "\n" if line.endswith("\n") else ""
        stripped = line.rstrip("\r\n")
        parts: list[str] = []
        pos = 0
        for key in sorted(cache.keys(), key=lambda k: int(k.split(",")[0])):
            s_str, e_str = key.split(",")
            s, e = int(s_str), int(e_str)
            parts.append(stripped[pos:s])
            parts.append(cache[key])
            pos = e
        parts.append(stripped[pos:])
        rebuilt.append("".join(parts) + newline)

    atomic_write(path, "".join(rebuilt), encoding="utf-8")
    atomic_write(progress_path, json.dumps(progress, ensure_ascii=False, indent=2))
    print(f"✓ {path}")


# --- resume mode (translate2.py) -------------------------------------------

_shutdown = False


def _handle_signal(signum: int, _frame) -> None:  # noqa: ANN001
    global _shutdown
    log.warning("Received signal %s — finishing current work and saving…", signum)
    _shutdown = True


def _resume_translate_batch(task: tuple) -> list[tuple[int, str]]:
    """Translate a batch of (line_idx, text) pairs (no-op for English/blank lines)."""
    source, target, items, retries, delay = task
    translator = Translator(source, target, retries, delay)
    out: list[tuple[int, str]] = []
    for idx, text in items:
        if not text.strip():
            out.append((idx, text))
            continue
        out.append((idx, translator.translate(text)))
    return out


def mode_resume(args: argparse.Namespace) -> int:
    """Batched, resumable, signal-safe translation. (translate2)"""
    global _shutdown
    _shutdown = False
    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    files = list(
        iter_files(
            args.paths,
            args.extensions,
            args.exclude,
            skip_hidden=not args.no_skip_hidden,
        )
    )
    if not files:
        print("No files to process.")
        return 0

    for path in files:
        if _shutdown:
            break
        _resume_one(path, args)

    if _shutdown:
        log.warning("Stopped early — rerun the same command to continue.")
        return 130
    return 0


def _resume_one(path: Path, args: argparse.Namespace) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.error("Cannot read %s: %s", path, exc)
        return

    lines = text.splitlines()
    if not lines:
        print(f"~ {path.name}: empty")
        return

    out_path = (
        Path(args.output)
        if args.output
        else path.with_suffix(path.suffix + ".translated.txt")
    )
    meta_path = Path(args.meta) if args.meta else Path(str(out_path) + ".meta.json")

    batch_size = max(1, args.batch_size)
    indexed = list(enumerate(lines))
    batches = [indexed[i : i + batch_size] for i in range(0, len(indexed), batch_size)]
    tasks = [(args.source, args.target, b, args.retries, args.delay) for b in batches]

    translations: dict[int, str] = {}
    print(
        f"→ {path.name}: {len(lines)} lines / {len(batches)} batches "
        f"(workers={args.workers}) -> {out_path}"
    )

    pool = mp.Pool(processes=args.workers) if args.workers > 1 else None
    last_save = time.time()
    try:
        for i, task in enumerate(tasks):
            if _shutdown:
                break
            results = (
                pool.apply(_resume_translate_batch, (task,))
                if pool
                else _resume_translate_batch(task)
            )
            translations.update(dict(results))

            now = time.time()
            if now - last_save >= args.save_interval or i == len(tasks) - 1:
                _resume_flush(
                    out_path, meta_path, path, lines, translations, complete=False
                )
                done = len(translations)
                print(f"   saved {done}/{len(lines)} lines")
                last_save = now
    finally:
        if pool is not None:
            pool.terminate()
            pool.join()

    complete = (not _shutdown) and len(translations) == len(lines)
    _resume_flush(out_path, meta_path, path, lines, translations, complete=complete)
    tag = "✓ complete" if complete else "… interrupted"
    print(f"{tag}: {out_path} ({len(translations)}/{len(lines)} lines)")


def _resume_flush(
    out_path: Path,
    meta_path: Path,
    source_path: Path,
    lines: list[str],
    translations: dict[int, str],
    complete: bool,
) -> None:
    merged = [translations.get(i, lines[i]) for i in range(len(lines))]
    atomic_write(out_path, "\n".join(merged) + "\n", encoding="utf-8")
    meta = {
        "input": str(source_path),
        "output": str(out_path),
        "total_lines": len(lines),
        "translated_lines": len(translations),
        "complete": complete,
        "updated_at": time.time(),
    }
    atomic_write(meta_path, json.dumps(meta, indent=2))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "paths",
        nargs="*",
        default=None,
        help="Files or directories (default: current directory).",
    )
    p.add_argument(
        "-s", "--source", default="auto", help="Source language code (default: auto)."
    )
    p.add_argument(
        "-t",
        "--target",
        default=DEFAULT_TARGET,
        help=f"Target language code (default: {DEFAULT_TARGET}).",
    )
    p.add_argument(
        "-w",
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Number of parallel workers (default: {DEFAULT_WORKERS}).",
    )
    p.add_argument(
        "--extensions",
        nargs="+",
        default=list(DEFAULT_EXTENSIONS),
        help="File extensions to process.",
    )
    p.add_argument("--exclude", nargs="+", default=[], help="Paths to exclude.")
    p.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help=f"Translation retries per item (default: {DEFAULT_RETRIES}).",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help=f"Base delay between retries in seconds (default: {DEFAULT_DELAY}).",
    )
    p.add_argument(
        "--detect",
        choices=["ascii-ratio", "non-ascii", "chinese", "langdetect", "none"],
        default="ascii-ratio",
        help="How to detect non-English lines (default: ascii-ratio).",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=0.6,
        help="Threshold for ascii-ratio detection (default: 0.6).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without writing.",
    )
    p.add_argument(
        "--no-skip-hidden", action="store_true", help="Do not skip hidden files / dirs."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xtranslate",
        description="Unified translation CLI (deep-translator).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    # inline ---------------------------------------------------------------
    p_inline = sub.add_parser("inline", help="Line-by-line in-place translation.")
    _add_common(p_inline)
    p_inline.add_argument(
        "--force", action="store_true", help="Translate even files that look English."
    )
    p_inline.add_argument(
        "--use-file-api",
        action="store_true",
        help="Use GoogleTranslator.translate_file (ultratranslator.py).",
    )
    p_inline.set_defaults(func=mode_inline)

    # copy -----------------------------------------------------------------
    p_copy = sub.add_parser("copy", help="Chunked translation to a new file.")
    _add_common(p_copy)
    p_copy.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"Max chars per chunk (default: {DEFAULT_CHUNK_SIZE}).",
    )
    p_copy.add_argument(
        "--output-suffix",
        default="_eng",
        help="Suffix before the extension (default: _eng).",
    )
    p_copy.add_argument(
        "--output-prefix", default="", help="Prefix before the filename stem."
    )
    p_copy.add_argument(
        "--output-dir",
        default=None,
        help="Write to this directory instead of alongside the input.",
    )
    p_copy.add_argument(
        "--check-python-syntax",
        action="store_true",
        help="Run ast.parse on translated .py before writing.",
    )
    p_copy.add_argument(
        "--force", action="store_true", help="Translate even files that look English."
    )
    p_copy.set_defaults(func=mode_copy)

    # json -----------------------------------------------------------------
    p_json = sub.add_parser("json", help="Chunked translation to a JSON file.")
    _add_common(p_json)
    p_json.add_argument(
        "--chunk-size",
        type=int,
        default=4500,
        help="Max chars per chunk (default: 4500).",
    )
    p_json.set_defaults(func=mode_json)

    # pair -----------------------------------------------------------------
    p_pair = sub.add_parser("pair", help="Side-by-side translation of one file.")
    _add_common(p_pair)
    p_pair.add_argument(
        "-o",
        "--output",
        default=None,
        help="Write side-by-side output to this file instead of stdout.",
    )
    p_pair.set_defaults(func=mode_pair)

    # marked ---------------------------------------------------------------
    p_marked = sub.add_parser("marked", help="In-place with [TRANSLATION: …] markers.")
    _add_common(p_marked)
    p_marked.add_argument(
        "--replace",
        action="store_true",
        help="Replace original lines instead of appending markers.",
    )
    p_marked.add_argument(
        "--backup-suffix",
        default=".backup",
        help="Backup file suffix (default: .backup).",
    )
    p_marked.set_defaults(func=mode_marked)

    # segment --------------------------------------------------------------
    p_seg = sub.add_parser("segment", help="Regex-segment in-place translation.")
    _add_common(p_seg)
    p_seg.add_argument(
        "--segment-pattern",
        default=CHINESE_RUN.pattern,
        help="Regex for segments to translate (default: CJK runs).",
    )
    p_seg.add_argument(
        "--progress-suffix",
        default=".xlprogress",
        help="Suffix of the resume cache file (default: .xlprogress).",
    )
    p_seg.set_defaults(func=mode_segment)

    # resume ---------------------------------------------------------------
    p_res = sub.add_parser("resume", help="Resumable batch translation with meta JSON.")
    _add_common(p_res)
    p_res.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output file (default: <name>.translated.txt).",
    )
    p_res.add_argument(
        "--meta", default=None, help="Meta JSON path (default: <output>.meta.json)."
    )
    p_res.add_argument(
        "--batch-size", type=int, default=100, help="Lines per batch (default: 100)."
    )
    p_res.add_argument(
        "--save-interval",
        type=float,
        default=10.0,
        help="Seconds between periodic saves (default: 10).",
    )
    p_res.set_defaults(func=mode_resume)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.paths:
        args.paths = ["."]
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        log.warning("Interrupted.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
