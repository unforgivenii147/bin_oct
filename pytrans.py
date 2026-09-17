#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import io
import logging
import multiprocessing
import time
import tokenize
from pathlib import Path

import pycld2
from deep_translator import GoogleTranslator
from dh import DOC_TH1, DOC_TH2

SKIP_DIRS: frozenset = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)
TARGET_LANG: str = "en"
DELAY_SECONDS: float = 0.5
MAX_WORKERS: int = 8
SHEBANG_PREFIX: str = "#!/"
KNOWN_ENGLISH_TOKENS: frozenset = frozenset(
    {
        "TODO",
        "FIXME",
        "HACK",
        "XXX",
        "NOTE",
        "BUG",
        "pylint",
        "noqa",
        "type: ignore",
        "pragma",
        "coding:",
        "encoding:",
        "charset:",
    }
)
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def should_skip(text: str) -> bool:
    clean = text.strip()
    if not clean or clean.startswith(SHEBANG_PREFIX):
        return True
    if clean.isascii():
        if any(token in clean.upper() for token in KNOWN_ENGLISH_TOKENS):
            return True
        if len(clean.split()) <= 2 and len(clean) < 30:
            return True
    return bool(not any(c.isalpha() for c in clean))


def is_non_english(text: str) -> bool:
    clean = text.strip()
    if len(clean) < 4 or should_skip(clean):
        return False
    try:
        _, _, details = pycld2.detect(clean)
        lang_code = details[0][1]
        return lang_code not in ("en", "un")
    except Exception:
        return False


def translate_text(text: str) -> str:
    if not text.strip():
        return text
    try:
        result = GoogleTranslator(source="auto", target=TARGET_LANG).translate(text)
        time.sleep(DELAY_SECONDS)
        return result if result else text
    except Exception as exc:
        logger.warning("  [warn] translation failed: %s", exc)
        return text


def get_node_positions(
    tree: ast.AST,
) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    print_positions = set()
    docstring_positions = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and (node.func.id == "print")
        ):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    print_positions.add((arg.lineno, arg.col_offset))
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)
        ) and (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            ds = node.body[0].value
            docstring_positions.add((ds.lineno, ds.col_offset))
    return (print_positions, docstring_positions)


def process_file(path: Path) -> bool:
    try:
        source = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error("[error] Could not read %s: %s", path, e)
        return False
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
        tree = ast.parse(source)
    except (tokenize.TokenError, SyntaxError) as e:
        logger.warning("[skip] %s: Parse error - %s", path, e)
        return False
    lines = source.splitlines(keepends=True)

    def get_offset(lineno: int, col: int) -> int:
        return sum(len(lines[i]) for i in range(lineno - 1)) + col

    print_pos, doc_pos = get_node_positions(tree)
    replacements: list[tuple[int, int, str]] = []
    for tok in tokens:
        start_offset = get_offset(tok.start[0], tok.start[1])
        end_offset = get_offset(tok.end[0], tok.end[1])
        if tok.type == tokenize.COMMENT:
            inner = tok.string.lstrip("#").strip()
            if is_non_english(inner):
                translated = translate_text(inner)
                print("  [comment] %s -> %s", inner, translated)
                replacements.append((start_offset, end_offset, f"# {translated}"))
        elif tok.type == tokenize.STRING:
            is_print = (tok.start[0], tok.start[1]) in print_pos
            is_doc = (tok.start[0], tok.start[1]) in doc_pos
            if is_print or is_doc:
                raw = tok.string
                if raw.startswith((DOC_TH1, DOC_TH2)):
                    quote = raw[:3]
                elif raw.startswith('"'):
                    quote = '"'
                else:
                    quote = "'"
                try:
                    inner = ast.literal_eval(raw)
                except Exception:
                    continue
                if isinstance(inner, str) and is_non_english(inner):
                    translated = translate_text(inner)
                    label = "docstring" if is_doc else "print-str"
                    print("  [%s] %s -> %s", label, inner, translated)
                    escaped = translated.replace("\\", "\\\\").replace(
                        quote, f"\\{quote}"
                    )
                    replacements.append(
                        (start_offset, end_offset, f"{quote}{escaped}{quote}")
                    )
    if not replacements:
        return False
    replacements.sort(key=lambda x: x[0], reverse=True)
    src_list = list(source)
    for start, end, new_text in replacements:
        src_list[start:end] = list(new_text)
    new_source = "".join(src_list)
    try:
        ast.parse(new_source)
        path.write_text(new_source, encoding="utf-8")
        return True
    except SyntaxError as e:
        logger.error("[error] %s: Generated invalid syntax, skipping: %s", path, e)
        return False


def worker(path_str: str) -> None:
    path = Path(path_str)
    try:
        if process_file(path):
            print("[updated] %s", path)
    except Exception as e:
        logger.error("[failed] %s: %s", path, e)


def main() -> None:
    files = [
        str(p)
        for p in Path(".").rglob("*.py")
        if not any(part in SKIP_DIRS for part in p.parts)
    ]
    if not files:
        print("No Python files found.")
        return
    print("Found %d files. Processing with %d workers...", len(files), MAX_WORKERS)
    with multiprocessing.Pool(processes=MAX_WORKERS) as pool:
        pool.map(worker, files)
    print("Done.")


if __name__ == "__main__":
    raise SystemExit(main())
