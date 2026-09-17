#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

import markdown
from bs4 import BeautifulSoup


def modify_classes(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")
    tag_class_map = {
        "h1": "text-4xl font-bold mt-4 mb-2",
        "h2": "text-4xl font-semibold mt-4 mb-2",
        "h3": "text-2xl font-medium mt-4 mb-2",
        "h4": "text-xl font-medium mt-4 mb-2",
        "p": "text-base leading-relaxed mt-2 mb-4",
        "code": "bg-gray-100 p-1 rounded-md",
        "pre": "bg-gray-900 text-white p-4 rounded-md overflow-x-auto",
    }
    for tag, tailwind_classes in tag_class_map.items():
        for element in soup.find_all(tag):
            existing_classes = element.get("class", [])
            new_classes = tailwind_classes.split()
            combined_classes = list(set(existing_classes + new_classes))
            element["class"] = combined_classes
    return str(soup)


def convert_latex_format(text: str) -> str:
    text = re.sub(
        r"\\\[(.*?)\\\]", '<div class="latex-displayr">\1</div>', text, flags=re.DOTALL
    )
    return re.sub(
        r"\\\((.*?)\\\)", '<span class="latex-inliner">\1</span>', text, flags=re.DOTALL
    )


def read_markdown_file(path: str) -> str:
    with Path(path).open(encoding="utf-8", errors="ignore") as f:
        return f.read()


def convert_markdown(md_path: str) -> str:
    if not md_path:
        raise ValueError(msg)
    markdown_text = read_markdown_file(md_path)
    markdown_text = convert_latex_format(markdown_text)
    base_name = Path(md_path).name.replace(".md", "")
    temp_html_path = os.path.join("/sdcard/tmp", f"{base_name}.html")
    final_output_path = md_path.replace(".md", ".html")
    html_content = markdown.markdown(
        markdown_text,
        ext=["md_in_html", "fenced_code", "codehilite", "toc", "attr_list", "tables"],
    )
    html_content = modify_classes(html_content)
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en" class="scroll-smooth bg-gray-50 text-gray-900 antialiased">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{base_name}</title>
            <link rel="stylesheet" href="/sdcard/_static/katex/tailwind.min.css">
            <link rel="stylesheet" href="/sdcard/_static/katex/custom.css">
            <link rel="stylesheet" href="/sdcard/_static/katex/katex.min.css">
            <script src="/sdcard/_static/katex/tex.js"></script>
            <script src="/sdcard/_static/katex/auto-render.min.js"></script>
            <script src="/sdcard/_static/katex/katex.min.js"></script>
        </head>
        <body for="html-export" class="min-h-screen flex flex-col justify-between">
            <main class="flex-1">
                <div class="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8 prose prose-lg prose-slate">
                    {html_content}
                </div>
            </main>
        </body>
    </html>
    """
    Path(temp_html_path).write_text(html_template, encoding="utf-8")
    shutil.copy(temp_html_path, final_output_path)
    return final_output_path


if __name__ == "__main__":
    md_path = sys.argv[1]
    output_path = convert_markdown(md_path)
    print(f"Output saved in {output_path}")
