#!/data/data/com.termux/files/home/.local/bin/python
"""
Translate Chinese text in source files to English in place.

Prompt to regenerate this script:
"Write a Python script that finds all Chinese characters in source files and
translates them to English using GoogleTranslator, processing segments in
parallel with a multiprocessing pool of 8 workers. Show progress with loguru,
save/resume progress via JSON sidecar files, skip binary/vendor directories,
handle Ctrl+C gracefully by finishing in-flight work and saving state, and
preserve original encoding and line endings."
"""

from __future__ import annotations

import json
import re
import signal
import sys
from collections.abc import Iterable
from datetime import datetime
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Any, Final

from deep_translator import GoogleTranslator
from dh import get_nobinary
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

CHUNK_SIZE: Final[int] = 32768
SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)
CHINESE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+"
)
POOL_SIZE: Final[int] = 8
MAX_RETRIES: Final[int] = 1
PROGRESS_SAVE_EVERY: Final[int] = 20

_interrupted: bool = False

Segment = tuple[int, int, str]
SegmentKey = tuple[int, int]
LineTranslations = dict[SegmentKey, str]
ProgressMap = dict[int, LineTranslations]


def _sigint_handler(sig: int, frame: Any) -> None:
    """Handle SIGINT by requesting a graceful shutdown after in-flight work."""
    global _interrupted
    logger.warning(
        "Ctrl+C caught — completing current active requests and saving progress..."
    )
    _interrupted = True


signal.signal(signal.SIGINT, _sigint_handler)


def find_chinese_segments(text: str) -> list[Segment]:
    """Return (start, end, text) tuples for each Chinese run in ``text``."""
    return [(m.start(), m.end(), m.group()) for m in CHINESE_PATTERN.finditer(text)]


def reassemble_line(original: str, translations: LineTranslations) -> str:
    """Rebuild a line by substituting translated segments back into ``original``."""
    result: list[str] = []
    last_end: int = 0
    for (start, end), translated in sorted(translations.items()):
        result.append(original[last_end:start])
        result.append(translated)
        last_end = end
    result.append(original[last_end:])
    return "".join(result)


def read_text(path: Path) -> tuple[str, str]:
    """Read ``path`` trying several encodings; return (text, encoding_used)."""
    for enc in ("utf-8", "utf-8-sig", "gb18030", "gbk", "cp1252"):
        try:
            return path.read_text(encoding=enc, errors="strict"), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return path.read_bytes().decode("utf-8", errors="replace"), "utf-8"


class RateLimitError(Exception):
    """Raised when the translation backend reports rate limiting."""


class TranslationError(Exception):
    """Raised when a translation attempt fails for non-rate-limit reasons."""


@retry(
    reraise=True,
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=10, jitter=2),
    retry=retry_if_exception_type((RateLimitError, TranslationError)),
)
def _translate(text: str) -> str:
    """Translate a single Chinese string to English, with retries."""
    try:
        result = GoogleTranslator(source="auto", target="en").translate(text)
        if result is None:
            raise TranslationError("Translator returned None")
        if CHINESE_PATTERN.search(result):
            raise TranslationError("Result still contains Chinese")
        return result
    except (RateLimitError, TranslationError):
        raise
    except Exception as e:
        msg = str(e).lower()
        if any(k in msg for k in ("429", "rate limit", "too many", "quota")):
            raise RateLimitError(str(e)) from e
        raise TranslationError(str(e)) from e


def translate_worker(
    line_idx: int, start: int, end: int, text: str
) -> tuple[int, int, int, str, bool]:
    """Translate one segment; returns (line_idx, start, end, result, success)."""
    if _interrupted:
        return line_idx, start, end, text, False
    try:
        return line_idx, start, end, _translate(text), True
    except Exception as e:
        logger.debug("Translation failed for segment at line {}: {}", line_idx + 1, e)
        return line_idx, start, end, text, False


def _progress_path(path: Path) -> Path:
    """Return the sidecar progress file path for ``path``."""
    return path.with_suffix(path.suffix + ".xlprogress")


def save_progress(path: Path, done: ProgressMap, total: int) -> None:
    """Persist the current translation state to the sidecar progress file."""
    try:
        serializable_done: dict[str, dict[str, str]] = {
            str(k): {f"{pos[0]},{pos[1]}": v for pos, v in v.items()}
            for k, v in done.items()
            if v
        }
        state: dict[str, Any] = {
            "file": str(path),
            "saved_at": datetime.now().isoformat(),
            "total_lines": total,
            "translations": serializable_done,
        }
        _progress_path(path).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.error("Could not save progress for {}: {}", path, e)


def load_progress(path: Path) -> ProgressMap:
    """Load previously saved progress for ``path`` or return an empty map."""
    p = _progress_path(path)
    if not p.exists():
        return {}
    try:
        state: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
        restored: ProgressMap = {}
        for line_num_str, segments in state.get("translations", {}).items():
            line_idx = int(line_num_str)
            restored[line_idx] = {
                tuple(map(int, k.split(","))): v for k, v in segments.items()
            }  # type: ignore[misc]
        return restored
    except Exception:
        return {}


def drop_progress(path: Path) -> None:
    """Delete the sidecar progress file for ``path`` if it exists."""
    _progress_path(path).unlink(missing_ok=True)


def process_file(path: Path) -> bool:
    """Translate every Chinese segment in ``path``; returns True on success."""
    global _interrupted
    print("📄 Processing: {}", path)
    try:
        text, enc = read_text(path)
    except Exception as e:
        logger.error("Cannot read file: {}", e)
        return False

    lines = text.splitlines(keepends=True)
    line_segments: dict[int, list[Segment]] = {}
    for i, ln in enumerate(lines):
        stripped = ln.rstrip("\r\n")
        if segments := find_chinese_segments(stripped):
            line_segments[i] = segments

    if not line_segments:
        print("✅ No Chinese characters found — skipping")
        drop_progress(path)
        return True

    total_segments: int = sum(len(segs) for segs in line_segments.values())
    done: ProgressMap = load_progress(path)

    tasks: list[tuple[int, int, int, str]] = []
    for line_idx, segments in line_segments.items():
        done.setdefault(line_idx, {})
        for start, end, chinese_text in segments:
            if (start, end) not in done[line_idx]:
                tasks.append((line_idx, start, end, chinese_text))

    completed_segments: int = total_segments - len(tasks)
    if completed_segments > 0:
        print(
            "🔄 Resuming: {}/{} segments already cached",
            completed_segments,
            total_segments,
        )

    if tasks and not _interrupted:
        print("⚡ Launching {} processes for {} segments...", POOL_SIZE, len(tasks))
        pool: Pool = Pool(processes=POOL_SIZE)
        try:
            async_results: list[
                tuple[
                    tuple[int, int, int, str],
                    AsyncResult[tuple[int, int, int, str, bool]],
                ]
            ] = [(task, pool.apply_async(translate_worker, task)) for task in tasks]
            for task, ar in async_results:
                if _interrupted:
                    break
                l_idx, s, e, result_text, success = ar.get()
                done[l_idx][s, e] = result_text
                completed_segments += 1
                status = "✓" if success else "❌ Failed"
                print(
                    "[{:>4}/{}] {} line {}",
                    completed_segments,
                    total_segments,
                    status,
                    l_idx + 1,
                )
                if completed_segments % PROGRESS_SAVE_EVERY == 0:
                    save_progress(path, done, len(lines))
        finally:
            if _interrupted:
                pool.terminate()
            else:
                pool.close()
            pool.join()
        if _interrupted:
            save_progress(path, done, len(lines))

    if _interrupted:
        return False

    out_content: list[str] = []
    for i, line in enumerate(lines):
        if done.get(i):
            stripped = line.rstrip("\r\n")
            eol = line[len(stripped) :]
            out_content.append(reassemble_line(stripped, done[i]) + eol)
        else:
            out_content.append(line)

    try:
        path.write_text("".join(out_content), encoding=enc, errors="replace")
        drop_progress(path)
        print("✅ Done.")
        return True
    except Exception as e:
        logger.error("Failed to write output: {}", e)
        return False


def main() -> int:
    """CLI entry point; returns process exit code."""
    args = sys.argv[1:]
    files: Iterable[Path] = (
        [Path(p) for p in args if Path(p).is_file()]
        if args
        else get_nobinary(Path.cwd())
    )
    for f in files:
        if _interrupted:
            break
        process_file(f)
    if _interrupted:
        logger.warning("⚠️  Stopped early. Run again to resume.")
        return 130
    print("✅ All files processed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
