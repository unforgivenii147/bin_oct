#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import time
from pathlib import Path


class BatchStripper:
    @staticmethod
    def strip_by_size_threshold(
        directory: str,
        min_size_mb: float = 1.0,
        verbose: bool = False,
        verify: bool = True,
    ) -> dict:
        print(f"\nStripping .so files larger than {min_size_mb} MB...")
        so_files = list(Path(directory).rglob("*.so*"))
        min_bytes = min_size_mb * 1024 * 1024
        large_files = [f for f in so_files if f.stat().st_size >= min_bytes]
        stripper = SoFileStripper(verbose=verbose, verify_ctypes=verify)
        for so_file in large_files:
            stripper.process_file(so_file)
        return stripper.stats

    @staticmethod
    def strip_by_extension(
        directory: str,
        extensions: list[str] | None = None,
        verbose: bool = False,
        verify: bool = True,
    ) -> dict:
        if extensions is None:
            pass
        print(f"\nStripping .so files with extensions: {extensions}")
        so_files = []
        for ext in extensions:
            so_files.extend(Path(directory).rglob(f"*{ext}"))
        so_files = list(set(so_files))
        stripper = SoFileStripper(verbose=verbose, verify_ctypes=verify)
        for so_file in so_files:
            stripper.process_file(so_file)
        return stripper.stats

    @staticmethod
    def strip_exclude_patterns(
        directory: str,
        exclude_patterns: list[str] | None = None,
        verbose: bool = False,
        verify: bool = True,
    ) -> dict:
        if exclude_patterns is None:
            exclude_patterns = ["test", "debug", "profile"]
        print(f"\nStripping .so files (excluding: {exclude_patterns})...")
        so_files = [
            f
            for f in Path(directory).rglob("*.so*")
            if not any(pattern in f.name for pattern in exclude_patterns)
        ]
        stripper = SoFileStripper(verbose=verbose, verify_ctypes=verify)
        for so_file in so_files:
            stripper.process_file(so_file)
        return stripper.stats

    @staticmethod
    def strip_with_retry(
        directory: str, max_retries: int = 3, verbose: bool = False, verify: bool = True
    ) -> dict:
        print(f"\nStripping with retry logic (max {max_retries} attempts)...")
        so_files = list(Path(directory).rglob("*.so*"))
        stripper = SoFileStripper(verbose=verbose, verify_ctypes=verify)
        for so_file in so_files:
            for attempt in range(max_retries):
                result = stripper.process_file(so_file)
                if result["success"]:
                    break
                if attempt < max_retries - 1:
                    if verbose:
                        print(f"  Retry {attempt + 1}/{max_retries - 1}...")
                    time.sleep(1)
        return stripper.stats


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Batch .so file stripping with ctypes verification"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    size_parser = subparsers.add_parser("size", help="Strip by size threshold")
    size_parser.add_argument("directory", nargs="?", default=".")
    size_parser.add_argument(
        "--min-mb", type=float, default=1.0, help="Minimum size in MB"
    )
    size_parser.add_argument("-v", "--verbose", action="store_true")
    size_parser.add_argument(
        "--no-verify", action="store_true", help="Skip ctypes verification"
    )
    ext_parser = subparsers.add_parser("ext", help="Strip by extensions")
    ext_parser.add_argument("directory", nargs="?", default=".")
    ext_parser.add_argument(
        "--extensions", nargs="+", default=[".so", ".so.1", ".so.6"]
    )
    ext_parser.add_argument("-v", "--verbose", action="store_true")
    ext_parser.add_argument(
        "--no-verify", action="store_true", help="Skip ctypes verification"
    )
    excl_parser = subparsers.add_parser("exclude", help="Strip excluding patterns")
    excl_parser.add_argument("directory", nargs="?", default=".")
    excl_parser.add_argument(
        "--patterns", nargs="+", default=["test", "debug", "profile"]
    )
    excl_parser.add_argument("-v", "--verbose", action="store_true")
    excl_parser.add_argument(
        "--no-verify", action="store_true", help="Skip ctypes verification"
    )
    retry_parser = subparsers.add_parser("retry", help="Strip with retry")
    retry_parser.add_argument("directory", nargs="?", default=".")
    retry_parser.add_argument("--max-retries", type=int, default=3)
    retry_parser.add_argument("-v", "--verbose", action="store_true")
    retry_parser.add_argument(
        "--no-verify", action="store_true", help="Skip ctypes verification"
    )
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return
    verify = not args.no_verify
    if args.command == "size":
        BatchStripper.strip_by_size_threshold(
            args.directory, args.min_mb, args.verbose, verify
        )
    elif args.command == "ext":
        BatchStripper.strip_by_extension(
            args.directory, args.extensions, args.verbose, verify
        )
    elif args.command == "exclude":
        BatchStripper.strip_exclude_patterns(
            args.directory, args.patterns, args.verbose, verify
        )
    elif args.command == "retry":
        BatchStripper.strip_with_retry(
            args.directory, args.max_retries, args.verbose, verify
        )


if __name__ == "__main__":
    raise SystemExit(main())
