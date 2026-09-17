#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

MAX_CHUNK_CHARS: Final[int] = 4800
DELAY_BETWEEN_CHUNKS: Final[float] = 1.2
DELAY_BETWEEN_FILES: Final[float] = 3.0
MAX_RETRIES: Final[int] = 5
PROGRESS_SAVE_EVERY: Final[int] = 5
SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
_interrupted: bool = False


def _sigint_handler(sig: int, frame: object) -> None:
    global _interrupted
    print("\n⚠️  Ctrl+C — finishing current chunk then stopping.")
    _interrupted = True


signal.signal(signal.SIGINT, _sigint_handler)


class RateLimitError(Exception):
    pass


class TranslationError(Exception):
    pass


def read_text(path: Path) -> tuple[str, str]:
    encodings = ("utf-8", "utf-8-sig", "utf-16", "cp1258", "gb18030")
    for enc in encodings:
        try:
            return (path.read_text(encoding=enc, errors="strict"), enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return (path.read_bytes().decode("utf-8", errors="replace"), "utf-8")


def split_into_chunks(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks = []
    remaining = text
    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        cut = window.rfind("\n\n")
        if cut == -1 or cut < max_chars // 4:
            cut = window.rfind("\n")
        if cut == -1 or cut < max_chars // 4:
            cut = window.rfind(" ")
        if cut == -1:
            cut = max_chars
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


@retry(
    reraise=True,
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=3, max=90, jitter=4),
    retry=retry_if_exception_type((RateLimitError, TranslationError)),
    before_sleep=before_sleep_log(logger, logging.DEBUG),
)
def _translate_chunk(text: str) -> str:
    try:
        result = GoogleTranslator(source="vi", target="en").translate(text)
        if not result or not result.strip():
            raise TranslationError("Empty result returned from translator")
        return result
    except Exception as e:
        msg = str(e).lower()
        if any(k in msg for k in ("429", "rate limit", "too many", "quota")):
            print("   ⏳ Rate limited — backing off…")
            raise RateLimitError(str(e)) from e
        if any(k in msg for k in ("timeout", "timed out", "connection", "reset")):
            raise TranslationError(str(e)) from e
        raise TranslationError(str(e)) from e


def translate_chunk_safe(text: str, idx: int) -> tuple[str, bool]:
    try:
        return (_translate_chunk(text), True)
    except Exception as e:
        print(f"   ❌ Chunk {idx} failed after all retries: {e}")
        return (text, False)


def _progress_path(src: Path) -> Path:
    return src.with_suffix(src.suffix + ".viprogress")


def save_progress(src: Path, done: dict[int, str], total: int) -> None:
    try:
        state = {
            "source": str(src),
            "saved_at": datetime.now().isoformat(),
            "total_chunks": total,
            "chunks": {str(k): v for k, v in done.items()},
        }
        _progress_path(src).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"   ⚠️  Could not save progress: {e}")


def load_progress(src: Path) -> dict[int, str]:
    p = _progress_path(src)
    if not p.exists():
        return {}
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
        if Path(state.get("source", "")) != src:
            return {}
        restored = {int(k): v for k, v in state.get("chunks", {}).items()}
        print(f"   🔄 Resuming: {len(restored)} chunk(s) already done")
        return restored
    except Exception:
        return {}


def drop_progress(src: Path) -> None:
    _progress_path(src).unlink(missing_ok=True)


def get_output_path(src: Path) -> Path:
    return src.with_suffix(src.suffix + ".en")


def process_file(path: Path) -> bool:
    global _interrupted
    out = get_output_path(path)
    print(f"\n📄 {path.name}  →  {out.name}")
    try:
        text, _ = read_text(path)
    except Exception as e:
        print(f"   ❌ Cannot read: {e}")
        return False
    if not text.strip():
        print("   ⚠️  File is empty — skipping")
        return True
    chunks = split_into_chunks(text)
    total = len(chunks)
    print(f"   📦 {total} chunk(s)  |  file size: {len(text):,} chars")
    done = load_progress(path)
    failed_count = 0
    for i, chunk in enumerate(chunks):
        if _interrupted:
            save_progress(path, done, total)
            print("   💾 Progress saved.")
            return False
        if i in done:
            print(f"   [{i + 1:>3}/{total}] ⏭  skipped (cached)")
            continue
        translated, ok = translate_chunk_safe(chunk, i)
        done[i] = translated
        if not ok:
            failed_count += 1
        preview = chunk[:40].replace("\n", "↵").strip()
        status = "✓" if ok else "✗"
        print(f"   [{i + 1:>3}/{total}] {status}  {preview!r}…")
        if (i + 1) % PROGRESS_SAVE_EVERY == 0:
            save_progress(path, done, total)
        if i < total - 1 and (not _interrupted):
            time.sleep(DELAY_BETWEEN_CHUNKS)
    translated_text = "\n".join(done[i] for i in range(total))
    try:
        out.write_text(translated_text, encoding="utf-8")
        drop_progress(path)
        if failed_count:
            print(
                f"   ⚠️  Done with {failed_count} chunk(s) untranslated — check {out.name}"
            )
        else:
            print(f"   ✅ Saved → {out}")
        return True
    except Exception as e:
        print(f"   ❌ Failed to write output: {e}")
        return False


def main() -> None:
    paths = [
        p for p in Path.cwd().glob("*.txt") if p.is_file() and p.name not in SKIP_DIRS
    ]
    if not paths:
        print("No .txt files found to translate.")
        return
    for path in sorted(paths):
        if not process_file(path):
            break
        time.sleep(DELAY_BETWEEN_FILES)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n👋 Processed stopped by user.")
        sys.exit(1)
