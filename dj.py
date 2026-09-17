#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import sys
from pathlib import Path

EMPTY_MODE = "-e" in sys.argv
REMOVE_MODE = "-r" in sys.argv
SKIP_DIRS = {".git", "var"}
REMOVABLE_EXTENSIONS = {".txt", ".md"}
JUNK_EXTENSIONS = {".tmp", ".bak", ".log", ".pyc"}


def empty_it(path: Path) -> None:
    try:
        path.write_text("", encoding="utf-8")
    except OSError as e:
        print(f"Error emptying {path}: {e}", file=sys.stderr)


def remove_it(path: Path) -> None:
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError as e:
        print(f"Error removing {path}: {e}", file=sys.stderr)


def should_skip(path: Path) -> bool:
    return any(skip_dir in path.parts for skip_dir in SKIP_DIRS)


def has_multiple_suffixes(path: Path) -> bool:
    return len(path.suffixes) > 1


def main() -> None:
    cwd = Path.cwd()
    removed_count = 0
    for path in cwd.rglob("*"):
        if should_skip(path):
            continue
        loname = path.name.lower()
        rel_path = path.relative_to(cwd)
        if path.is_file() and loname in {
            "copyrightnotice.txt",
            "history.rst",
            ".dirinfo",
            "licence.md",
            ".ds_store",
            ".reqcache.json",
            ".travis.yml",
            "bsd-2-clause.txt",
            "cc-by-sa-4.0.txt",
            "copyright.html",
            "gcc-exception-3.1.txt",
            "gpl-2.0-only.txt",
            "gpl-3.0-or-later.txt",
            "isc.txt",
            "license-apache",
            "license-mit",
            "license-third-party",
            "llvm-exception.txt",
            "mit.txt",
            "ncsa.txt",
            "ofl-1.1.txt",
            "author",
            "author.md",
            "author.rst",
            "author.txt",
            "authors",
            "authors.md",
            "authors.rst",
            "authors.txt",
            "bsd-0-clause.rst",
            "bsd-2-clause.rst",
            "changelog",
            "changelog.1",
            "changelog.debian",
            "changelog.md",
            "changelog.rst",
            "changelog.txt",
            "changes",
            "changes.md",
            "changes.rst",
            "changes.txt",
            "citation",
            "citation.bib",
            "citation.md",
            "citation.rst",
            "citation.txt",
            "code_of_conduct",
            "code_of_conduct.md",
            "code_of_conduct.rst",
            "code_of_conduct.txt",
            "contributing",
            "contributing.md",
            "contributing.rst",
            "contributing.txt",
            "contributing.markdown",
            "contributors",
            "contributors.md",
            "contributors.rst",
            "contributors.txt",
            "copying",
            "copying-lgpl",
            "copying-mit",
            "copying.0bsd",
            "copying.0mit",
            "copying.bsd-3-clause",
            "copying.bsd-4-clause-uc",
            "copying.gpl",
            "copying.gpl-2.0-or-later",
            "copying.gpl-3.0-or-later",
            "copying.gplv2",
            "copying.gplv3",
            "copying.isc",
            "copying.lesser",
            "copying.lgpl",
            "copying.lgpl-2.1-or-later",
            "copying.md",
            "copying.mit",
            "copying.mpl",
            "copying.obstack",
            "copying.rst",
            "copying.txt",
            "copying_ccbysa3",
            "copying_lgpl",
            "copyright",
            "copyright-chapter.mom",
            "copyright-chapter.pdf",
            "copyright-default.mom",
            "copyright-default.pdf",
            "copyright-library.html",
            "copyright.1",
            "copyright.debian",
            "copyright.txt",
            "cpl1.o.txt",
            "description.rst",
            "gpl-3-0.txt",
            "icon_license.md",
            "importz.txt",
            "installer",
            "licence",
            "licence.rst",
            "license",
            "license-apache.md",
            "license-apache.rst",
            "license-apache.txt",
            "license-gpl",
            "license-mit.md",
            "license-mit.rst",
            "license-mit.txt",
            "license-swig",
            "license-universities",
            "license.apache",
            "license.apache-2.0.txt",
            "license.apache2",
            "license.bsd",
            "license.docs",
            "license.markdown-it",
            "license.md",
            "license.mit",
            "license.rst",
            "license.txt",
            "license_numpy.txt",
            "license_scipy.txt",
            "licenses",
            "licenses.md",
            "licenses.txt",
            "lisense",
            "metadata.json",
            "namespace_packages.txt",
            "news",
            "news.debian",
            "news.html",
            "news.md",
            "news.rst",
            "news.txt",
            "notice",
            "notice.txt",
            "pbr.json",
            "readme.debian",
            "release-notes.rst",
            "release-notes.txt",
            "requested",
            "security.md",
            "thanks",
            "thanks.md",
            "thanks.rst",
            "thanks.txt",
            "third-party-notices.md",
            "third-party-notices.rst",
            "third-party-notices.txt",
            "third-party_notices.md",
            "third_party_notices",
            "thirdpartynotices.txt",
            "toplevel.txt",
            "unlicense",
            "zip-safe",
            ".pyformat_cache.json",
            "simz.json",
            ".gitkeep",
            "acknowledgements",
            "history.deb822",
            "readme.changelog",
        }:
            remove_it(path)
            removed_count += 1
            print(f"{rel_path} removed")
            continue
        if path.is_dir() and loname == "licenses" and ("dist-info" in path.parent.name):
            remove_it(path)
            print(rel_path)
            removed_count += 1
            continue
    if removed_count:
        print(f"\n{removed_count} item(s) removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
