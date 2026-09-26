#!/data/data/com.termux/files/home/.local/bin/python
import argparse
import multiprocessing as mp
import pathlib
import warnings
import tokenize
import re
import io
import sys

# ANSI color codes
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"


def check_and_fix_file(args):
    filepath_str, fix = args
    filepath = pathlib.Path(filepath_str)

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source_text = f.read()
    except Exception as e:
        return (
            filepath_str,
            False,
            [f"{RED}Error reading {filepath_str}: {e}{RESET}"],
            None,
        )

    has_warning = False
    has_syntax_error = False

    # Fast path: check if the whole file emits the warning
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always", SyntaxWarning)
        try:
            compile(source_text, str(filepath), "exec")
        except SyntaxError:
            has_syntax_error = True  # File has other syntax errors, must manually tokenize to check strings
        except Exception:
            pass

        has_warning = any("invalid escape sequence" in str(warn.message) for warn in w)

    # If the file compiled cleanly and had no warnings, skip it entirely
    if not has_warning and not has_syntax_error:
        return filepath_str, False, [], None

    # Tokenize the file to find exact string literals
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source_text).readline))
    except tokenize.TokenError:
        # If tokenization crashes, we just process what we were able to parse
        pass

    issues = []
    replacements = []  # Store as (start_row, start_col, end_row, end_col, new_string)

    for tok in tokens:
        if tok.type == tokenize.STRING:
            # Check if this specific token triggers the warning
            with warnings.catch_warnings(record=True) as w2:
                warnings.simplefilter("always", SyntaxWarning)
                try:
                    compile(tok.string, "<string>", "eval")
                except Exception:
                    pass

                if any("invalid escape sequence" in str(warn.message) for warn in w2):
                    # Separate the prefix (e.g., f, b, u) from the quotes and content
                    m = re.match(r'^([a-zA-Z_]*)(["\'].*)$', tok.string, re.DOTALL)
                    if m:
                        prefix = m.group(1)
                        rest = m.group(2)

                        if "r" not in prefix.lower():
                            # Remove outdated 'u' prefix if present and convert to raw string 'r'
                            prefix = prefix.replace("u", "").replace("U", "")
                            new_string = prefix + "r" + rest

                            replacements.append(
                                (
                                    tok.start[0],
                                    tok.start[1],
                                    tok.end[0],
                                    tok.end[1],
                                    new_string,
                                )
                            )
                            issues.append((tok.start[0], tok.string, new_string))

    if not issues:
        return filepath_str, False, [], None

    lines = source_text.splitlines(keepends=True)
    output = []
    output.append(f"{CYAN}File: {filepath}{RESET}")

    # Display the lines with context
    issue_lines = sorted(list(set(line_num for line_num, _, _ in issues)))
    for lineno in issue_lines:
        idx = lineno - 1

        if idx - 1 >= 0:  # -1 line
            output.append(f"  {idx}: {lines[idx - 1].rstrip('\n')}")

        # Target line with issue in color
        output.append(f"{RED}> {idx + 1}: {lines[idx].rstrip('\n')}{RESET}")

        if idx + 1 < len(lines):  # +1 line
            output.append(f"  {idx + 2}: {lines[idx + 1].rstrip('\n')}")

        output.append("-" * 40)

    new_content = None
    if fix and replacements:
        # Sort replacements bottom-up (reverse order) so column indices remain valid after modification
        replacements.sort(key=lambda x: (x[0], x[1]), reverse=True)
        text_lines = source_text.splitlines(keepends=True)

        for r_start, c_start, r_end, c_end, new_string in replacements:
            r1 = r_start - 1
            r2 = r_end - 1

            if r1 == r2:  # Same line string
                line = text_lines[r1]
                text_lines[r1] = line[:c_start] + new_string + line[c_end:]
            else:  # Multi-line string
                first_line = text_lines[r1]
                last_line = text_lines[r2]
                text_lines[r1] = first_line[:c_start] + new_string + last_line[c_end:]
                # Delete the intermediate lines that were swallowed by the replacement
                for i in range(r2, r1, -1):
                    del text_lines[i]

        new_content = "".join(text_lines)

    return filepath_str, True, output, new_content


def main():
    parser = argparse.ArgumentParser(
        description="Recursively find and fix 'invalid escape sequence' SyntaxWarnings in Python code."
    )
    parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Update inplace in -a mode to fix issues (convert to raw regex)",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    args = parser.parse_args()

    base_path = pathlib.Path(args.path)

    if base_path.is_file():
        files = [base_path]
    else:
        # Ignore hidden folders like .git and virtual environments
        files = [
            f
            for f in base_path.rglob("*.py")
            if not any(part.startswith(".") for part in f.parts[:-1])
            and "venv" not in f.parts
            and "__pycache__" not in f.parts
        ]

    if not files:
        print("No Python files found.")
        sys.exit(0)

    tasks = [(str(f), args.apply) for f in files]

    with mp.Pool(8) as pool:
        # Use imap_unordered to process files as quickly as possible with 8 workers
        for filepath_str, has_issues, output_lines, new_content in pool.imap_unordered(
            check_and_fix_file, tasks
        ):
            if has_issues:
                for line in output_lines:
                    print(line)

                if args.apply and new_content is not None:
                    try:
                        with open(filepath_str, "w", encoding="utf-8") as f:
                            f.write(new_content)
                        print(f"{CYAN}Fixed inplace: {filepath_str}{RESET}\n")
                    except Exception as e:
                        print(f"{RED}Failed to write {filepath_str}: {e}{RESET}\n")


if __name__ == "__main__":
    main()
