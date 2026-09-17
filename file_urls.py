#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

from dh import BIN_EXT, TXT_EXT

EXCLUDED = {
    ".net",
    ".ai",
    ".org",
    ".com",
    ".me",
    ".svg",
    ".webp",
    ".png",
    ".jpg",
    ".jpeg",
    ".ico",
    ".cgi",
    ".xsl",
    ".bmp",
    ".gif",
}
ALL_EXT = set(list(TXT_EXT) + list(BIN_EXT))
ALL_EXT = [p for p in ALL_EXT if p not in EXCLUDED]


def extract_urls_to_file(output_filename: str = "file_urls.txt") -> None:
    extracted_urls = set()
    html_urls = []
    pdf_urls = []
    targz_urls = []
    whl_urls = []
    font_urls = []
    js_css_urls = []
    with open("urls.txt", encoding="utf-8", errors="ignore") as f:
        for line in f:
            stripped = line.strip()
            if any(stripped.endswith(p) for p in ALL_EXT):
                if stripped.endswith((".html", ".htm")):
                    html_urls.append(stripped)
                    continue
                if stripped.endswith(".pdf"):
                    pdf_urls.append(stripped)
                    continue
                if stripped.endswith(".whl"):
                    whl_urls.append(stripped)
                    continue
                if stripped.endswith((".tar.gz", ".tar.xz", ".tgz", ".txz")):
                    targz_urls.append(stripped)
                    continue
                if stripped.endswith(
                    (".ttf", ".woff", ".woff2", ".eot", ".otf", ".ttc")
                ):
                    font_urls.append(stripped)
                    continue
                if stripped.endswith((".js", ".css")):
                    js_css_urls.append(stripped)
                    continue
                if stripped not in extracted_urls:
                    extracted_urls.add(stripped)
    pdf_file = Path("pdf_urls.txt")
    html_file = Path("html_urls.txt")
    whl_file = Path("whl_urls.txt")
    font_file = Path("font_urls.txt")
    targz_file = Path("targz_urls.txt")
    js_css_file = Path("js_css_urls.txt")
    if pdf_urls:
        pdf_content = "\n".join(pdf_urls)
        pdf_file.write_text(pdf_content, encoding="utf8")
    if html_urls:
        html_content = "\n".join(html_urls)
        html_file.write_text(html_content, encoding="utf8")
    if whl_urls:
        whl_content = "\n".join(whl_urls)
        whl_file.write_text(whl_content, encoding="utf8")
    if font_urls:
        font_content = "\n".join(font_urls)
        font_file.write_text(font_content, encoding="utf8")
    if targz_urls:
        targz_content = "\n".join(targz_urls)
        targz_file.write_text(targz_content, encoding="utf8")
    if js_css_urls:
        js_css_content = "\n".join(js_css_urls)
        js_css_file.write_text(js_css_content, encoding="utf8")
    if extracted_urls:
        with open(output_filename, "w", encoding="utf-8") as outfile:
            outfile.writelines(url + "\n" for url in sorted(extracted_urls))
        print(f"\nSuccessfully extracted {len(extracted_urls)} unique URLs")
    else:
        print("\nNo URLs with specified file extensions found.")


if __name__ == "__main__":
    extract_urls_to_file()
