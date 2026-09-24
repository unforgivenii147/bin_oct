#!/data/data/com.termux/files/home/.local/bin/python
import sys, string


def varnames():
    letters = string.ascii_letters  # a-zA-Z, 52 names
    for c in letters:
        yield c
    for c in letters:
        yield c + "z"
    for c in letters:
        for d in letters:
            yield c + d + "z"


def obfuscate(src: str) -> str:
    names = varnames()
    out = []
    eval_parts = []

    # split source into small chunks (e.g. 3 chars each)
    CHUNK = 3
    for i in range(0, len(src), CHUNK):
        piece = src[i : i + CHUNK]
        name = next(names)
        # single-quote the chunk, escape single quotes inside
        escaped = piece.replace("'", "'\\''")
        out.append(f"{name}='{escaped}';")
        eval_parts.append(f"${name}")

    out.append('eval "' + "".join(eval_parts) + '"')
    return "\n".join(out)


if __name__ == "__main__":
    src = open(sys.argv[1]).read()
    print(obfuscate(src))
