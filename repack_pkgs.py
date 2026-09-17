#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import base64
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class PackageInfo:
    name: str
    version: str
    location: str
    is_pure_python: bool
    has_c_extension: bool
    has_binary: bool
    py_version: str
    abi_tag: str
    platform_tag: str
    wheel_filename: str
    metadata_version: str = "2.1"


class PackageDetector:
    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose

    def log(self, message: str) -> None:
        if self.verbose:
            print(f"[DETECT] {message}")

    def detect_package_type(self, package_dir: Path) -> tuple[bool, bool, bool]:
        so_files = list(package_dir.rglob("*.so"))
        pyd_files = list(package_dir.rglob("*.pyd"))
        dll_files = list(package_dir.rglob("*.dll"))
        has_c_extension = bool(so_files or pyd_files or dll_files)
        is_pure_python = not has_c_extension
        if has_c_extension:
            self.log(
                f"Found C extensions: {len(so_files)} .so, {len(pyd_files)} .pyd, {len(dll_files)} .dll"
            )
        binary_extensions = {".exe", ".bin", ".dylib", ".so", ".pyd", ".dll"}
        has_binary = any(
            path.suffix.lower() in binary_extensions
            for path in package_dir.rglob("*")
            if path.is_file()
        )
        return (is_pure_python, has_c_extension, has_binary)

    @staticmethod
    def get_python_version() -> str:
        major, minor = sys.version_info[:2]
        return f"py{major}{minor}"

    @staticmethod
    def get_abi_tag() -> str:
        major, minor = sys.version_info[:2]
        flags = sys.abiflags if hasattr(sys, "abiflags") else ""
        if hasattr(sys, "implementation") and sys.implementation.name == "cpython":
            return f"cp{major}{minor}{flags}"
        return f"cp{major}{minor}"

    @staticmethod
    def get_platform_tag() -> str:
        import platform

        system = platform.system().lower()
        machine = platform.machine().lower()
        platform_map = {
            "linux": f"linux_{machine}",
            "darwin": f"macosx_10_9_{machine}",
            "windows": f"win_{machine}",
        }
        return platform_map.get(system, f"{system}_{machine}")

    @staticmethod
    def read_dist_info(dist_info_dir: Path) -> dict[str, str]:
        metadata = {}
        metadata_file = dist_info_dir / "METADATA"
        if not metadata_file.exists():
            metadata_file = dist_info_dir / "PKG-INFO"
        if metadata_file.exists():
            try:
                content = metadata_file.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if ":" in line:
                        key, value = line.split(":", 1)
                        metadata[key.strip()] = value.strip()
            except Exception:
                pass
        return metadata

    def analyze_package(
        self, site_packages: Path, package_name: str
    ) -> PackageInfo | None:
        package_dir = site_packages / package_name
        if not package_dir.is_dir():
            self.log(f"Package not found: {package_name}")
            return None
        try:
            is_pure, has_c_ext, has_binary = self.detect_package_type(package_dir)
            dist_info_dirs = list(site_packages.glob(f"{package_name}*.dist-info"))
            if not dist_info_dirs:
                self.log(f"No dist-info found for {package_name}")
                return None
            dist_info_dir = dist_info_dirs[0]
            metadata = self.read_dist_info(dist_info_dir)
            version = metadata.get("Version", "0.0.0")
            py_version = "py3" if is_pure else self.get_python_version()
            abi_tag = "none" if is_pure else self.get_abi_tag()
            platform_tag = "any" if is_pure else self.get_platform_tag()
            normalized_name = package_name.lower().replace("-", "_").replace(".", "_")
            wheel_filename = (
                f"{normalized_name}-{version}-{py_version}-{abi_tag}-{platform_tag}.whl"
            )
            return PackageInfo(
                name=package_name,
                version=version,
                location=str(package_dir),
                is_pure_python=is_pure,
                has_c_extension=has_c_ext,
                has_binary=has_binary,
                py_version=py_version,
                abi_tag=abi_tag,
                platform_tag=platform_tag,
                wheel_filename=wheel_filename,
            )
        except Exception as e:
            self.log(f"Error analyzing {package_name}: {e!s}")
            return None


class WheelBuilder:
    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose

    def log(self, message: str) -> None:
        if self.verbose:
            print(f"[BUILD] {message}")

    @staticmethod
    def calculate_hash(path: Path, algorithm: str = "sha256") -> str:
        hasher = hashlib.new(algorithm)
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        digest = hasher.digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    @staticmethod
    def get_file_size(path: Path) -> int:
        return path.stat().st_size

    def create_record(self, wheel_path: Path, dist_info_dir: str) -> str:
        records = []
        with zipfile.ZipFile(wheel_path, "r") as zf:
            for info in zf.infolist():
                if info.filename.endswith("RECORD"):
                    continue
                content = zf.read(info.filename)
                hasher = hashlib.sha256()
                hasher.update(content)
                digest = hasher.digest()
                hash_str = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
                records.append(f"{info.filename},sha256={hash_str},{len(content)}")
        records.append(f"{dist_info_dir}/RECORD,,")
        return "\n".join(records) + "\n"

    def create_wheel(
        self, package_info: PackageInfo, source_dir: Path, output_dir: Path
    ) -> tuple[bool, str]:
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            wheel_path = output_dir / package_info.wheel_filename
            self.log(f"Creating wheel: {wheel_path}")
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                pkg_name = package_info.name.lower().replace("-", "_")
                pkg_dest = temp_path / pkg_name
                if not source_dir.is_dir():
                    return (False, f"Source directory not found: {source_dir}")
                shutil.copytree(source_dir, pkg_dest, dirs_exist_ok=True)
                normalized_name = (
                    package_info.name.lower().replace("-", "_").replace(".", "_")
                )
                dist_info_name = f"{normalized_name}-{package_info.version}.dist-info"
                dist_info_dir = temp_path / dist_info_name
                dist_info_dir.mkdir(parents=True, exist_ok=True)
                wheel_content = f"Wheel-Version: 1.0\nGenerator: repack_venv_packages\nRoot-Is-Purelib: {
                    ('true' if package_info.is_pure_python else 'false')
                }\nTag: {package_info.py_version}-{package_info.abi_tag}-{
                    package_info.platform_tag
                }\n"
                (dist_info_dir / "WHEEL").write_text(wheel_content)
                metadata_content = f"Metadata-Version: {
                    package_info.metadata_version
                }\nName: {package_info.name}\nVersion: {
                    package_info.version
                }\nSummary: Repacked wheel from site-packages\nHome-page: UNKNOWN\nAuthor: UNKNOWN\nAuthor-email: UNKNOWN\nLicense: UNKNOWN\nPlatform: UNKNOWN\n"
                (dist_info_dir / "METADATA").write_text(metadata_content)
                top_level = pkg_name.split("-")[0]
                (dist_info_dir / "top_level.txt").write_text(top_level + "\n")
                with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for path in temp_path.rglob("*"):
                        if path.is_file():
                            arcname = path.relative_to(temp_path)
                            zf.write(path, arcname)
                record_content = self.create_record(wheel_path, dist_info_name)
                temp_wheel = wheel_path.with_suffix(".whl.tmp")
                shutil.move(wheel_path, temp_wheel)
                with (
                    zipfile.ZipFile(temp_wheel, "r") as zf_read,
                    zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as zf_write,
                ):
                    for item in zf_read.infolist():
                        zf_write.writestr(item, zf_read.read(item.filename))
                    record_path = f"{dist_info_name}/RECORD"
                    zf_write.writestr(record_path, record_content)
                temp_wheel.unlink()
            size_mb = wheel_path.stat().st_size / (1024 * 1024)
            self.log(f"Wheel created successfully: {wheel_path} ({size_mb:.2f} MB)")
            return (True, f"Successfully created {package_info.wheel_filename}")
        except Exception as e:
            return (False, f"Error creating wheel: {e!s}")


class VenvRepacker:
    def __init__(
        self,
        site_packages_dir: str | None = None,
        output_dir: str | None = None,
        verbose: bool = False,
        dry_run: bool = False,
    ) -> None:
        self.verbose = verbose
        self.dry_run = dry_run
        self.site_packages = Path(site_packages_dir or Path.cwd()).resolve()
        if not self.site_packages.exists():
            raise ValueError(f"Site-packages directory not found: {self.site_packages}")
        self.output_dir = Path(output_dir or Path.home() / "tmp" / "whl").resolve()
        self.detector = PackageDetector(verbose=verbose)
        self.builder = WheelBuilder(verbose=verbose)
        self.stats = {
            "total_packages": 0,
            "pure_python_packages": 0,
            "packages_with_c_extensions": 0,
            "successfully_repacked": 0,
            "failed_packages": 0,
            "total_size_before": 0,
            "total_size_after": 0,
        }
        self.results = []

    def log(self, message: str, level: str = "INFO") -> None:
        if self.verbose or level in {"ERROR", "WARNING"}:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] [{level}] {message}")

    def find_packages(self) -> list[str]:
        exclude_patterns = {".dist-info", ".egg-info", ".egg", "__pycache__"}
        packages = {
            item.name
            for item in self.site_packages.iterdir()
            if item.is_dir()
            and (not item.name.startswith("."))
            and (not any(item.name.endswith(p) for p in exclude_patterns))
        }
        self.log(f"Found {len(packages)} packages")
        return sorted(packages)

    def repack_package(self, package_name: str) -> tuple[bool, str, PackageInfo | None]:
        try:
            package_info = self.detector.analyze_package(
                self.site_packages, package_name
            )
            if not package_info:
                return (False, "Failed to analyze package", None)
            self.log(f"Repacking: {package_name} v{package_info.version}")
            self.log(
                f"  Type: {('Pure Python' if package_info.is_pure_python else 'With C extensions')}"
            )
            self.log(f"  Wheel: {package_info.wheel_filename}")
            if self.dry_run:
                self.log("DRY RUN: Would create wheel")
                return (True, "Dry run - wheel not created", package_info)
            package_dir = self.site_packages / package_name
            success, message = self.builder.create_wheel(
                package_info, package_dir, self.output_dir
            )
            return (success, message, package_info)
        except Exception as e:
            return (False, f"Error: {e!s}", None)

    def repack_all(self) -> dict:
        print("\n╔════════════════════════════════════════════════════════════╗")
        print("║         Virtual Environment Package Repacker               ║")
        print("╚════════════════════════════════════════════════════════════╝\n")
        print(f"Site-packages: {self.site_packages}")
        print(f"Output directory: {self.output_dir}")
        print(f"Mode: {('DRY RUN' if self.dry_run else 'NORMAL')}")
        print("-" * 40)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        packages = self.find_packages()
        if not packages:
            print("No packages found to repack")
            return self.stats
        print(f"\nRepacking {len(packages)} packages...\n")
        for i, package_name in enumerate(packages, 1):
            print(f"[{i}/{len(packages)}] {package_name}...", end=" ", flush=True)
            success, message, package_info = self.repack_package(package_name)
            self.stats["total_packages"] += 1
            if success and package_info:
                self.stats["successfully_repacked"] += 1
                if package_info.is_pure_python:
                    self.stats["pure_python_packages"] += 1
                else:
                    self.stats["packages_with_c_extensions"] += 1
                print(f"✓ {message}")
                self.results.append(
                    {
                        "package": package_name,
                        "version": package_info.version,
                        "is_pure_python": package_info.is_pure_python,
                        "wheel_filename": package_info.wheel_filename,
                        "success": True,
                    }
                )
            else:
                self.stats["failed_packages"] += 1
                print(f"✗ {message}")
                self.results.append(
                    {"package": package_name, "success": False, "error": message}
                )
        return self.stats

    def print_stats(self) -> None:
        print("\n" + "=" * 40)
        print("STATISTICS")
        print("-" * 40)
        print(f"Total packages: {self.stats['total_packages']}")
        print(f"Successfully repacked: {self.stats['successfully_repacked']}")
        print(f"Failed: {self.stats['failed_packages']}")
        print()
        print(f"Pure Python packages: {self.stats['pure_python_packages']}")
        print(f"Packages with C extensions: {self.stats['packages_with_c_extensions']}")
        print("-" * 40)

    def save_report(self, report_file: str = "repack_report.json") -> None:
        report = {
            "timestamp": datetime.now().isoformat(),
            "site_packages": str(self.site_packages),
            "output_directory": str(self.output_dir),
            "statistics": self.stats,
            "results": self.results,
        }
        try:
            report_path = self.output_dir / report_file
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(f"\n✓ Report saved: {report_path}")
        except Exception as e:
            print(f"\n✗ Error saving report: {e!s}")

    def list_wheels(self) -> None:
        wheels = list(self.output_dir.glob("*.whl"))
        if not wheels:
            print("No .whl files found")
            return
        print(f"\nGenerated {len(wheels)} .whl files:")
        print("-" * 40)
        total_size = 0
        for wheel in sorted(wheels):
            size_mb = wheel.stat().st_size / (1024 * 1024)
            total_size += wheel.stat().st_size
            print(f"  {wheel.name:<50} {size_mb:>8.2f} MB")
        total_size_mb = total_size / (1024 * 1024)
        print("-" * 40)
        print(f"Total size: {total_size_mb:.2f} MB")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Repack Python packages from site-packages into .whl files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n  python repack_venv_packages.py\n  python repack_venv_packages.py --site-packages /path/to/site-packages\n  python repack_venv_packages.py --output /path/to/output\n  python repack_venv_packages.py --dry-run\n  python repack_venv_packages.py -v\n  python repack_venv_packages.py --report repack_report.json\n  python repack_venv_packages.py --list-wheels\n        ",
    )
    parser.add_argument(
        "--site-packages",
        default=None,
        help="Path to site-packages directory (default: current dir)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory for .whl files (default: ~/tmp/whl)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without creating files",
    )
    parser.add_argument(
        "--report", metavar="FILE", help="Save detailed report to JSON file"
    )
    parser.add_argument(
        "--list-wheels", action="store_true", help="List generated .whl files"
    )
    args = parser.parse_args()
    try:
        repacker = VenvRepacker(
            site_packages_dir=args.site_packages,
            output_dir=args.output,
            verbose=args.verbose,
            dry_run=args.dry_run,
        )
        repacker.repack_all()
        repacker.print_stats()
        if args.report:
            repacker.save_report(args.report)
        if args.list_wheels:
            repacker.list_wheels()
    except Exception as e:
        print(f"Error: {e!s}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
