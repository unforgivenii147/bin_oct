#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

matplotlib.use("Agg")
if len(sys.argv) < 2:
    print("Usage: python script.py 'f(x)=expression'")
    print("Examples:")
    print("  python script.py 'f(x)=arctan(x)'")
    print("  python script.py 'f(x)=sin(x)'")
    print("  python script.py 'f(x)=(x+1)/(x-1)'")
    sys.exit(1)
input_str = sys.argv[1]
if "=" not in input_str:
    print("Error: Input must be in format 'f(x)=expression'")
    sys.exit(1)
function_expr = input_str.split("=", 1)[1].strip()
print(f"Plotting: {input_str}")


def f(x):
    return eval(
        function_expr,
        {"__builtins__": {}},
        {
            "x": x,
            "np": np,
            "sin": np.sin,
            "cos": np.cos,
            "tan": np.tan,
            "arctan": np.arctan,
            "arcsin": np.arcsin,
            "arccos": np.arccos,
            "sqrt": np.sqrt,
            "exp": np.exp,
            "log": np.log,
            "pi": np.pi,
            "e": np.e,
        },
    )


x = np.linspace(-10, 10, 1000)
try:
    y = f(x)
except Exception as e:
    print(f"Error evaluating function: {e}")
    sys.exit(1)
mask = np.isfinite(y)
x_clean = x[mask]
y_clean = y[mask]
y_min, y_max = np.percentile(y_clean, [1, 99]) if len(y_clean) > 0 else (-10, 10)
y_range = y_max - y_min if y_max != y_min else 10
y_min -= y_range * 0.1
y_max += y_range * 0.1
plt.figure(figsize=(10, 6))
plt.plot(x_clean, y_clean, "b-", linewidth=2, label=function_expr)
plt.axhline(y=0, color="black", linewidth=0.5)
plt.axvline(x=0, color="black", linewidth=0.5)
plt.xlabel("x")
plt.ylabel("f(x)")
plt.title(f"f(x) = {function_expr}")
plt.grid(True, alpha=0.3)
plt.legend()
plt.xlim(-10, 10)
plt.ylim(y_min, y_max)
plt.savefig("plot.png", dpi=300, bbox_inches="tight")
print("✅ Plot saved as 'plot.png'")
