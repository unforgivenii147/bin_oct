#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import contextlib
import os
import sys

import matplotlib.pyplot as plt

MAX_DIRS = 25
MIN_SIZE_KB = 100
OUTPUT_FILENAME = "dirinfo.png"
CHART_TYPE = "bar"


def get_dir_size(start_path: str) -> int:
    total_size = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(start_path):
            for f in filenames:
                path = os.path.join(dirpath, f)
                if not os.path.islink(path):
                    with contextlib.suppress(OSError):
                        total_size += os.path.getsize(path)
    except Exception as e:
        print(f"Error walking directory {start_path}: {e}", file=sys.stderr)
    return total_size


def create_chart(target_dir: str = ".") -> None:
    target_dir = os.path.abspath(target_dir)
    print(f"Analyzing directory: {target_dir}")
    subdir_sizes = {}
    total_size = 0
    try:
        for entry in os.scandir(target_dir):
            if (
                entry.is_dir()
                and not entry.name.startswith(".")
                and not os.path.islink(entry.path)
            ):
                size = get_dir_size(entry.path)
                if size >= MIN_SIZE_KB * 1024:
                    subdir_sizes[entry.name] = size
                    total_size += size
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return
    if not subdir_sizes:
        print("No subdirectories meeting criteria.")
        return
    sorted_subdirs = sorted(
        subdir_sizes.items(), key=lambda item: item[1], reverse=True
    )
    top_subdirs = dict(sorted_subdirs[:MAX_DIRS])
    remaining_size = sum(
        size for name, size in subdir_sizes.items() if name not in top_subdirs
    )
    percentages = {name: size / total_size * 40 for name, size in top_subdirs.items()}
    if remaining_size > 0:
        percentages["Other"] = remaining_size / total_size * 40
    labels = list(top_subdirs.keys())
    if remaining_size > 0:
        labels.append("Other")
    sizes = list(percentages.values())
    _fig, ax = plt.subplots(figsize=(10, 6))
    if CHART_TYPE == "bar":
        ax.bar(labels, sizes, color="skyblue")
        ax.set_ylabel("Percentage %")
        ax.set_title("Directory Size Distribution")
    elif CHART_TYPE == "pie":
        ax.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=140)
        ax.set_title("Directory Size Distribution")
    elif CHART_TYPE == "circle":
        ax.pie(
            sizes,
            labels=labels,
            autopct="%1.1f%%",
            startangle=140,
            wedgeprops={"width": 0.4},
        )
        ax.set_title("Directory Size Distribution")
    else:
        print(f"Chart type '{CHART_TYPE}' is not supported.")
        return
    plt.tight_layout()
    try:
        plt.savefig(OUTPUT_FILENAME, dpi=300)
        print(f"Chart saved to {OUTPUT_FILENAME}")
    except Exception as e:
        print(f"Error saving chart: {e}", file=sys.stderr)
    plt.close()


if __name__ == "__main__":
    create_chart()
