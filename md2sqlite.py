#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sqlite3

DB_NAME = "ruff_rules.db"
MD_FILE = "ruff.md"


def create_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ruff_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            name TEXT,
            what_it_does TEXT,
            why_it_bad TEXT,
            example TEXT,
            fix_safety TEXT,
            options TEXT,
            references_list TEXT
        )
    """)
    conn.commit()
    conn.close()


def parse_and_insert():
    with open(MD_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    rule_blocks = re.findall(
        r"^#\s+(.*?)\s+\((.*?)\)\s*\n(.*?)(?=\n#\s+|\Z)",
        content,
        re.DOTALL | re.MULTILINE,
    )
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    inserted_count = 0
    for name, code, body in rule_blocks:

        def extract_section(header_title):
            pattern = rf"##\s+{header_title}\s*\n(.*?)(?=\n##\s+|\Z)"
            match = re.search(pattern, body, re.DOTALL | re.IGNORECASE)
            return match.group(1).strip() if match else None

        what_it_does = extract_section("What it does")
        why_it_bad = extract_section(r"Why is this bad\??")
        example = extract_section("Example")
        fix_safety = extract_section("Fix safety")
        options = extract_section("Options")
        references = extract_section("References")
        try:
            cursor.execute(
                """
                INSERT OR REPLACE INTO ruff_rules
                (code, name, what_it_does, why_it_bad, example, fix_safety, options, references_list)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    code.strip(),
                    name.strip(),
                    what_it_does,
                    why_it_bad,
                    example,
                    fix_safety,
                    options,
                    references,
                ),
            )
            inserted_count += 1
        except sqlite3.Error as e:
            print(f"Error inserting rule {code}: {e}")
    conn.commit()
    conn.close()
    print(f"Success! Successfully saved {inserted_count} rules into '{DB_NAME}'.")


if __name__ == "__main__":
    create_database()
    parse_and_insert()
