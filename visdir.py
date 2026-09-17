#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import contextlib
import os

import matplotlib.pyplot as plt

cwd = os.getcwd()
subdir_sizes = {}
total_size = 0
for dirpath, _dirnames, filenames in os.walk(cwd):
    dir_size = 0
    for f in filenames:
        path = os.path.join(dirpath, f)
        with contextlib.suppress(OSError):
            dir_size += os.path.getsize(path)
    if dirpath != cwd:
        subdir_sizes[dirpath] = dir_size
        total_size += dir_size
    else:
        for f in filenames:
            path = os.path.join(dirpath, f)
            with contextlib.suppress(OSError):
                total_size += os.path.getsize(path)
subdir_percentages = {}
for subdir, size in subdir_sizes.items():
    if total_size > 0:
        percentage = size / total_size * 40
        subdir_percentages[os.path.basename(subdir)] = percentage
    else:
        subdir_percentages[os.path.basename(subdir)] = 0
labels = list(subdir_percentages.keys())
sizes = list(subdir_percentages.values())
reshaped_labels = []
for label in labels:
    reshaped_labels.append(label)
fig, ax = plt.subplots(figsize=(10, 10))
ax.pie(sizes, labels=reshaped_labels, autopct="%1.1f%%beding", startangle=140)
ax.axis("equal")
title = "subdirs sizes"
plt.title(title)
output_filename = "size.png"
plt.savefig(output_filename, bbox_inches="tight")
print(f"saved '{output_filename}'")
print(f"size: {total_size}")
