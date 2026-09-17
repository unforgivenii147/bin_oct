#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    print("Error: tqdm is required. Install it with: pip install tqdm")
    sys.exit(1)


def find_dist_info_dirs(site_packages: Path) -> list[Path]:
    dist_dirs = []
    dist_dirs.extend(site_packages.glob("*.dist-info"))
    dist_dirs.extend(site_packages.glob("*.egg-info"))
    return sorted(dist_dirs)


def get_package_name_version(dist_dir: Path) -> tuple[str, str]:
    name = dist_dir.name
    if name.endswith(".dist-info"):
        name = name[:-10]
    elif name.endswith(".egg-info"):
        name = name[:-9]
    parts = name.rsplit("-", 1)
    if len(parts) == 2:
        return (parts[0], parts[1])
    return (parts[0], "0.0.0")


def read_record_file(
    dist_dir: Path, site_packages: Path
) -> tuple[list[Path], set[Path]]:
    record_file = dist_dir / "RECORD"
    if not record_file.exists():
        return ([], set())
    existing_files = []
    missing_files = set()
    with record_file.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or not row[0]:
                continue
            path = row[0]
            full_path = Path(path) if Path(path).is_absolute() else site_packages / path
            if full_path.suffix == ".pyc":
                continue
            if full_path.exists():
                existing_files.append(full_path)
            else:
                missing_files.add(full_path)
    return (existing_files, missing_files)


def get_wheel_tag(dist_dir: Path) -> str | None:
    wheel_file = dist_dir / "WHEEL"
    if not wheel_file.exists():
        return None
    with wheel_file.open(encoding="utf-8") as f:
        for line in f:
            if line.startswith("Tag:"):
                return line.split(":", 1)[1].strip()
    return None


def copy_files_to_temp(files: list[Path], site_packages: Path, temp_dir: Path) -> None:
    for path in files:
        try:
            rel_path = path.relative_to(site_packages)
        except ValueError:
            rel_path = Path(path.name)
        dest_path = temp_dir / rel_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            shutil.copy2(path, dest_path)
        elif path.is_dir():
            shutil.copytree(path, dest_path, dirs_exist_ok=True)


def create_wheel(
    pkg_name: str,
    pkg_version: str,
    temp_dir: Path,
    output_dir: Path,
    wheel_tag: str | None,
) -> bool:
    try:
        wheel_name = f"{pkg_name}-{pkg_version}"
        wheel_name += f"-{wheel_tag}" if wheel_tag else "-py3-none-any"
        wheel_file = output_dir / f"{wheel_name}.whl"
        cmd = [
            sys.executable,
            "-m",
            "wheel",
            "pack",
            str(temp_dir),
            "-d",
            str(output_dir),
        ]
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if result.returncode == 0:
            return True
        with zipfile.ZipFile(wheel_file, "w", zipfile.ZIP_DEFLATED) as whl:
            for path in temp_dir.rglob("*"):
                if path.is_file():
                    arcname = path.relative_to(temp_dir)
                    whl.write(path, arcname)
        return True
    except Exception as e:
        print(f"Error creating wheel: {e}")
        return False


def repack_package(
    dist_dir: Path, site_packages: Path, output_dir: Path, not_repacked_dir: Path
) -> bool:
    pkg_name, pkg_version = get_package_name_version(dist_dir)
    existing_files, missing_files = read_record_file(dist_dir, site_packages)
    if not existing_files:
        return False
    has_missing_critical = any(
        f.suffix in {".py", ""} or f.is_dir() for f in missing_files
    )
    if has_missing_critical:
        pkg_not_repacked = not_repacked_dir / pkg_name
        pkg_not_repacked.mkdir(parents=True, exist_ok=True)
        for path in existing_files:
            try:
                rel_path = path.relative_to(site_packages)
                dest = pkg_not_repacked / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                if path.is_file():
                    shutil.copy2(path, dest)
            except Exception as e:
                print(f"Error copying {path}: {e}")
        return False
    wheel_tag = get_wheel_tag(dist_dir)
    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_path = Path(temp_dir_str)
        copy_files_to_temp(existing_files, site_packages, temp_path)
        return create_wheel(pkg_name, pkg_version, temp_path, output_dir, wheel_tag)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Repack installed Python packages as wheels"
    )
    parser.add_argument("packages", nargs="*", help="Package names to repack")
    parser.add_argument(
        "-a", "--all", action="store_true", help="Repack all installed packages"
    )
    args = parser.parse_args()
    if not args.all and (not args.packages):
        parser.error("Specify package names or use -a/--all")
    site_packages = Path.cwd()
    output_dir = Path.home() / "tmp" / "whl"
    not_repacked_dir = Path.home() / "tmp" / "not_repacked"
    output_dir.mkdir(parents=True, exist_ok=True)
    not_repacked_dir.mkdir(parents=True, exist_ok=True)
    all_dist_dirs = find_dist_info_dirs(site_packages)
    if not args.all:
        pkg_set = set(args.packages)
        all_dist_dirs = [
            d for d in all_dist_dirs if get_package_name_version(d)[0] in pkg_set
        ]
    success_count = 0
    failed_count = 0
    with tqdm(total=len(all_dist_dirs), desc="Repacking packages") as pbar:
        for dist_dir in all_dist_dirs:
            pkg_name, _ = get_package_name_version(dist_dir)
            pbar.set_description(f"Repacking {pkg_name}")
            if repack_package(dist_dir, site_packages, output_dir, not_repacked_dir):
                success_count += 1
            else:
                failed_count += 1
            pbar.update(1)
    print(f"\n✓ Successfully repacked: {success_count}")
    print(f"✗ Failed to repack: {failed_count}")
    print(f"\nWheels saved to: {output_dir}")
    if failed_count > 0:
        print(f"Failed packages copied to: {not_repacked_dir}")


if __name__ == "__main__":
    raise SystemExit(main())
