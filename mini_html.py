#!/data/data/com.termux/files/home/.local/bin/python
import sys

import minify_html as mh


def main():
    fn = sys.argv[1]
    data = ""
    with open(fn, encoding="utf-8") as f:
        data = f.read()
    minified = mh.minify(data)
    if minified != data:
        print(minified)
        with open(fn, "w") as fo:
            fo.write(minified)
    print("done")


if __name__ == "__main__":
    main()
