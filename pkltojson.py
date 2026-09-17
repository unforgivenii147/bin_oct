#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path
from typing import Any


def is_json_serializable(obj: Any) -> bool:
    try:
        json.dumps(obj)
        return True
    except (TypeError, ValueError):
        return False


def serialize_for_json(obj: Any) -> Any:
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    elif isinstance(obj, (list, tuple)):
        return [serialize_for_json(item) for item in obj]
    elif isinstance(obj, dict):
        return {str(k): serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, set):
        return list(obj)
    elif hasattr(obj, "__dict__"):
        return str(obj)
    else:
        return str(obj)


def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <pickle_file>")
        sys.exit(1)
    pkl_path = Path(sys.argv[1])
    if not pkl_path.exists():
        print(f"Error: File not found: {pkl_path}")
        sys.exit(1)
    if pkl_path.suffix != ".pkl":
        print(f"Warning: Expected .pkl file, got {pkl_path.suffix}")
    try:
        with open(pkl_path, "rb") as f:
            data = pickle.load(f)
    except Exception as e:
        print(f"Error loading pickle: {e}")
        sys.exit(1)
    print(f"✓ Loaded: {pkl_path}")
    print(f"  Type: {type(data).__name__}")
    print(f"  Size: {len(str(data))} chars\n")
    print("Content:")
    print("-" * 40)
    if isinstance(data, dict):
        print(json.dumps(data, indent=2, default=str))
    else:
        print(json.dumps(data, indent=2, default=str))
    print("-" * 40)
    json_path = pkl_path.with_suffix(".json")
    if is_json_serializable(data):
        try:
            with open(json_path, "w") as f:
                json.dump(data, f, indent=2)
            print(f"\n✓ Saved to: {json_path}")
        except Exception as e:
            print(f"\n✗ Failed to save JSON: {e}")
    else:
        try:
            serialized = serialize_for_json(data)
            with open(json_path, "w") as f:
                json.dump(serialized, f, indent=2)
            print(f"\n⚠ Converted non-serializable objects → {json_path}")
        except Exception as e:
            print(f"\n✗ Cannot convert to JSON: {e}")


if __name__ == "__main__":
    main()
