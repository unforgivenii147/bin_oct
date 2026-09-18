#!/data/data/com.termux/files/home/.local/bin/python
"""
Create a new C++ file with a starter template and open it in an editor.
Usage: cppnew <filename.cpp>
"""

import subprocess
import sys
from pathlib import Path

TEMPLATE = """\
#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    // Your code here
    return 0;
}
"""


def cppnew(*args):
    if not args:
        print("Usage: cppnew <filename.cpp>")
        return 1

    file = Path(args[0]).expanduser()

    # Refuse to clobber an existing file (cat > would silently overwrite).
    if file.exists():
        print(f"Error: {file} already exists", file=sys.stderr)
        return 1

    file.write_text(TEMPLATE)
    print(f"Created {file} with basic C++ template")

    # Open in an editor. Prefer $EDITOR, else nano (Termux default).
    editor = (
        subprocess.run(
            ["sh", "-c", 'printf %s "$EDITOR"'], capture_output=True, text=True
        ).stdout.strip()
        or "nano"
    )
    try:
        return subprocess.run([editor, str(file)]).returncode
    except FileNotFoundError:
        print(f"Error: editor '{editor}' not found", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(cppnew(*sys.argv[1:]))
