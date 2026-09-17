#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

try:
    import cv2
    import pytesseract
    from PIL import Image

    HAS_OCR = True
except ImportError:
    HAS_OCR = False


class TreeParser:
    TREE_SYMBOLS = ["├", "└", "│", "┌", "─", "┐"]

    def __init__(self, base_path: Path = Path.cwd()):
        self.base_path = base_path
        self.entries: list[dict[str, Any]] = []

    def parse(self, text: str) -> list[dict[str, Any]]:
        lines = [line.rstrip() for line in text.split("\n") if line.strip()]
        if not lines:
            return []
        format_type = self._detect_format(lines)
        if format_type == "tree":
            self._parse_tree_format(lines)
        elif format_type == "indented":
            self._parse_indented_format(lines)
        else:
            self._parse_simple_format(lines)
        self._determine_file_types()
        return self.entries

    def _detect_format(self, lines: list[str]) -> str:
        has_tree_symbols = any(
            any(sym in line for sym in self.TREE_SYMBOLS) for line in lines
        )
        has_indentation = any(line.startswith((" ", "\t")) for line in lines)
        has_paths = any("/" in line or "\\" in line for line in lines)
        if has_tree_symbols:
            return "tree"
        elif has_indentation:
            return "indented"
        else:
            return "simple"

    def _parse_tree_format(self, lines: list[str]) -> None:
        stack: list[tuple[int, Path]] = []
        for line in lines:
            if not line.strip() or line.strip().startswith("#"):
                continue
            tree_matches = []
            for sym in ["├── ", "└── ", "│   ", "    "]:
                if line.startswith(sym):
                    tree_matches.append((len(sym), sym))
            if tree_matches:
                depth = len(tree_matches) // 4
                name = line[len(tree_matches[0][1]) :].strip()
            else:
                match = re.match(r"^([\s\|┌└├─]+)([^\s]+)(.*)$", line)
                if match:
                    prefix, name, _ = match.groups()
                    depth = len(prefix) // 4
                else:
                    name = line.strip()
                    depth = 0
            name = self._clean_name(name)
            if not name:
                continue
            if name in (".", "./", ".\\"):
                self.entries.append(
                    {
                        "depth": 0,
                        "name": ".",
                        "is_dir": True,
                        "explicit_dir": True,
                        "raw": name,
                    }
                )
                stack = [(0, self.base_path)]
                continue
            while stack and stack[-1][0] >= depth:
                stack.pop()
            if stack:
                parent_path = stack[-1][1]
                current_path = parent_path / name
            else:
                current_path = self.base_path / name
            explicit_dir = name.endswith(("/", "\\"))
            self.entries.append(
                {
                    "depth": depth,
                    "name": name,
                    "path": current_path,
                    "is_dir": explicit_dir,
                    "explicit_dir": explicit_dir,
                    "raw": name,
                }
            )
            if not explicit_dir:
                stack.append((depth, current_path))

    def _parse_indented_format(self, lines: list[str]) -> None:
        stack: list[tuple[int, Path]] = []
        for line in lines:
            if not line.strip() or line.strip().startswith("#"):
                continue
            stripped = line.lstrip()
            indent_len = len(line) - len(stripped)
            indent = indent_len // 4
            name = stripped.strip()
            name = self._clean_name(name)
            if not name:
                continue
            while stack and stack[-1][0] >= indent:
                stack.pop()
            if stack:
                parent_path = stack[-1][1]
                current_path = parent_path / name
            else:
                current_path = self.base_path / name
            explicit_dir = name.endswith(("/", "\\"))
            self.entries.append(
                {
                    "depth": indent,
                    "name": name,
                    "path": current_path,
                    "is_dir": explicit_dir,
                    "explicit_dir": explicit_dir,
                    "raw": name,
                }
            )
            if not explicit_dir:
                stack.append((indent, current_path))

    def _parse_simple_format(self, lines: list[str]) -> None:
        for line in lines:
            if not line.strip() or line.strip().startswith("#"):
                continue
            name = line.strip()
            name = self._clean_name(name)
            if not name:
                continue
            explicit_dir = name.endswith(("/", "\\"))
            clean_name = name.rstrip("/\\")
            self.entries.append(
                {
                    "depth": 0,
                    "name": clean_name,
                    "path": self.base_path / clean_name,
                    "is_dir": explicit_dir,
                    "explicit_dir": explicit_dir,
                    "raw": name,
                }
            )

    def _clean_name(self, name: str) -> str:
        name = re.sub(r"\s+#.*$", "", name)
        name = name.strip()
        return name

    def _determine_file_types(self) -> None:
        for entry in self.entries:
            if entry["explicit_dir"] or entry["name"] in (".", "./", ".\\"):
                entry["is_dir"] = True
        depths = [e["depth"] for e in self.entries]
        for i, entry in enumerate(self.entries):
            if entry["is_dir"]:
                continue
            if i + 1 < len(self.entries):
                next_entry = self.entries[i + 1]
                if next_entry["depth"] > entry["depth"]:
                    entry["is_dir"] = True
        for entry in self.entries:
            if (
                not entry["is_dir"]
                and "." in entry["name"].split("/")[-1].split("\\")[-1]
            ):
                entry["is_dir"] = False


class ImageProcessor:
    @staticmethod
    def is_image_file(path: Path) -> bool:
        image_extensions = [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"]
        return path.suffix.lower() in image_extensions

    @staticmethod
    def preprocess_image(image_path: Path) -> Image.Image | None:
        try:
            img = Image.open(image_path)
            if img.mode != "RGB":
                img = img.convert("RGB")
            img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
            thresh = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2
            )
            kernel = np.ones((2, 2), np.uint8)
            cleaned = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
            result = Image.fromarray(cv2.cvtColor(cleaned, cv2.COLOR_BGR2RGB))
            return result
        except Exception as e:
            print(f"Warning: Image preprocessing failed: {e}")
            return None

    @staticmethod
    def extract_text_from_image(image_path: Path) -> str:
        if not HAS_OCR:
            raise ImportError(
                "OCR libraries not installed. "
                "Install with: pip install pytesseract opencv-python pillow"
            )
        processed_img = ImageProcessor.preprocess_image(image_path)
        if processed_img:
            img_to_ocr = processed_img
        else:
            img_to_ocr = Image.open(image_path)
        try:
            custom_config = r"--oem 3 --psm 6 -c tessedit_char_whitelist=./\abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-\|"
            text = pytesseract.image_to_string(img_to_ocr, config=custom_config)
            return text
        except Exception as e:
            raise RuntimeError(f"OCR failed: {e}")


def read_input(source: str) -> str:
    path = Path(source)
    if source == "-":
        return sys.stdin.read()
    if not path.exists():
        raise FileNotFoundError(f"Input not found: {source}")
    if ImageProcessor.is_image_file(path):
        if not HAS_OCR:
            raise ImportError(
                "Image input requires OCR libraries. "
                "Install with: pip install pytesseract opencv-python pillow numpy"
            )
        text = ImageProcessor.extract_text_from_image(path)
        return text
    return path.read_text(encoding="utf-8", errors="replace")


def create_tree(
    entries: list[dict[str, Any]],
    base_path: Path,
    dry_run: bool = False,
    verbose: bool = False,
) -> tuple[int, int]:
    created_dirs = 0
    created_files = 0
    sorted_entries = sorted(entries, key=lambda x: (x["depth"], str(x["path"])))
    for entry in sorted_entries:
        name = entry["name"]
        path = entry["path"]
        is_dir = entry["is_dir"]
        if name == ".":
            continue
        try:
            relative_path = path.relative_to(base_path)
        except ValueError:
            relative_path = path
        if dry_run:
            item_type = "dir" if is_dir else "file"
            print(f"  [{item_type.upper()}] {relative_path}")
            if is_dir:
                created_dirs += 1
            else:
                created_files += 1
            continue
        parent = path.parent
        if not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
            if verbose:
                print(f"  Created parent dir: {parent.relative_to(base_path)}/")
        if is_dir:
            if not path.exists():
                path.mkdir(exist_ok=True)
                created_dirs += 1
                if verbose:
                    print(f"  Created dir:  {relative_path}/")
            else:
                if verbose:
                    print(f"  Exists dir:  {relative_path}/")
        else:
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
                created_files += 1
                if verbose:
                    print(f"  Created file: {relative_path}")
            else:
                if verbose:
                    print(f"  Exists file: {relative_path}")
    return created_dirs, created_files


def validate_entries(entries: list[dict[str, Any]]) -> bool:
    if not entries:
        print("Warning: No valid entries found in input.")
        return False
    has_root = any(e["name"] == "." for e in entries)
    for entry in entries:
        if "path" not in entry:
            print(f"Warning: Entry missing path: {entry}")
            return False
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Create folder tree from text file or image",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python create_tree.py tree.txt
  python create_tree.py folder_tree.png
  python create_tree.py tree.txt --output ./my_project
  python create_tree.py tree.txt --dry-run
  python create_tree.py tree.txt -v
        """,
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help='Input file (text or image) or "-" for stdin',
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=".",
        help="Output directory (default: current directory)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show detailed output"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without creating",
    )
    parser.add_argument(
        "--force", action="store_true", help="Overwrite existing files/directories"
    )
    parser.add_argument(
        "--format",
        choices=["auto", "tree", "simple", "indented"],
        default="auto",
        help="Force a specific input format (default: auto-detect)",
    )
    args = parser.parse_args()
    try:
        text = read_input(args.input)
    except Exception as e:
        print(f"Error reading input: {e}", file=sys.stderr)
        sys.exit(1)
    if args.verbose:
        print(f"Input: {args.input}")
        print(f"Output: {args.output}")
        print(f"Format: {args.format}")
        print(f"Text length: {len(text)} characters")
        print()
    base_path = Path(args.output).resolve()
    parser = TreeParser(base_path)
    entries = parser.parse(text)
    if not validate_entries(entries):
        print("No valid tree structure found in input.")
        sys.exit(1)
    if args.verbose:
        print(f"Parsed {len(entries)} entries:")
        for entry in entries:
            if entry["name"] != ".":
                item_type = "DIR" if entry["is_dir"] else "FILE"
                print(f"  [{item_type}] depth={entry['depth']} {entry['name']}")
        print()
    created_dirs, created_files = create_tree(
        entries, base_path, dry_run=args.dry_run, verbose=args.verbose
    )
    if args.dry_run:
        print(
            f"\n[DRY RUN] Would create {created_dirs} directories and {created_files} files"
        )
    else:
        print(
            f"\nCreated {created_dirs} directories and {created_files} files in: {base_path}"
        )


if __name__ == "__main__":
    try:
        import numpy as np
    except ImportError:
        np = None
    main()
