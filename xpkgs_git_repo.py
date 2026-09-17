#!/data/data/com.termux/files/home/.local/bin/python
"""
Extract git repository URLs from packages installed in the system site-packages
and save the results as JSON in the home folder.
"""

import json
import subprocess
import sys
from pathlib import Path


def get_system_site_packages() -> list[str]:
    """Return a list of package names installed in system site-packages."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=json"],
            capture_output=True,
            text=True,
            check=True,
        )
        packages = json.loads(result.stdout)
        return [pkg["name"] for pkg in packages]
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"Error listing packages: {e}", file=sys.stderr)
        return []


def get_package_metadata(package_name: str) -> dict:
    """
    Retrieve metadata for a single package using pip show.
    Returns a dict with relevant fields.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", package_name],
            capture_output=True,
            text=True,
            check=True,
        )
        metadata = {}
        for line in result.stdout.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                metadata[key.strip()] = value.strip()
        return metadata
    except subprocess.CalledProcessError:
        return {}


def extract_git_url(metadata: dict) -> str | None:
    """
    Try to find a git repository URL from package metadata.
    Checks these fields in order:
      1. Home-page
      2. Project-URL entries (Source Code, Code, Homepage)
      3. Download-URL
    Returns the first URL that looks like a git host, or None.
    """
    git_hosts = (
        "github.com",
        "gitlab.com",
        "bitbucket.org",
        "sourcehut.org",
        "codeberg.org",
    )

    candidates: list[str] = []

    home_page = metadata.get("Home-page", "").strip()
    if home_page and home_page.lower() not in ("none", "unknown", ""):
        candidates.append(home_page)

    # Project-URL is a comma-separated "Label, URL" list, one per line
    project_urls_raw = metadata.get("Project-URLs") or metadata.get("Project-URL", "")
    for entry in project_urls_raw.split("\n"):
        entry = entry.strip()
        if not entry:
            continue
        # Each entry looks like "Source Code, https://..."
        label, sep, url = entry.partition(",")
        if sep:
            label_lower = label.strip().lower()
            url = url.strip()
            # Prioritise labels that strongly suggest the source repo
            if any(
                kw in label_lower
                for kw in ("source", "repository", "repo", "code", "git")
            ):
                candidates.insert(0, url)
            else:
                candidates.append(url)

    download_url = metadata.get("Download-URL", "").strip()
    if download_url and download_url.lower() not in ("none", "unknown", ""):
        candidates.append(download_url)

    for url in candidates:
        if any(host in url for host in git_hosts):
            # Normalise: strip trailing slashes and .git suffix noise
            url = url.rstrip("/")
            return url

    return None


def collect_git_urls(packages: list[str]) -> dict[str, str | None]:
    """
    Build a mapping of {package_name: git_url_or_none} for every package.
    """
    results: dict[str, str | None] = {}
    total = len(packages)
    for idx, name in enumerate(packages, start=1):
        print(f"[{idx}/{total}] Checking {name} ...", end="\r", flush=True)
        meta = get_package_metadata(name)
        results[name] = extract_git_url(meta)
    print()  # newline after progress line
    return results


def main() -> None:
    output_path = Path.home() / "pkg_git_urls.json"

    print("Fetching installed package list ...")
    packages = get_system_site_packages()
    if not packages:
        print("No packages found. Exiting.")
        sys.exit(1)

    print(f"Found {len(packages)} packages. Extracting git URLs ...")
    url_map = collect_git_urls(packages)

    found = {k: v for k, v in url_map.items() if v}
    missing = {k: v for k, v in url_map.items() if not v}

    output = {
        "summary": {
            "total_packages": len(url_map),
            "with_git_url": len(found),
            "without_git_url": len(missing),
        },
        "packages": url_map,
    }

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nDone.")
    print(f"  {len(found)} packages have a git URL.")
    print(f"  {len(missing)} packages have no detectable git URL.")
    print(f"  Results saved to: {output_path}")


if __name__ == "__main__":
    main()
