#!/data/data/com.termux/files/home/.local/bin/python
"""Extract all .whl files in the current directory into sibling directories named after their package.

Uses a multiprocessing pool of 8 workers to extract each wheel in parallel, logging
progress with loguru, deleting each wheel after successful extraction, and reporting
per-file success or failure.
"""

from multiprocessing import Pool
from pathlib import Path
from zipfile import ZipFile

from loguru import logger

MAX_WORKERS: int = 8


def get_package_name(wheel_filename: str) -> str:
    """Derive the package name from a wheel filename.

    The wheel filename format is ``{name}-{version}-...whl``; this returns the
    portion before the first dash-separated component that starts with a digit.
    """
    parts: list[str] = wheel_filename.replace(".whl", "").split("-")
    for i, part in enumerate(parts):
        if part and part[0].isdigit():
            return "-".join(parts[:i])
    return parts[0]


def extract_wheel(wheel_path: Path) -> tuple[str, bool]:
    """Extract a wheel into a sibling directory named after its package.

    Returns a tuple of (message, success) where ``message`` is the wheel filename
    on success or an error description on failure.
    """
    pkg_name: str = get_package_name(wheel_path.name)
    output_dir: Path = wheel_path.parent / pkg_name
    output_dir.mkdir(exist_ok=True)
    try:
        with ZipFile(wheel_path) as whl:
            whl.extractall(output_dir)
        wheel_path.unlink()
        return wheel_path.name, True
    except Exception as e:
        return f"{wheel_path.name}: {e}", False


def main() -> int:
    """Find all wheels in the current directory and extract them in parallel."""
    wheels: list[Path] = list(Path.cwd().glob("*.whl"))
    if not wheels:
        print("No .whl files found")
        return 0

    results: list[tuple[str, bool] | BaseException] = []
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [pool.apply_async(extract_wheel, (w,)) for w in wheels]
        for ar in async_results:
            try:
                results.append(ar.get())
            except Exception as e:  # pragma: no cover - defensive
                results.append(e)

    for result in results:
        if isinstance(result, BaseException):
            logger.error(f"✗ {result}")
            continue
        name, success = result
        status = "✓" if success else "✗"
        if success:
            print(f"{status} {name}")
        else:
            logger.error(f"{status} {name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
