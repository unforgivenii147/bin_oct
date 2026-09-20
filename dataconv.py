#!/data/data/com.termux/files/home/.local/bin/python
"""
dataconv.py — universal data container converter.

Convert between: csv, tsv, json, jsonl/ndjson, sqlite (.db), sql dump (.sql),
excel (.xlsx/.xls/.xlsm), parquet, feather, orc, arrow, yaml, toml, xml,
pickle, msgpack, avro, dbf, hdf5, netcdf, zarr, ods, xlsb, rds, dta, sav,
sas7bdat, geojson, shapefile, bson, lua-like, ini, fixed-width, and more.

Design
------
* Every loader returns a common in-memory model:
      Tables = {table_name: [ {col: value, ...}, ... ]}
* Every writer consumes that model and writes a file (or set of files).
* Files > 5 MB are read via `mmap` (for text formats).
* Multiple input files convert in parallel via ``multiprocessing.Pool.map``.
* Optional 3rd-party libs are imported lazily; missing ones only affect
  the specific format, with a clear install hint.
* All failures go through loguru.

Examples
--------
    python dataconv.py --csv   data.json
    python dataconv.py --json  data.csv
    python dataconv.py --db    dump.sql
    python dataconv.py --parquet data.csv
    python dataconv.py --csv   a.json b.json c.json -j 4 -o out/
    python dataconv.py --xlsx  report.parquet
"""

from __future__ import annotations

import argparse
import csv
import importlib
import io
import json
import mmap
import os
import re
import sqlite3
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger

# --------------------------------------------------------------------------- #
# Types / constants
# --------------------------------------------------------------------------- #

# Canonical in-memory representation every loader/writer agrees on.
Tables = Dict[str, List[Dict[str, Any]]]

# Files above this size get read via mmap (text formats only).
MMAP_THRESHOLD = 5 * 1024 * 1024  # 5 MB


# --------------------------------------------------------------------------- #
# Small shared helpers
# --------------------------------------------------------------------------- #


def _require(modname: str):
    """
    Import a module lazily. If missing, raise a friendly error naming the
    pip package so users know exactly what to install. Doing this lazily
    matters because multiprocessing workers only pay the import cost for
    formats they actually touch.
    """
    try:
        return importlib.import_module(modname)
    except ImportError as exc:
        raise ImportError(
            f"format requires '{modname}'; install with: pip install {modname}"
        ) from exc


def read_text(path: Path) -> str:
    """Read a text file, mmap'ing it when it exceeds MMAP_THRESHOLD."""
    size = path.stat().st_size
    if size == 0:
        return ""
    if size > MMAP_THRESHOLD:
        logger.debug(f"mmap read: {path} ({size / 1_048_576:.1f} MB)")
        with path.open("rb") as fh:
            with mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                return mm[:].decode("utf-8", errors="replace")
    return path.read_text(encoding="utf-8")


def _columns(rows: List[Dict[str, Any]]) -> List[str]:
    """Ordered union of keys across all rows (stable, insertion-ordered)."""
    cols: List[str] = []
    seen: set = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                cols.append(key)
    return cols


def _flat(value: Any) -> Any:
    """Flatten a value for CSV/XML output."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float, str)):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _infer_sql_type(values) -> str:
    """Very simple type inference for SQLite / SQL dumps."""
    kind: Optional[str] = None
    for v in values:
        if v is None:
            continue
        if isinstance(v, bool) or isinstance(v, int):
            if kind in (None, "INTEGER"):
                kind = "INTEGER"
            elif kind == "REAL":
                kind = "REAL"
            else:
                return "TEXT"
        elif isinstance(v, float):
            if kind in (None, "INTEGER", "REAL"):
                kind = "REAL"
            else:
                return "TEXT"
        else:
            return "TEXT"
    return kind or "TEXT"


def _sqlite_val(value: Any) -> Any:
    """Adapt a python value into something sqlite3 accepts."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str, bytes)):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _sql_literal(value: Any) -> str:
    """Render a python value as a SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return (
        "'"
        + json.dumps(value, ensure_ascii=False, default=str).replace("'", "''")
        + "'"
    )


def _is_table_dict(data: Any) -> bool:
    """True if `data` looks like {table_name: [row, row, ...]}."""
    return (
        isinstance(data, dict)
        and bool(data)
        and all(isinstance(v, list) for v in data.values())
    )


def _as_tables(data: Any, fallback_name: str) -> Tables:
    """
    Normalize arbitrary loaded structures into Tables form.
    Used by many loaders (json, yaml, msgpack, pickle, ...).
    """
    if _is_table_dict(data):
        return {
            str(k): [r if isinstance(r, dict) else {"value": r} for r in v]
            for k, v in data.items()
        }
    if isinstance(data, list):
        return {
            fallback_name: [r if isinstance(r, dict) else {"value": r} for r in data]
        }
    return {fallback_name: [data if isinstance(data, dict) else {"value": data}]}


# =========================================================================== #
# CORE FORMATS: csv, json, sqlite, sql dump
# =========================================================================== #

# ------------------------------- CSV / TSV --------------------------------- #


def load_csv(path: Path) -> Tables:
    """Load CSV/TSV into a single table named after the file stem."""
    text = read_text(path)
    # Tab-delimited TSV files get sniffed as such if their ext says so.
    dialect: Any = "excel-tab" if path.suffix.lower() == ".tsv" else "excel"
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    return {path.stem: [dict(r) for r in reader]}


def write_csv(tables: Tables, out_path: Path) -> List[Path]:
    """Write each table as a CSV file. Multi-table => suffixed filenames."""
    multi = len(tables) > 1
    written: List[Path] = []
    for name, rows in tables.items():
        target = (
            out_path.with_name(f"{out_path.stem}.{name}{out_path.suffix}")
            if multi
            else out_path
        )
        cols = _columns(rows)
        with target.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=cols)
            writer.writeheader()
            for row in rows:
                writer.writerow({c: _flat(row.get(c)) for c in cols})
        written.append(target)
    return written


# ------------------------------- JSON -------------------------------------- #


def load_json(path: Path) -> Tables:
    """Accept a list of dicts, a dict of tables, or a single object."""
    return _as_tables(json.loads(read_text(path)), path.stem)


def write_json(tables: Tables, out_path: Path) -> List[Path]:
    """Single table -> flat list; multiple tables -> {name: [...]}."""
    payload: Any = next(iter(tables.values())) if len(tables) == 1 else tables
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return [out_path]


# ---------------------------- JSON Lines ----------------------------------- #


def load_jsonl(path: Path) -> Tables:
    """One JSON object per line — streams naturally."""
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            rows.append(obj if isinstance(obj, dict) else {"value": obj})
    return {path.stem: rows}


def write_jsonl(tables: Tables, out_path: Path) -> List[Path]:
    """JSONL only supports a single table; flatten the first one."""
    name, rows = next(iter(tables.items()))
    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return [out_path]


# ------------------------------- SQLite ------------------------------------ #


def load_db(path: Path) -> Tables:
    """Open SQLite read-only, mmap it if large, and read every table."""
    size = path.stat().st_size
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        if size > MMAP_THRESHOLD:
            logger.debug(f"sqlite mmap_size for {path} ({size / 1_048_576:.1f} MB)")
            con.execute(f"PRAGMA mmap_size={size}")
        names = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        out: Tables = {}
        for name in names:
            out[name] = [dict(r) for r in con.execute(f'SELECT * FROM "{name}"')]
        return out
    finally:
        con.close()


def write_db(tables: Tables, out_path: Path) -> List[Path]:
    """Create a fresh SQLite file. Types are inferred per column."""
    if out_path.exists():
        out_path.unlink()
    con = sqlite3.connect(out_path)
    try:
        for name, rows in tables.items():
            cols = _columns(rows)
            if not cols:
                logger.warning(f"skipping empty table {name!r}")
                continue
            types = {c: _infer_sql_type([r.get(c) for r in rows]) for c in cols}
            col_defs = ", ".join(f'"{c}" {types[c]}' for c in cols)
            con.execute(f'CREATE TABLE "{name}" ({col_defs})')
            placeholders = ", ".join("?" * len(cols))
            con.executemany(
                f'INSERT INTO "{name}" VALUES ({placeholders})',
                [[_sqlite_val(r.get(c)) for c in cols] for r in rows],
            )
        con.commit()
    finally:
        con.close()
    return [out_path]


# ------------------------------ SQL dump ----------------------------------- #

# Regexes for the (necessarily heuristic) SQL parser.
_CREATE_RE = re.compile(
    r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\[\]]?(\w+)[`"\[\]]?\s*\(',
    re.I,
)
_INSERT_RE = re.compile(
    r'INSERT\s+(?:OR\s+\w+\s+)?INTO\s+[`"\[\]]?(\w+)[`"\[\]]?\s*'
    r"(?:\(([^)]*)\))?\s*VALUES\s*",
    re.I,
)
_NON_COLUMN_KEYWORDS = {
    "PRIMARY",
    "FOREIGN",
    "UNIQUE",
    "CHECK",
    "CONSTRAINT",
    "KEY",
    "INDEX",
}


def _split_top_level(s: str) -> List[str]:
    """Split on commas at paren depth 0 (respecting quoted strings)."""
    parts: List[str] = []
    cur: List[str] = []
    depth = 0
    in_str = False
    quote = ""
    for ch in s:
        if in_str:
            cur.append(ch)
            if ch == quote:
                in_str = False
        elif ch in "'\"":
            in_str, quote = True, ch
            cur.append(ch)
        elif ch == "(":
            depth += 1
            cur.append(ch)
        elif ch == ")":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return parts


def _iter_create_tables(text: str):
    """Yield (table_name, body) for each CREATE TABLE, honoring nesting."""
    for m in _CREATE_RE.finditer(text):
        name = m.group(1)
        i, depth, start = m.end(), 1, m.end()
        in_str, quote = False, ""
        while i < len(text) and depth:
            c = text[i]
            if in_str:
                if c == "\\":
                    i += 2
                    continue
                if c == quote:
                    in_str = False
            elif c in "'\"":
                in_str, quote = True, c
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            i += 1
        yield name, text[start : i - 1]


def _iter_inserts(text: str):
    """Yield (table, column_list_or_None, raw_values_string)."""
    for m in _INSERT_RE.finditer(text):
        name = m.group(1)
        cols = m.group(2)
        i, depth, start = m.end(), 0, m.end()
        in_str, quote = False, ""
        while i < len(text):
            c = text[i]
            if in_str:
                if c == "\\" and quote == "'":
                    i += 2
                    continue
                if c == quote:
                    if i + 1 < len(text) and text[i + 1] == quote:
                        i += 2
                        continue
                    in_str = False
                i += 1
            elif c in "'\"":
                in_str, quote = True, c
                i += 1
            elif c == "(":
                depth += 1
                i += 1
            elif c == ")":
                depth -= 1
                i += 1
            elif c == ";" and depth == 0:
                break
            else:
                i += 1
        yield name, cols, text[start:i]


def _convert_sql_value(tok: str) -> Any:
    """Turn one SQL literal token into a python value."""
    if tok == "":
        return None
    upper = tok.upper()
    if upper == "NULL":
        return None
    if upper == "TRUE":
        return True
    if upper == "FALSE":
        return False
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "'\"":
        q = tok[0]
        return tok[1:-1].replace(q + q, q)
    try:
        return int(tok)
    except ValueError:
        pass
    try:
        return float(tok)
    except ValueError:
        pass
    return tok


def _parse_value_tuples(raw: str) -> List[List[Any]]:
    """Parse `(1,'a',NULL),(2,'b',NULL)` into python rows."""
    rows: List[List[Any]] = []
    i, n = 0, len(raw)
    while i < n:
        while i < n and raw[i] in " \t\r\n,":
            i += 1
        if i >= n or raw[i] != "(":
            break
        i += 1
        row: List[str] = []
        cur: List[str] = []
        in_str, quote = False, ""
        while i < n:
            c = raw[i]
            if in_str:
                if c == "\\" and quote == "'" and i + 1 < n:
                    nxt = raw[i + 1]
                    cur.append(
                        {"n": "\n", "t": "\t", "r": "\r", "0": "\0"}.get(nxt, nxt)
                    )
                    i += 2
                    continue
                if c == quote:
                    if i + 1 < n and raw[i + 1] == quote:
                        cur.append(c)
                        i += 2
                        continue
                    in_str = False
                    cur.append(c)
                    i += 1
                    continue
                cur.append(c)
                i += 1
            else:
                if c in "'\"":
                    in_str, quote = True, c
                    cur.append(c)
                    i += 1
                elif c == ",":
                    row.append("".join(cur).strip())
                    cur = []
                    i += 1
                elif c == ")":
                    row.append("".join(cur).strip())
                    i += 1
                    break
                else:
                    cur.append(c)
                    i += 1
        rows.append([_convert_sql_value(v) for v in row])
    return rows


def load_sql(path: Path) -> Tables:
    """Extract CREATE/INSERT statements into Tables (heuristic but robust)."""
    text = read_text(path)
    # Strip comments so our regexes don't trip over them.
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"^\s*--.*$", "", text, flags=re.M)
    text = re.sub(r"^\s*#.*$", "", text, flags=re.M)

    tables: Tables = {}
    declared_cols: Dict[str, List[str]] = {}

    for name, body in _iter_create_tables(text):
        cols: List[str] = []
        for part in _split_top_level(body):
            part = part.strip()
            if not part:
                continue
            head = part.split()[0].strip('`"[]')
            if head.upper() in _NON_COLUMN_KEYWORDS:
                continue
            cols.append(head)
        declared_cols[name] = cols
        tables.setdefault(name, [])

    for name, col_list, raw_values in _iter_inserts(text):
        if col_list:
            cols = [c.strip().strip('`"[]') for c in col_list.split(",")]
        else:
            cols = list(declared_cols.get(name, []))

        for values in _parse_value_tuples(raw_values):
            if not cols:
                cols = [f"c{i}" for i in range(len(values))]
                declared_cols[name] = cols
            tables.setdefault(name, []).append(dict(zip(cols, values)))

    return tables


def write_sql(tables: Tables, out_path: Path) -> List[Path]:
    """Emit a portable CREATE + INSERT dump."""
    lines: List[str] = ["-- generated by dataconv.py", ""]
    for name, rows in tables.items():
        cols = _columns(rows)
        if not cols:
            continue
        types = {c: _infer_sql_type([r.get(c) for r in rows]) for c in cols}
        col_defs = ", ".join(f'"{c}" {types[c]}' for c in cols)
        lines.append(f'CREATE TABLE IF NOT EXISTS "{name}" ({col_defs});')
        col_list = ", ".join(f'"{c}"' for c in cols)
        for row in rows:
            values = ", ".join(_sql_literal(row.get(c)) for c in cols)
            lines.append(f'INSERT INTO "{name}" ({col_list}) VALUES ({values});')
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return [out_path]


# =========================================================================== #
# EXCEL & FRIENDS: xlsx / xls / xlsm / xlsb / ods
# =========================================================================== #


def load_xlsx(path: Path) -> Tables:
    """openpyxl handles xlsx/xlsm (read-only, values-only for speed)."""
    openpyxl = _require("openpyxl")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out: Tables = {}
    try:
        for ws in wb.worksheets:
            rows_iter = ws.iter_rows(values_only=True)
            try:
                header = [
                    str(c) if c is not None else f"c{i}"
                    for i, c in enumerate(next(rows_iter))
                ]
            except StopIteration:
                out[ws.title] = []
                continue
            out[ws.title] = [dict(zip(header, r)) for r in rows_iter]
    finally:
        wb.close()
    return out


def load_xls(path: Path) -> Tables:
    """Legacy .xls — read-only via xlrd, and xlrd only supports xls."""
    xlrd = _require("xlrd")
    book = xlrd.open_workbook(path)
    out: Tables = {}
    for sheet in book.sheets():
        if sheet.nrows == 0:
            out[sheet.name] = []
            continue
        header = [str(sheet.cell_value(0, c)) for c in range(sheet.ncols)]
        out[sheet.name] = [
            {header[c]: sheet.cell_value(r, c) for c in range(sheet.ncols)}
            for r in range(1, sheet.nrows)
        ]
    return out


def load_xlsb(path: Path) -> Tables:
    """Binary Excel — pyxlsb for read."""
    pyxlsb = _require("pyxlsb")
    out: Tables = {}
    with pyxlsb.open_workbook(path) as wb:
        for name in wb.sheets:
            with wb.get_sheet(name) as sheet:
                rows_iter = sheet.rows()
                try:
                    header = [
                        str(c.v) if c.v is not None else f"c{i}"
                        for i, c in enumerate(next(rows_iter))
                    ]
                except StopIteration:
                    out[name] = []
                    continue
                out[name] = [
                    {header[i]: c.v for i, c in enumerate(row)} for row in rows_iter
                ]
    return out


def load_ods(path: Path) -> Tables:
    """OpenDocument Spreadsheet via odfpy (pulls the XML apart manually)."""
    odf = _require("odf.opendocument")
    table_mod = _require("odf.table")
    text_mod = _require("odf.text")

    doc = odf.load(path)
    out: Tables = {}
    for sheet in doc.spreadsheet.getElementsByType(table_mod.Table):
        name = sheet.getAttribute("name") or f"sheet{len(out)}"
        rows_out: List[Dict[str, Any]] = []
        header: Optional[List[str]] = None
        for row in sheet.getElementsByType(table_mod.TableRow):
            cells = row.getElementsByType(table_mod.TableCell)
            # Expand number-columns-repeated for correctness.
            values: List[Any] = []
            for cell in cells:
                repeat = int(cell.getAttribute("numbercolumnsrepeated") or 1)
                p = cell.getElementsByType(text_mod.P)
                text = "".join(node.data for node in p[0].childNodes) if p else ""
                values.extend([text] * repeat)
            if header is None:
                header = [str(v) if v != "" else f"c{i}" for i, v in enumerate(values)]
                continue
            rows_out.append(
                {
                    header[i] if i < len(header) else f"c{i}": v
                    for i, v in enumerate(values)
                }
            )
        out[name] = rows_out
    return out


def write_xlsx(tables: Tables, out_path: Path) -> List[Path]:
    """One sheet per table; sheet names truncated to Excel's 31-char limit."""
    openpyxl = _require("openpyxl")
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in tables.items():
        ws = wb.create_sheet(title=name[:31])
        cols = _columns(rows)
        ws.append(cols)
        for row in rows:
            ws.append([_flat(row.get(c)) for c in cols])
    wb.save(out_path)
    return [out_path]


def write_ods(tables: Tables, out_path: Path) -> List[Path]:
    """Write one OpenDocument Spreadsheet with a sheet per table."""
    odf_opendoc = _require("odf.opendocument")
    table_mod = _require("odf.table")
    text_mod = _require("odf.text")

    doc = odf_opendoc.OpenDocumentSpreadsheet()
    for name, rows in tables.items():
        sheet = table_mod.Table(name=name[:31])
        cols = _columns(rows)
        header_row = table_mod.TableRow()
        for c in cols:
            cell = table_mod.TableCell(valuetype="string")
            cell.addElement(text_mod.P(text=str(c)))
            header_row.addElement(cell)
        sheet.addElement(header_row)
        for row in rows:
            tr = table_mod.TableRow()
            for c in cols:
                v = _flat(row.get(c))
                cell = table_mod.TableCell(valuetype="string")
                cell.addElement(text_mod.P(text="" if v is None else str(v)))
                tr.addElement(cell)
            sheet.addElement(tr)
        doc.spreadsheet.addElement(sheet)
    doc.save(str(out_path).rsplit(".", 1)[0])
    # odfpy appends the .ods extension itself
    return [Path(str(out_path).rsplit(".", 1)[0] + ".ods")]


# =========================================================================== #
# COLUMNAR: parquet / feather / orc / arrow
# =========================================================================== #


def load_parquet(path: Path) -> Tables:
    """pyarrow-backed parquet read (single table per file)."""
    pq = _require("pyarrow.parquet")
    return {path.stem: pq.read_table(path).to_pylist()}


def write_parquet(tables: Tables, out_path: Path) -> List[Path]:
    """Snappy-compressed parquet. Multiple tables => separate files."""
    pa = _require("pyarrow")
    pq = _require("pyarrow.parquet")
    multi = len(tables) > 1
    written: List[Path] = []
    for name, rows in tables.items():
        cols = _columns(rows)
        arrays = {c: [r.get(c) for r in rows] for c in cols}
        tbl = pa.table(arrays)
        target = (
            out_path.with_name(f"{out_path.stem}.{name}{out_path.suffix}")
            if multi
            else out_path
        )
        pq.write_table(tbl, target, compression="snappy")
        written.append(target)
    return written


def load_feather(path: Path) -> Tables:
    """Arrow Feather v2 via pyarrow."""
    feather = _require("pyarrow.feather")
    return {path.stem: feather.read_table(path).to_pylist()}


def write_feather(tables: Tables, out_path: Path) -> List[Path]:
    """Feather supports a single table; use the first."""
    pa = _require("pyarrow")
    feather = _require("pyarrow.feather")
    name, rows = next(iter(tables.items()))
    cols = _columns(rows)
    arrays = {c: [r.get(c) for r in rows] for c in cols}
    feather.write_feather(pa.table(arrays), out_path, compression="lz4")
    return [out_path]


def load_orc(path: Path) -> Tables:
    """Apache ORC via pyarrow."""
    orc = _require("pyarrow.orc")
    return {path.stem: orc.read_table(path).to_pylist()}


def write_orc(tables: Tables, out_path: Path) -> List[Path]:
    """ORC single-table only."""
    pa = _require("pyarrow")
    orc = _require("pyarrow.orc")
    _, rows = next(iter(tables.items()))
    cols = _columns(rows)
    arrays = {c: [r.get(c) for r in rows] for c in cols}
    orc.write_table(pa.table(arrays), out_path)
    return [out_path]


def load_arrow(path: Path) -> Tables:
    """Arrow IPC file format."""
    ipc = _require("pyarrow.ipc")
    ipc_feather = _require("pyarrow.feather")  # not used, just ensures dep
    with path.open("rb") as fh:
        reader = ipc.open_file(fh)
        return {path.stem: reader.read_all().to_pylist()}


def write_arrow(tables: Tables, out_path: Path) -> List[Path]:
    """Arrow IPC file format."""
    pa = _require("pyarrow")
    ipc = _require("pyarrow.ipc")
    _, rows = next(iter(tables.items()))
    cols = _columns(rows)
    arrays = {c: [r.get(c) for r in rows] for c in cols}
    tbl = pa.table(arrays)
    with out_path.open("wb") as fh:
        with ipc.new_file(fh, tbl.schema) as writer:
            writer.write_table(tbl)
    return [out_path]


# =========================================================================== #
# SERIALIZATION: yaml / toml / xml / pickle / msgpack / avro / bson
# =========================================================================== #


def load_yaml(path: Path) -> Tables:
    yaml = _require("yaml")
    return _as_tables(yaml.safe_load(read_text(path)), path.stem)


def write_yaml(tables: Tables, out_path: Path) -> List[Path]:
    yaml = _require("yaml")
    payload = next(iter(tables.values())) if len(tables) == 1 else tables
    out_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return [out_path]


def load_toml(path: Path) -> Tables:
    """tomllib is stdlib on 3.11+; tomli for older versions."""
    try:
        import tomllib as toml_mod  # py3.11+
    except ImportError:
        toml_mod = _require("tomli")
    return _as_tables(toml_mod.loads(read_text(path)), path.stem)


def write_toml(tables: Tables, out_path: Path) -> List[Path]:
    tomli_w = _require("tomli_w")
    payload = next(iter(tables.values())) if len(tables) == 1 else tables
    out_path.write_bytes(tomli_w.dumps(payload))
    return [out_path]


def load_xml(path: Path) -> Tables:
    """
    Simple XML: expects <root><row><col>v</col>...</row></root> or
    <table>...</table> wrappers. Not a general-purpose XML mapper.
    """
    ET = _require("xml.etree.ElementTree")
    tree = ET.parse(path)
    root = tree.getroot()

    # <data><table1>...</table1><table2>...</table2></data> pattern.
    if any(child.tag != "row" for child in root):
        out: Tables = {}
        for child in root:
            rows: List[Dict[str, Any]] = []
            for r in child:
                rows.append({sub.tag: sub.text for sub in r})
            out[child.tag] = rows
        return out

    # Flat <root><row>...</row></root>
    rows = []
    for child in root:
        rows.append({sub.tag: sub.text for sub in child})
    return {path.stem: rows}


def write_xml(tables: Tables, out_path: Path) -> List[Path]:
    ET = _require("xml.etree.ElementTree")
    root = ET.Element("data")
    for name, rows in tables.items():
        tbl = ET.SubElement(root, name)
        cols = _columns(rows)
        for row in rows:
            r = ET.SubElement(tbl, "row")
            for c in cols:
                v = row.get(c)
                el = ET.SubElement(r, c)
                el.text = "" if v is None else str(v)
    ET.ElementTree(root).write(out_path, encoding="utf-8", xml_declaration=True)
    return [out_path]


def load_pickle(path: Path) -> Tables:
    import pickle

    return _as_tables(pickle.loads(path.read_bytes()), path.stem)


def write_pickle(tables: Tables, out_path: Path) -> List[Path]:
    import pickle

    payload = next(iter(tables.values())) if len(tables) == 1 else tables
    out_path.write_bytes(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
    return [out_path]


def load_msgpack(path: Path) -> Tables:
    msgpack = _require("msgpack")
    data = msgpack.unpackb(path.read_bytes(), raw=False)
    return _as_tables(data, path.stem)


def write_msgpack(tables: Tables, out_path: Path) -> List[Path]:
    msgpack = _require("msgpack")
    payload = next(iter(tables.values())) if len(tables) == 1 else tables
    out_path.write_bytes(msgpack.packb(payload, use_bin_type=True))
    return [out_path]


def load_avro(path: Path) -> Tables:
    fastavro = _require("fastavro")
    with path.open("rb") as fh:
        return {path.stem: list(fastavro.reader(fh))}


def write_avro(tables: Tables, out_path: Path) -> List[Path]:
    """Avro schema is inferred (nullable union) from the first rows."""
    fastavro = _require("fastavro")
    name, rows = next(iter(tables.items()))
    if not rows:
        raise ValueError("cannot infer Avro schema from empty table")
    fields = []
    for c in _columns(rows):
        sample = next((r.get(c) for r in rows if r.get(c) is not None), None)
        if isinstance(sample, bool):
            ftype = "boolean"
        elif isinstance(sample, int):
            ftype = "long"
        elif isinstance(sample, float):
            ftype = "double"
        else:
            ftype = "string"
        fields.append({"name": c, "type": ["null", ftype], "default": None})
    schema = {"type": "record", "name": name, "fields": fields}
    with out_path.open("wb") as fh:
        fastavro.writer(fh, schema, rows)
    return [out_path]


def load_bson(path: Path) -> Tables:
    """MongoDB BSON documents concatenated in one file."""
    bson_mod = _require("bson")
    data = path.read_bytes()
    rows = list(bson_mod.decode_all(data))
    return _as_tables(rows, path.stem)


def write_bson(tables: Tables, out_path: Path) -> List[Path]:
    bson_mod = _require("bson")
    _, rows = next(iter(tables.items()))
    with out_path.open("wb") as fh:
        for row in rows:
            fh.write(bson_mod.encode(row))
    return [out_path]


# =========================================================================== #
# STATISTICS / SCIENTIFIC: hdf5 / netcdf / zarr / rds / dta / sav / sas7bdat
# =========================================================================== #


def load_hdf5(path: Path) -> Tables:
    """
    HDF5: each top-level key that behaves like a table becomes a Table.
    Uses pandas' HDFStore so we can read whatever PyTables stored.
    """
    pd = _require("pandas")
    out: Tables = {}
    with pd.HDFStore(path, mode="r") as store:
        for key in store.keys():
            clean = key.lstrip("/")
            df = store.get(key)
            out[clean] = df.to_dict(orient="records")
    return out


def write_hdf5(tables: Tables, out_path: Path) -> List[Path]:
    """Each table becomes a key in a fresh HDF5 file."""
    pd = _require("pandas")
    _require("tables")  # PyTables is needed for HDFStore
    with pd.HDFStore(out_path, mode="w") as store:
        for name, rows in tables.items():
            store.put(name, pd.DataFrame(rows), format="table")
    return [out_path]


def load_netcdf(path: Path) -> Tables:
    """NetCDF via xarray; each data variable becomes a flattened table."""
    xr = _require("xarray")
    ds = xr.open_dataset(path)
    try:
        return {
            var: ds[var].to_dataframe().reset_index().to_dict("records")
            for var in ds.data_vars
        }
    finally:
        ds.close()


def write_netcdf(tables: Tables, out_path: Path) -> List[Path]:
    """Write each table as a data variable inside one NetCDF file."""
    xr = _require("xarray")
    pd = _require("pandas")
    ds = xr.Dataset()
    for name, rows in tables.items():
        df = pd.DataFrame(rows)
        ds[name] = xr.DataArray(df.values, dims=[f"{name}_i", f"{name}_j"])
    ds.to_netcdf(out_path)
    return [out_path]


def load_zarr(path: Path) -> Tables:
    """Zarr via xarray; treats each data variable as a table."""
    xr = _require("xarray")
    ds = xr.open_zarr(path)
    try:
        return {
            var: ds[var].to_dataframe().reset_index().to_dict("records")
            for var in ds.data_vars
        }
    finally:
        ds.close()


def write_zarr(tables: Tables, out_path: Path) -> List[Path]:
    xr = _require("xarray")
    pd = _require("pandas")
    ds = xr.Dataset()
    for name, rows in tables.items():
        df = pd.DataFrame(rows)
        ds[name] = xr.DataArray(df.values, dims=[f"{name}_i", f"{name}_j"])
    ds.to_zarr(out_path, mode="w")
    return [out_path]


def load_rds(path: Path) -> Tables:
    """R data files (.rds / .rdata) via pyreadr."""
    pyreadr = _require("pyreadr")
    result = pyreadr.read_r(str(path))
    return {name: df.to_dict(orient="records") for name, df in result.items()}


def write_rds(tables: Tables, out_path: Path) -> List[Path]:
    """Write a single-table RDS via pyreadr (multi-table unsupported)."""
    pyreadr = _require("pyreadr")
    pd = _require("pandas")
    _, rows = next(iter(tables.items()))
    pyreadr.write_rds(str(out_path), pd.DataFrame(rows))
    return [out_path]


def load_dta(path: Path) -> Tables:
    """Stata .dta via pandas."""
    pd = _require("pandas")
    df = pd.read_stata(path)
    return {path.stem: df.to_dict(orient="records")}


def write_dta(tables: Tables, out_path: Path) -> List[Path]:
    """Stata .dta via pandas (single table only)."""
    pd = _require("pandas")
    _, rows = next(iter(tables.items()))
    pd.DataFrame(rows).to_stata(out_path)
    return [out_path]


def load_sav(path: Path) -> Tables:
    """SPSS .sav via pyreadstat."""
    pyreadstat = _require("pyreadstat")
    df, _meta = pyreadstat.read_sav(str(path))
    return {path.stem: df.to_dict(orient="records")}


def load_sas7bdat(path: Path) -> Tables:
    """SAS .sas7bdat via pyreadstat."""
    pyreadstat = _require("pyreadstat")
    df, _meta = pyreadstat.read_sas7bdat(str(path))
    return {path.stem: df.to_dict(orient="records")}


# =========================================================================== #
# DBF / dBASE
# =========================================================================== #


def load_dbf(path: Path) -> Tables:
    dbfread = _require("dbfread")
    return {path.stem: [dict(r) for r in dbfread.DBF(str(path))]}


def write_dbf(tables: Tables, out_path: Path) -> List[Path]:
    """dbf only supports a single table; use the first one."""
    dbf = _require("dbf")
    _, rows = next(iter(tables.items()))
    if not rows:
        raise ValueError("cannot write an empty dbf")
    cols = _columns(rows)
    table = dbf.Table(str(out_path), " ".join(f"{c} C(254)" for c in cols))
    table.open(dbf.READ_WRITE)
    try:
        for row in rows:
            table.append(
                tuple("" if row.get(c) is None else str(row.get(c)) for c in cols)
            )
    finally:
        table.close()
    return [out_path]


# =========================================================================== #
# GEO: geojson / shapefile (attribute tables only, geometry as WKT)
# =========================================================================== #


def _geo_to_tables(gdf) -> Tables:
    """
    Convert a GeoDataFrame to Tables. Geometry becomes WKT; that keeps
    the data JSON/CSV-friendly at the cost of losing spatial semantics.
    """
    df = gdf.copy()
    if "geometry" in df.columns:
        df["geometry"] = df["geometry"].apply(
            lambda g: g.wkt if g is not None else None
        )
    return {df.attrs.get("name", "features"): df.to_dict(orient="records")}


def load_geojson(path: Path) -> Tables:
    gpd = _require("geopandas")
    gdf = gpd.read_file(path)
    gdf.attrs["name"] = path.stem
    return _geo_to_tables(gdf)


def write_geojson(tables: Tables, out_path: Path) -> List[Path]:
    """
    Best-effort: if a 'geometry' column of WKT strings exists we rebuild
    the geometry and emit true GeoJSON; otherwise we emit a FeatureCollection
    with null geometries so the properties round-trip losslessly.
    """
    gpd = _require("geopandas")
    shapely_wkt = _require("shapely.wkt")
    _, rows = next(iter(tables.items()))
    df = _geo = None  # placeholder for linters
    import pandas as pd

    df = pd.DataFrame(rows)
    if "geometry" in df.columns:
        df["geometry"] = df["geometry"].apply(
            lambda w: shapely_wkt.loads(w) if isinstance(w, str) and w else None
        )
        gdf = gpd.GeoDataFrame(df, geometry="geometry")
    else:
        gdf = gpd.GeoDataFrame(
            df, geometry=gpd.points_from_xy([0] * len(df), [0] * len(df))
        )
    gdf.to_file(out_path, driver="GeoJSON")
    return [out_path]


def load_shapefile(path: Path) -> Tables:
    gpd = _require("geopandas")
    gdf = gpd.read_file(path)
    gdf.attrs["name"] = path.stem
    return _geo_to_tables(gdf)


def write_shapefile(tables: Tables, out_path: Path) -> List[Path]:
    """Shapefiles always carry at least a stub geometry column."""
    gpd = _require("geopandas")
    shapely_wkt = _require("shapely.wkt")
    import pandas as pd

    _, rows = next(iter(tables.items()))
    df = pd.DataFrame(rows)
    if "geometry" in df.columns:
        df["geometry"] = df["geometry"].apply(
            lambda w: shapely_wkt.loads(w) if isinstance(w, str) and w else None
        )
        gdf = gpd.GeoDataFrame(df, geometry="geometry")
    else:
        gdf = gpd.GeoDataFrame(
            df, geometry=gpd.points_from_xy([0] * len(df), [0] * len(df))
        )
    gdf.to_file(out_path)
    return [out_path]


# =========================================================================== #
# MISC: ini, fixed-width
# =========================================================================== #


def load_ini(path: Path) -> Tables:
    """INI: each [section] becomes a table with key/value rows."""
    import configparser

    cp = configparser.ConfigParser()
    cp.read(path)
    out: Tables = {}
    for section in cp.sections():
        out[section] = [{"key": k, "value": v} for k, v in cp.items(section)]
    return out


def write_ini(tables: Tables, out_path: Path) -> List[Path]:
    """INI writer expects tables whose rows have 'key' and 'value' columns."""
    import configparser

    cp = configparser.ConfigParser()
    for name, rows in tables.items():
        cp[name] = {
            str(r.get("key")): str(r.get("value", ""))
            for r in rows
            if r.get("key") is not None
        }
    with out_path.open("w", encoding="utf-8") as fh:
        cp.write(fh)
    return [out_path]


def load_fixed_width(path: Path) -> Tables:
    """
    Fixed-width loader: expects a sibling `<name>.schema.json` file that
    describes column widths:
        {"columns": [{"name": "id", "width": 5}, ...]}
    """
    schema_path = path.with_suffix(path.suffix + ".schema.json")
    if not schema_path.exists():
        raise ValueError(f"fixed-width '{path}' requires a schema at {schema_path}")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    columns = schema["columns"]

    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            pos = 0
            row: Dict[str, Any] = {}
            for c in columns:
                w = int(c["width"])
                row[c["name"]] = line[pos : pos + w].strip()
                pos += w
            rows.append(row)
    return {path.stem: rows}


def write_fixed_width(tables: Tables, out_path: Path) -> List[Path]:
    """
    Fixed-width writer: emits data + a schema sidecar file next to it.
    """
    _, rows = next(iter(tables.items()))
    cols = _columns(rows)
    # Compute widths from the longest rendered value per column.
    widths = {}
    for c in cols:
        widths[c] = max([len(str(c))] + [len(str(row.get(c, ""))) for row in rows])
    schema = {"columns": [{"name": c, "width": widths[c]} for c in cols]}
    schema_path = out_path.with_suffix(out_path.suffix + ".schema.json")
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    with out_path.open("w", encoding="utf-8") as fh:
        fh.write("".join(str(c).ljust(widths[c]) for c in cols) + "\n")
        for row in rows:
            fh.write("".join(str(row.get(c, "")).ljust(widths[c]) for c in cols) + "\n")
    return [out_path, schema_path]


# =========================================================================== #
# DISPATCH TABLES
# =========================================================================== #

# Every extension we recognize -> canonical format id.
EXT_TO_FMT: Dict[str, str] = {
    # core
    ".csv": "csv",
    ".tsv": "csv",
    ".json": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".db": "db",
    ".sqlite": "db",
    ".sqlite3": "db",
    ".sql": "sql",
    # excel-family
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".xls": "xls",
    ".xlsb": "xlsb",
    ".ods": "ods",
    # columnar
    ".parquet": "parquet",
    ".pq": "parquet",
    ".feather": "feather",
    ".orc": "orc",
    ".arrow": "arrow",
    ".ipc": "arrow",
    # serialization
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".pkl": "pickle",
    ".pickle": "pickle",
    ".msgpack": "msgpack",
    ".mp": "msgpack",
    ".avro": "avro",
    ".bson": "bson",
    # scientific
    ".h5": "hdf5",
    ".hdf5": "hdf5",
    ".nc": "netcdf",
    ".nc4": "netcdf",
    ".zarr": "zarr",
    ".rds": "rds",
    ".rdata": "rds",
    ".dta": "dta",
    ".sav": "sav",
    ".sas7bdat": "sas7bdat",
    # dbase
    ".dbf": "dbf",
    # geo
    ".geojson": "geojson",
    ".shp": "shapefile",
    # misc
    ".ini": "ini",
    ".fw": "fixedwidth",
    ".fixed": "fixedwidth",
}

# Reverse mapping for choosing output filenames.
FMT_TO_EXT: Dict[str, str] = {
    "csv": ".csv",
    "json": ".json",
    "jsonl": ".jsonl",
    "db": ".db",
    "sql": ".sql",
    "xlsx": ".xlsx",
    "xls": ".xls",
    "xlsb": ".xlsb",
    "ods": ".ods",
    "parquet": ".parquet",
    "feather": ".feather",
    "orc": ".orc",
    "arrow": ".arrow",
    "yaml": ".yaml",
    "toml": ".toml",
    "xml": ".xml",
    "pickle": ".pkl",
    "msgpack": ".msgpack",
    "avro": ".avro",
    "bson": ".bson",
    "hdf5": ".h5",
    "netcdf": ".nc",
    "zarr": ".zarr",
    "rds": ".rds",
    "dta": ".dta",
    "sav": ".sav",
    "sas7bdat": ".sas7bdat",
    "dbf": ".dbf",
    "geojson": ".geojson",
    "shapefile": ".shp",
    "ini": ".ini",
    "fixedwidth": ".fw",
}

# Registered loaders/writers. Formats not present here are read-only
# or write-only (e.g. xls and sas7bdat can be read but not written).
LOADERS: Dict[str, Callable[[Path], Tables]] = {
    # core
    "csv": load_csv,
    "json": load_json,
    "jsonl": load_jsonl,
    "db": load_db,
    "sql": load_sql,
    # excel
    "xlsx": load_xlsx,
    "xls": load_xls,
    "xlsb": load_xlsb,
    "ods": load_ods,
    # columnar
    "parquet": load_parquet,
    "feather": load_feather,
    "orc": load_orc,
    "arrow": load_arrow,
    # serialization
    "yaml": load_yaml,
    "toml": load_toml,
    "xml": load_xml,
    "pickle": load_pickle,
    "msgpack": load_msgpack,
    "avro": load_avro,
    "bson": load_bson,
    # scientific
    "hdf5": load_hdf5,
    "netcdf": load_netcdf,
    "zarr": load_zarr,
    "rds": load_rds,
    "dta": load_dta,
    "sav": load_sav,
    "sas7bdat": load_sas7bdat,
    # dbase
    "dbf": load_dbf,
    # geo
    "geojson": load_geojson,
    "shapefile": load_shapefile,
    # misc
    "ini": load_ini,
    "fixedwidth": load_fixed_width,
}

WRITERS: Dict[str, Callable[[Tables, Path], List[Path]]] = {
    # core
    "csv": write_csv,
    "json": write_json,
    "jsonl": write_jsonl,
    "db": write_db,
    "sql": write_sql,
    # excel
    "xlsx": write_xlsx,
    "ods": write_ods,
    # columnar
    "parquet": write_parquet,
    "feather": write_feather,
    "orc": write_orc,
    "arrow": write_arrow,
    # serialization
    "yaml": write_yaml,
    "toml": write_toml,
    "xml": write_xml,
    "pickle": write_pickle,
    "msgpack": write_msgpack,
    "avro": write_avro,
    "bson": write_bson,
    # scientific
    "hdf5": write_hdf5,
    "netcdf": write_netcdf,
    "zarr": write_zarr,
    "rds": write_rds,
    "dta": write_dta,
    # dbase
    "dbf": write_dbf,
    # geo
    "geojson": write_geojson,
    "shapefile": write_shapefile,
    # misc
    "ini": write_ini,
    "fixedwidth": write_fixed_width,
}


# --------------------------------------------------------------------------- #
# Job plumbing (module-level so multiprocessing can pickle it)
# --------------------------------------------------------------------------- #


def _output_path(src: Path, target_fmt: str, out_dir: Optional[Path]) -> Path:
    """Compute an output path preserving the input stem."""
    name = src.stem + FMT_TO_EXT[target_fmt]
    return (out_dir / name) if out_dir else src.with_name(name)


def convert_job(
    job: Tuple[str, str, Optional[str]],
) -> Tuple[str, bool, List[str], str]:
    """
    Worker entry point:
    (source_path, target_format, output_dir_or_None)
        -> (source_path, ok, [output_paths], message)
    """
    src_str, target_fmt, out_dir_str = job
    src = Path(src_str)
    try:
        src_fmt = detect_format(src)
        if src_fmt is None:
            raise ValueError(f"unsupported input extension {src.suffix!r}")
        if src_fmt not in LOADERS:
            raise ValueError(f"format {src_fmt!r} is write-only, cannot read")
        if target_fmt not in WRITERS:
            raise ValueError(f"format {target_fmt!r} is read-only, cannot write")
        if src_fmt == target_fmt:
            return src_str, True, [], f"skipped: already {target_fmt}"

        logger.info(f"{src} [{src_fmt}] -> {target_fmt}")
        tables = LOADERS[src_fmt](src)
        if not tables:
            raise ValueError("no tables / rows found in input")

        out_path = _output_path(
            src, target_fmt, Path(out_dir_str) if out_dir_str else None
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        written = WRITERS[target_fmt](tables, out_path)
        return src_str, True, [str(p) for p in written], "ok"
    except Exception as exc:  # noqa: BLE001 - report everything
        logger.exception(f"failed to convert {src}")
        return src_str, False, [], f"{type(exc).__name__}: {exc}"


def detect_format(path: Path) -> Optional[str]:
    """Extension-based format detection, case insensitive."""
    return EXT_TO_FMT.get(path.suffix.lower())


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dataconv",
        description="Convert between CSV, JSON, SQLite, SQL, Excel, Parquet, "
        "YAML, XML, Avro, HDF5, NetCDF, GeoJSON, and many more.",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    # Only expose target formats that have a writer. Read-only formats
    # (xls, sav, sas7bdat) are intentionally not offered as outputs.
    for fmt in sorted(WRITERS.keys()):
        group.add_argument(f"--{fmt}", action="store_true", help=f"write {fmt} output")

    parser.add_argument("inputs", nargs="+", type=Path, help="input file(s)")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="directory for outputs (default: next to input)",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=os.cpu_count() or 1,
        help="parallel workers for multiple inputs",
    )
    return parser.parse_args(argv)


def _resolve_target(args: argparse.Namespace) -> str:
    """Which writer did the user ask for?"""
    for fmt in WRITERS:
        if getattr(args, fmt, False):
            return fmt
    raise SystemExit("no output format specified")


def main(argv: Optional[List[str]] = None) -> int:
    logger.remove()
    logger.add(sys.stderr, format="<level>{level: <8}</level> | {message}")

    args = parse_args(argv)
    target_fmt = _resolve_target(args)

    sources: List[Path] = []
    for p in args.inputs:
        if not p.exists():
            logger.error(f"input not found: {p}")
            continue
        if not p.is_file() and p.suffix.lower() != ".zarr":
            # zarr paths are directories, not files
            logger.error(f"not a file: {p}")
            continue
        sources.append(p)

    if not sources:
        logger.error("no usable inputs")
        return 2

    jobs = [
        (str(p), target_fmt, str(args.output_dir) if args.output_dir else None)
        for p in sources
    ]

    if len(jobs) > 1 and args.jobs > 1:
        workers = min(args.jobs, len(jobs))
        logger.info(f"converting {len(jobs)} files with {workers} workers")
        with Pool(processes=workers) as pool:
            results = pool.map(convert_job, jobs, chunksize=1)
    else:
        results = [convert_job(j) for j in jobs]

    failures = 0
    for src, ok, outputs, msg in results:
        if ok:
            if outputs:
                logger.success(f"{src} -> {', '.join(outputs)}")
            elif msg:
                logger.warning(f"{src}: {msg}")
        else:
            failures += 1
            logger.error(f"{src}: {msg}")

    logger.info(f"done: {len(results) - failures} ok, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
