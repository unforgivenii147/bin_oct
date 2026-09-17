#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


def read_links_from_file(filename="links.txt"):
    try:
        with open(filename) as file:
            links = [line.strip() for line in file if line.strip()]
        return links
    except FileNotFoundError:
        print(
            f"Error: {filename} not found. Please create a {filename} with website URLs."
        )
        return []


def extract_th18_bases(website_url, timeout=10):
    th18_links = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(website_url, headers=headers, timeout=timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        all_links = soup.find_all("a", href=True)
        for link in all_links:
            href = link.get("href")
            text = link.get_text(strip=True).lower()
            if any(
                indicator in text.lower() or indicator in href.lower()
                for indicator in ["th18", "town hall 18", "townhall 18", "th-18"]
            ):
                absolute_url = urljoin(website_url, href)
                if absolute_url not in th18_links:
                    th18_links.append(
                        {
                            "url": absolute_url,
                            "title": text if text else "TH18 Base",
                            "source": website_url,
                        }
                    )
        print(f"✓ Found {len(th18_links)} TH18 bases from {website_url}")
    except requests.exceptions.RequestException as e:
        print(f"✗ Error fetching {website_url}: {e!s}")
    return th18_links


def save_to_html(all_bases, output_file="th18_bases.html"):
    html_content = (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n    <meta charset="UTF-8">\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <title>Clash of Clans TH18 Base Links</title>\n    <style>\n        * {\n            margin: 0;\n            padding: 0;\n            box-sizing: border-box;\n        }\n        \n        body {\n            font-family: \'Segoe UI\', Tahoma, Geneva, Verdana, sans-serif;\n            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);\n            min-height: 100vh;\n            padding: 20px;\n        }\n        \n        .container {\n            max-width: 1000px;\n            margin: 0 auto;\n            background: white;\n            border-radius: 10px;\n            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);\n            padding: 30px;\n        }\n        \n        h1 {\n            color: #333;\n            margin-bottom: 10px;\n            text-align: center;\n        }\n        \n        .info {\n            text-align: center;\n            color: #666;\n            margin-bottom: 30px;\n            font-size: 14px;\n        }\n        \n        .stats {\n            display: flex;\n            justify-content: center;\n            gap: 30px;\n            margin-bottom: 30px;\n            flex-wrap: wrap;\n        }\n        \n        .stat {\n            text-align: center;\n        }\n        \n        .stat-number {\n            font-size: 28px;\n            font-weight: bold;\n            color: #667eea;\n        }\n        \n        .stat-label {\n            color: #999;\n            font-size: 12px;\n            text-transform: uppercase;\n            margin-top: 5px;\n        }\n        \n        .bases-grid {\n            display: grid;\n            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));\n            gap: 20px;\n        }\n        \n        .base-card {\n            background: #f8f9fa;\n            border-left: 4px solid #667eea;\n            border-radius: 5px;\n            padding: 15px;\n            transition: all 0.3s ease;\n        }\n        \n        .base-card:hover {\n            background: #fff;\n            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);\n            transform: translateY(-2px);\n        }\n        \n        .base-title {\n            font-weight: bold;\n            color: #333;\n            margin-bottom: 10px;\n            word-break: break-word;\n        }\n        \n        .base-link {\n            display: inline-block;\n            background: #667eea;\n            color: white;\n            padding: 10px 15px;\n            border-radius: 5px;\n            text-decoration: none;\n            font-size: 14px;\n            margin-bottom: 10px;\n            transition: background 0.3s ease;\n            word-break: break-all;\n        }\n        \n        .base-link:hover {\n            background: #764ba2;\n        }\n        \n        .base-source {\n            font-size: 12px;\n            color: #999;\n            margin-top: 10px;\n            word-break: break-word;\n        }\n        \n        .empty {\n            text-align: center;\n            padding: 40px;\n            color: #999;\n        }\n        \n        .footer {\n            text-align: center;\n            margin-top: 30px;\n            padding-top: 20px;\n            border-top: 1px solid #eee;\n            font-size: 12px;\n            color: #999;\n        }\n    </style>\n</head>\n<body>\n    <div class="container">\n        <h1>🏰 Clash of Clans TH18 Base Links</h1>\n        <p class="info">Extracted and compiled base links from various sources</p>\n        \n        <div class="stats">\n            <div class="stat">\n                <div class="stat-number">'
        + str(len(all_bases))
        + '</div>\n                <div class="stat-label">Total Bases</div>\n            </div>\n            <div class="stat">\n                <div class="stat-number">'
        + str(len({base["source"] for base in all_bases}))
        + '</div>\n                <div class="stat-label">Sources</div>\n            </div>\n        </div>\n        \n        <div class="bases-grid">\n'
    )
    if all_bases:
        for i, base in enumerate(all_bases, 1):
            html_content += f"""            <div class="base-card">\n                <div class="base-title">Base #{
                i
            }: {base["title"]}</div>\n                <a href="{
                base["url"]
            }" class="base-link" target="_blank">🔗 Open Base</a>\n                <div class="base-source"><strong>Source:</strong> {
                base["source"]
            }</div>\n            </div>\n"""
    else:
        html_content += '            <div class="empty">\n                <p>No TH18 bases found. Make sure your links.txt contains valid URLs and the websites have TH18 bases.</p>\n            </div>\n'
    html_content += '        </div>\n        \n        <div class="footer">\n            <p>Generated automatically | Clash of Clans Base Scraper</p>\n        </div>\n    </div>\n</body>\n</html>\n'
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"\n✓ HTML file saved as {output_file}")


def main():
    print("-" * 40)
    print("Clash of Clans TH18 Base Link Extractor")
    print("-" * 40)
    websites = read_links_from_file("links.txt")
    if not websites:
        return
    print(f"\nFound {len(websites)} websites to scrape...\n")
    all_th18_bases = []
    for i, website in enumerate(websites, 1):
        print(f"[{i}/{len(websites)}] Scraping {website}...")
        if not website.startswith(("http://", "https://")):
            website = "https://" + website
        bases = extract_th18_bases(website)
        all_th18_bases.extend(bases)
        time.sleep(1)
    print(f"\nTotal TH18 bases found: {len(all_th18_bases)}")
    save_to_html(all_th18_bases)
    print("\nDone! Open 'th18_bases.html' in your browser to view the results.")


if __name__ == "__main__":
    raise SystemExit(main())
