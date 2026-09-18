#!/data/data/com.termux/files/home/.local/bin/python
"""
dl — a small pip-style download manager for the command line.

Features
--------
* Three interchangeable HTTP backends (`-b python|requests|pycurl`).
* Resumable downloads via `.part` files + HTTP `Range`.
* Skips files that already exist on disk with a non-zero size.
* Chunked streaming with adaptive chunk sizes for large files.
* Reads URLs from the command line and/or from a file (`-f`).
* Concurrent downloads with a pip-flavoured progress display.
* Uses `pathlib` for every filesystem traversal.

Usage
-----
    dl https://example.com/file.iso
    dl -b requests -j 4 url1 url2 url3
    dl -f urls.txt -b pycurl
    dl -o movie.mp4 https://example.com/video
"""

from __future__ import annotations

import argparse
import hashlib
import os
import queue
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

__version__ = "2.0.0"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Adaptive chunk sizes: bigger files -> bigger reads, fewer syscalls.
CHUNK_SMALL: int = 64 * 1024  # files < 10 MB
CHUNK_MEDIUM: int = 256 * 1024  # files 10–100 MB
CHUNK_LARGE: int = 1024 * 1024  # files > 100 MB
BIG_FILE_THRESHOLD: int = 10 * 1024 * 1024
HUGE_FILE_THRESHOLD: int = 100 * 1024 * 1024

USER_AGENT: str = f"dl/{__version__} (pip-style download manager)"

# Progress-bar glyphs (pip-like).
FULL, HEAD, EMPTY = "━", "╸", " "

# Set by Ctrl-C so worker threads bail out promptly.
STOP = threading.Event()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def fmt_size(n: float | None) -> str:
    """Format a byte count with SI units, e.g. ``9.2 MB``."""
    if n is None:
        return "?"
    if n > 1000 * 1000:
        return f"{n / 1e6:.1f} MB"
    if n > 10 * 1000:
        return f"{n / 1000:.0f} kB"
    if n > 1000:
        return f"{n / 1000:.1f} kB"
    return f"{n:.0f} bytes"


def fmt_pair(done: float, total: float) -> str:
    """Render ``done/total`` with a shared unit, pip-style."""
    if total < 1000:
        return f"{done:.0f}/{total:.0f} bytes"
    if total < 1000 * 1000:
        return f"{done / 1e3:.1f}/{total / 1e3:.1f} kB"
    return f"{done / 1e6:.1f}/{total / 1e6:.1f} MB"


def fmt_time(seconds: float | None) -> str:
    """Format a duration as ``H:MM:SS``."""
    if seconds is None or seconds < 0 or seconds != seconds:
        return "--:--:--"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def fmt_bar(fraction: float | None, width: int, spin: int = 0) -> str:
    """Render a pip-style bar.  ``fraction=None`` gives an indeterminate bar."""
    if width <= 0:
        return ""
    if fraction is None:
        block = max(1, width // 5)
        pos = spin % (width + block) - block
        return "".join(FULL if pos <= i < pos + block else EMPTY for i in range(width))
    frac = min(max(fraction, 0.0), 1.0)
    filled = int(frac * width)
    if filled >= width:
        return FULL * width
    return FULL * filled + HEAD + EMPTY * (width - filled - 1)


def shorten(url: str, n: int = 42) -> str:
    """A short human label for a URL (its basename, truncated)."""
    path = urllib.parse.urlparse(url).path
    name = Path(path).name or url
    return name if len(name) <= n else name[: n - 1] + "…"


def pick_chunk_size(total: int | None) -> int:
    """Choose a streaming chunk size based on the expected file size."""
    if total is None:
        return CHUNK_MEDIUM
    if total >= HUGE_FILE_THRESHOLD:
        return CHUNK_LARGE
    if total >= BIG_FILE_THRESHOLD:
        return CHUNK_MEDIUM
    return CHUNK_SMALL


# ---------------------------------------------------------------------------
# Progress bars
# ---------------------------------------------------------------------------


class Bar:
    """State and rendering for a single download."""

    def __init__(self, label: str, total: int | None = None) -> None:
        self.label: str = label
        self.total: int | None = total
        self.done: int = 0
        self.speed: float = 0.0
        self.spin: int = 0
        self.finished: bool = False
        self.failed: bool = False
        self.skipped: bool = False
        self.error: str | None = None
        self.start: float = time.monotonic()
        self._last_t: float = self.start
        self._last_d: int = 0

    # -- helpers -----------------------------------------------------------

    @property
    def elapsed(self) -> float:
        """Seconds since this bar was created."""
        return max(time.monotonic() - self.start, 1e-6)

    def _tick(self) -> None:
        """Update the smoothed speed estimate (called from ``render``)."""
        now = time.monotonic()
        dt = now - self._last_t
        if dt < 0.15:
            return
        inst = (self.done - self._last_d) / dt
        self.speed = inst if self.speed <= 0 else 0.6 * self.speed + 0.4 * inst
        self._last_t, self._last_d = now, self.done

    def _eta(self) -> float | None:
        """Estimated seconds remaining, or ``None`` if unknown."""
        if not self.total or self.speed <= 0:
            return None
        return max(self.total - self.done, 0) / self.speed

    # -- rendering ---------------------------------------------------------

    def render(self, width: int) -> str:
        """Render this bar to a single line of at most ``width`` columns."""
        if self.skipped:
            return f"{self.label}  already downloaded ({fmt_size(self.done)})"
        if self.failed:
            return f"{self.label}: error: {self.error}"
        if self.finished:
            el = self.elapsed
            rate = self.done / el if el > 0 else 0.0
            return (
                f"{self.label}  {fmt_size(self.done)} in {fmt_time(el)} "
                f"({fmt_size(rate)}/s)"
            )

        self._tick()

        if self.total:
            frac: float | None = self.done / self.total
            parts = [
                fmt_pair(self.done, self.total),
                f"{fmt_size(self.speed)}/s",
                f"eta {fmt_time(self._eta())}",
            ]
        else:
            frac = None
            parts = [fmt_size(self.done), f"{fmt_size(self.speed)}/s"]

        tail = "  ".join(parts)
        room = width - len(tail) - 1
        prefix = ""
        if len(self.label) + 12 <= room:
            prefix = self.label + " "
            room -= len(prefix)
        if room < 5:
            return tail
        return prefix + fmt_bar(frac, room, self.spin) + " " + tail


class Progress:
    """Renders N bars in place using ANSI cursor movement."""

    def __init__(
        self,
        stream: Any | None = None,
        enabled: bool | None = None,
        final: bool = True,
    ) -> None:
        self.stream = stream if stream is not None else sys.stdout
        if enabled is None:
            enabled = bool(getattr(self.stream, "isatty", lambda: False)())
        self.enabled = enabled
        self.final = final
        self.bars: list[Bar] = []
        self.lock = threading.RLock()
        self._drawn: int = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------

    def add(self, bar: Bar) -> None:
        """Register a bar for rendering."""
        with self.lock:
            self.bars.append(bar)

    def __enter__(self) -> "Progress":
        if self.enabled:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> bool:
        self.close()
        return False

    def _loop(self) -> None:
        while not self._stop.wait(0.1):
            self.refresh()

    # -- drawing -----------------------------------------------------------

    def refresh(self) -> None:
        with self.lock:
            for b in self.bars:
                b.spin += 1
            self._paint()

    def _width(self) -> int:
        return max(shutil.get_terminal_size((80, 24)).columns - 1, 24)

    def _paint(self) -> None:
        if not self.bars:
            return
        width = self._width()
        lines = [b.render(width) for b in self.bars]
        out: list[str] = []
        if self._drawn:
            out.append(f"\x1b[{self._drawn}A")
        for ln in lines:
            out.append("\x1b[2K" + ln + "\n")
        self.stream.write("".join(out))
        self.stream.flush()
        self._drawn = len(lines)

    def close(self) -> None:
        """Stop the refresh thread and print the final lines."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

        with self.lock:
            if self.enabled and self._drawn:
                out = [f"\x1b[{self._drawn}A"]
                out.extend(["\x1b[2K\n"] * self._drawn)
                out.append(f"\x1b[{self._drawn}A")
                self.stream.write("".join(out))
                self._drawn = 0

            if self.final:
                width = self._width()
                for b in self.bars:
                    self.stream.write(b.render(width) + "\n")
            self.stream.flush()


# ---------------------------------------------------------------------------
# HTTP backends
# ---------------------------------------------------------------------------


@dataclass
class StreamInfo:
    """Metadata about the HTTP response, before reading the body."""

    status: int
    total_length: int | None  # body length as advertised (excluding offset)
    content_disposition: str | None


class Backend(ABC):
    """
    Abstract HTTP backend.

    ``open`` returns a context manager that yields ``(StreamInfo, chunks)``
    where ``chunks`` is an iterator of ``bytes``.  Implementations must
    be usable from multiple threads at once.
    """

    name: str = "?"

    @abstractmethod
    def open(
        self,
        url: str,
        offset: int,
        timeout: float,
    ) -> Iterator[tuple[StreamInfo, Iterator[bytes]]]:
        """Context manager yielding ``(info, chunks)`` for the given URL."""
        raise NotImplementedError


class PurePythonBackend(Backend):
    """Backend based on the standard library's ``urllib``."""

    name = "python"

    @contextmanager
    def open(
        self, url: str, offset: int, timeout: float
    ) -> Iterator[tuple[StreamInfo, Iterator[bytes]]]:
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"

        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=timeout)

        try:
            status = getattr(resp, "status", 200)
            length_hdr = resp.headers.get("Content-Length")
            total = int(length_hdr) if length_hdr is not None else None

            info = StreamInfo(
                status=status,
                total_length=total,
                content_disposition=resp.headers.get("Content-Disposition"),
            )
            csize = pick_chunk_size(total)

            def gen() -> Iterator[bytes]:
                while True:
                    if STOP.is_set():
                        return
                    data = resp.read(csize)
                    if not data:
                        return
                    yield data

            yield info, gen()
        finally:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass


class RequestsBackend(Backend):
    """Backend based on the popular third-party ``requests`` library."""

    name = "requests"

    def __init__(self) -> None:
        import requests  # imported lazily so it's only required when selected

        self._requests = requests

    @contextmanager
    def open(
        self, url: str, offset: int, timeout: float
    ) -> Iterator[tuple[StreamInfo, Iterator[bytes]]]:
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"

        r = self._requests.get(
            url,
            headers=headers,
            stream=True,
            timeout=timeout,
            allow_redirects=True,
        )
        try:
            r.raise_for_status()
            length_hdr = r.headers.get("Content-Length")
            total = int(length_hdr) if length_hdr is not None else None
            info = StreamInfo(
                status=r.status_code,
                total_length=total,
                content_disposition=r.headers.get("Content-Disposition"),
            )
            csize = pick_chunk_size(total)

            def gen() -> Iterator[bytes]:
                for chunk in r.iter_content(chunk_size=csize):
                    if STOP.is_set():
                        return
                    if chunk:
                        yield chunk

            yield info, gen()
        finally:
            r.close()


class PycurlBackend(Backend):
    """Backend based on ``pycurl`` (libcurl bindings)."""

    name = "pycurl"

    def __init__(self) -> None:
        import pycurl  # lazy

        self._pc = pycurl

    @contextmanager
    def open(
        self, url: str, offset: int, timeout: float
    ) -> Iterator[tuple[StreamInfo, Iterator[bytes]]]:
        pc = self._pc
        q: "queue.Queue[bytes | None]" = queue.Queue()
        headers_ready = threading.Event()
        stop_flag = threading.Event()

        # Shared state between the curl worker thread and the consumer.
        state: dict[str, Any] = {
            "status": None,
            "headers": {},
            "error": None,
        }

        def write_cb(data: bytes) -> int:
            """libcurl write callback: push body bytes into the queue."""
            if stop_flag.is_set():
                return 0  # abort the transfer
            q.put(bytes(data))
            return len(data)

        def header_cb(data: bytes) -> int:
            """libcurl header callback: parse status line + headers."""
            line = data.decode("latin-1").rstrip("\r\n")
            if line.startswith("HTTP/"):
                state["headers"] = {}
                state["status"] = None
                try:
                    state["status"] = int(line.split()[1])
                except (IndexError, ValueError):
                    pass
            elif line == "":
                # End of one response block.  Ignore redirect hops (3xx).
                st = state["status"]
                if st is not None and not (300 <= st < 400):
                    headers_ready.set()
            elif ":" in line:
                k, v = line.split(":", 1)
                state["headers"][k.strip().lower()] = v.strip()
            return len(data)

        def run() -> None:
            """Worker thread: perform the request and stream into the queue."""
            try:
                curl = pc.Curl()
                try:
                    curl.setopt(pc.URL, url)
                    curl.setopt(pc.WRITEFUNCTION, write_cb)
                    curl.setopt(pc.HEADERFUNCTION, header_cb)
                    curl.setopt(pc.TIMEOUT, max(int(timeout), 1))
                    curl.setopt(pc.CONNECTTIMEOUT, max(int(timeout), 1))
                    curl.setopt(pc.FOLLOWLOCATION, True)
                    curl.setopt(pc.USERAGENT, USER_AGENT)
                    curl.setopt(pc.ACCEPT_ENCODING, "")
                    if offset:
                        curl.setopt(pc.HTTPHEADER, [f"Range: bytes={offset}-"])
                    curl.perform()
                finally:
                    curl.close()
            except Exception as exc:  # noqa: BLE001
                state["error"] = exc
            finally:
                headers_ready.set()
                q.put(None)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        headers_ready.wait(timeout=timeout + 5)

        if state["error"] is not None and state["status"] is None:
            stop_flag.set()
            raise state["error"]
        if state["status"] is None:
            stop_flag.set()
            raise RuntimeError("no response received")

        hdrs = state["headers"]
        length_hdr = hdrs.get("content-length")
        total = int(length_hdr) if length_hdr is not None else None

        info = StreamInfo(
            status=state["status"],
            total_length=total,
            content_disposition=hdrs.get("content-disposition"),
        )

        def gen() -> Iterator[bytes]:
            while True:
                item = q.get()
                if item is None:
                    if state["error"] is not None and not stop_flag.is_set():
                        raise state["error"]
                    return
                yield item

        try:
            yield info, gen()
        finally:
            stop_flag.set()


def get_backend(name: str) -> Backend:
    """Instantiate a backend by name, with helpful import errors."""
    if name == "python":
        return PurePythonBackend()
    if name == "requests":
        try:
            return RequestsBackend()
        except ImportError as exc:
            raise SystemExit(
                "backend 'requests' requires the requests package: pip install requests"
            ) from exc
    if name == "pycurl":
        try:
            return PycurlBackend()
        except ImportError as exc:
            raise SystemExit(
                "backend 'pycurl' requires the pycurl package: pip install pycurl"
            ) from exc
    raise SystemExit(f"unknown backend: {name}")


# ---------------------------------------------------------------------------
# Filename resolution
# ---------------------------------------------------------------------------

_CD_STAR = re.compile(r"filename\*\s*=\s*[^']*''([^;]+)", re.I)
_CD_QUOTED = re.compile(r'filename\s*=\s*"([^"]*)"', re.I)
_CD_BARE = re.compile(r"filename\s*=\s*([^;]+)", re.I)


def _sanitize(name: str) -> str:
    """Strip path components and dangerous characters from a filename."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = name.strip().strip('"').strip("'").replace("\x00", "")
    return "" if name in ("", ".", "..") else name


def parse_content_disposition(cd: str | None) -> str | None:
    """Extract ``filename`` from a Content-Disposition header value."""
    if not cd:
        return None
    for pattern in (_CD_STAR, _CD_QUOTED, _CD_BARE):
        m = pattern.search(cd)
        if m:
            name = _sanitize(urllib.parse.unquote(m.group(1)))
            if name:
                return name
    return None


def guess_from_url(url: str) -> str:
    """Derive a sensible filename from a URL's path."""
    path = urllib.parse.urlparse(url).path
    name = _sanitize(urllib.parse.unquote(Path(path).name))
    return name or "index.html"


def filename_from_info(info: StreamInfo, url: str) -> str:
    """Prefer Content-Disposition, fall back to the URL's basename."""
    return parse_content_disposition(info.content_disposition) or guess_from_url(url)


def unique_path(path: Path) -> Path:
    """Return ``path`` if free, else ``name (1).ext``, ``name (2).ext``, …"""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    parent = path.parent
    i = 1
    while True:
        candidate = parent / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def part_path(outdir: Path, url: str) -> Path:
    """Stable path for the in-progress file of a given URL."""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    return outdir / f".dl-{digest}.part"


# ---------------------------------------------------------------------------
# The download itself
# ---------------------------------------------------------------------------


def download_one(
    progress: Progress,
    backend: Backend,
    url: str,
    dest_hint: Path | None,
    outdir: Path,
    resume: bool,
    timeout: float,
) -> tuple[Path, bool]:
    """
    Download a single URL to ``outdir``.

    Returns ``(final_path, was_skipped)``.  On error, raises; the caller
    collects the exception.  The bar is registered immediately so failures
    are visible in the progress display.
    """
    bar = Bar(shorten(url))
    progress.add(bar)

    try:
        part = part_path(outdir, url)
        offset = part.stat().st_size if (resume and part.exists()) else 0

        with backend.open(url, offset, timeout) as response:
            info, chunks = response

            # Reject hard errors early.
            if not (200 <= info.status < 300):
                raise RuntimeError(f"HTTP {info.status}")

            # Server ignored our Range header -> restart from scratch.
            if offset > 0 and info.status != 206:
                offset = 0
                try:
                    part.unlink()
                except FileNotFoundError:
                    pass

            # Figure out the final destination.
            if dest_hint is not None:
                final = dest_hint if dest_hint.is_absolute() else outdir / dest_hint
            else:
                final = outdir / filename_from_info(info, url)

            # Skip already-downloaded files (unless size == 0).
            if final.exists() and final.stat().st_size > 0:
                bar.done = final.stat().st_size
                bar.total = bar.done
                bar.skipped = True
                # Discard any orphaned .part file if we're not resuming.
                if part.exists() and offset > 0:
                    try:
                        part.unlink()
                    except FileNotFoundError:
                        pass
                return final, True

            bar.label = final.name
            total = info.total_length
            if total is not None:
                total += offset
            bar.total = total
            bar.done = offset

            # Stream the body straight into the .part file.
            mode = "r+b" if offset > 0 else "wb"
            with part.open(mode) as fh:
                if offset > 0:
                    fh.seek(offset)
                for chunk in chunks:
                    if STOP.is_set():
                        raise KeyboardInterrupt
                    if not chunk:
                        continue
                    fh.write(chunk)
                    bar.done += len(chunk)
                fh.flush()
                os.fsync(fh.fileno())

            if total is not None and bar.done < total:
                raise IOError(f"truncated download ({bar.done}/{total} bytes)")

        # Atomic move from .part to the final name.
        part.replace(final)
        bar.finished = True
        return final, False

    except BaseException as exc:  # noqa: BLE001 - re-raised to the caller
        bar.failed = True
        bar.error = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        raise


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the ``dl`` CLI."""
    p = argparse.ArgumentParser(
        prog="dl",
        description="pip-style download manager",
        epilog=(
            "examples:\n"
            "  dl https://example.com/a.iso\n"
            "  dl -b requests -j 4 url1 url2 url3\n"
            "  dl -f urls.txt -b pycurl\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("urls", nargs="*", metavar="URL", help="URL(s) to download")
    p.add_argument(
        "-f",
        "--file",
        action="append",
        default=[],
        metavar="FILE",
        help="read URLs from FILE (one per line, '#' comments allowed); "
        "may be given multiple times",
    )
    p.add_argument(
        "-b",
        "--backend",
        default="python",
        choices=["python", "requests", "pycurl"],
        help="HTTP backend to use (default: python)",
    )
    p.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        help="output filename (single URL only); relative paths use the CWD",
    )
    p.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=4,
        metavar="N",
        help="number of parallel downloads (default: 4)",
    )
    p.add_argument(
        "--no-resume",
        action="store_true",
        help="ignore partial files and restart from scratch",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        metavar="SECS",
        help="socket timeout in seconds (default: 30)",
    )
    p.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="suppress the progress display",
    )
    p.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"dl {__version__}",
    )
    return p


def collect_urls(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> list[str]:
    """Combine positional URLs with any URLs read from ``-f`` files."""
    urls: list[str] = list(args.urls)
    for path_str in args.file:
        fpath = Path(path_str)
        if not fpath.is_file():
            parser.error(f"file not found: {path_str}")
        for line in fpath.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    return urls


def main(argv: list[str] | None = None) -> int:
    """Entry point.  Returns a process exit status."""
    parser = build_parser()
    args = parser.parse_args(argv)

    urls = collect_urls(args, parser)
    if not urls:
        parser.error("no URLs provided (give them positionally or with -f)")
    if args.output and len(urls) > 1:
        parser.error("-o/--output can only be used with a single URL")
    if args.jobs < 1:
        parser.error("-j/--jobs must be >= 1")

    # Files always land in the current working directory — no subdir creation.
    outdir = Path.cwd()

    dest_hint: Path | None = None
    if args.output:
        dest_hint = Path(args.output)
        if dest_hint.is_absolute():
            if not dest_hint.parent.is_dir():
                parser.error(f"output directory does not exist: {dest_hint.parent}")
        elif dest_hint.parent != Path(".") and not (outdir / dest_hint.parent).is_dir():
            parser.error(f"output directory does not exist: {dest_hint.parent}")

    backend = get_backend(args.backend)
    resume = not args.no_resume

    stream = sys.stdout
    progress = Progress(
        stream,
        enabled=(not args.quiet) and bool(getattr(stream, "isatty", lambda: False)()),
        final=not args.quiet,
    )

    results: list[tuple[str, Path | None, bool, BaseException | None]] = []
    interrupted = False
    t0 = time.monotonic()

    pool = ThreadPoolExecutor(max_workers=min(args.jobs, len(urls)))
    try:
        with progress:
            # Submit every URL; only the first may use the -o hint.
            futures = {
                pool.submit(
                    download_one,
                    progress,
                    backend,
                    url,
                    dest_hint if i == 0 else None,
                    outdir,
                    resume,
                    args.timeout,
                ): url
                for i, url in enumerate(urls)
            }
            try:
                for fut in as_completed(futures):
                    url = futures[fut]
                    try:
                        path, skipped = fut.result()
                        results.append((url, path, skipped, None))
                    except BaseException as exc:  # noqa: BLE001
                        results.append((url, None, False, exc))
            except KeyboardInterrupt:
                interrupted = True
                STOP.set()
                for f in futures:
                    f.cancel()
    finally:
        STOP.set()
        pool.shutdown(wait=True, cancel_futures=True)

    elapsed = time.monotonic() - t0

    if not args.quiet:
        downloaded = skipped = failed = 0
        total_bytes = 0
        for url, path, was_skipped, exc in results:
            if exc is not None:
                failed += 1
                print(f"dl: {url}: {exc}", file=sys.stderr)
                continue
            if was_skipped:
                skipped += 1
                continue
            downloaded += 1
            if path is not None:
                try:
                    total_bytes += path.stat().st_size
                except OSError:
                    pass

        if interrupted:
            print("interrupted", file=sys.stderr)

        parts: list[str] = []
        if downloaded:
            parts.append(f"downloaded {downloaded}")
        if skipped:
            parts.append(f"skipped {skipped}")
        if failed:
            parts.append(f"failed {failed}")
        if parts:
            print(
                f"{', '.join(parts)} ({fmt_size(total_bytes)} new) "
                f"in {fmt_time(elapsed)}"
            )

    if interrupted:
        return 130
    if any(exc is not None for _, _, _, exc in results):
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
