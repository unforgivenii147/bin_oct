#!/data/data/com.termux/files/home/.local/bin/python
from bs4 import BeautifulSoup
from dh import get_files, mpf
import syd


def process_file(path) -> bool:
    try:
        with open(path, encoding="utf-8") as file:
            content = file.read()

        soup = BeautifulSoup(content, "html.parser")
        beautified_content = soup.prettify()
        if content != beautified_content:
            with open(path, "w", encoding="utf-8") as file:
                file.write(beautified_content)
    except Exception as e:
        print(f"Error beautifying HTML file {path}: {e}")
        return False
    return True


if __name__ == "__main__":
    args = sys.argv[1:]
    cwd = Path.cwd()
    files = [Path(p) for p in args] if args else get_files(cwd, ext == [".html"])
    mpf(process_file, files)
