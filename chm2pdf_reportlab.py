#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import html.parser
import re
import sys
from pathlib import Path

import chm
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer


class CHMToPDF:
    def __init__(self, chm_file, output_file):
        self.chm_file = chm_file
        self.output_file = output_file
        self.chm_obj = None
        self.content = []

    def open_chm(self):
        try:
            self.chm_obj = chm.CHMFile(str(self.chm_file))
            print(f"Successfully opened: {self.chm_file}")
            return True
        except Exception as e:
            print(f"Error opening CHM file: {e}")
            return False

    def extract_html_content(self, path):
        try:
            data = self.chm_obj.get_obj(path)
            if data:
                try:
                    html_content = data.decode("utf-8", errors="ignore")
                    return self.clean_html(html_content)
                except:
                    return "[Binary or encoded content]"
            return ""
        except Exception as e:
            print(f"Error extracting {path}: {e}")
            return ""

    def clean_html(self, html_content):
        html_content = re.sub(
            r"<script[^>]*>.*?</script>",
            "",
            html_content,
            flags=re.DOTALL | re.IGNORECASE,
        )
        html_content = re.sub(
            r"<style[^>]*>.*?</style>",
            "",
            html_content,
            flags=re.DOTALL | re.IGNORECASE,
        )
        html_content = (
            html_content.replace("<br>", "\n")
            .replace("<br/>", "\n")
            .replace("<br />", "\n")
        )
        html_content = html_content.replace("</p>", "\n\n").replace("<p>", "")
        html_content = html_content.replace("</h1>", "\n\n").replace("<h1>", "")
        html_content = html_content.replace("</h2>", "\n\n").replace("<h2>", "")
        html_content = html_content.replace("</h3>", "\n\n").replace("<h3>", "")
        html_content = html_content.replace("</h4>", "\n\n").replace("<h4>", "")
        html_content = html_content.replace("</li>", "\n").replace("<li>", "• ")
        html_content = html_content.replace("</div>", "\n").replace("<div>", "")
        html_content = html_content.replace("</span>", "").replace("<span>", "")
        html_content = html_content.replace("&nbsp;", " ")
        html_content = html_content.replace("&amp;", "&")
        html_content = html_content.replace("&lt;", "<")
        html_content = html_content.replace("&gt;", ">")
        html_content = html_content.replace("&quot;", '"')
        html_content = re.sub(r"<[^>]+>", "", html_content)
        html_content = re.sub(r"\n\s*\n", "\n\n", html_content)
        html_content = html_content.strip()
        return html_content

    def get_toc(self):
        toc_entries = []
        try:
            if hasattr(self.chm_obj, "get_toc"):
                toc = self.chm_obj.get_toc()
                if toc:
                    return self.parse_toc(toc)
            for path in ["#SYSTEM", "#TOPICS", "#STRINGS", "#URLTBL"]:
                try:
                    data = self.chm_obj.get_obj(path)
                    if data:
                        print(f"Found {path}")
                        text = data.decode("utf-8", errors="ignore")
                        entries = re.findall(r"[\w\s\-\.]+\.html?", text, re.IGNORECASE)
                        if entries:
                            toc_entries.extend(entries)
                except:
                    pass
            if not toc_entries:
                print("Scanning for HTML files...")
                for path in self.chm_obj.list():
                    if path.endswith((".html", ".htm")):
                        toc_entries.append(path)
            return sorted(set(toc_entries))
        except Exception as e:
            print(f"Error getting TOC: {e}")
            return []

    def parse_toc(self, toc_obj):
        entries = []
        if isinstance(toc_obj, list):
            for item in toc_obj:
                if isinstance(item, dict):
                    if "path" in item:
                        entries.append(item["path"])
                    if "children" in item:
                        entries.extend(self.parse_toc(item["children"]))
                elif isinstance(item, str):
                    entries.append(item)
        return entries

    def convert_to_pdf(self):
        if not self.open_chm():
            return False
        print("Extracting content from CHM file...")
        toc_entries = self.get_toc()
        if not toc_entries:
            print("No content found in CHM file.")
            return False
        print(f"Found {len(toc_entries)} pages.")
        try:
            doc = SimpleDocTemplate(
                str(self.output_file),
                pagesize=letter,
                rightMargin=72,
                leftMargin=72,
                topMargin=72,
                bottomMargin=72,
            )
            styles = getSampleStyleSheet()
            story = []
            title_style = ParagraphStyle(
                "CustomTitle",
                parent=styles["Heading1"],
                fontSize=24,
                textColor="darkblue",
                alignment=TA_CENTER,
                spaceAfter=30,
            )
            story.append(Paragraph(f"<b>{self.chm_file.stem}</b>", title_style))
            story.append(Spacer(1, 0.25 * inch))
            page_count = 0
            for i, entry in enumerate(toc_entries):
                try:
                    content = self.extract_html_content(entry)
                    if content:
                        if i > 0:
                            story.append(PageBreak())
                        heading = Path(entry).stem.replace("_", " ").replace("-", " ")
                        if heading:
                            story.append(
                                Paragraph(f"<b>{heading}</b>", styles["Heading2"])
                            )
                            story.append(Spacer(1, 0.1 * inch))
                        paragraphs = content.split("\n\n")
                        for para in paragraphs:
                            if para.strip():
                                para_text = para.replace("\n", " ").strip()
                                try:
                                    story.append(Paragraph(para_text, styles["Normal"]))
                                    story.append(Spacer(1, 0.05 * inch))
                                except:
                                    story.append(
                                        Paragraph(para_text[:1000], styles["Normal"])
                                    )
                        page_count += 1
                        print(f"Processed: {entry}")
                except Exception as e:
                    print(f"Error processing {entry}: {e}")
                    continue
            if not story:
                print("No content extracted to create PDF.")
                return False
            print(f"Building PDF with {page_count} pages...")
            doc.build(story)
            print(f"PDF created successfully: {self.output_file}")
            return True
        except Exception as e:
            print(f"Error creating PDF: {e}")
            return False


def main():
    if len(sys.argv) != 2:
        print("Usage: python chm_to_pdf.py <chm_file>")
        print("Example: python chm_to_pdf.py document.chm")
        sys.exit(1)
    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Error: File '{input_path}' not found.")
        sys.exit(1)
    if not input_path.suffix.lower() == ".chm":
        print(f"Warning: '{input_path}' may not be a CHM file.")
    output_path = input_path.with_suffix(".pdf")
    converter = CHMToPDF(input_path, output_path)
    success = converter.convert_to_pdf()
    if success:
        print(f"Conversion complete: {output_path}")
    else:
        print("Conversion failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
