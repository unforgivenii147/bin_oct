#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import os
import re
import urllib
from pathlib import Path

import lxml.html
import pypdf


class Section:
    def __init__(self, title: str, source_file: str, depth: int, index: int) -> None:
        self.title = title
        self.source_file = source_file
        self.depth = depth
        self.index = index
        self.parent = None
        self.children = []
        self.outline_item = None

    def set_parent(self, parent: Section) -> None:
        self.parent = parent

    def add_children(self, child: Section) -> None:
        self.children.append(child)

    def path_to_root(self):
        path = []
        node = self
        while not node.is_root():
            path.append(str(node.index + 1))
            node = node.parent
        return path[::-1]

    def is_root(self):
        return self.parent is None

    def __str__(self) -> str:
        path = self.path_to_root()
        return "{}. {}".format(".".join(path), self.title)


def check_title(prefix_path: str, node: Section, overwrite: bool) -> bool:
    all_matched = True
    for child in node.children:
        child_result = check_title(prefix_path, child, overwrite)
        if not child_result:
            return False
    if node.is_root():
        return True
    source_file = os.path.join(prefix_path, node.source_file)
    if not Path(source_file).exists():
        print(f"File {source_file} does not exist")
        return False
    with Path(source_file).open(encoding="utf-8") as f:
        lines = f.readlines()
    for idx, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:]
            if not title.startswith(node.title):
                all_matched = False
                print(
                    f"[ERROR] Title not matched: source_file:{source_file}, line num:{
                        idx
                    }, title:{title}, title in `SUMMARY.md`:{node.title}"
                )
                break
    if not all_matched and overwrite:
        lines.insert(0, f"# {node.title}\n")
        print(f"[Info] Overwrite title as {node.title} in {node.source_file}")
        with Path(source_file).open("w", encoding="utf-8") as f:
            f.writelines(lines)
        all_matched = True
    return all_matched


def get_dom_id(node: Section) -> str:
    source_path = node.source_file
    source_path = source_path.removeprefix("./")
    source_path = source_path.split(".")[0]
    result = source_path
    result = result.lower()
    result = result.replace("/", "-")
    return result.replace(" ", "-")


def add_outline(
    html_root, reader: pypdf.PdfReader, writer: pypdf.PdfWriter, node: Section
) -> None:
    if not node.is_root():
        id = get_dom_id(node)
        try:
            results = html_root.get_element_by_id(id)
        except KeyError:
            print(f"[ERROR] Element not found: [{id}]")
            return
        if results is None:
            print(f"[ERROR] Element is None, id: [{id}]")
            return
        dest = reader.named_destinations[f"/{urllib.parse.quote(id)}"]
        page = None
        fit = None
        if dest.get("/Type") != "/Fit":
            page = reader.get_destination_page_number(dest)
            fit = pypdf.generic.Fit(
                dest.get("/Type"),
                (dest.get("/Left"), dest.get("/Top"), dest.get("/Zoom")),
            )
        node.outline_item = writer.add_outline_item(
            str(node), page, node.parent.outline_item, fit=fit
        )
    for child in node.children:
        add_outline(html_root, reader, writer, child)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mdbook_pdf_summary", description="Add outline to the PDF file."
    )
    parser.add_argument(
        "--html_path",
        type=str,
        help="path of the `print.html` generated `mdbook-pdf`",
        default="print.html",
    )
    parser.add_argument(
        "--pdf_path",
        type=str,
        help="path of the `output.pdf` generated `mdbook-pdf`",
        default="output.pdf",
    )
    parser.add_argument(
        "--summary_path",
        type=str,
        help="path of the `SUMMARY.md`",
        default="src/SUMMARY.md",
    )
    parser.add_argument(
        "--output_path",
        type=str,
        help="path of the output PDF file",
        default="output_with_outline.pdf",
    )
    args = parser.parse_args()
    print("============ args =============")
    print("args.html_path: ", args.html_path)
    print("args.pdf_path: ", args.pdf_path)
    print("args.summary_path: ", args.summary_path)
    print("args.output_path: ", args.output_path)
    if not Path(args.html_path).exists():
        raise FileNotFoundError(msg)
    if not Path(args.pdf_path).exists():
        raise FileNotFoundError(msg)
    if not Path(args.summary_path).exists():
        raise FileNotFoundError(msg)
    reader = pypdf.PdfReader(args.pdf_path)
    writer = pypdf.PdfWriter()
    writer.append(reader)
    md_text = Path(args.summary_path).read_text(encoding="utf-8")
    section_root = parse_section_tree(md_text)
    html_root = None
    with Path(args.html_path).open(encoding="utf8") as f:
        data = f.read()
        html_root = lxml.html.fromstring(data)
    if html_root is None:
        raise "[ERROR] html_root is None"
    add_outline(html_root, reader, writer, section_root)
    with Path(args.output_path).open("wb") as f:
        writer.write(f)
        print(f"[INFO] Write to {args.output_path}")


def print_section_tree(root: Section) -> None:
    print(root)
    for child in root.children:
        print_section_tree(child)


def parse_section_tree(md_text: str) -> Section:
    root = Section("root", "", 0, 0)
    bfs_map = {(0): [root]}
    pattern = re.compile(r"( *)- ([^:\n]+)(?:: ([^\n]*))?\n?")
    tmp = None
    min_indent_num = 4
    for indent, name, _value in pattern.findall(md_text):
        title = name.split("](")[0].split("[")[1]
        source_file = name.split("](")[1].split(")")[0]
        indent_num = len(indent)
        if indent_num > 0 and indent_num < min_indent_num:
            min_indent_num = indent_num
        depth = indent_num // min_indent_num
        if depth + 1 not in bfs_map:
            bfs_map[depth + 1] = []
        tmp = Section(title, source_file, depth + 1, 0)
        bfs_map[depth + 1].append(tmp)
        parent = bfs_map[depth][-1]
        tmp.set_parent(parent)
        tmp.index = len(parent.children)
        parent.add_children(tmp)
    return root


if __name__ == "__main__":
    raise SystemExit(main())
