#!/data/data/com.termux/files/home/.local/bin/python
from pathlib import Path

if __name__ == "__main__":
    cwd = Path.cwd()
    for path in cwd.rglob("*.whl"):
        fname = path.name
        target_dir = Path("/sdcard/whl")
        target_path = target_dir / fname
        if target_path.exists():
            target_path.unlink()
        data = path.read_bytes()
        target_path.write_bytes(data)
        path.unlink()
        print(f"{path.name} -> {target_path.name}")
    print("done")
