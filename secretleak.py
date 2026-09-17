#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that scans a directory tree for hardcoded secrets using regex patterns,
skipping binary/large file types, common vendor directories, and any file containing known
signatures of a zip brute-forcer or a pdfminer-based extraction tool. It uses multiprocessing.Pool
with a fixed pool of 8 workers, loguru for logging, pathlib for path handling, complete type hints,
and excludes the script itself from the scan. The script reports leaks and exits with code 1 if any
secrets are found, 0 if clean, and 2 on error or interrupt.
"""

import re
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from loguru import logger

SECRET_PATTERNS: dict[str, str] = {
    "AWS Key": "AKIA[0-9A-Z]{16}",
    "Private Key": "-----BEGIN (?:RSA|DSA|EC|OPENSSH) PRIVATE KEY-----",
    "GitHub Token": "ghp_[A-Za-z0-9_]{36,255}",
    "Generic API Key": "api[_-]?key['\\\"]?\\s*[:=]\\s*['\\\"]?[A-Za-z0-9\\-_]{20,}",
    "Database URL": "(?:mysql|postgresql|mongodb)://[^\\s]+",
    "Slack Token": "xox[baprs]-[0-9]{10,13}-[0-9]{10,13}[A-Za-z0-9-]*",
    "Generic Password": "password['\\\"]?\\s*[:=]\\s*['\\\"]?[A-Za-z0-9\\-_!@#$%]{8,}",
    "AWS Secret": "aws_secret_access_key['\\\"]?\\s*[:=]\\s*['\\\"]?[A-Za-z0-9/+=]{40}",
    "Google API Key": "AIza[0-9A-Za-z\\-_]{35}",
    "JWT Token": "eyJ[A-Za-z0-9_-]+\\.eyJ[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+",
}

SKIP_EXTENSIONS: set[str] = {
    ".pyc",
    ".so",
    ".o",
    ".a",
    ".exe",
    ".dll",
    ".dylib",
    ".jpg",
    ".png",
    ".gif",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".git",
    ".svg",
    ".lock",
    ".bin",
    ".class",
}

SKIP_PATTERNS: set[str] = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".env.example",
}

# Signatures used to detect and skip known files from the scan.
SKIP_CONTENT_SIGNATURES: tuple[str, ...] = (
    # Zip brute-forcer signatures
    "Optimized Zip Brute-Forcer for Python 3.12",
    "def brute_force_zip(",
    "def check_password_batch(",
    "CrackResult",
    # pdfminer extraction tool signatures
    "extract_text_from_page",
    "extract_pages",
    "no-laparams",
    "float_or_disabled",
    "pdfminer.high_level",
)

SCRIPT_PATH: Path = Path(__file__).resolve()

POOL_SIZE: int = 8


def _read_file_text(path: Path) -> str | None:
    """Read a file as text (utf-8, ignoring errors) and return its content, or None on OSError."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return None


def _contains_skip_signature(content: str) -> bool:
    """Return True if the file content contains any of the known skip signatures."""
    return any(sig in content for sig in SKIP_CONTENT_SIGNATURES)


def should_skip_file(path: Path) -> bool:
    """Return True if the file should be skipped based on extension, path patterns, symlink status, being this script, or known content signatures."""
    if path.resolve() == SCRIPT_PATH:
        return True
    if path.suffix.lower() in SKIP_EXTENSIONS:
        return True
    for pattern in SKIP_PATTERNS:
        if pattern in path.parts:
            return True
    if path.is_symlink():
        return True
    content = _read_file_text(path)
    return bool(content is not None and _contains_skip_signature(content))


def scan_file(path: Path) -> tuple[str, list[dict[str, Any]]]:
    """Scan a single file for secret patterns and return its path along with a list of leak dictionaries."""
    leaks: list[dict[str, Any]] = []
    content: str | None = _read_file_text(path)
    if content is None:
        return str(path), leaks

    for secret_name, pattern in SECRET_PATTERNS.items():
        matches = re.finditer(pattern, content, re.IGNORECASE)
        for match in matches:
            line_num: int = content[: match.start()].count("\n") + 1
            lines: list[str] = content.split("\n")
            line_content: str = lines[line_num - 1] if line_num <= len(lines) else ""
            matched_text: str = match.group(0)
            leaks.append(
                {
                    "secret_type": secret_name,
                    "line_number": line_num,
                    "matched_text": matched_text[:50] + "..."
                    if len(matched_text) > 50
                    else matched_text,
                    "line_content": line_content[:80] + "..."
                    if len(line_content) > 80
                    else line_content,
                }
            )
    return str(path), leaks


def get_all_files(root_dir: Path = Path(".")) -> list[Path]:
    """Recursively collect all non-skipped files under root_dir."""
    files: list[Path] = []
    try:
        for path in root_dir.rglob("*"):
            if path.is_file() and not should_skip_file(path):
                files.append(path)
    except PermissionError:
        pass
    return files


def check_secrets(root_dir: Path = Path(".")) -> tuple[int, int, int]:
    """Scan all files under root_dir for secrets using a multiprocessing pool and return (files_scanned, total_leaks, files_with_leaks)."""
    files: list[Path] = get_all_files(root_dir)
    if not files:
        print("No files found to scan.")
        return 0, 0, 0

    print(f"Scanning {len(files)} files for secrets...\n")

    total_leaks: int = 0
    files_with_leaks: int = 0

    with Pool(processes=POOL_SIZE) as pool:
        async_results = [pool.apply_async(scan_file, (file,)) for file in files]

        for async_result in async_results:
            path, leaks = async_result.get()
            if leaks:
                files_with_leaks += 1
                logger.warning(f"⚠️  Found {len(leaks)} secret(s) in: {path}")
                for leak in leaks:
                    logger.warning(
                        f"   - {leak['secret_type']} at line {leak['line_number']}"
                    )
                    logger.warning(f"     Matched: {leak['matched_text']}")
                    logger.warning(f"     Content: {leak['line_content']}\n")
                total_leaks += len(leaks)

    return len(files), total_leaks, files_with_leaks


def main() -> int:
    """Entry point: run the secret scan and return an exit code (0 clean, 1 leaks found, 2 error/interrupt)."""
    print("-" * 40)
    print("SECRET LEAK DETECTOR - Pre-GitHub Push Scanner")
    print("-" * 40)
    print()
    try:
        total_files, total_leaks, files_affected = check_secrets()
        print("-" * 40)
        print("Scan Complete!")
        print(f"Files scanned: {total_files}")
        print(f"Leaks found: {total_leaks}")
        print(f"Files with leaks: {files_affected}")
        print("-" * 40)
        if total_leaks > 0:
            logger.error("\n❌ SECRETS DETECTED! DO NOT PUSH TO GITHUB!")
            logger.error("Please review and remove the secrets before committing.\n")
            return 1
        else:
            logger.success("\n✅ No secrets detected. Safe to push!\n")
            return 0
    except KeyboardInterrupt:
        logger.warning("\n\nScan interrupted by user.")
        return 2
    except Exception as e:
        logger.error(f"\n❌ Error during scan: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
