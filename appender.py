#!/data/data/com.termux/files/home/.local/bin/python
from pathlib import Path

# text = "\n# convert concurrent.futures to mp.pool.apply_async with fixed 8 workers\n# add type annotations to code\n# add module docstring if missing (short description about what this script does to first lines after shebang)"
# text ='\n#add required docstring to missing parts (function/class) of above code\n'
# text='\n# fix any possible errors (make (ty) typechecker happy)\n'
text = "\n#migrate from logging with print and standard logging module to loguru\n"

for py_file in Path.cwd().glob("*.py"):
    try:
        py_file.write_text(py_file.read_text(encoding="utf-8") + text, encoding="utf-8")
        print(f"✓ Updated: {py_file.name}")
    except Exception as e:
        print(f"✗ Error: {py_file.name} - {e}")
