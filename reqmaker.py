#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REQ = Path("requirements.txt")
BLACKLIST = {
    "pydantic-core",
    "h5py",
    "jiter",
    "jupyter-server-ydoc",
    "scipy",
    "rpds-py",
    "nh3",
    "pandas",
    "torch",
    "torchvision",
    "scikit-learn",
    "pynacl",
    "gensim",
    "spacy",
    "torchaudio",
    "selenium",
    "jupyter-ydoc",
    "tensorflow",
}


def save_to_req(packages) -> None:
    REQ.write_text("\n".join(packages) + "\n", encoding="utf-8")


def run_pip_check():
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "check"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return e.stdout.strip() if e.stdout else ""


def parse_pip_check(output):
    pattern = re.compile(
        r"^(\S+)\s+.*requires\s+([^,]+),\s+which is not installed\.$", re.MULTILINE
    )
    missing_deps = defaultdict(list)
    for line in output.splitlines():
        match = pattern.match(line.strip())
        if match:
            requirer = match.group(1)
            missing_pkg = match.group(2).strip()
            if missing_pkg in BLACKLIST:
                continue
            missing_deps[missing_pkg].append(requirer)
    return missing_deps


def format_deptree(missing_deps) -> None:
    if not missing_deps:
        print("No missing dependencies found.")
        return
    print("required packages:")
    for pkg, requirers in sorted(missing_deps.items()):
        unique_requirers = sorted(set(requirers))
        requirers_str = ", ".join(unique_requirers)
        print(f"  - {pkg} --> {requirers_str}")


def main() -> None:
    output = run_pip_check()
    if not output:
        print("No output from `pip check`. Are you in a virtual environment?")
        return
    missing_deps = parse_pip_check(output)
    format_deptree(missing_deps)
    save_to_req(sorted(missing_deps.keys()))


if __name__ == "__main__":
    raise SystemExit(main())
