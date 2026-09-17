#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import json
import multiprocessing
from pathlib import Path

from dh import unique_path


def load_json_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            else:
                return [data]
    except json.JSONDecodeError:
        return []
    except Exception:
        return []


def merge_json_files(input_paths):
    json_files = []
    for path_str in input_paths:
        path = Path(path_str)
        if path.is_file() and path.suffix == ".json":
            json_files.append(path)
        elif path.is_dir():
            for file in path.rglob("*.json"):
                json_files.append(file)
        else:
            print("no json file")
    if not json_files:
        return []
    with multiprocessing.Pool(8) as pool:
        list_of_data_lists = pool.map(load_json_file, json_files)
    merged_data = []
    for data_list in list_of_data_lists:
        merged_data.extend(data_list)
    return merged_data


def main():
    parser = argparse.ArgumentParser(description="Объединение JSON-файлов.")
    parser.add_argument(
        "input_paths",
        nargs="*",
        help="Пути к файлам или директориям для обработки. Если не указаны, обрабатывается текущая директория.",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="merged.json",
        help="output file name",
    )
    args = parser.parse_args()
    if not args.input_paths:
        input_paths = ["."]
    else:
        input_paths = args.input_paths
    merged_result = merge_json_files(input_paths)
    if merged_result:
        out_path = Path(args.output)
        if out_path.exists():
            out_path = unique_path(out_path)
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(merged_result, f, ensure_ascii=False, indent=4)
        except Exception:
            print("error")
    else:
        print("There is no data to write to the output file.")


if __name__ == "__main__":
    raise SystemExit(main())
