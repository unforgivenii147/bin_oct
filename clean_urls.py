#!/data/data/com.termux/files/home/.local/bin/python
"""
Read URLs from a file, extract unique domains, and collect GitHub links.

Outputs
-------
- ``urls.txt``     : unique domains (netloc) found across all input lines,
                     one per line.
- ``gitlinks.txt`` : every line whose netloc is exactly ``github.com``.
                     Opened in append mode, so repeated runs accumulate.

Usage
-----
    script.py [INPUT_FILE]

If ``INPUT_FILE`` is omitted, ``urls.txt`` in the current directory is used.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_INPUT = "urls.txt"  # Fallback input when no CLI argument is given.
DOMAINS_OUTPUT = "urls.txt"  # Where unique domains are written.
GITHUB_OUTPUT = "gitlinks.txt"  # Where GitHub links are written (appended).
GITHUB_NETLOC = "github.com"  # Exact host we treat as "GitHub links".


def extract_domains_and_github_links(
    lines: Iterable[str],
) -> tuple[set[str], list[str]]:
    """
    Parse each line as a URL and split the results into two collections.

    Args:
        lines: Iterable of raw lines (may include trailing newlines).

    Returns:
        A tuple ``(domains, github_lines)`` where:
        - ``domains`` is a set of unique non-empty netlocs (hostnames).
        - ``github_lines`` is the list of raw input lines whose netloc is
          exactly ``github.com``. Trailing newlines are normalised so the
          caller can safely join them without gluing lines together.
    """
    domains: set[str] = set()
    github_lines: list[str] = []

    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            # Skip blank lines rather than adding "" to the domain set.
            continue

        try:
            netloc = urlparse(stripped).netloc
        except ValueError as exc:
            # ``urlparse`` rarely raises, but malformed bracketed IPv6
            # literals can trip it up; report and move on.
            print(f"skipping unparsable line: {stripped!r} ({exc})", file=sys.stderr)
            continue

        if not netloc:
            # Not a URL we can extract a host from (e.g. a bare word).
            continue

        # GitHub links: preserve the original raw line, normalised to end
        # with exactly one newline so the caller can ``"".join`` them.
        if netloc == GITHUB_NETLOC:
            github_lines.append(stripped + "\n")

        domains.add(netloc)

    return domains, github_lines


def write_domains(path: Path, domains: set[str]) -> None:
    """Write the unique domains to ``path``, one per line, sorted."""
    with path.open("w", encoding="utf-8") as fo:
        fo.writelines(f"{d}\n" for d in sorted(domains))


def append_github_links(path: Path, github_lines: list[str]) -> None:
    """Append GitHub links to ``path`` (created if missing)."""
    with path.open("a", encoding="utf-8") as fg:
        fg.write("".join(github_lines))


def main() -> int:
    """Entry point: read input, split URLs, and write the two outputs."""
    parser = argparse.ArgumentParser(
        description=(
            "Extract unique domains and GitHub links from a file of URLs. "
            f"With no argument, reads '{DEFAULT_INPUT}'."
        )
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=DEFAULT_INPUT,
        help=f"Input file containing URLs (default: {DEFAULT_INPUT}).",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"error: input file not found: {input_path}", file=sys.stderr)
        return 1

    # Read the whole file up front. These URL lists are small, so streaming
    # would add complexity without a real memory benefit.
    try:
        lines = input_path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        print(f"error: could not read {input_path}: {exc}", file=sys.stderr)
        return 1

    domains, github_lines = extract_domains_and_github_links(lines)

    # Write unique domains (overwrite) and GitHub links (append).
    write_domains(Path(DOMAINS_OUTPUT), domains)
    append_github_links(Path(GITHUB_OUTPUT), github_lines)

    print(
        f"Wrote {len(domains)} unique domain(s) to {DOMAINS_OUTPUT}; "
        f"appended {len(github_lines)} GitHub link(s) to {GITHUB_OUTPUT}."
    )
    return 0


if __name__ == "__main__":
    # ``raise SystemExit`` propagates the exit code cleanly.
    raise SystemExit(main())
