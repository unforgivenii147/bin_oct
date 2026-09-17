#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import multiprocessing
import os
import subprocess
import sys
from functools import partial


def get_pip_command():
    for pip_cmd in ["pip", "pip3"]:
        try:
            subprocess.run([pip_cmd, "--version"], capture_output=True, check=True)
            return pip_cmd
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return None


def install_package(pkg_name, pip_cmd="pip3", dry_run=False):
    cmd = [
        pip_cmd,
        "install",
        "--force-reinstall",
        "--upgrade",
        "--no-deps",
        pkg_name,
    ]
    if dry_run:
        print(f"[DRY RUN] Would run: {' '.join(cmd)}")
        return (pkg_name, True, "Dry run")
    print(f"Reinstalling: {pkg_name}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
        if result.returncode == 0:
            print(f"✓ Successfully reinstalled: {pkg_name}")
            return (pkg_name, True, result.stdout)
        else:
            print(f"✗ Failed to reinstall {pkg_name}")
            error_msg = result.stderr.strip() or result.stdout.strip()
            print(f"  Error: {error_msg[:200]}")
            return (pkg_name, False, error_msg)
    except subprocess.TimeoutExpired:
        print(f"✗ Timeout reinstalling {pkg_name}")
        return (pkg_name, False, "Timeout after 300 seconds")
    except Exception as e:
        print(f"✗ Error reinstalling {pkg_name}: {e}")
        return (pkg_name, False, str(e))


def read_package_list(path):
    packages = []
    try:
        with open(path, "r") as f:
            for line in f:
                pkg = line.strip()
                if pkg and not pkg.startswith("#"):
                    packages.append(pkg)
    except FileNotFoundError:
        print(f"Error: File '{path}' not found.")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading file: {e}")
        sys.exit(1)
    return packages


def check_package_in_system_site(pkg_name):
    try:
        import site

        system_site = site.getsitepackages()
        user_site = site.getusersitepackages()
        result = subprocess.run(
            ["pip3", "show", "-f", pkg_name],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if line.startswith("Location:"):
                    location = line.split(":", 1)[1].strip()
                    if location in system_site:
                        return True
                    elif location == user_site:
                        return False
        return False
    except:
        return False


def main():
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    else:
        input_file = os.path.expanduser("~/missing.txt")
    dry_run = "--dry-run" in sys.argv
    cpu_count = multiprocessing.cpu_count()
    max_workers = min(max(1, cpu_count // 2), 8)
    if "--workers" in sys.argv:
        idx = sys.argv.index("--workers")
        if idx + 1 < len(sys.argv):
            try:
                max_workers = int(sys.argv[idx + 1])
            except ValueError:
                print(f"Invalid worker count, using default: {max_workers}")
    print(f"Reading packages from: {input_file}")
    print(f"Using {max_workers} parallel workers")
    if dry_run:
        print("DRY RUN MODE - No packages will be installed")
    print("-" * 40)
    pip_cmd = get_pip_command()
    if not pip_cmd:
        print("Error: pip is not installed or not found in PATH")
        sys.exit(1)
    print(f"Using: {pip_cmd}")
    packages = read_package_list(input_file)
    if not packages:
        print("No packages found in file.")
        sys.exit(0)
    print(f"Found {len(packages)} package(s) to reinstall.")
    print("-" * 40)
    if dry_run:
        for pkg in packages:
            install_package(pkg, pip_cmd, dry_run=True)
        sys.exit(0)
    worker_func = partial(install_package, pip_cmd=pip_cmd)
    successful = 0
    failed = 0
    failed_packages = []
    try:
        with multiprocessing.Pool(processes=max_workers) as pool:
            results = pool.map(worker_func, packages)
            for pkg_name, success, _output in results:
                if success:
                    successful += 1
                else:
                    failed += 1
                    failed_packages.append(pkg_name)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Terminating...")
        pool.terminate()
        sys.exit(1)
    except Exception as e:
        print(f"\nError during parallel execution: {e}")
        sys.exit(1)
    print("\n" + "=" * 40)
    print(f"Summary: {successful} successful, {failed} failed")
    if failed_packages:
        print("\nFailed packages:")
        for pkg in failed_packages:
            print(f"  - {pkg}")
    print("-" * 40)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
