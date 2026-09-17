#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

import py7zr
from joblib import Parallel, delayed
from tqdm import tqdm

try:
    import zstandard as zstd
except ImportError:
    zstd = None
try:
    from brotli import decompress as brotli_decompress
except ImportError:
    brotli_decompress = None


def copy_chunks(src, dst, chunk_size: int = 1024 * 1024) -> None:
    while True:
        chunk = src.read(chunk_size)
        if not chunk:
            break
        dst.write(chunk)


class ArchiveExtractor:
    SUPPORTED_EXTENSIONS = {
        ".gz": "gzip",
        ".xz": "xz",
        ".zip": "zip",
        ".whl": "zip",
        ".br": "brotli",
        ".zst": "zstandard",
        ".7z": "sevenz",
        ".tar": "tar",
        ".tar.gz": "tar_gz",
        ".tar.xz": "tar_xz",
        ".tar.bz2": "tar_bz2",
        ".tgz": "tar_gz",
        ".txz": "tar_xz",
    }

    def __init__(self, remove_after: bool = True, verbose: bool = True):
        self.remove_after = remove_after
        self.verbose = verbose
        self.stats = {"processed": 0, "success": 0, "failed": 0, "skipped": 0}

    def _print_header(self, message: str, char: str = "=", width: int = 80):
        print(f"\n{char * width}")
        print(f" {message} ".center(width, char))
        print(f"{char * width}\n")

    def _print_status(self, archive: Path, status: str, details: str = ""):
        colors = {
            "SUCCESS": "\x1b[92m",
            "FAILED": "\x1b[91m",
            "SKIPPED": "\x1b[93m",
            "PROCESSING": "\x1b[94m",
            "RESET": "\x1b[0m",
        }
        color = colors.get(status.upper(), colors["RESET"])
        icon = {
            "SUCCESS": "✅",
            "FAILED": "❌",
            "SKIPPED": "⏭️",
            "PROCESSING": "🔄",
        }.get(status.upper(), "➡️")
        msg = f"{icon} {archive.name:<40} [{status:<8}]"
        if details:
            msg += f" {details}"
        print(f"{color}{msg}{colors['RESET']}")

    def _detect_format(self, archive: Path) -> str | None:
        for ext in [".tar.gz", ".tar.xz", ".tar.bz2", ".tgz", ".txz"]:
            if str(archive).endswith(ext):
                return self.SUPPORTED_EXTENSIONS.get(ext)
        if archive.suffix:
            if archive.suffix == ".zst":
                return "zstandard"
            return self.SUPPORTED_EXTENSIONS.get(archive.suffix)
        return None

    def _extract_tar(self, archive: Path, output_dir: Path) -> bool:
        import tarfile

        try:
            with tarfile.open(archive, "r:*") as tar:
                tar.extractall(path=output_dir)
            return True
        except Exception as e:
            if self.verbose:
                self._print_status(archive, "FAILED", f"Tar extraction error: {e}")
            return False

    def _extract_gz(self, archive: Path, output_dir: Path) -> bool:
        try:
            import gzip

            output_file = output_dir / archive.stem
            with gzip.open(archive, "rb") as f_in, open(output_file, "wb") as f_out:
                copy_chunks(f_in, f_out)
            return True
        except Exception as e:
            if self.verbose:
                self._print_status(archive, "FAILED", f"Gzip error: {e}")
            return False

    def _extract_xz(self, archive: Path, output_dir: Path) -> bool:
        try:
            import lzma

            output_file = output_dir / archive.stem
            with lzma.open(archive, "rb") as f_in, open(output_file, "wb") as f_out:
                copy_chunks(f_in, f_out)
            return True
        except Exception as e:
            if self.verbose:
                self._print_status(archive, "FAILED", f"XZ error: {e}")
            return False

    def _extract_zip(self, archive: Path, output_dir: Path) -> bool:
        try:
            import zipfile

            with zipfile.ZipFile(archive, "r") as zip_ref:
                zip_ref.extractall(path=output_dir)
            return True
        except Exception as e:
            if self.verbose:
                self._print_status(archive, "FAILED", f"ZIP error: {e}")
            return False

    def _extract_brotli(self, archive: Path, output_dir: Path) -> bool:
        if brotli_decompress is None:
            if self.verbose:
                self._print_status(archive, "FAILED", "brotli library not installed")
            return False
        try:
            output_file = output_dir / archive.stem
            with open(archive, "rb") as f_in:
                decompressed_data = brotli_decompress(f_in.read())
            with open(output_file, "wb") as f_out:
                f_out.write(decompressed_data)
            return True
        except Exception as e:
            if self.verbose:
                self._print_status(archive, "FAILED", f"Brotli error: {e}")
            return False

    def _extract_zstandard(self, archive: Path, output_dir: Path) -> bool:
        if zstd is None:
            if self.verbose:
                self._print_status(archive, "FAILED", "zstandard library not installed")
            return False
        try:
            output_name = archive.stem
            if output_name.endswith(".tar"):
                output_name = output_name[:-4]
                output_file = output_dir / output_name
                import tarfile
                import tempfile

                with tempfile.NamedTemporaryFile(delete=False, suffix=".tar") as tmp:
                    temp_path = Path(tmp.name)
                    with open(archive, "rb") as f_in:
                        dctx = zstd.ZstdDecompressor()
                        with dctx.stream_reader(f_in) as reader:
                            copy_chunks(reader, tmp)
                        tmp.flush()
                    try:
                        with tarfile.open(temp_path, "r") as tar:
                            tar.extractall(path=output_dir)
                        temp_path.unlink()
                        return True
                    except Exception as e:
                        temp_path.unlink()
                        if self.verbose:
                            self._print_status(
                                archive,
                                "FAILED",
                                f"Tar extraction from .zst failed: {e}",
                            )
                        return False
            else:
                output_file = output_dir / output_name
                with open(archive, "rb") as f_in:
                    dctx = zstd.ZstdDecompressor()
                    with (
                        dctx.stream_reader(f_in) as reader,
                        open(output_file, "wb") as f_out,
                    ):
                        copy_chunks(reader, f_out)
                return True
        except Exception as e:
            if self.verbose:
                self._print_status(archive, "FAILED", f"Zstandard error: {e}")
            return False

    def _extract_7z(self, archive: Path, output_dir: Path) -> bool:
        try:
            with py7zr.SevenZipFile(archive, mode="r") as sz:
                sz.extractall(path=output_dir)
            return True
        except Exception as e:
            if self.verbose:
                self._print_status(archive, "FAILED", f"7z error: {e}")
            return False

    def extract_single(self, archive_path: Path) -> tuple[Path, bool, str | None]:
        archive = Path(archive_path)
        if not archive.exists() or not archive.is_file():
            return archive, False, "File not found"
        format_type = self._detect_format(archive)
        if not format_type:
            return archive, False, f"Unsupported format: {archive.suffix}"
        stem = archive.stem
        if str(archive).endswith(".tar.zst"):
            stem = archive.stem.removesuffix(".tar")
        elif format_type.startswith("tar_") and stem.endswith(".tar"):
            stem = stem[:-4]
        output_dir = archive.parent / stem
        output_dir.mkdir(exist_ok=True)
        if format_type == "zstandard" and str(archive).endswith(".zst"):
            pass
        extractors = {
            "tar": self._extract_tar,
            "tar_gz": self._extract_tar,
            "tar_xz": self._extract_tar,
            "tar_bz2": self._extract_tar,
            "gzip": self._extract_gz,
            "xz": self._extract_xz,
            "zip": self._extract_zip,
            "brotli": self._extract_brotli,
            "zstandard": self._extract_zstandard,
            "sevenz": self._extract_7z,
        }
        try:
            extractor = extractors.get(format_type)
            if not extractor:
                return archive, False, f"No extractor for {format_type}"
            if self.verbose:
                self._print_status(archive, "PROCESSING", f"-> {output_dir}/")
            success = extractor(archive, output_dir)
            if success and self.remove_after:
                archive.unlink()
                if self.verbose:
                    self._print_status(archive, "SUCCESS", f"Removed: {archive.name}")
            elif success and self.verbose:
                self._print_status(archive, "SUCCESS", f"Extracted to: {output_dir}")
            return archive, success, None if success else "Extraction failed"
        except Exception as e:
            return archive, False, str(e)

    def extract_recursive(self, root_dir: Path = Path.cwd(), n_jobs: int = -1) -> dict:
        self._print_header(f"ARCHIVE EXTRACTOR - {root_dir}", "=")
        archives = []
        for ext in self.SUPPORTED_EXTENSIONS:
            if ext.startswith(".tar."):
                archives.extend(root_dir.rglob(f"*{ext}"))
            elif ext == ".tar":
                continue
            else:
                archives.extend(root_dir.rglob(f"*{ext}"))
        archives.extend(root_dir.rglob("*.zst"))
        archives.extend(root_dir.rglob("*.whl"))
        archives = sorted(set(archives))
        self.stats["total"] = len(archives)
        if not archives:
            print("📭 No archive files found to extract.")
            return self.stats
        print(f"📦 Found {len(archives)} archive(s) to process")
        print(f"⚡ Using {n_jobs if n_jobs > 0 else 'all'} CPU core(s)\n")
        if any(str(a).endswith(".zst") for a in archives) and zstd is None:
            print(
                "⚠️  Warning: zstandard library not installed. Install with: pip install zstandard"
            )
        if any(str(a).endswith(".br") for a in archives) and brotli_decompress is None:
            print(
                "⚠️  Warning: brotli library not installed. Install with: pip install brotli"
            )
        results = Parallel(n_jobs=n_jobs, prefer="threads")(
            delayed(self.extract_single)(archive)
            for archive in tqdm(archives, desc="Extracting")
        )
        for archive, success, error in results:
            self.stats["processed"] += 1
            if success:
                self.stats["success"] += 1
            elif error and "Unsupported" in str(error):
                self.stats["skipped"] += 1
            else:
                self.stats["failed"] += 1
                if error and self.verbose:
                    self._print_status(archive, "FAILED", f"Error: {error}")
        self._print_summary()
        return self.stats

    def _print_summary(self):
        self._print_header("EXTRACTION SUMMARY", "-")
        total = self.stats["total"]
        if total == 0:
            print("No archives processed.")
            return
        success = self.stats["success"]
        failed = self.stats["failed"]
        skipped = self.stats["skipped"]
        print(f"📊 Total processed:  {total}")
        print(f"✅ Successful:       {success} ({success / total * 40:.1f}%)")
        print(f"❌ Failed:           {failed} ({failed / total * 40:.1f}%)")
        print(f"⏭️  Skipped:          {skipped} ({skipped / total * 40:.1f}%)")
        print(f"🗑️  Remove original:  {'Enabled' if self.remove_after else 'Disabled'}")
        if failed > 0:
            print("\n⚠️  Some archives failed to extract. Check errors above.")
        self._print_header("FINISHED", "-")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract archive files recursively with parallel processing"
    )
    parser.add_argument(
        "-d", "--dir", default=".", help="Root directory to search (default: current)"
    )
    parser.add_argument(
        "-k",
        "--keep",
        action="store_true",
        help="Keep original archive files after extraction",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Reduce verbosity (only show summary)",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=-1,
        help="Number of parallel jobs (-1 for all cores)",
    )
    args = parser.parse_args()
    root_dir = Path(args.dir).resolve()
    if not root_dir.exists():
        print(f"❌ Error: Directory '{root_dir}' does not exist")
        sys.exit(1)
    extractor = ArchiveExtractor(remove_after=not args.keep, verbose=not args.quiet)
    try:
        extractor.extract_recursive(root_dir, n_jobs=args.jobs)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
