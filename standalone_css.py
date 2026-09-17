#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import base64
import os
import re
import sys
from pathlib import Path

import requests
from loguru import logger

STATIC_DIR = "/sdcard/_static"


def get_file_extension(url):
    return os.path.splitext(url)[1].lower()


def is_font_url(url) -> bool:
    return any(url.lower().endswith(ext) for ext in extensions)


def find_local_font(font_filename: str) -> str | None:
    if not Path(STATIC_DIR).is_dir():
        return None
    for root, _, files in os.walk(STATIC_DIR):
        if font_filename in files:
            return os.path.join(root, font_filename)
    return None


def get_local_font_base64(local_path: str) -> str | None:
    try:
        content = Path(local_path).read_bytes()
        ext = get_file_extension(local_path)
        content_type = ""
        if ext == ".eot":
            content_type = "application/vnd.ms-fontobject"
        elif ext == ".ttf":
            content_type = "application/font-sfnt"
        elif ext == ".woff":
            content_type = "application/font-woff"
        elif ext == ".woff2":
            content_type = "font/woff2"
        elif ext == ".svg":
            content_type = "image/svg+xml"
        else:
            return None
        encoded_string = base64.b64encode(content).decode("utf-8")
        return f"data:{content_type};charset=utf-8;base64,{encoded_string}"
    except FileNotFoundError:
        print(f"Error: Local font file not found at {local_path}")
        return None
    except Exception as e:
        print(f"An error occurred reading local font {local_path}: {e}")
        return None


def get_remote_font_base64(url) -> str | None:
    try:
        response = requests.get(url, timeout=15, stream=True)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";")[0]
        if (
            not content_type.lower().startswith("font")
            and "svg" not in content_type.lower()
        ):
            print(
                f"Warning: Content-Type '{content_type}' for {url} doesn't look like a font. Proceeding anyway."
            )
        ext = get_file_extension(url)
        if ext == ".eot":
            content_type = "application/vnd.ms-fontobject"
        elif ext == ".ttf":
            content_type = "application/font-sfnt"
        elif ext == ".woff":
            content_type = "application/font-woff"
        elif ext == ".woff2":
            content_type = "font/woff2"
        elif ext == ".svg":
            content_type = "image/svg+xml"
        else:
            return None
        encoded_string = base64.b64encode(response.content).decode("utf-8")
        return f"data:{content_type};charset=utf-8;base64,{encoded_string}"
    except requests.exceptions.RequestException as e:
        print(f"Error fetching remote font {url}: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred for remote font {url}: {e}")
        return None


def url_to_base64(url, base_css_path: Path) -> str | None:
    cleaned_url = url.strip("'\"")
    font_filename = Path(cleaned_url).name
    logger.debug(f"looking for {font_filename} in {STATIC_DIR}")
    local_path = find_local_font(font_filename)
    if local_path:
        print(f"Found local font: {font_filename} at {local_path}")
        return get_local_font_base64(local_path)
    full_url = cleaned_url
    if not cleaned_url.startswith(("http://", "https://", "//")):
        base_dir = Path(Path(base_css_path).resolve()).parent
        full_url = os.path.normpath(Path(base_dir) / cleaned_url)
        if not full_url.startswith(("http://", "https://", "//")):
            full_url = f"file:///{full_url}"
    print(f"Attempting to fetch remote font: {full_url}")
    return get_remote_font_base64(full_url)


def make_css_standalone(input_css_path: Path, output_css_path: Path) -> None:
    input_css_path = Path(input_css_path).resolve()
    try:
        content = Path(input_css_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"Error: Input CSS file not found at {input_css_path}")
        return
    except Exception as e:
        print(f"Error reading input CSS file {input_css_path}: {e}")
        return
    import_pattern = re.compile(
        r"@import\s+(?:url\()?([\"\'])(.*?)\1\)?;", re.IGNORECASE
    )
    font_url_pattern = re.compile(r"url\(([\"\']?)([^)\"\'\s]+?)\1?\)", re.IGNORECASE)
    processed_content = content
    import_urls_to_process = []
    for match in import_pattern.finditer(content):
        import_url = match.group(2)
        import_urls_to_process.append(import_url)
        processed_content = processed_content.replace(match.group(0), "", 1)
    processed_imports = set()
    queue = import_urls_to_process.copy()
    while queue:
        current_import_url = queue.pop(0)
        normalized_import_url = os.path.normpath(current_import_url)
        if normalized_import_url in processed_imports:
            continue
        processed_imports.add(normalized_import_url)
        print(f"Processing imported CSS: {current_import_url}")
        try:
            if not current_import_url.startswith(("http://", "https://", "//")):
                base_dir = Path(Path(input_css_path).resolve()).parent
                fetch_url = os.path.normpath(Path(base_dir) / current_import_url)
                if not fetch_url.startswith(("http://", "https://", "//")):
                    if Path(fetch_url).exists():
                        imported_css = Path(fetch_url).read_text(encoding="utf-8")
                        import_source_ref = fetch_url
                    else:
                        print(
                            f"Warning: Local import file not found: {fetch_url}. Skipping."
                        )
                        continue
                else:
                    response = requests.get(current_import_url, timeout=15)
                    response.raise_for_status()
                    imported_css = response.text
                    import_source_ref = current_import_url
            else:
                response = requests.get(current_import_url, timeout=15)
                response.raise_for_status()
                imported_css = response.text
                import_source_ref = current_import_url
            for sub_match in import_pattern.finditer(imported_css):
                sub_import_url = sub_match.group(2)
                if os.path.normpath(sub_import_url) not in processed_imports:
                    queue.append(sub_import_url)
                imported_css = imported_css.replace(sub_match.group(0), "", 1)
            processed_content += (
                f"\n/* Imported from: {import_source_ref} */\n{imported_css}\n"
            )
        except FileNotFoundError:
            print(
                f"Could not import local file {current_import_url} (resolved to {fetch_url}): File not found."
            )
        except requests.exceptions.RequestException as e:
            print(f"Could not import remote CSS from {current_import_url}: {e}")
        except Exception as e:
            print(
                f"An unexpected error occurred while processing import {current_import_url}: {e}"
            )

    def replace_font_urls_in_content(match):
        url_part = match.group(2)
        quote_style = match.group(1)
        base64_data = url_to_base64(url_part, input_css_path)
        if base64_data:
            if quote_style:
                return f"url({quote_style}{base64_data}{quote_style})"
            return f'url("{base64_data}")'
        print(f"Failed to process font URL: {url_part}. Keeping original.")
        return match.group(0)

    processed_content = font_url_pattern.sub(
        replace_font_urls_in_content, processed_content
    )
    try:
        output_dir = Path(output_css_path).parent
        if output_dir:
            Path(output_dir).mkdir(exist_ok=True, parents=True)
        Path(output_css_path).write_text(processed_content, encoding="utf-8")
        print(f"Standalone CSS file created at: {output_css_path}")
    except Exception as e:
        print(f"Error writing output CSS file {output_css_path}: {e}")


if __name__ == "__main__":
    infile = Path(sys.argv[1])
    outfile = infile.with_stem(infile.stem + "_standalone")
    make_css_standalone(infile, outfile)
