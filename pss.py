#!/data/data/com.termux/files/home/.local/bin/python
"""
Search PyPI packages by name (case-insensitive substring) using SQLite FTS5.

Data flow:
  /sdcard/data/pip.db   --  prebuilt SQLite database (read-only)

The script auto-detects the table name and column names at runtime.
It assumes the table has exactly two columns: the first is the package
name (searchable), the second is the download count (sortable).

Why FTS5 with the trigram tokenizer?
  A plain SQLite table with `LIKE '%foo%'` still does a full table scan.
  The trigram tokenizer builds an inverted index of 3-character substrings,
  so a query like "pand" becomes a small B-tree intersection -- O(matches)
  instead of O(rows). This is what makes SQLite beat the mmap/CSV approach
  by an order of magnitude for substring search.

Why heapq.nlargest?
  For a broad keyword (e.g. "py") FTS5 may return tens of thousands of rows.
  Sorting the full list with `list.sort` is O(k log k) time and O(k) memory.
  `heapq.nlargest` streams the SQLite cursor through a size-`limit` min-heap,
  giving O(k log limit) time and O(limit) extra memory. It never materialises
  the full result set.

Usage:
  search pandas                 # top 20 substring matches by downloads
  search -n 100 pandas          # top 100
"""

import argparse
import heapq
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("/sdcard/data/pip.db")

DEFAULT_LIMIT = 20
TRIGRAM_MIN = 3  # FTS5 trigram cannot index/query strings shorter than 3 chars


# ----------------------------------------------------------- introspection ---


def get_table_info(con: sqlite3.Connection):
    """
    Discover the table name, the name column, the downloads column, and
    whether the table is an FTS5 virtual table.

    Returns:
        (table, name_col, dl_col, is_fts5)
    """
    # Find all user tables (exclude SQLite internal ones)
    cur = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    tables = [row[0] for row in cur.fetchall()]
    if not tables:
        sys.exit("No tables found in database.")

    # Prefer a table with exactly two columns
    chosen = None
    for t in tables:
        cur = con.execute(f'PRAGMA table_info("{t}")')
        cols = cur.fetchall()
        if len(cols) == 2:
            chosen = (t, [c[1] for c in cols])
            break

    if chosen is None:
        # Fallback: take the first table and hope it has at least two columns
        t = tables[0]
        cur = con.execute(f'PRAGMA table_info("{t}")')
        cols = [c[1] for c in cur.fetchall()]
        if len(cols) < 2:
            sys.exit(f"Table '{t}' must have at least two columns.")
        chosen = (t, cols)

    table, col_names = chosen
    name_col, dl_col = col_names[0], col_names[1]

    # Is it an FTS5 virtual table?
    cur = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    row = cur.fetchone()
    is_fts5 = bool(row and row[0] and "fts5" in row[0].lower())

    return table, name_col, dl_col, is_fts5


# --------------------------------------------------------------- search ---


def search(
    con: sqlite3.Connection,
    table: str,
    name_col: str,
    dl_col: str,
    is_fts5: bool,
    keyword: str,
    limit: int,
):
    """
    Return the top `limit` matches as a list of (name, downloads) tuples,
    sorted by downloads descending.

    Uses FTS5 MATCH for keywords of length >= 3 when the table is FTS5.
    Falls back to LIKE for shorter keywords or non-FTS5 tables.
    """
    kw = keyword.lower()

    # Quote identifiers to be safe with any names
    q_table = f'"{table}"'
    q_name = f'"{name_col}"'
    q_dl = f'"{dl_col}"'

    def run_like():
        # Escape the LIKE metacharacters (\ % _) so "a_b" is literal.
        escaped = kw.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        sql = (
            f"SELECT {q_name}, {q_dl} FROM {q_table} WHERE {q_name} LIKE ? ESCAPE '\\'"
        )
        return con.execute(sql, (f"%{escaped}%",))

    cur = None
    if is_fts5 and len(kw) >= TRIGRAM_MIN:
        # Double-quote the keyword so FTS5 treats it as a literal phrase
        # rather than interpreting MATCH operators (AND, OR, NEAR, *, etc.).
        # Inner double quotes are escaped by doubling them, per FTS5 rules.
        fts_query = '"' + kw.replace('"', '""') + '"'
        sql = f"SELECT {q_name}, {q_dl} FROM {q_table} WHERE {q_name} MATCH ?"
        try:
            cur = con.execute(sql, (fts_query,))
        except sqlite3.OperationalError:
            # Fallback: e.g. the column is UNINDEXED in FTS5, or MATCH failed
            cur = run_like()
    else:
        cur = run_like()

    # Streaming top-N: the cursor is consumed lazily, one row at a time,
    # and only a size-`limit` heap is retained.
    return heapq.nlargest(limit, cur, key=lambda r: r[1])


# ----------------------------------------------------------------- main ---


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Search PyPI packages by substring (SQLite FTS5 trigram).",
    )
    ap.add_argument(
        "keyword", nargs="?", help="substring to search for (case-insensitive)"
    )
    ap.add_argument(
        "-n",
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"max results (default: {DEFAULT_LIMIT})",
    )
    args = ap.parse_args()

    if not DB_PATH.exists():
        sys.exit(f"Index not found: {DB_PATH}")

    keyword = args.keyword
    if not keyword:
        keyword = input("Search package: ").strip()
        if not keyword:
            print("No keyword given.")
            return

    con = sqlite3.connect(str(DB_PATH))
    try:
        table, name_col, dl_col, is_fts5 = get_table_info(con)
        rows = search(con, table, name_col, dl_col, is_fts5, keyword, args.limit)
    finally:
        con.close()

    if not rows:
        print(f"No matches for '{keyword}'.")
        return

    for name, dl in rows:
        print(f"{name}  {dl}")


if __name__ == "__main__":
    main()
