#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import base64
import os
import re
import sys
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

from dh import unique_path


def sanitize_filename(name: str) -> str:
    name = name.strip().strip('"').strip("'")
    name = name.replace("\\\\", "/").split("/")[-1]
    return re.sub("[^A-Za-z0-9._-]+", "_", name) or "resource"


def split_data_url(src: str):
    if not src or not src.startswith("data:"):
        return None
    m = re.match("data:([^;]+);base64,(.*)$", src, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    mime = m.group(1)
    b64 = m.group(2)
    try:
        raw = base64.b64decode(b64)
        return (mime, raw)
    except Exception:
        return None


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: python mhtml_to_html.py input.mhtml [output.html] [output_files_dir]"
        )
        sys.exit(1)
    in_path = Path(sys.argv[1])
    out_html = sys.argv[2] if len(sys.argv) >= 3 else Path(in_path).with_suffix(".html")
    out_dir = sys.argv[3] if len(sys.argv) >= 4 else Path(in_path).stem + "_files"
    os.makedirs(out_dir, exist_ok=True)
    with open(in_path, "rb") as f:
        raw = f.read()
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    parts = []
    if msg.is_multipart():

        def walk(m: EmailMessage) -> None:
            for p in m.iter_parts():
                parts.append(p)
                if p.is_multipart():
                    walk(p)

        walk(msg)
    else:
        parts = [msg]
    html_candidates = []
    resource_parts = []
    for p in parts:
        ctype = p.get_content_type()
        disp = (p.get("Content-Disposition") or "").lower()
        cid = (p.get("Content-ID") or "").strip()
        if cid.startswith("<") and cid.endswith(">"):
            cid = cid[1:-1]
        payload = p.get_payload(decode=True)
        if ctype == "text/html":
            html_candidates.append((cid, payload))
        elif payload:
            resource_parts.append((cid, ctype, disp, payload, p))
    if not html_candidates:
        for p in parts:
            if p.get_content_type().startswith("text/"):
                payload = p.get_payload(decode=True)
                if payload:
                    html_candidates.append((None, payload))
                    break
    if not html_candidates:
        raise RuntimeError("No HTML part found in the MHTML.")
    _, html_bytes = html_candidates[0]
    html_text = html_bytes.decode(errors="replace")
    cid_to_file = {}

    def get_name_from_headers(part) -> str:
        filename = (
            part.get_param("name", header="Content-Type")
            if part.get("Content-Type")
            else None
        )
        if filename:
            return sanitize_filename(filename)
        cd = part.get("Content-Disposition") or ""
        m = re.search(
            "filename-\\*?=(?:UTF-8'')?[\\\"']?([^\\\"';]+)", cd, flags=re.IGNORECASE
        )
        if m:
            return sanitize_filename(m.group(1))
        return None

    for cid, ctype, disp, payload, part in resource_parts:
        if not payload:
            continue
        if ctype == "text/html":
            continue
        ext = None
        m = re.match("^[^/]+/([^;\\s]+)", ctype)
        if m:
            ext = m.group(1)
        if ext == "svg+xml":
            ext = "svg"
        base_name = get_name_from_headers(part) or cid or "resource"
        base_name = sanitize_filename(base_name)
        if ext:
            if not os.path.splitext(base_name)[1]:
                fname = f"{base_name}.{ext}"
            else:
                fname = base_name
        else:
            fname = base_name
        out_path = os.path.join(out_dir, fname)
        if os.path.exists(out_path):
            stem, suffix = os.path.splitext(fname)
            i = 1
            while True:
                cand = os.path.join(out_dir, f"{stem}_{i}{suffix}")
                if not os.path.exists(cand):
                    out_path = cand
                    fname = os.path.basename(cand)
                    break
                i += 1
        with open(out_path, "wb") as f:
            f.write(payload)
        if cid:
            cid_to_file[cid] = fname

    def repl_cid(match):
        cid = match.group(1)
        if cid in cid_to_file:
            return f'src="{os.path.basename(out_dir)}/{cid_to_file[cid]}"'
        return match.group(0)

    html_text = re.sub(
        "(src|href)=[\\\"']cid:([^\\\"']+)[\\\"']",
        lambda m: (
            f'{m.group(1)}="{os.path.basename(out_dir)}/{cid_to_file.get(m.group(2), m.group(2))}"'
            if m.group(2) in cid_to_file
            else m.group(0)
        ),
        html_text,
        flags=re.IGNORECASE,
    )

    def data_uri_replacer(match):
        attr = match.group(1)
        data_url = match.group(2)
        parsed = split_data_url(data_url)
        if not parsed:
            return match.group(0)
        mime, raw = parsed
        ext = None
        m = re.match("^[^/]+/([^;\\s]+)", mime)
        if m:
            ext = m.group(1)
        if ext == "svg+xml":
            ext = "svg"
        fname = f"data_resource_{abs(hash(data_url)) % 10**8}.{ext or 'bin'}"
        out_path = os.path.join(out_dir, fname)
        with open(out_path, "wb") as f:
            f.write(raw)
        return f'{attr}="{os.path.basename(out_dir)}/{fname}"'

    if out_html.exists():
        out_html = unique_path(out_html)
    html_text = re.sub(
        "(src|href)=[\\\"'](data:[^\\\"']+)[\\\"']",
        data_uri_replacer,
        html_text,
        flags=re.IGNORECASE,
    )
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html_text)
    print("Done.")
    print(f"HTML: {out_html}")
    print(f"Resources: {out_dir}/ (extracted {len(cid_to_file)} CID items)")


if __name__ == "__main__":
    raise SystemExit(main())
