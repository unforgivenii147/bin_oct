#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
from collections import Counter, defaultdict


def walk_file_stems(root: str = "."):
    stack = [root]
    while stack:
        top = stack.pop()
        try:
            with os.scandir(top) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name != ".git":
                            stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        stem = os.path.splitext(entry.name)[0]
                        yield stem
        except (PermissionError, OSError):
            pass


def levenshtein_bounded(a: str, b: str, max_dist: int) -> int:
    n, m = (len(a), len(b))
    if abs(n - m) > max_dist:
        return max_dist + 1
    if n < m:
        a, b = (b, a)
        n, m = (m, n)
    INF = max_dist + 1
    previous_row = [INF] * (m + 1)
    for j in range(min(m, max_dist) + 1):
        previous_row[j] = j
    for i in range(1, n + 1):
        current_row = [INF] * (m + 1)
        low = max(0, i - max_dist)
        high = min(m, i + max_dist)
        if low == 0 and i <= max_dist:
            current_row[0] = i
        for j in range(max(low, 1), high + 1):
            insert = previous_row[j] + 1
            delete = current_row[j - 1] + 1
            substitute = previous_row[j - 1] + (a[i - 1] != b[j - 1])
            current_row[j] = min(insert, delete, substitute)
        row_min = min(current_row[low : high + 1])
        if low == 0:
            row_min = min(row_min, current_row[0])
        if row_min > max_dist:
            return max_dist + 1
        previous_row = current_row
    return previous_row[m] if previous_row[m] <= max_dist else max_dist + 1


def group_similar(names: list[str], threshold: float = 0.8):
    n = len(names)
    used = [False] * n
    length_buckets = defaultdict(list)
    for idx, name in enumerate(names):
        length_buckets[len(name)].append(idx)
    groups = []
    for i, name in enumerate(names):
        if used[i]:
            continue
        used[i] = True
        group = [name]
        L = len(name)
        min_len = (L * 4 + 4) // 5
        max_len = 5 * L // 4
        candidates = []
        for l in range(min_len, max_len + 1):
            for idx in length_buckets.get(l, ()):
                if not used[idx]:
                    candidates.append(idx)
        for j in candidates:
            other = names[j]
            max_allowed_dist = max(L, len(other)) * 2 // 10
            if levenshtein_bounded(name, other, max_allowed_dist) <= max_allowed_dist:
                group.append(other)
                used[j] = True
        if len(group) > 1:
            groups.append(group)
    return groups


def main() -> None:
    cwd = os.getcwd()
    counter = Counter(walk_file_stems(cwd))
    for name, count in counter.most_common(100):
        if count > 2:
            print(f"{name}: {count}")
    print("\n=== Similar Filename Groups ===")
    groups = group_similar(list(counter.keys()), threshold=0.8)
    if not groups:
        print("No similar groups found.")
    else:
        for i, group in enumerate(groups, 1):
            print(f"Group {i}: {', '.join(group)}")


if __name__ == "__main__":
    raise SystemExit(main())
