#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import pycurl
from dh import fsz


def get_remote_size(url):
    c = pycurl.Curl()
    c.setopt(c.URL, url)
    c.setopt(c.NOBODY, True)
    c.setopt(c.FOLLOWLOCATION, True)
    c.setopt(c.TIMEOUT, 15)
    c.setopt(c.USERAGENT, "Mozilla/5.0")
    try:
        c.perform()
        size = c.getinfo(c.CONTENT_LENGTH_DOWNLOAD)
        return int(size) if size > 0 else None
    except pycurl.error:
        return None
    finally:
        c.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: python download_checker.py <url> [-d]")
        print("  <url>  : The remote file URL (must be sys.argv[1])")
        print("  -d     : Download the file to the current directory")
        sys.exit(1)
    url = sys.argv[1]
    do_download = "-d" in sys.argv
    print(f"Checking remote link: {url}")
    total_size = get_remote_size(url)
    if total_size:
        print(f"Remote file size: {fsz(total_size)}")
    else:
        print("Remote file size: Unknown (Server didn't provide Content-Length)")
    if not do_download:
        print("\nUse the -d flag to download the file.")
        return
    print("Starting chunked download...\n")
    parsed = urlparse(url)
    filename = Path(parsed.path).name
    if not filename or filename == "/":
        filename = "downloaded_file"
    path = Path.cwd() / filename
    if path.exists():
        print(f"{path} exists.")
        sys.exit(0)
    downloaded = 0
    start_time = time.time()

    def write_function(data):
        nonlocal downloaded
        with open(path, "ab") as f:
            f.write(data)
        downloaded += len(data)
        elapsed = time.time() - start_time
        speed = downloaded / elapsed if elapsed > 0 else 0
        if total_size and total_size > 0:
            progress = (downloaded / total_size) * 40
            remaining = total_size - downloaded
            eta = remaining / speed if speed > 0 else 0
            eta_str = time.strftime("%H:%M:%S", time.gmtime(eta))
            size_str = f"{fsz(downloaded)}/{fsz(total_size)}"
        else:
            progress = 0.0
            eta_str = "Unknown"
            size_str = f"{fsz(downloaded)}/Unknown"
        sys.stdout.write(
            f"\r[{progress:5.1f}%] {size_str} | Speed: {fsz(speed)}/s | ETA: {eta_str}   "
        )
        sys.stdout.flush()

    c = pycurl.Curl()
    c.setopt(c.URL, url)
    c.setopt(c.FOLLOWLOCATION, True)
    c.setopt(c.USERAGENT, "Mozilla/5.0")
    c.setopt(c.WRITEFUNCTION, write_function)
    try:
        c.perform()
        http_code = c.getinfo(c.HTTP_CODE)
        if http_code >= 400:
            print(f"\n\nError: Server returned HTTP {http_code}")
            if path.exists():
                print(f"{path} exists")
                sys.exit(0)
            sys.exit(1)
    except pycurl.error as e:
        print(f"\n\nDownload error: {e}")
        if path.exists():
            print("file exists.")
        sys.exit(1)
    finally:
        c.close()
    print(f"\n\nDownload complete! Saved to: {path}")


if __name__ == "__main__":
    main()
