#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import TextIO

try:
    import yaml
except ImportError:
    print(
        "Error: PyYAML is required. Install with: pip install PyYAML", file=sys.stderr
    )
    sys.exit(1)


@dataclass
class ConversionArgs:
    input: TextIO
    output: TextIO
    indent: int | None
    compact: bool
    sort_keys: bool
    ensure_ascii: bool
    strict: bool
    allow_unicode: bool

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> ConversionArgs:
        return cls(
            input=ns.input,
            output=ns.output,
            indent=ns.indent,
            compact=ns.compact,
            sort_keys=ns.sort_keys,
            ensure_ascii=ns.ensure_ascii,
            strict=ns.strict,
            allow_unicode=ns.allow_unicode,
        )


def convert_yaml_to_json(
    yaml_input: str | TextIO,
    indent: int | None = None,
    compact: bool = False,
    sort_keys: bool = False,
    ensure_ascii: bool = True,
    strict: bool = False,
    allow_unicode: bool = False,
) -> str:
    try:
        if strict:
            loader = yaml.SafeLoader
            data = yaml.load(yaml_input, Loader=loader)
        else:
            data = yaml.safe_load(yaml_input)
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"YAML parsing error: {e}") from e
    try:
        json.dumps(data, ensure_ascii=ensure_ascii, allow_nan=False)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Data cannot be serialized to JSON: {e}") from e
    separators = (",", ":") if compact else None
    json_indent = None if compact else indent
    try:
        return json.dumps(
            data,
            indent=json_indent,
            separators=separators,
            sort_keys=sort_keys,
            ensure_ascii=ensure_ascii,
            allow_nan=False,
        )
    except (TypeError, ValueError) as e:
        raise ValueError(f"JSON serialization error: {e}") from e


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert YAML to JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s config.yaml
  %(prog)s config.yaml -o config.json
  cat config.yaml | %(prog)s
  %(prog)s config.yaml --indent 4
  %(prog)s config.yaml --compact
  %(prog)s config.yaml --sort-keys
  %(prog)s config.yaml --no-ensure-ascii
  %(prog)s config.yaml --strict
        """,
    )
    io_group = parser.add_argument_group("Input/Output")
    io_group.add_argument(
        "input",
        nargs="?",
        type=argparse.FileType("r", encoding="utf-8"),
        default=sys.stdin,
        help="Input YAML file (default: stdin)",
    )
    io_group.add_argument(
        "-o",
        "--output",
        type=argparse.FileType("w", encoding="utf-8"),
        default=sys.stdout,
        help="Output JSON file (default: stdout)",
    )
    format_group = parser.add_argument_group("Formatting")
    format_group.add_argument(
        "-i",
        "--indent",
        type=int,
        default=2,
        help="Indentation spaces for pretty printing (default: 2, use 0 for compact)",
    )
    format_group.add_argument(
        "-c",
        "--compact",
        action="store_true",
        help="Compact output (minified, overrides --indent)",
    )
    format_group.add_argument(
        "-s",
        "--sort-keys",
        action="store_true",
        help="Sort dictionary keys alphabetically",
    )
    encoding_group = parser.add_argument_group("Encoding")
    encoding_group.add_argument(
        "--no-ensure-ascii",
        dest="ensure_ascii",
        action="store_false",
        default=True,
        help="Allow non-ASCII characters in output (default: escape them)",
    )
    encoding_group.add_argument(
        "-u",
        "--allow-unicode",
        action="store_true",
        help="Keep unicode characters as-is (alias for --no-ensure-ascii)",
    )
    parsing_group = parser.add_argument_group("Parsing")
    parsing_group.add_argument(
        "--strict",
        action="store_true",
        help="Strict YAML parsing (disallow duplicate keys, etc.)",
    )
    parsing_group.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate YAML, don't output JSON",
    )
    args = parser.parse_args()
    if args.allow_unicode:
        args.ensure_ascii = False
    conv_args = ConversionArgs.from_namespace(args)
    try:
        if conv_args.input is sys.stdin and sys.stdin.isatty():
            print("Enter YAML content (Ctrl+D to finish):", file=sys.stderr)
        yaml_content = conv_args.input.read()
    except Exception as e:
        print(f"Error reading input: {e}", file=sys.stderr)
        return 1
    if not yaml_content.strip():
        print("Error: Empty YAML input", file=sys.stderr)
        return 1
    try:
        json_output = convert_yaml_to_json(
            yaml_content,
            indent=conv_args.indent,
            compact=conv_args.compact,
            sort_keys=conv_args.sort_keys,
            ensure_ascii=conv_args.ensure_ascii,
            strict=conv_args.strict,
            allow_unicode=conv_args.allow_unicode,
        )
    except yaml.YAMLError as e:
        print(f"YAML Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Conversion Error: {e}", file=sys.stderr)
        return 1
    if not args.validate_only:
        try:
            conv_args.output.write(json_output)
            if conv_args.output is sys.stdout:
                conv_args.output.write("\n")
            conv_args.output.flush()
        except Exception as e:
            print(f"Error writing output: {e}", file=sys.stderr)
            return 1
    else:
        print("✓ YAML is valid", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
