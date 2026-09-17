#!/data/data/com.termux/files/home/.local/bin/python
"""Validate HTTP(S) proxies from proxies.txt via httpbin.org/ip and optionally save the working ones.

Regenerate this script: read newline-separated proxies from proxies.txt with pathlib, strip whitespace,
check each via requests.get("http://httpbin.org/ip", proxies=..., timeout=5) using a fixed 8-worker
multiprocessing Pool selected by --pool-method (map, starmap, imap_unordered, apply_async), print
colorama-tagged results, then interactively ask whether to save valid proxies to a user-chosen file,
logging with loguru.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from time import sleep
from typing import Final, TypeAlias

import requests
from colorama import Fore, Style, init as colorama_init
from loguru import logger

colorama_init(autoreset=True)

POOL_WORKERS: Final[int] = 8
POOL_METHODS: Final[tuple[str, ...]] = (
    "map",
    "starmap",
    "imap_unordered",
    "apply_async",
)

PROXIES_FILE: Final[Path] = Path("proxies.txt")
CHECK_URL: Final[str] = "http://httpbin.org/ip"
REQUEST_TIMEOUT: Final[int] = 5
THROTTLE_SECONDS: Final[float] = 0.5

ProxyTask: TypeAlias = tuple[int, int, str]
ProxyCheckResult: TypeAlias = tuple[str, str | None]


def check_proxy(task: ProxyTask) -> ProxyCheckResult:
    """Check one proxy and return (colored_result, proxy_if_valid_or_none)."""
    index, total, proxy = task
    proxy = proxy.strip()
    proxies = {
        "http": f"http://{proxy}",
        "https": f"https://{proxy}",
    }

    is_valid = False
    try:
        response = requests.get(CHECK_URL, proxies=proxies, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            result = f"{Fore.GREEN}[{index}/{total}] ✅ {proxy}{Style.RESET_ALL}"
            is_valid = True
        else:
            result = f"{Fore.RED}[{index}/{total}] ❌ {proxy}{Style.RESET_ALL}"
    except requests.exceptions.RequestException:
        result = f"{Fore.RED}[{index}/{total}] ❌ {proxy}{Style.RESET_ALL}"

    sleep(THROTTLE_SECONDS)
    return (result, proxy if is_valid else None)


def _check_proxy_tuple(item: tuple[ProxyTask]) -> ProxyCheckResult:
    """Tuple-argument wrapper around :func:`check_proxy` for ``Pool.map``."""
    return check_proxy(item[0])


def _run_pool(tasks: Sequence[ProxyTask], method: str) -> list[ProxyCheckResult]:
    """Check *tasks* with a fixed 8-worker Pool using *method*."""
    with Pool(processes=POOL_WORKERS) as pool:
        if method == "map":
            return pool.map(_check_proxy_tuple, [(task,) for task in tasks])

        if method == "starmap":
            return pool.starmap(check_proxy, tasks)

        if method == "imap_unordered":
            return list(pool.imap_unordered(_check_proxy_tuple, [(t,) for t in tasks]))

        if method == "apply_async":
            async_results: list[AsyncResult[ProxyCheckResult]] = [
                pool.apply_async(check_proxy, (task,)) for task in tasks
            ]
            return [result.get() for result in async_results]

    raise ValueError(f"Unsupported pool method: {method}")


def load_proxies(path: Path) -> list[str]:
    """Return the non-empty, stripped lines of *path*, or an empty list if missing."""
    if not path.exists():
        logger.error(f"Proxies file not found: {path}")
        return []
    try:
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except OSError as exc:
        logger.error(f"Error reading {path}: {exc}")
        return []


def save_valid_proxies(valid_proxies: Sequence[str]) -> None:
    """Prompt for a filename and write *valid_proxies* to it."""
    save_choice = input(
        "Do you want to save the valid proxies to a file? (y/n): "
    ).strip()
    if save_choice.lower() != "y":
        return

    raw_name = input(
        "Enter the filename to save valid proxies (default: valid_proxies.txt): "
    ).strip()
    output_file = Path(raw_name) if raw_name else Path("valid_proxies.txt")

    try:
        output_file.write_text(
            "".join(f"{proxy}\n" for proxy in valid_proxies), encoding="utf-8"
        )
        logger.info(f"Valid proxies saved to {output_file}")
    except OSError as exc:
        logger.error(f"Error writing {output_file}: {exc}")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pool-method",
        choices=POOL_METHODS,
        default="map",
        help="Multiprocessing pool method to use for proxy checking.",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args: argparse.Namespace = parse_args()
    pool_method: str = args.pool_method

    proxies_list = load_proxies(PROXIES_FILE)
    if not proxies_list:
        logger.warning("No proxies to check.")
        return 0

    total_proxies = len(proxies_list)
    tasks: list[ProxyTask] = [
        (index, total_proxies, proxy)
        for index, proxy in enumerate(proxies_list, start=1)
    ]

    valid_proxies: list[str] = []
    for result, valid_proxy in _run_pool(tasks, pool_method):
        logger.info(result)
        if valid_proxy:
            valid_proxies.append(valid_proxy)

    if valid_proxies:
        save_valid_proxies(valid_proxies)
    else:
        logger.warning("No valid proxies found.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
