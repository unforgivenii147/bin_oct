#!/data/data/com.termux/files/home/.local/bin/python
"""Scan and optionally autofix deprecated ``pkg_resources`` usage in Python files.

This script walks the current working directory, reports every occurrence of
``pkg_resources`` imports and usages (with known replacements for common
patterns such as ``get_distribution``, ``resource_string``, ``require`` and
``DistributionNotFound``), and can mechanically rewrite safe usages to the
modern ``importlib.metadata`` / ``importlib.resources`` equivalents. It uses
a ``multiprocessing.Pool`` with 8 workers, ``pathlib`` for all path handling,
``loguru`` for logging and full strict type annotations.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from multiprocessing import Pool
from pathlib import Path

from loguru import logger

IMPORT_RE: re.Pattern[str] = re.compile(
    r"""^(?P<indent>\s*)(?P<stmt>(?:import|from)\s+pkg_resources(?:\s+import\s+(?P<names>[^\n#]+))?)\s*(?P<comment>#.*)?$""",
    re.VERBOSE,
)

USAGE_PATTERNS: list[tuple[re.Pattern[str], str, bool, bool]] = [
    (
        re.compile(r"pkg_resources\.get_distribution\(\s*([^)]+?)\s*\)\.version"),
        r"importlib.metadata.version(\1)",
        True,
        False,
    ),
    (
        re.compile(r"pkg_resources\.get_distribution\(\s*([^)]+?)\s*\)"),
        r"importlib.metadata.distribution(\1)",
        True,
        False,
    ),
    (
        re.compile(r"pkg_resources\.resource_string\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)"),
        r"importlib.resources.files(\1).joinpath(\2).read_bytes()",
        False,
        True,
    ),
    (
        re.compile(r"pkg_resources\.resource_text\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)"),
        r"importlib.resources.files(\1).joinpath(\2).read_text(encoding='utf-8')",
        False,
        True,
    ),
    (
        re.compile(
            r"pkg_resources\.resource_filename\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)"
        ),
        r"str(importlib.resources.files(\1).joinpath(\2))",
        False,
        True,
    ),
    (
        re.compile(r"pkg_resources\.resource_stream\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)"),
        r"importlib.resources.files(\1).joinpath(\2).open('rb')",
        False,
        True,
    ),
    (
        re.compile(r"pkg_resources\.require\(\s*([^)]+?)\s*\)"),
        r"importlib.metadata.requires(\1)",
        True,
        False,
    ),
    (
        re.compile(r"pkg_resources\.DistributionNotFound"),
        r"importlib.metadata.PackageNotFoundError",
        True,
        False,
    ),
]

GENERIC_USAGE_RE: re.Pattern[str] = re.compile(
    r"pkg_resources\.([A-Za-z_][A-Za-z0-9_]*)"
)

SKIPPED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        ".tox",
        "build",
        "dist",
        ".eggs",
    }
)

ALIAS_RE: re.Pattern[str] = re.compile(r"\bas\s+\w+\b")

POOL_SIZE: int = 8


@dataclass
class Finding:
    """A single detected ``pkg_resources`` import or usage site."""

    path: Path
    lineno: int
    col: int
    line: str
    kind: str
    pattern: str = ""
    autofixable: bool = False


@dataclass
class FileReport:
    """Aggregated scan results for a single Python file."""

    path: Path
    findings: list[Finding] = field(default_factory=list)
    needs_metadata: bool = False
    needs_resources: bool = False
    has_pkg_resources_import: bool = False

    @property
    def has_findings(self) -> bool:
        """Return ``True`` if any findings were recorded for this file."""
        return bool(self.findings)


def scan_file(path: Path) -> FileReport:
    """Scan a single Python file for ``pkg_resources`` imports and usages."""
    report = FileReport(path=path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        report.findings.append(
            Finding(
                path=path,
                lineno=0,
                col=0,
                line=f"<unreadable: {exc}>",
                kind="usage_unknown",
                pattern="",
                autofixable=False,
            )
        )
        return report

    for i, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.rstrip("\n")
        m_import = IMPORT_RE.match(stripped)
        if m_import:
            report.has_pkg_resources_import = True
            report.findings.append(
                Finding(
                    path=path,
                    lineno=i,
                    col=m_import.start("stmt") + 1,
                    line=stripped,
                    kind="import",
                    pattern=m_import.group("stmt"),
                    autofixable=True,
                )
            )
            continue

        for pat, _repl, needs_meta, needs_res in USAGE_PATTERNS:
            for m in pat.finditer(stripped):
                report.findings.append(
                    Finding(
                        path=path,
                        lineno=i,
                        col=m.start() + 1,
                        line=stripped,
                        kind="usage_known",
                        pattern=m.group(0),
                        autofixable=True,
                    )
                )
                report.needs_metadata = report.needs_metadata or needs_meta
                report.needs_resources = report.needs_resources or needs_res

        for m in GENERIC_USAGE_RE.finditer(stripped):
            span = m.span()
            already = False
            for f in report.findings:
                if f.lineno == i and f.kind == "usage_known":
                    pos = stripped.find(f.pattern)
                    if pos != -1 and pos <= span[0] and span[1] <= pos + len(f.pattern):
                        already = True
                        break
            if not already:
                report.findings.append(
                    Finding(
                        path=path,
                        lineno=i,
                        col=m.start() + 1,
                        line=stripped,
                        kind="usage_unknown",
                        pattern=m.group(0),
                        autofixable=False,
                    )
                )
    return report


def autofix_file(path: Path) -> tuple[bool, list[str]]:
    """Apply mechanical ``pkg_resources`` replacements to a single file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False, [f"cannot read {path}"]

    original = text
    notes: list[str] = []
    needs_metadata = False
    needs_resources = False

    for pat, repl, needs_meta, needs_res in USAGE_PATTERNS:
        new_text, n = pat.subn(repl, text)
        if n:
            notes.append(f"replaced {n} occurrence(s) of {pat.pattern!r}")
            needs_metadata = needs_metadata or needs_meta
            needs_resources = needs_resources or needs_res
            text = new_text

    lines = text.splitlines(keepends=True)
    new_lines: list[str] = []
    removed_import = False
    skipped_alias = False

    for line in lines:
        m = IMPORT_RE.match(line.rstrip("\n"))
        if not m:
            new_lines.append(line)
            continue
        stmt = m.group("stmt")
        names = m.group("names")
        if ALIAS_RE.search(stmt) or (
            stmt.startswith("from") and names and ALIAS_RE.search(names)
        ):
            skipped_alias = True
            new_lines.append(line)
            continue
        removed_import = True
        notes.append(f"removed import: {stmt.strip()}")

    text = "".join(new_lines)

    if removed_import or needs_metadata or needs_resources:
        insertion_lines: list[str] = []
        if needs_metadata:
            insertion_lines.append("import importlib.metadata\n")
        if needs_resources:
            insertion_lines.append("import importlib.resources\n")
        if insertion_lines:
            text = "".join(insertion_lines) + text
            notes.append("added importlib.metadata / importlib.resources imports")

    if skipped_alias:
        notes.append(
            "WARNING: aliased pkg_resources import left untouched; manual review required"
        )

    if text == original:
        return False, notes

    path.write_text(text, encoding="utf-8")
    return True, notes


def iter_python_files(root: Path) -> Iterator[Path]:
    """Yield all Python files under ``root``, skipping common junk directories."""
    for p in root.rglob("*.py"):
        if any(part in SKIPPED_DIRS for part in p.parts):
            continue
        if p.is_file():
            yield p


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        description="Report (and optionally autofix) deprecated pkg_resources usage in .py files."
    )
    parser.add_argument(
        "-a", "--autofix", action="store_true", help="Apply mechanical autofixes."
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress per-file output."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point: scan (and optionally autofix) ``pkg_resources`` usages."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    root = Path.cwd()
    files: list[Path] = list(iter_python_files(root))
    if not files:
        print("no .py files found")
        return 0

    total_findings = 0
    files_with_findings = 0
    autofixed_files = 0
    reports: list[FileReport] = []

    with Pool(processes=POOL_SIZE) as pool:
        async_results = [pool.apply_async(scan_file, (p,)) for p in files]
        for p, ar in zip(files, async_results):
            try:
                rep: FileReport = ar.get()
            except Exception as exc:  # pragma: no cover - defensive
                logger.error(f"error scanning {p}: {exc}")
                continue
            reports.append(rep)

    reports.sort(key=lambda r: r.path)

    for rep in reports:
        if not rep.has_findings:
            continue
        files_with_findings += 1
        if not args.quiet:
            print(f"== {rep.path} ==")
        for f in rep.findings:
            total_findings += 1
            tag = "AUTOFIX" if f.autofixable else "MANUAL"
            if not args.quiet:
                print(f"  {f.lineno}:{f.col}  [{tag}] ({f.kind})  {f.pattern!r}")
                print(f"      | {f.line.strip()}")

    print(f"scanned files      : {len(files)}")
    print(f"files with findings: {files_with_findings}")
    print(f"total findings     : {total_findings}")

    if args.autofix:
        print("--autofix enabled--")
        with Pool(processes=POOL_SIZE) as pool:
            targets: list[Path] = [r.path for r in reports if r.has_findings]
            async_results = [pool.apply_async(autofix_file, (p,)) for p in targets]
            for p, ar in zip(targets, async_results):
                try:
                    changed, notes = ar.get()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.error(f"  error autofixing {p}: {exc}")
                    continue
                if changed:
                    autofixed_files += 1
                    print(f"  fixed: {p}")
                    for n in notes:
                        print(f"      - {n}")
                else:
                    if notes:
                        print(f"  no-op: {p}")
                        for n in notes:
                            print(f"      - {n}")
        print(f"files autofixed    : {autofixed_files}")

    return 0 if total_findings == 0 or not args.autofix else 1


if __name__ == "__main__":
    sys.exit(main())
