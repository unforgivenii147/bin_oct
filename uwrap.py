#!/data/data/com.termux/files/home/.local/bin/python
"""
Universal command wrapper with:
- Glob expansion for arguments
- Colored output (auto-disables when not a TTY)
- Logging to ~/tmp/log/apps/
- Exit code preservation
- Optional timestamp prefix
- Clipboard support via termux-clipboard-set (max 1MB) — ENABLED BY DEFAULT
"""

import argparse
import datetime
import glob
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

# ── Configuration ──────────────────────────────────────────
LOG_DIR = Path.home() / "tmp" / "log" / "apps"
CLIPBOARD_MAX_BYTES = 1 * 1024 * 1024  # 1MB
COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "gray": "\033[90m",
}
# ──────────────────────────────────────────────────────────


def supports_color() -> bool:
    """Check if stdout supports ANSI colors.

    Returns True only if:
    - NO_COLOR env var is not set
    - TERM is not "dumb"
    - stdout is a TTY (interactive terminal)
    """
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def color(text: str, color_name: str = "reset", bold: bool = False) -> str:
    """Wrap text in ANSI color codes if supported.

    Args:
        text: The string to colorize
        color_name: Key into COLORS dict (e.g. "red", "green")
        bold: Whether to add bold attribute

    Returns:
        Colorized string, or original text if colors are disabled
    """
    if not supports_color():
        return text
    prefix = COLORS.get(color_name, COLORS["reset"])
    if bold:
        prefix += COLORS["bold"]
    return f"{prefix}{text}{COLORS['reset']}"


def expand_glob_args(args: list[str]) -> list[str]:
    """Expand glob patterns in arguments (like bash does).

    Args:
        args: List of command-line arguments

    Returns:
        Expanded list where glob patterns are replaced with matching files.
        Non-glob arguments are passed through unchanged.
        If a glob matches nothing, the original pattern is kept (bash behavior).
    """
    expanded = []
    for arg in args:
        # Skip if it's an option or contains no glob chars
        if not any(ch in arg for ch in "*?["):
            expanded.append(arg)
            continue
        # Try glob expansion
        matches = glob.glob(arg)
        if matches:
            expanded.extend(sorted(matches))
        else:
            # Keep original if no matches (bash behavior)
            expanded.append(arg)
    return expanded


def create_log_file(name: str) -> Path:
    """Create a unique log file in LOG_DIR.

    Args:
        name: Command name used as filename prefix

    Returns:
        Path to the created log file (guaranteed unique via timestamp + counter)
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    milliseconds = int(time.time() * 1000) % 1000
    log_file = LOG_DIR / f"{name}_{timestamp}_{milliseconds:03d}.log"
    counter = 1
    while log_file.exists():
        log_file = LOG_DIR / f"{name}_{timestamp}_{milliseconds:03d}_{counter}.log"
        counter += 1
    return log_file


def write_log_header(log_file: Path, command: list[str], cwd: str) -> None:
    """Write header info to log file.

    Args:
        log_file: Path to log file
        command: Full command list (binary + args)
        cwd: Current working directory
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"{'=' * 50}\n")
        f.write(f"Command: {shlex.join(command)}\n")
        f.write(f"Timestamp: {timestamp}\n")
        f.write(f"Cwd: {cwd}\n")
        f.write(f"{'=' * 50}\n\n")


def write_log_footer(log_file: Path, exit_code: int) -> None:
    """Write footer info to log file.

    Args:
        log_file: Path to log file
        exit_code: Exit code of the wrapped command
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 50}\n")
        f.write(f"Exit Code: {exit_code}\n")
        f.write(f"Completed: {timestamp}\n")
        f.write(f"{'=' * 50}\n")


def copy_to_clipboard(data: str) -> bool:
    """Copy text to Android clipboard via termux-clipboard-set.

    Args:
        data: Text to copy

    Returns:
        True if successful, False otherwise (e.g. termux-api not installed)
    """
    try:
        proc = subprocess.run(
            ["termux-clipboard-set"],
            input=data,
            text=True,
            capture_output=True,
            timeout=10,
        )
        return proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def parse_args(argv: list[str]) -> tuple[str, list[str], argparse.Namespace]:
    """Parse wrapper-specific options and return command components.



    Args:
        argv: sys.argv[1:] (arguments after script name)

    Returns:
        Tuple of (command_name, command_args, options_namespace)
    """
    parser = argparse.ArgumentParser(
        description="Universal command wrapper with logging, colors, and clipboard",
        add_help=False,
    )
    parser.add_argument(
        "--no-color", action="store_true", help="Disable colored output"
    )
    parser.add_argument("--no-log", action="store_true", help="Disable logging")
    parser.add_argument(
        "--timestamp", action="store_true", help="Prefix output with timestamps"
    )
    parser.add_argument(
        "--no-clipboard",
        action="store_true",
        help="Disable clipboard copying (enabled by default)",
    )
    parser.add_argument("--help", action="store_true", help="Show this help message")

    known, rest = parser.parse_known_args(argv)

    if known.help:
        parser.print_help()
        raise SystemExit(0)

    if not rest:
        parser.print_usage(sys.stderr)
        raise SystemExit(
            "error: provide a command to wrap, e.g. wrapper.py ls -la *.py"
        )

    return rest[0], rest[1:], known


def main() -> None:
    """Main entry point: parse args, run command, log output, optionally copy to clipboard."""
    name, command_args, opts = parse_args(sys.argv[1:])

    # Expand glob patterns in arguments
    command_args = expand_glob_args(command_args)

    # Build full command list
    command = [name, *command_args]

    # Setup logging (unless disabled)
    log_file = None
    if not opts.no_log:
        log_file = create_log_file(name)
        write_log_header(log_file, command, os.getcwd())

    # Run command
    exit_code = 1
    # Buffer for clipboard (None if disabled or exceeded size limit)
    output_buffer = [] if not opts.no_clipboard else None
    output_size = 0

    try:
        # Open log file for appending if logging is enabled
        with (
            open(log_file, "a", encoding="utf-8")
            if log_file
            else nullcontext() as log_f
        ):
            # Start subprocess with stdout piped for real-time reading
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Merge stderr into stdout
                text=True,
                bufsize=1,  # Line-buffered
            )

            # Read output line by line in real-time
            for line in process.stdout:
                # Colorize lines that look like errors/warnings
                if line.startswith(("Error:", "error:", "WARNING:", "warning:")):
                    output = color(line, "yellow")
                elif line.startswith(("Fatal:", "fatal:", "Traceback")):
                    output = color(line, "red", bold=True)
                else:
                    output = line

                # Optional timestamp prefix
                if opts.timestamp:
                    ts = datetime.datetime.now().strftime("%H:%M:%S")
                    output = color(f"[{ts}] ", "gray") + output

                # Write to stdout (real-time display)
                sys.stdout.write(output)
                sys.stdout.flush()

                # Write to log file if logging enabled
                if log_f:
                    log_f.write(line)
                    log_f.flush()

                # Buffer for clipboard (track cumulative size)
                if output_buffer is not None:
                    output_buffer.append(line)
                    output_size += len(line.encode("utf-8"))
                    # If exceeds 1MB limit, disable clipboard copying
                    if output_size > CLIPBOARD_MAX_BYTES:
                        output_buffer = None  # Too large, disable clipboard
                        print(
                            color(
                                f"\n[clipboard] Output exceeds {CLIPBOARD_MAX_BYTES // 1024}KB limit, skipping copy",
                                "yellow",
                            ),
                            file=sys.stderr,
                        )

            # Wait for process to complete and get exit code
            process.wait()
            exit_code = process.returncode

    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully
        exit_code = 130
        print(color("\nInterrupted by user", "red", bold=True), file=sys.stderr)
    except FileNotFoundError:
        # Command not found in PATH
        exit_code = 127
        msg = color(f"Error: command '{name}' not found", "red", bold=True)
        print(msg, file=sys.stderr)
        if log_file:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"Error: command '{name}' not found\n")
    except Exception as exc:
        # Catch-all for other errors
        exit_code = 1
        error_msg = color(f"Error running command: {exc}", "red", bold=True)
        print(error_msg, file=sys.stderr)
        if log_file:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"Error: {exc}\n")

    # Copy to clipboard if enabled, within size limit, and command succeeded
    if output_buffer is not None:
        clipboard_text = "".join(output_buffer)
        copy_to_clipboard(clipboard_text)

    # Finalize logging
    if log_file:
        write_log_footer(log_file, exit_code)
        print(color(f"Log saved to: {log_file}", "cyan"), file=sys.stderr)

    # Exit with the wrapped command's exit code
    raise SystemExit(exit_code)


class nullcontext:
    """Null context manager for when logging is disabled.

    Provides a no-op context manager so `with` statements work
    even when there's no log file to open.
    """

    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False


if __name__ == "__main__":
    main()
