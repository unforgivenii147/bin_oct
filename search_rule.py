#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sqlite3
import sys

DB_NAME = "/sdcard/data/ruff.db"


def search_rule(code):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ruff_rules WHERE code = ?", (code.strip().upper(),))
    row = cursor.fetchone()
    conn.close()
    if not row:
        print(f"❌ No rule found matching code: {code}")
        return
    print("-" * 40)
    print(f"📜 RULE: {row['name']} ({row['code']})")
    print("-" * 40)
    print(f"\n💡 WHAT IT DOES:\n{row['what_it_does']}")
    print(f"\n⚠️ WHY IT IS BAD:\n{row['why_it_bad']}")
    print(f"\n💻 EXAMPLE:\n{row['example']}")
    if row["fix_safety"]:
        print(f"\n🔒 FIX SAFETY:\n{row['fix_safety']}")
    if row["options"]:
        print(f"\n⚙️ OPTIONS:\n{row['options']}")
    if row["references_list"]:
        print(f"\n🔗 REFERENCES:\n{row['references_list']}")
    print("-" * 40)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        search_rule(sys.argv[1])
    else:
        user_code = input("Enter Ruff rule code to look up (e.g., TRY400): ")
        search_rule(user_code)
