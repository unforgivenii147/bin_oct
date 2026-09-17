#!/data/data/com.termux/files/home/.local/bin/python
"""
tpv - a terminal PDF viewer that needs no Python PDF bindings.

Pages are rasterised by shelling out to one of the native PDF renderers
that Termux ships as prebuilt 32-bit ARM binaries:

    * Ghostscript          `gs`         (pkg install ghostscript)
    * poppler              `pdftoppm`   (pkg install poppler)
    * MuPDF tools          `mutool`     (pkg install mupdf-tools)

Every one of them can emit a binary PPM (P6) image, which is just an
ASCII header followed by raw RGB bytes -- so the parser below is pure
Python and needs no Pillow/numpy.  Each page is then painted into the
terminal using 24-bit-colour "half block" characters (U+2580): the
foreground colour paints the upper pixel of a cell, the background
colour the lower one, doubling the vertical resolution.

Usage:
    python tpv.py document.pdf [-p PAGE] [-z ZOOM] [-b BACKEND]

Keys:
    q / Esc / Ctrl-C    quit
    j / Down            scroll down one line
    k / Up              scroll up one line
    h / Left            scroll left
    l / Right           scroll right
    Space / PgDn / f    next screen (next page when already at the bottom)
    b / PgUp            prev screen (prev page when already at the top)
    n / N / p           next / previous page
    g / Home            top of page
    G / End             bottom of page
    + / -               zoom in / out
    0                   reset zoom and scroll
"""

from __future__ import annotations

import argparse
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import termios
import tty


# ---------------------------------------------------------------------------
# ANSI escape sequences
# ---------------------------------------------------------------------------
RESET = "\x1b[0m"
HOME = "\x1b[H"
CLEAR = "\x1b[2J"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
ENTER_ALT = "\x1b[?1049h"  # switch to the alternate screen buffer
LEAVE_ALT = "\x1b[?1049l"
REVERSE = "\x1b[7m"

HALF_BLOCK = "\u2580"  # fg paints the top pixel, bg the bottom pixel

DEVNULL = subprocess.DEVNULL
WHITESPACE = b" \t\r\n\v\f"
PAGES_RE = re.compile(rb"^Pages:\s*(\d+)", re.MULTILINE)
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


# ---------------------------------------------------------------------------
# PPM (P6) parsing
# ---------------------------------------------------------------------------
def parse_ppm(data: bytes) -> tuple[int, int, bytes]:
    """Parse a binary PPM (P6) image.

    A P6 file looks like::

        P6<ws>WIDTH<ws>HEIGHT<ws>MAXVAL<ws><W*H*3 raw RGB bytes>

    where ``<ws>`` is any run of whitespace and ``#`` starts a comment
    that runs to the end of the line.  MAXVAL is almost always 255.

    Returns ``(width, height, rgb_samples)``.  Raises ``RuntimeError``
    on malformed input.
    """
    if len(data) < 2 or data[:2] != b"P6":
        raise RuntimeError("renderer did not produce a P6 PPM image")

    pos = 2
    n = len(data)
    fields: list[int] = []

    # Read the three header integers, skipping whitespace and comments.
    while len(fields) < 3:
        while pos < n and data[pos] in WHITESPACE:
            pos += 1
        if pos >= n:
            raise RuntimeError("truncated PPM header")
        if data[pos] == 0x23:  # '#' comment
            while pos < n and data[pos] != 0x0A:
                pos += 1
            continue
        start = pos
        while pos < n and data[pos] not in WHITESPACE:
            pos += 1
        try:
            fields.append(int(data[start:pos]))
        except ValueError:
            raise RuntimeError("malformed PPM header") from None

    pos += 1  # one whitespace after maxval
    w, h, maxval = fields
    if maxval != 255:
        raise RuntimeError(f"unsupported PPM maxval {maxval}")

    need = w * h * 3
    raster = data[pos : pos + need]
    if len(raster) != need:
        raise RuntimeError("truncated PPM raster")
    return w, h, raster


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------
class RenderError(RuntimeError):
    """Raised when a backend cannot produce an image for a page."""


class Renderer:
    """Rasterises PDF pages by spawning an external command line tool.

    All three supported tools can write a P6 PPM; from this class's point
    of view they are interchangeable, apart from how you ask for a given
    pixel width (gs wants a resolution, the other two take it directly).
    """

    CACHE_LIMIT = 6  # rendered pages kept in memory
    BACKENDS = ("gs", "pdftoppm", "mutool")
    # A short hint used when a chosen backend is missing on PATH.
    INSTALL_HINT = {
        "gs": "ghostscript",
        "pdftoppm": "poppler",
        "mutool": "mupdf-tools",
    }

    def __init__(self, path: str, backend: str | None = None) -> None:
        self.path = path
        self.tool = self._detect_tool(backend)
        self._tmp = tempfile.mkdtemp(prefix="tpv-")
        # (page_index, pixel_width) -> (w, h, rgb_bytes)
        self._cache: dict[tuple[int, int], tuple[int, int, bytes]] = {}
        # page_index -> (width_points, height_points); only gs needs this
        self._pt_cache: dict[int, tuple[float, float]] = {}
        self._count: int | None = None

    # -- setup -------------------------------------------------------------
    @classmethod
    def _detect_tool(cls, backend: str | None) -> str:
        """Pick a backend, honouring an explicit request if given."""
        if backend:
            if backend not in cls.BACKENDS:
                sys.exit(
                    f"tpv: unknown backend {backend!r} "
                    f"(choose from {', '.join(cls.BACKENDS)})"
                )
            if not shutil.which(backend):
                sys.exit(
                    f"tpv: backend {backend!r} not found on PATH.\n"
                    f"    pkg install {cls.INSTALL_HINT[backend]}"
                )
            return backend

        # No explicit choice: first one found on PATH wins.
        for name in cls.BACKENDS:
            if shutil.which(name):
                return name

        sys.exit(
            "tpv: no PDF rasteriser found.\n"
            "Install one of these Termux packages and retry:\n"
            "    pkg install ghostscript    (provides gs)\n"
            "    pkg install poppler        (provides pdftoppm + pdfinfo)\n"
            "    pkg install mupdf-tools    (provides mutool)"
        )

    def close(self) -> None:
        """Remove the scratch directory."""
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- page count --------------------------------------------------------
    def page_count(self) -> int:
        """Number of pages in the document (queried once, then cached).

        Tries the cheapest source first: pdfinfo (poppler) if present,
        then Ghostscript.  mutool has no equivalent one-liner for a bare
        count, so it is only reached if the first two are both absent.
        """
        if self._count is not None:
            return self._count

        # 1. pdfinfo -- trivial and fast, but requires poppler.
        if shutil.which("pdfinfo"):
            try:
                res = subprocess.run(
                    ["pdfinfo", self.path],
                    stdout=subprocess.PIPE,
                    stderr=DEVNULL,
                    timeout=60,
                )
                m = PAGES_RE.search(res.stdout)
                if res.returncode == 0 and m:
                    self._count = int(m.group(1))
                    return self._count
            except (OSError, subprocess.SubprocessError):
                pass

        # 2. Ghostscript -- works even on a gs-only install, as long as
        #    the sandbox permits reading the file.  See _gs_page_points
        #    for why --permit-file-read is required on gs >= 9.50.
        if shutil.which("gs"):
            script = (
                f"{self._ps_string(self.path)} (r) file runpdfbegin "
                f"pdfpagecount == quit"
            )
            argv = [
                "gs",
                "-q",
                "-dNODISPLAY",
                "-dBATCH",
                "-dNOPAUSE",
                f"--permit-file-read={self.path}",
                "-c",
                script,
            ]
            try:
                res = subprocess.run(
                    argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60
                )
                if res.returncode == 0:
                    self._count = int(res.stdout.strip() or b"0")
                    if self._count:
                        return self._count
            except (OSError, subprocess.SubprocessError, ValueError):
                pass

        # 3. mutool info -- parse "Pages: N" out of the human-readable dump.
        if shutil.which("mutool"):
            try:
                res = subprocess.run(
                    ["mutool", "info", self.path],
                    stdout=subprocess.PIPE,
                    stderr=DEVNULL,
                    timeout=60,
                )
                m = PAGES_RE.search(res.stdout)
                if res.returncode == 0 and m:
                    self._count = int(m.group(1))
                    return self._count
            except (OSError, subprocess.SubprocessError):
                pass

        raise RenderError("could not determine the page count")

    # -- Ghostscript helpers ----------------------------------------------
    @staticmethod
    def _ps_string(s: str) -> str:
        """Escape a Python string as a PostScript literal string."""
        return "(" + "".join("\\" + c if c in "()\\" else c for c in s) + ")"

    def _gs_page_points(self, index: int) -> tuple[float, float]:
        """Page size in points, CropBox-aware and rotation-aware.

        gs needs a *resolution* rather than a target pixel width, so to
        hit a given width we first need the page's physical size:

            dpi = pixel_width * 72 / page_width_in_points

        The query runs once per page and is cached.  Note that gs applies
        /Rotate when rendering to a raster device, so we swap width and
        height for 90/270 degree pages to keep the DPI math consistent
        with what actually comes back.

        Since gs 9.50 the PostScript interpreter is sandboxed: the
        `file` operator refuses paths that were not pre-declared on the
        command line.  `-dNOSAFER` alone is not enough any more; the
        supported escape hatch is `--permit-file-read=<path>`, which
        grants read access to exactly the one file we care about.
        """
        hit = self._pt_cache.get(index)
        if hit is not None:
            return hit

        p = index + 1
        pdf = self._ps_string(self.path)
        # Emit the four CropBox (or MediaBox) coordinates, then the
        # /Rotate value, each via `==` which appends a newline.
        script = (
            f"{pdf} (r) file runpdfbegin "
            f"{p} pdfgetpage "
            f"dup /CropBox known {{ /CropBox get }} {{ pop /MediaBox get }} ifelse "
            f"{{ == == == == }} stopped pop "
            f"{p} pdfgetpage /Rotate known "
            f"{{ {p} pdfgetpage /Rotate get }} {{ 0 }} ifelse == "
            f"quit"
        )
        argv = [
            "gs",
            "-q",
            "-dNODISPLAY",
            "-dBATCH",
            "-dNOPAUSE",
            f"--permit-file-read={self.path}",
            "-c",
            script,
        ]
        try:
            res = subprocess.run(
                argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RenderError(f"gs page query failed: {exc}") from None
        if res.returncode != 0:
            msg = res.stderr.decode("utf-8", "replace").strip()
            raise RenderError(msg or "gs page query failed")

        lines = [
            ln.strip() for ln in res.stdout.decode("latin-1").splitlines() if ln.strip()
        ]
        # We expect at least 5 numbers: four box coordinates + rotation.
        nums = [float(v) for v in NUMBER_RE.findall(" ".join(lines))]
        if len(nums) < 5:
            raise RenderError("gs page query returned unexpected output")

        llx, lly, urx, ury = nums[:4]
        rotate = int(nums[-1])

        w = abs(urx - llx)
        h = abs(ury - lly)
        if rotate % 180 == 90:
            w, h = h, w
        if w <= 0 or h <= 0:
            raise RenderError("gs reported an empty page")

        self._pt_cache[index] = (w, h)
        return w, h

    # -- rendering ---------------------------------------------------------
    def _wipe_tmp(self) -> None:
        """Clear the scratch directory before a backend writes to it."""
        for name in os.listdir(self._tmp):
            try:
                os.unlink(os.path.join(self._tmp, name))
            except OSError:
                pass

    def _run_gs(self, index: int, width: int) -> bytes:
        """Render one page with Ghostscript's ppmraw device."""
        pw, _ph = self._gs_page_points(index)
        dpi = max(4.0, width * 72.0 / pw)

        out = os.path.join(self._tmp, "page.ppm")
        argv = [
            "gs",
            "-q",
            "-dBATCH",
            "-dNOPAUSE",
            "-sDEVICE=ppmraw",
            "-dUseCropBox",  # match the size query above
            "-dTextAlphaBits=4",  # anti-aliased text...
            "-dGraphicsAlphaBits=4",  # ...and graphics
            f"-r{dpi:.3f}",
            f"-dFirstPage={index + 1}",
            f"-dLastPage={index + 1}",
            f"-sOutputFile={out}",
            self.path,  # as an input file -> SAFER ok
        ]
        res = subprocess.run(argv, stdout=DEVNULL, stderr=subprocess.PIPE, timeout=300)
        if res.returncode != 0:
            raise RenderError(
                res.stderr.decode("utf-8", "replace").strip() or "gs failed"
            )
        try:
            with open(out, "rb") as fh:
                return fh.read()
        except OSError:
            raise RenderError("gs produced no output") from None

    def _run_pdftoppm(self, index: int, width: int) -> bytes:
        """Render one page with poppler's pdftoppm."""
        self._wipe_tmp()
        root = os.path.join(self._tmp, "page")
        argv = [
            "pdftoppm",
            "-f",
            str(index + 1),
            "-l",
            str(index + 1),
            "-scale-to-x",
            str(width),
            "-scale-to-y",
            "-1",  # keep the aspect ratio
            "-singlefile",
            self.path,
            root,
        ]
        res = subprocess.run(argv, stdout=DEVNULL, stderr=subprocess.PIPE, timeout=300)
        if res.returncode != 0:
            raise RenderError(
                res.stderr.decode("utf-8", "replace").strip() or "pdftoppm failed"
            )

        # -singlefile names the output "<root>.ppm" ... in theory.
        out = root + ".ppm"
        if not os.path.exists(out):
            leftovers = [
                os.path.join(self._tmp, f) for f in sorted(os.listdir(self._tmp))
            ]
            if not leftovers:
                raise RenderError("pdftoppm produced no output")
            out = leftovers[0]

        with open(out, "rb") as fh:
            return fh.read()

    def _run_mutool(self, index: int, width: int) -> bytes:
        """Render one page with MuPDF's mutool draw."""
        out = os.path.join(self._tmp, "page.ppm")
        argv = [
            "mutool",
            "draw",
            "-F",
            "ppm",
            "-o",
            out,
            "-w",
            str(width),
            self.path,
            str(index + 1),
        ]
        res = subprocess.run(argv, stdout=DEVNULL, stderr=subprocess.PIPE, timeout=300)
        if res.returncode != 0:
            raise RenderError(
                res.stderr.decode("utf-8", "replace").strip() or "mutool draw failed"
            )
        try:
            with open(out, "rb") as fh:
                return fh.read()
        except OSError:
            raise RenderError("mutool draw produced no output") from None

    # -- dispatch ----------------------------------------------------------
    def page(self, index: int, width: int) -> tuple[int, int, bytes]:
        """Return ``(width, height, rgb_bytes)`` for a page, with caching.

        The cache is what keeps scrolling cheap: the backend only runs
        when the page number or the render width changes.
        """
        key = (index, width)
        hit = self._cache.get(key)
        if hit is not None:
            return hit

        runner = {
            "gs": self._run_gs,
            "pdftoppm": self._run_pdftoppm,
            "mutool": self._run_mutool,
        }[self.tool]
        try:
            raw = runner(index, width)
        except subprocess.TimeoutExpired:
            raise RenderError(f"{self.tool} timed out") from None

        result = parse_ppm(raw)

        if len(self._cache) >= self.CACHE_LIMIT:
            self._cache.clear()
        self._cache[key] = result
        return result


# ---------------------------------------------------------------------------
# Keyboard input
# ---------------------------------------------------------------------------
def read_key(fd: int, timeout: float | None = None) -> str | None:
    """Read one logical key from *fd*.

    Returns a string such as ``"j"`` or ``"\\x1b[A"`` (Up), or ``None`` if
    *timeout* elapsed with no input.  A lone ``"\\x1b"`` means Escape.

    Escape sequences are swallowed whole: after the initial ESC we keep
    reading (with a short per-byte deadline) until a final byte arrives,
    so a bare ESC keypress still returns promptly instead of blocking.
    """
    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return None

    first = os.read(fd, 1)
    if not first:  # EOF - terminal went away
        return "q"
    if first != b"\x1b":
        return first.decode("utf-8", "replace")

    seq = bytearray(first)
    while len(seq) < 8:
        ready, _, _ = select.select([fd], [], [], 0.03)
        if not ready:
            break
        seq += os.read(fd, 1)
        if seq[-1:].isalpha() or seq[-1:] == b"~":
            break
    return seq.decode("latin-1")


# ---------------------------------------------------------------------------
# Viewer
# ---------------------------------------------------------------------------
class Viewer:
    MIN_ZOOM = 0.25
    MAX_ZOOM = 8.0
    ZOOM_STEP = 1.25
    MAX_RENDER_WIDTH = 4000  # guard against absurd raster allocations

    def __init__(
        self, path: str, page: int = 1, zoom: float = 1.0, backend: str | None = None
    ) -> None:
        self.path = path
        self.renderer = Renderer(path, backend)
        self.page_count = self.renderer.page_count()
        if self.page_count == 0:
            raise RenderError("document contains no pages")

        self.page_index = max(0, min(page - 1, self.page_count - 1))
        self.zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, zoom))
        self.x = 0  # horizontal scroll, in pixels
        self.y = 0  # vertical scroll, in pixels
        self.running = True

    # -- geometry ----------------------------------------------------------
    def term_size(self) -> tuple[int, int]:
        size = shutil.get_terminal_size((80, 24))
        return size.columns, size.lines

    def view_rows(self) -> int:
        """Terminal rows available for the page (the last row is status)."""
        _, lines = self.term_size()
        return max(1, lines - 1)

    def render_width(self) -> int:
        """Pixel width the page is rasterised at."""
        cols, _ = self.term_size()
        return max(1, min(self.MAX_RENDER_WIDTH, int(round(cols * self.zoom))))

    def page_px_size(self) -> tuple[int, int]:
        w, h, _ = self.renderer.page(self.page_index, self.render_width())
        return w, h

    # -- painting ----------------------------------------------------------
    @staticmethod
    def _paint_row(data: bytes, w: int, h: int, top: int, x0: int, cols: int) -> str:
        """Render one terminal row (two pixel rows) as an ANSI string.

        The cell column ``i`` shows pixel row ``top`` in the foreground
        of a U+2580 (upper half block) and pixel row ``top+1`` in the
        background.  Colour escape codes are only emitted when a colour
        actually changes, which keeps the output compact.
        """
        bottom = top + 1
        have_top = 0 <= top < h
        have_bot = 0 <= bottom < h
        base_t = top * w * 3
        base_b = bottom * w * 3

        out: list[str] = []
        last_fg: tuple[int, int, int] | None = None
        last_bg: tuple[int, int, int] | None = None
        blank = False

        for i in range(cols):
            x = x0 + i
            if x >= w:  # past the right edge of the page
                if not blank:
                    out.append(RESET)
                    last_fg = last_bg = None
                    blank = True
                out.append(" ")
                continue

            blank = False
            if have_top:
                p = base_t + x * 3
                fg = (data[p], data[p + 1], data[p + 2])
            else:
                fg = (0, 0, 0)

            if have_bot:
                p = base_b + x * 3
                bg = (data[p], data[p + 1], data[p + 2])
            else:
                bg = (0, 0, 0)

            if fg != last_fg:
                out.append(f"\x1b[38;2;{fg[0]};{fg[1]};{fg[2]}m")
                last_fg = fg
            if bg != last_bg:
                out.append(f"\x1b[48;2;{bg[0]};{bg[1]};{bg[2]}m")
                last_bg = bg
            out.append(HALF_BLOCK)

        out.append(RESET)
        return "".join(out)

    def _status(self, cols: int, note: str = "") -> str:
        """The reverse-video line at the bottom of the screen."""
        name = os.path.basename(self.path)
        if note:
            line = f" {note} "
        else:
            try:
                _, h = self.page_px_size()
            except RenderError:
                h = 0
            max_y = max(0, h - self.view_rows() * 2)
            pct = 100 if max_y == 0 else int(round(100 * self.y / max_y))
            line = (
                f" {name}  {self.page_index + 1}/{self.page_count}"
                f"  {pct:3d}%  {self.zoom:.2f}x "
                f"[{self.renderer.tool}] "
            )
        hint = " q quit  n/p page  j/k scroll  +/- zoom "
        if len(line) + len(hint) <= cols:
            line = line + " " * (cols - len(line) - len(hint)) + hint
        return REVERSE + line[:cols].ljust(cols) + RESET

    def draw(self) -> None:
        """Repaint the whole screen."""
        cols, _ = self.term_size()
        rows = self.view_rows()
        width = self.render_width()

        error: str | None = None
        try:
            w, h, data = self.renderer.page(self.page_index, width)
        except RenderError as exc:
            error = str(exc)
            w = h = 1
            data = b"\x00\x00\x00"
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            w = h = 1
            data = b"\x00\x00\x00"

        # Clamp scrolling into range.
        if error is None:
            max_y = max(0, h - rows * 2)
            self.y = max(0, min(self.y, max_y))
            max_x = max(0, w - cols)
            self.x = max(0, min(self.x, max_x))

        buf = [HOME]
        if error:
            buf.append(RESET)
            buf.append(f" {error} ".ljust(cols)[:cols])
            for _ in range(rows - 1):
                buf.append("\r\n")
        else:
            for row in range(rows):
                buf.append(self._paint_row(data, w, h, self.y + row * 2, self.x, cols))
                # Raw mode: \n moves down but keeps the column, so we need CR.
                buf.append("\r\n")

        buf.append(RESET)
        buf.append(self._status(cols, error or ""))
        sys.stdout.write("".join(buf))
        sys.stdout.flush()

    # -- navigation --------------------------------------------------------
    def goto_page(self, index: int) -> None:
        if 0 <= index < self.page_count:
            self.page_index = index
            self.x = self.y = 0

    def screen_down(self) -> None:
        """Scroll a full screen; at the bottom, turn the page."""
        step = self.view_rows() * 2
        _, h = self.page_px_size()
        max_y = max(0, h - step)
        if self.y >= max_y:
            if self.page_index + 1 < self.page_count:
                self.page_index += 1
                self.x = self.y = 0
        else:
            self.y = min(self.y + step, max_y)

    def screen_up(self) -> None:
        """Scroll a full screen; at the top, go back and land at the bottom."""
        step = self.view_rows() * 2
        if self.y <= 0:
            if self.page_index > 0:
                self.page_index -= 1
                self.x = 0
                _, h = self.page_px_size()
                self.y = max(0, h - step)
        else:
            self.y = max(0, self.y - step)

    def set_zoom(self, value: float) -> None:
        """Change zoom, keeping the current reading position roughly stable."""
        value = max(self.MIN_ZOOM, min(self.MAX_ZOOM, value))
        if value == self.zoom:
            return
        old_w = self.render_width()
        _, old_h = self.page_px_size()  # cached from the current frame
        frac = self.y / old_h if old_h else 0.0
        self.zoom = value
        new_w = self.render_width()
        # Cheap proportional estimate; draw() clamps it exactly afterwards.
        new_h = max(1, round(old_h * new_w / old_w))
        self.y = int(frac * new_h)

    # -- key dispatch ------------------------------------------------------
    def handle(self, key: str) -> None:
        if key in ("q", "Q", "\x03") or key == "\x1b":
            self.running = False

        elif key in ("j", "\x1b[B", "\n", "\r"):
            self.y += 2
        elif key in ("k", "\x1b[A"):
            self.y -= 2
        elif key in ("h", "\x1b[D"):
            self.x -= 4
        elif key in ("l", "\x1b[C"):
            self.x += 4

        elif key in (" ", "\x1b[6~", "f", "J"):
            self.screen_down()
        elif key in ("b", "\x1b[5~", "K"):
            self.screen_up()

        elif key == "n":
            self.goto_page(self.page_index + 1)
        elif key in ("N", "p"):
            self.goto_page(self.page_index - 1)

        elif key in ("g", "\x1b[H", "\x1b[1~", "\x1b[7~", "\x1bOH"):
            self.x = self.y = 0
        elif key in ("G", "\x1b[F", "\x1b[4~", "\x1b[8~", "\x1bOF"):
            self.y = 1 << 30  # draw() clamps this

        elif key in ("+", "="):
            self.set_zoom(self.zoom * self.ZOOM_STEP)
        elif key in ("-", "_"):
            self.set_zoom(self.zoom / self.ZOOM_STEP)
        elif key == "0":
            self.zoom = 1.0
            self.x = self.y = 0

    # -- main loop ---------------------------------------------------------
    def run(self, fd: int) -> None:
        dirty = True
        last_size = (0, 0)

        while self.running:
            size = self.term_size()
            if size != last_size:
                last_size = size
                # The render width changed, so the cached rasters are stale.
                self.renderer._cache.clear()
                self.renderer._pt_cache.clear()
                dirty = True

            if dirty:
                self.draw()
                dirty = False

            key = read_key(fd, 0.25)  # also wakes us up on resize
            if key is None:
                continue
            self.handle(key)
            dirty = True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tpv",
        description="View a PDF file in the terminal.",
    )
    parser.add_argument("file", help="path to the PDF file")
    parser.add_argument(
        "-p",
        "--page",
        type=int,
        default=1,
        help="page to open first (1-based, default 1)",
    )
    parser.add_argument(
        "-z",
        "--zoom",
        type=float,
        default=1.0,
        help="initial zoom factor (default 1.0)",
    )
    parser.add_argument(
        "-b",
        "--backend",
        choices=Renderer.BACKENDS,
        default=None,
        help="PDF rasteriser to use (default: first one found on PATH)",
    )
    args = parser.parse_args(argv)

    if not os.path.isfile(args.file):
        parser.error(f"no such file: {args.file}")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error("must be run from an interactive terminal")

    try:
        viewer = Viewer(args.file, args.page, args.zoom, args.backend)
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"tpv: could not open {args.file!r}: {exc}")

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        sys.stdout.write(ENTER_ALT + HIDE_CURSOR + CLEAR + HOME)
        sys.stdout.flush()
        viewer.run(fd)
    except KeyboardInterrupt:
        pass
    finally:
        # Always restore the terminal, even on an unexpected exception.
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write(RESET + SHOW_CURSOR + LEAVE_ALT)
        sys.stdout.flush()
        viewer.renderer.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
