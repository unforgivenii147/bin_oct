#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import html
import os
import re
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import chm.chm as pychm
from weasyprint import HTML


class CHMHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.content = []
        self.in_body = False
        self.skip_tags = {"script", "style", "meta", "link", "iframe"}
        self.current_skip_tag = None

    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            self.current_skip_tag = tag
        elif tag == "body":
            self.in_body = True
        elif not self.current_skip_tag and self.in_body:
            attrs_str = "".join(
                f' {k}="{v}"' for k, v in attrs if k != "href" and k != "src"
            )
            self.content.append(f"<{tag}{attrs_str}>")

    def handle_endtag(self, tag):
        if tag == self.current_skip_tag:
            self.current_skip_tag = None
        elif tag == "body":
            self.in_body = False
        elif not self.current_skip_tag and self.in_body:
            self.content.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.current_skip_tag and self.in_body:
            self.content.append(data)

    def handle_startendtag(self, tag, attrs):
        if tag not in self.skip_tags and self.in_body:
            attrs_str = "".join(
                f' {k}="{v}"' for k, v in attrs if k != "href" and k != "src"
            )
            self.content.append(f"<{tag}{attrs_str} />")

    def get_content(self):
        return "".join(self.content)


def extract_html_content(chm_file):
    try:
        chm = pychm.CHMFile()
        if not chm.LoadCHM(str(chm_file)):
            raise Exception(f"Failed to load CHM file: {chm_file}")
        toc = chm.GetTopicsTree()
        if not toc:
            default_topic = chm.GetDefaultTopic()
            if default_topic:
                return extract_single_topic(chm, default_topic)
            else:
                files = chm.GetAllFiles()
                html_files = [f for f in files if f.lower().endswith((".html", ".htm"))]
                if html_files:
                    return extract_multiple_topics(chm, html_files)
                else:
                    raise Exception("No HTML content found in CHM file")
        else:
            return extract_topics_from_toc(chm, toc)
    except Exception as e:
        raise Exception(f"Error extracting HTML from CHM: {e}")
    finally:
        if "chm" in locals():
            chm.CloseCHM()


def extract_single_topic(chm, topic_path):
    try:
        content = chm.RetrieveObject(chm.ResolveObject(topic_path))
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="ignore")
        return clean_html(content)
    except Exception as e:
        print(f"Warning: Could not extract topic {topic_path}: {e}")
        return ""


def extract_multiple_topics(chm, topics):
    combined_html = [
        (
            '<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
            "body { font-family: Arial, sans-serif; line-height: 1.6; margin: 2em; }"
            "img { max-width: 100%; }"
            "h1, h2, h3, h4 { color: #333; }"
            "pre { background-color: #f5f5f5; padding: 1em; border-radius: 4px; }"
            "code { background-color: #f5f5f5; padding: 0.2em 0.4em; border-radius: 3px; }"
            "</style></head><body>"
        )
    ]
    for topic in topics:
        try:
            content = chm.RetrieveObject(chm.ResolveObject(topic))
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="ignore")
            cleaned = clean_html(content)
            if cleaned:
                combined_html.append(cleaned)
                combined_html.append(
                    '<hr style="border: 1px solid #ccc; margin: 20px 0;">'
                )
        except Exception as e:
            print(f"Warning: Could not extract topic {topic}: {e}")
    combined_html.append("</body></html>")
    return "".join(combined_html)


def extract_topics_from_toc(chm, toc):
    html_parts = [
        (
            '<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
            "body { font-family: Arial, sans-serif; line-height: 1.6; margin: 2em; }"
            "img { max-width: 100%; }"
            "h1, h2, h3, h4 { color: #333; }"
            "pre { background-color: #f5f5f5; padding: 1em; border-radius: 4px; }"
            "code { background-color: #f5f5f5; padding: 0.2em 0.4em; border-radius: 3px; }"
            "</style></head><body>"
        )
    ]

    def process_toc_node(node, level=0):
        if hasattr(node, "GetTitle") and hasattr(node, "GetLocal"):
            title = node.GetTitle()
            local_path = node.GetLocal()
            if title and local_path:
                heading_level = min(level + 1, 6)
                html_parts.append(
                    f"<h{heading_level}>{html.escape(title)}</h{heading_level}>"
                )
                try:
                    content = chm.RetrieveObject(chm.ResolveObject(local_path))
                    if isinstance(content, bytes):
                        content = content.decode("utf-8", errors="ignore")
                    cleaned = clean_html(content)
                    if cleaned:
                        html_parts.append(cleaned)
                except Exception as e:
                    print(f"Warning: Could not extract topic {local_path}: {e}")
                html_parts.append(
                    '<hr style="border: 1px solid #ccc; margin: 20px 0;">'
                )
        if hasattr(node, "GetChildren"):
            for child in node.GetChildren():
                process_toc_node(child, level + 1)

    if isinstance(toc, list):
        for topic in toc:
            process_toc_node(topic)
    else:
        process_toc_node(toc)
    html_parts.append("</body></html>")
    return "".join(html_parts)


def clean_html(html_content):
    if not html_content:
        return ""
    html_content = re.sub(
        r"<script[^>]*>.*?</script>", "", html_content, flags=re.DOTALL | re.IGNORECASE
    )
    html_content = re.sub(
        r"<style[^>]*>.*?</style>", "", html_content, flags=re.DOTALL | re.IGNORECASE
    )
    parser = CHMHTMLParser()
    try:
        parser.feed(html_content)
        body_content = parser.get_content()
        body_content = re.sub(r"\n\s*\n", "\n\n", body_content)
        return body_content.strip()
    except Exception as e:
        print(f"Warning: HTML parsing failed: {e}")
        return html_content


def convert_chm_to_pdf(input_path, output_path):
    print(f"Converting {input_path} to {output_path}...")
    print("Extracting HTML content from CHM...")
    html_content = extract_html_content(input_path)
    if not html_content:
        raise Exception("No content extracted from CHM file")
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as temp_html:
        full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @page {{
        size: A4;
        margin: 2cm;
        @bottom-center {{
            content: counter(page);
            font-size: 10px;
            color:
        }}
    }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
        line-height: 1.6;
        font-size: 11pt;
        color:
        max-width: 100%;
    }}
    h1 {{
        font-size: 24pt;
        color:
        border-bottom: 2px solid
        padding-bottom: 10px;
        margin-top: 30px;
    }}
    h2 {{
        font-size: 20pt;
        color:
        border-bottom: 1px solid
        padding-bottom: 8px;
        margin-top: 25px;
    }}
    h3 {{
        font-size: 16pt;
        color:
        margin-top: 20px;
    }}
    h4 {{
        font-size: 14pt;
        color:
        margin-top: 15px;
    }}
    img {{
        max-width: 100%;
        height: auto;
        margin: 10px 0;
    }}
    pre {{
        background-color:
        border: 1px solid
        border-radius: 4px;
        padding: 15px;
        overflow-x: auto;
        font-family: 'Courier New', monospace;
        font-size: 9pt;
        line-height: 1.4;
    }}
    code {{
        background-color:
        padding: 2px 4px;
        border-radius: 3px;
        font-family: 'Courier New', monospace;
        font-size: 9pt;
    }}
    table {{
        border-collapse: collapse;
        width: 100%;
        margin: 15px 0;
    }}
    th, td {{
        border: 1px solid
        padding: 8px;
        text-align: left;
    }}
    th {{
        background-color:
        font-weight: bold;
    }}
    a {{
        color:
        text-decoration: none;
    }}
    blockquote {{
        border-left: 4px solid
        margin: 15px 0;
        padding: 10px 20px;
        background-color:
    }}
    hr {{
        border: none;
        border-top: 1px solid
        margin: 20px 0;
    }}
</style>
</head>
<body>
{html_content}
</body>
</html>"""
        temp_html.write(full_html)
        temp_html_path = temp_html.name
    try:
        print("Converting HTML to PDF using WeasyPrint...")
        HTML(filename=temp_html_path).write_pdf(output_path)
        print(f"PDF successfully created: {output_path}")
    finally:
        if os.path.exists(temp_html_path):
            os.unlink(temp_html_path)


def main():
    if len(sys.argv) != 2:
        print("Usage: python chm_to_pdf.py <input_file.chm>")
        print("Example: python chm_to_pdf.py documentation.chm")
        sys.exit(1)
    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Error: Input file '{input_path}' does not exist")
        sys.exit(1)
    if input_path.suffix.lower() != ".chm":
        print(f"Error: Input file '{input_path}' is not a CHM file")
        sys.exit(1)
    output_path = input_path.with_suffix(".pdf")
    try:
        convert_chm_to_pdf(input_path, output_path)
    except Exception as e:
        print(f"Error during conversion: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
