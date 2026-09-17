#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup


def find_html_files(cwd: str = ".") -> list[Path]:
    root_path = Path(cwd).resolve()
    html_files = [
        path for path in root_path.rglob("*.html") if path.name != "template.html"
    ]
    for path in root_path.rglob("*.htm"):
        html_files.append(path)
    return sorted(html_files)


def extract_common_structure(html_files: list[Path]) -> dict:
    body_classes = []
    meta_tags = []
    link_tags = []
    script_tags = []
    for path in html_files:
        try:
            with Path(path).open(encoding="utf-8") as f:
                soup = BeautifulSoup(f.read(), "html.parser")
                if soup.head:
                    meta_tags.extend(str(meta) for meta in soup.head.find_all("meta"))
                    link_tags.extend(str(link) for link in soup.head.find_all("link"))
                    script_tags.extend(
                        str(script)
                        for script in soup.head.find_all("script")
                        if script.get("src")
                    )
                if soup.body and soup.body.get("class"):
                    body_classes.extend(soup.body.get("class"))
        except Exception as e:
            print(f"Error processing {path}: {e}")
    common_meta = list(set(meta_tags))
    common_links = list(set(link_tags))
    common_scripts = list(set(script_tags))
    common_body_class = " ".join(set(body_classes)) if body_classes else ""
    return {
        "meta_tags": common_meta,
        "link_tags": common_links,
        "script_tags": common_scripts,
        "body_class": common_body_class,
    }


def merge_html_content(html_files: list[Path]) -> str:
    merged_sections = []
    for path in html_files:
        try:
            with Path(path).open(encoding="utf-8") as f:
                soup = BeautifulSoup(f.read(), "html.parser")
                content = soup.body.decode_contents() if soup.body else str(soup)
                section_html = f"""
    <!-- Content from: {path.relative_to(Path.cwd())} -->
    <section class="merged-content" data-source="{path.name}">
        {content}
    </section>
"""
                merged_sections.append(section_html)
        except Exception as e:
            print(f"Error merging {path}: {e}")
    return "".join(merged_sections)


def create_template_html(
    html_files: list[Path],
    output_file: str = "template.html",
    title: str = "Merged HTML Template",
) -> bool:
    if not html_files:
        print("No HTML files found")
        return False
    print(f"Processing {len(html_files)} HTML files...")
    structure = extract_common_structure(html_files)
    merged_content = merge_html_content(html_files)
    template = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    {chr(10).join("    " + tag for tag in structure["meta_tags"])}
    {chr(10).join("    " + tag for tag in structure["link_tags"])}
    <style>
            body {{
                font-family: Arial, sans-serif;
                line-height: 1.6;
                margin: 0;
                padding: 20px;
                background-color:
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
                background: white;
                padding: 20px;
                box-shadow: 0 0 10px rgba(0,0,0,0.1);
            }}
            .merged-content {{
                margin-bottom: 40px;
                padding: 20px;
                border-left: 4px solid
                background:
            }}
            .merged-content::before {{
                content: attr(data-source);
            display: block;
            font-weight: bold;
            color:
            margin-bottom: 10px;
            font-size: 0.9em;
        }}
        h1, h2, h3 {{
            color:
        }}
        .toc {{
            background:
            padding: 20px;
            margin-bottom: 30px;
            border-radius: 5px;
        }}
        .toc h2 {{
            margin-top: 0;
        }}
        .toc ul {{
            list-style: none;
            padding-left: 0;
        }}
        .toc li {{
            margin: 5px 0;
        }}
        .toc a {{
            color:
            text-decoration: none;
        }}
        .toc a:hover {{
            text-decoration: underline;
            }}
    </style>
    {chr(10).join("    " + tag for tag in structure["script_tags"])}
</head>
<body{' class="' + structure["body_class"] + '"' if structure["body_class"] else ""}>
    <div class="container">
        <h1>{title}</h1>
        <div class="toc">
            <h2>Table of Contents</h2>
            <ul>
        {
        chr(10).join(
            f'                <li><a href="#{Path(f).stem}">{
                Path(f).relative_to(Path.cwd())
            }</a></li>'
            for f in html_files
        )
    }
            </ul>
        </div>
{merged_content}
    </div>
    <script>
        document.querySelectorAll('.toc a').forEach(anchor => {{
            anchor.addEventListener('click', function (e) {{
                e.preventDefault();
                const target = document.querySelector(this.getAttribute('href'));
                if (target) {{
                    target.scrollIntoView({{ behavior: 'smooth' }});
                }}
            }});
        }});
        document.querySelectorAll('.merged-content').forEach((section, index) => {{
            const source = section.getAttribute('data-source');
            const id = source.replace(/\\.html?$/, '');
            section.id = id;
        }});
    </script>
</body>
</html>
"""
    try:
        Path(output_file).write_text(template, encoding="utf-8")
        print(f"Template created successfully: {output_file}")
        print(f"Merged {len(html_files)} HTML files")
        return True
    except Exception as e:
        print(f"Error writing template: {e}")
        return False


def main() -> None:
    html_files = find_html_files()
    success = create_template_html(
        html_files, output_file="template.html", title="Merged HTML Template"
    )
    if success:
        print("Output file: template.html")


if __name__ == "__main__":
    raise SystemExit(main())
