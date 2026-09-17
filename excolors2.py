#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from pathlib import Path

from dh import is_binary

HEX_RE = re.compile(
    r"""
    (?<![0-9A-Fa-f])
    (?:
        [0-9A-Fa-f]{3}
        |[0-9A-Fa-f]{6}
        |[0-9A-Fa-f]{8}
    )
    (?![0-9A-Fa-f])
    """,
    re.VERBOSE,
)
RGBA_RE = re.compile(
    r"""
    \b
    rgba?
    \(
        \s*
        (?P<r>\d{1,3})
        \s*,\s*
        (?P<g>\d{1,3})
        \s*,\s*
        (?P<b>\d{1,3})
        (?: \s*,\s*(?P<a>[\d\.]+) )?
        \s*
    \)
    \b
    """,
    re.VERBOSE | re.IGNORECASE,
)


@dataclass(frozen=True)
class Color:
    r: int
    g: int
    b: int
    a: float = 1.0

    def as_tuple(self) -> tuple[int, int, int, float]:
        return self.r, self.g, self.b, self.a


def clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else min(x, 1.0)


def parse_hex_to_rgba(hex_body: str) -> Color:
    if len(hex_body) == 3:
        r = int(hex_body[0] * 2, 16)
        g = int(hex_body[1] * 2, 16)
        b = int(hex_body[2] * 2, 16)
        a = 1.0
    elif len(hex_body) == 6:
        r = int(hex_body[0:2], 16)
        g = int(hex_body[2:4], 16)
        b = int(hex_body[4:6], 16)
        a = 1.0
    elif len(hex_body) == 8:
        r = int(hex_body[0:2], 16)
        g = int(hex_body[2:4], 16)
        b = int(hex_body[4:6], 16)
        aa = int(hex_body[6:8], 16)
        a = aa / 255.0
    else:
        msg = f"Unexpected hex length: {len(hex_body)}"
        raise ValueError(msg)
    return Color(r=r, g=g, b=b, a=a)


def parse_rgba_match(m: re.Match) -> Color | None:
    r = int(m.group("r"))
    g = int(m.group("g"))
    b = int(m.group("b"))
    a_str = m.groupdict().get("a")
    if not (0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255):
        return None
    if a_str is None:
        a = 1.0
    else:
        a_val = float(a_str)
        a = a_val / 255.0 if a_val > 1.0 else a_val
        a = clamp01(a)
    return Color(r=r, g=g, b=b, a=a)


def extract_colors_from_text(text: str) -> list[Color]:
    colors: list[Color] = []
    for hm in HEX_RE.finditer(text):
        hex_body = hm.group(0)
        with contextlib.suppress(Exception):
            colors.append(parse_hex_to_rgba(hex_body))
    for rm in RGBA_RE.finditer(text):
        c = parse_rgba_match(rm)
        if c is not None:
            colors.append(c)
    return colors


TEXT_LIKE_EXTS = TXT_EXT


def iter_text_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext in TEXT_LIKE_EXTS or not is_binary(str(path)):
            yield path


def safe_read_text(path: Path, limit_bytes: int = 5000000) -> str | None:
    try:
        size = path.stat().st_size
        if size > limit_bytes:
            return None
        data = path.read_bytes()
        for enc in ("utf-8", "utf-16", "latin-1"):
            try:
                return data.decode(enc, errors="strict")
            except Exception:
                pass
        return data.decode("utf-8", errors="replace")
    except Exception:
        return None


def rgba_to_hex(c: Color) -> str:
    return f"#{c.r:02x}{c.g:02x}{c.b:02x}"


def rgb_to_luminance(r: int, g: int, b: int) -> float:
    def lin(x: int):
        x = x / 255.0
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4

    R = lin(r)
    G = lin(g)
    B = lin(b)
    return 0.2126 * R + 0.7152 * G + 0.0722 * B


def ansi_rgb_bg(r: int, g: int, b: int) -> str:
    return f"\x1b[48;2;{r};{g};{b}m"


def ansi_rgb_fg(r: int, g: int, b: int) -> str:
    return f"\x1b[38;2;{r};{g};{b}m"


ANSI_RESET = "\x1b[0m"


def best_text_color(c: Color) -> tuple[int, int, int]:
    lum = rgb_to_luminance(c.r, c.g, c.b)
    return (0, 0, 0) if lum > 0.35 else (255, 255, 255)


def demo_color_blocks(colors: list[Color], max_items: int = 200) -> None:
    uniq: dict[tuple[int, int, int, float], Color] = {}
    for c in colors:
        uniq[c.as_tuple()] = c
    all_colors = list(uniq.values())
    all_colors.sort(key=lambda c: (rgb_to_luminance(c.r, c.g, c.b), c.r, c.g, c.b))
    if len(all_colors) > max_items:
        all_colors = all_colors[:max_items]
    print(f"Found {len(uniq)} unique colors (showing {len(all_colors)}).")
    for c in all_colors:
        fg_r, fg_g, fg_b = best_text_color(c)
        bg = ansi_rgb_bg(c.r, c.g, c.b)
        fg = ansi_rgb_fg(fg_r, fg_g, fg_b)
        rgba_str = f"rgba({c.r},{c.g},{c.b},{c.a:.3f})"
        hex_str = rgba_to_hex(c)
        block = f"{bg}{fg}  {hex_str}  {ANSI_RESET}"
        text = f"{bg}{fg}  {rgba_str}  {ANSI_RESET}"
        print(block + "\n" + text + "\n")


def main() -> None:
    root = Path(".")
    all_found: list[Color] = []
    for path in iter_text_files(root):
        text = safe_read_text(path)
        if not text:
            continue
        found = extract_colors_from_text(text)
        if found:
            all_found.extend(found)
    if not all_found:
        print("No colors found.")
        return
    demo_color_blocks(all_found, max_items=200)


if __name__ == "__main__":
    raise SystemExit(main())
