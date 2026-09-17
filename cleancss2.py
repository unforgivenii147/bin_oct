#!/data/data/com.termux/files/home/.local/bin/python
import multiprocessing as mp
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import tree_sitter_css
from tree_sitter import Language, Node, Parser

PathLike = str | Path


@dataclass
class ProcessResult:
    path: Path
    success: bool
    comments_removed: int = 0
    error_message: str = ""
    processing_time: float = 0.0
    file_size: int = 0


class CSSCommentRemover:
    def __init__(self):
        self.parser = Parser()
        language = Language(tree_sitter_css.language())
        self.parser.language = language

    def _is_comment_node(self, node: Node) -> bool:
        return node.type == "comment"

    def _get_comment_ranges(self, root_node: Node) -> list[tuple[int, int]]:
        comment_ranges = []

        def visit_node(node: Node):
            if self._is_comment_node(node):
                comment_ranges.append((node.start_byte, node.end_byte))
                return
            for child in node.children:
                visit_node(child)

        visit_node(root_node)
        comment_ranges.sort(key=lambda x: x[0])
        if comment_ranges:
            merged_ranges = [comment_ranges[0]]
            for start, end in comment_ranges[1:]:
                last_start, last_end = merged_ranges[-1]
                if start <= last_end:
                    merged_ranges[-1] = (last_start, max(last_end, end))
                else:
                    merged_ranges.append((start, end))
            comment_ranges = merged_ranges
        return comment_ranges

    def _cleanup_empty_lines(self, content: bytes) -> bytes:
        while b"\n\n\n" in content:
            content = content.replace(b"\n\n\n", b"\n\n")
        content = content.strip(b"\n") + b"\n" if content else b""
        return content

    def remove_comments(self, content: bytes) -> tuple[bytes, int]:
        tree = self.parser.parse(content)
        comment_ranges = self._get_comment_ranges(tree.root_node)
        if not comment_ranges:
            return content, 0
        result_parts = []
        last_end = 0
        comments_removed = 0
        for start, end in comment_ranges:
            before_comment = content[last_end:start]
            line_start = content.rfind(b"\n", 0, start) + 1
            prefix_on_line = content[line_start:start]
            if prefix_on_line.strip() == b"":
                line_end = content.find(b"\n", end)
                if line_end == -1:
                    line_end = len(content)
                else:
                    line_end += 1
                suffix_on_line = content[end:line_end].strip()
                if suffix_on_line == b"":
                    result_parts.append(before_comment[: len(prefix_on_line)])
                    last_end = line_end
                else:
                    result_parts.append(before_comment)
                    last_end = end
            else:
                result_parts.append(before_comment)
                last_end = end
            comments_removed += 1
        result_parts.append(content[last_end:])
        processed_content = b"".join(result_parts)
        processed_content = self._cleanup_empty_lines(processed_content)
        return processed_content, comments_removed


def collect_css_files(inputs: list[str]) -> list[Path]:
    css_files = []
    if not inputs:
        inputs = ["."]
    for input_path in inputs:
        path = Path(input_path)
        if path.is_file():
            if path.suffix.lower() == ".css":
                css_files.append(path)
            else:
                print(f"Warning: {path} is not a .css file, skipping")
        elif path.is_dir():
            css_files.extend(path.rglob("*.css"))
            css_files.extend(path.rglob("*.CSS"))
        else:
            print(f"Warning: {path} does not exist, skipping")
    seen = set()
    unique_files = []
    for f in css_files:
        resolved = f.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_files.append(resolved)
    return unique_files


def process_file(path: Path) -> ProcessResult:
    start_time = time.perf_counter()
    try:
        remover = CSSCommentRemover()
        with open(path, "rb") as f:
            content = f.read()
        file_size = len(content)
        if file_size == 0:
            return ProcessResult(
                path=path,
                success=True,
                comments_removed=0,
                processing_time=time.perf_counter() - start_time,
                file_size=0,
            )
        processed_content, comments_removed = remover.remove_comments(content)
        if comments_removed > 0 and processed_content != content:
            temp_path = path.with_suffix(path.suffix + ".tmp")
            try:
                with open(temp_path, "wb") as f:
                    f.write(processed_content)
                    f.flush()
                    os.fsync(f.fileno())
                original_mode = os.stat(path).st_mode
                os.chmod(temp_path, original_mode)
                size = os.stat(temp_path).st_size
                if size:
                    temp_path.replace(path)
                else:
                    print("result css is empty,skiping write")
            except Exception:
                if temp_path.exists():
                    temp_path.unlink()
                raise
        processing_time = time.perf_counter() - start_time
        return ProcessResult(
            path=path,
            success=True,
            comments_removed=comments_removed,
            processing_time=processing_time,
            file_size=file_size,
        )
    except Exception as e:
        processing_time = time.perf_counter() - start_time
        return ProcessResult(
            path=path,
            success=False,
            error_message=str(e),
            processing_time=processing_time,
        )


def process_files_parallel(
    files: list[Path], num_workers: int = 8
) -> list[ProcessResult]:
    results = []
    total_files = len(files)
    completed = 0
    with mp.Pool(processes=num_workers) as pool:
        async_results = []
        for path in files:
            async_result = pool.apply_async(process_file, (path,))
            async_results.append(async_result)
        for async_result in async_results:
            try:
                result = async_result.get(timeout=30)
                results.append(result)
                completed += 1
                if result.success:
                    if result.comments_removed > 0:
                        size_kb = result.file_size / 1024 if result.file_size else 0
                        print(
                            f"✓ {result.path}: removed {result.comments_removed} comments "
                            f"({size_kb:.1f} KB, {result.processing_time:.3f}s)"
                        )
                    else:
                        print(
                            f"• {result.path}: no comments found "
                            f"({result.processing_time:.3f}s)"
                        )
                else:
                    print(f"✗ {result.path}: ERROR - {result.error_message}")
                if completed % 25 == 0 and completed < total_files:
                    print(f"Progress: {completed}/{total_files} files processed")
            except mp.TimeoutError:
                print(f"✗ Timeout processing file (30s limit)")
                results.append(
                    ProcessResult(
                        path=Path("unknown"),
                        success=False,
                        error_message="Timeout exceeded 30 seconds",
                    )
                )
                completed += 1
    return results


def print_summary(results: list[ProcessResult], total_files: int, start_time: float):
    total_time = time.perf_counter() - start_time
    successful = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)
    total_comments_removed = sum(r.comments_removed for r in results if r.success)
    files_with_comments = sum(
        1 for r in results if r.success and r.comments_removed > 0
    )
    total_size_processed = sum(
        r.file_size for r in results if r.success and r.file_size
    )
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total files processed:     {total_files}")
    print(f"Successful:                {successful}")
    print(f"Failed:                    {failed}")
    print(f"Files with comments:       {files_with_comments}")
    print(f"Files without comments:    {successful - files_with_comments}")
    print(f"Total comments removed:    {total_comments_removed}")
    if total_size_processed > 0:
        size_mb = total_size_processed / (1024 * 1024)
        print(f"Total size processed:      {size_mb:.2f} MB")
    print(f"Total processing time:     {total_time:.2f}s")
    if successful > 0:
        avg_time = total_time / successful
        print(f"Average time per file:     {avg_time:.3f}s")
    if failed > 0:
        print(f"\nFailed files:")
        for r in results:
            if not r.success:
                print(f"  - {r.path}: {r.error_message}")
    print("=" * 70)


def main():
    inputs = sys.argv[1:]
    print("CSS Comment Remover")
    print("=" * 40)
    print("Collecting .css files...")
    css_files = collect_css_files(inputs)
    if not css_files:
        print("No .css files found to process.")
        return
    print(f"Found {len(css_files)} .css file(s) to process")
    print(f"Using 8 worker processes\n")
    start_time = time.perf_counter()
    results = process_files_parallel(css_files, num_workers=8)
    print_summary(results, len(css_files), start_time)


if __name__ == "__main__":
    mp.freeze_support()
    main()
