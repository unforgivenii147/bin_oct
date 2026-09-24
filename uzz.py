#!/data/data/com.termux/files/home/.local/bin/python
"""
Python equivalent of:

    for f in *.whl; do
        unzip $f
        rm -v $f
    done

Behavior:
    * Iterate over every .whl file (a .whl is just a ZIP archive)
      in the target directory.
    * Extract each archive into the same directory that contains it.
    * Delete the original .whl **only if extraction succeeded**.
    * Any error is logged via `loguru` and the original .whl is preserved.
"""

from pathlib import Path
from zipfile import ZipFile, BadZipFile

# `loguru` gives us pretty, colored, timestamped logs out of the box.
from loguru import logger


def process_wheels(directory: Path = Path(".")) -> None:
    """
    Extract every .whl file in `directory` and delete the original archive
    on success. On any failure, the original .whl is left untouched.

    Parameters
    ----------
    directory : Path
        Folder to scan. Defaults to the current working directory,
        mirroring the shell glob `*.whl`.
    """
    # `Path(".").glob("*.whl")` mirrors the shell glob `*.whl`.
    # Materialize the list first: we mutate the directory while iterating
    # (by deleting extracted files), and generators don't like that.
    wheel_files = list(directory.glob("*.whl"))

    if not wheel_files:
        logger.warning("No .whl files found in {}", directory.resolve())
        return

    logger.info("Found {} .whl file(s) in {}", len(wheel_files), directory.resolve())

    for wheel_path in wheel_files:
        # Skip anything that isn't a regular file (e.g. a directory
        # that happens to end with ".whl").
        if not wheel_path.is_file():
            logger.debug("Skipping non-file entry: {}", wheel_path)
            continue

        logger.info("Processing {}", wheel_path.name)

        try:
            # `unzip $f` -> ZipFile(...).extractall(...)
            # Extract into the same directory that contains the .whl file.
            with ZipFile(wheel_path, "r") as archive:
                archive.extractall(path=wheel_path.parent)

            # Only reached if extractall() succeeded — safe to delete now.
            # `rm -v $f` -> Path.unlink() + verbose log.
            wheel_path.unlink()
            logger.success("Extracted and removed {}", wheel_path.name)

        except BadZipFile:
            # Not a valid ZIP archive — do NOT delete the original.
            logger.exception(
                "{} is not a valid ZIP/wheel file; original kept", wheel_path
            )

        except PermissionError:
            # E.g. read-only filesystem, or file in use.
            logger.exception("Permission error on {}; original kept", wheel_path)

        except OSError:
            # Any other OS-level error (disk full, path too long, ...).
            logger.exception("OS error while processing {}; original kept", wheel_path)

        except Exception:
            # Catch-all so a single bad archive can't kill the whole loop.
            logger.exception("Unexpected error on {}; original kept", wheel_path)

    logger.info("Done.")


if __name__ == "__main__":
    import sys

    # Allow an optional directory argument, e.g.:
    #     python extract_wheels.py /some/folder
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    process_wheels(target)
