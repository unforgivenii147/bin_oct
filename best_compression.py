#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import bz2
import gzip
import hashlib
import lzma
import multiprocessing as mp
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import brotli
import py7zr
import zstandard as zstd
from dh import fsz
from loguru import logger

try:
    import huffman as huffman_lib
except Exception:
    huffman_lib = None
_HASH_TABLE_SIZE = 1 << 14
_MAX_OFFSET_1 = 2047
_MAX_OFFSET_2 = 65535


def _encode_varint(value: int) -> bytes:
    result = bytearray()
    while value >= 128:
        result.append(value & 127 | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def _hash_4_bytes(data: bytes, pos: int) -> int:
    val = data[pos] | data[pos + 1] << 8 | data[pos + 2] << 16 | data[pos + 3] << 24
    return val * 406832829 >> 32 - 14 & _HASH_TABLE_SIZE - 1


def _emit_literal(output: bytearray, data: bytes, start: int, length: int) -> None:
    if length <= 0:
        return
    if length <= 60:
        output.append(length - 1 << 2)
    elif length <= 256:
        output.append(60 << 2)
        output.append(length - 1)
    elif length <= 65536:
        output.append(61 << 2)
        output.append(length - 1 & 255)
        output.append(length - 1 >> 8 & 255)
    elif length <= 16777216:
        output.append(62 << 2)
        output.append(length - 1 & 255)
        output.append(length - 1 >> 8 & 255)
        output.append(length - 1 >> 16 & 255)
    else:
        output.append(63 << 2)
        output.append(length - 1 & 255)
        output.append(length - 1 >> 8 & 255)
        output.append(length - 1 >> 16 & 255)
        output.append(length - 1 >> 24 & 255)
    output.extend(data[start : start + length])


def _emit_copy(output: bytearray, offset: int, length: int) -> None:
    while length > 0:
        if length >= 4 and length <= 11 and (offset <= _MAX_OFFSET_1):
            tag = 1 | length - 4 << 2 | offset >> 8 << 5
            output.append(tag)
            output.append(offset & 255)
            return
        if offset <= _MAX_OFFSET_2:
            copy_len = min(length, 64)
            tag = 2 | copy_len - 1 << 2
            output.append(tag)
            output.append(offset & 255)
            output.append(offset >> 8 & 255)
            length -= copy_len
        else:
            copy_len = min(length, 64)
            tag = 3 | copy_len - 1 << 2
            output.append(tag)
            output.append(offset & 255)
            output.append(offset >> 8 & 255)
            output.append(offset >> 16 & 255)
            output.append(offset >> 24 & 255)
            length -= copy_len


def compress(data: bytes) -> bytes:
    if not data:
        return _encode_varint(0)
    data_len = len(data)
    output = bytearray()
    output.extend(_encode_varint(data_len))
    if data_len < 4:
        _emit_literal(output, data, 0, data_len)
        return bytes(output)
    hash_table = [0] * _HASH_TABLE_SIZE
    pos = 0
    literal_start = 0
    while pos <= data_len - 4:
        h = _hash_4_bytes(data, pos)
        candidate = hash_table[h]
        hash_table[h] = pos
        if (
            (candidate > 0 or (candidate == 0 and pos > 0))
            and pos - candidate <= _MAX_OFFSET_2
            and (data[candidate : candidate + 4] == data[pos : pos + 4])
        ):
            if pos > literal_start:
                _emit_literal(output, data, literal_start, pos - literal_start)
            offset = pos - candidate
            match_len = 4
            max_match = min(data_len - pos, 64)
            while (
                match_len < max_match
                and data[candidate + match_len] == data[pos + match_len]
            ):
                match_len += 1
            _emit_copy(output, offset, match_len)
            pos += match_len
            literal_start = pos
            if pos <= data_len - 4:
                hash_table[_hash_4_bytes(data, pos - 1)] = pos - 1
        else:
            pos += 1
    if literal_start < data_len:
        _emit_literal(output, data, literal_start, data_len - literal_start)
    return bytes(output)


def copy_chunks(src, dst, chunk_size: int = 1024 * 1024) -> None:
    while True:
        chunk = src.read(chunk_size)
        if not chunk:
            break
        dst.write(chunk)


@dataclass
class Result:
    algo: str
    input_path: str
    out_path: str
    out_size: int
    elapsed_s: float
    ok: bool
    error: str | None = None


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def best_ext(algo: str) -> str:
    return {
        "brotli": ".br",
        "huffman": ".hf",
        "gz": ".gz",
        "bz2": ".bz2",
        "lzma": ".xz",
        "zip": ".zip",
        "snappy": ".snappy",
        "zstd": ".zst",
        "7z": ".7z",
    }.get(algo, f".{algo}")


def compress_7z(in_path: Path, out_path: Path) -> None:
    with py7zr.SevenZipFile(out_path, mode="w", filters=None) as z:
        z.write(in_path, arcname=in_path.name)


def compress_gz(in_path: Path, out_path: Path) -> None:
    with in_path.open("rb") as fin, gzip.open(out_path, "wb", compresslevel=9) as fout:
        copy_chunks(fin, fout)


def compress_bz2(in_path: Path, out_path: Path) -> None:
    with in_path.open("rb") as fin, bz2.open(out_path, "wb", compresslevel=9) as fout:
        copy_chunks(fin, fout)


def compress_lzma(in_path: Path, out_path: Path) -> None:
    with (
        lzma.open(out_path, "wb", preset=9 | lzma.PRESET_EXTREME) as fout,
        in_path.open("rb") as fin,
    ):
        copy_chunks(fin, fout)


def compress_zip(in_path: Path, out_path: Path) -> None:
    with zipfile.ZipFile(
        out_path, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as zf:
        zf.write(in_path, arcname=in_path.name)


def compress_brotli(in_path: Path, out_path: Path) -> None:
    data = in_path.read_bytes()
    out_path.write_bytes(brotli.compress(data, quality=11, lgwin=22))


def compress_huffman(in_path: Path, out_path: Path) -> None:
    if huffman_lib is None:
        raise RuntimeError("huffman library not available")
    data = in_path.read_bytes()
    if hasattr(huffman_lib, "compress"):
        out_path.write_bytes(huffman_lib.compress(data))
    elif hasattr(huffman_lib, "HuffmanCodec"):
        codec = huffman_lib.HuffmanCodec(data)
        out_path.write_bytes(codec.encode(data))
    else:
        raise RuntimeError("Unsupported huffman library API")


def compress_snappy(in_path: Path, out_path: Path) -> None:
    out_path.write_bytes(snappy_compress(in_path.read_bytes()))


def compress_zstd(in_path: Path, out_path: Path) -> None:
    cctx = zstd.ZstdCompressor(level=21)
    out_path.write_bytes(cctx.compress(in_path.read_bytes()))


ALGO_SINGLE: dict[str, tuple[str, Any]] = {
    "7z": ("7z", compress_7z),
    "gz": ("gz", compress_gz),
    "lzma": ("lzma", compress_lzma),
    "bz2": ("bz2", compress_bz2),
    "zip": ("zip", compress_zip),
    "brotli": ("brotli", compress_brotli),
    "huffman": ("huffman", compress_huffman),
    "snappy": ("snappy", compress_snappy),
    "zstd": ("zstd", compress_zstd),
}


def run_single(algo: str, in_path: Path, tmpdir: Path) -> Result:
    try:
        out_path = tmpdir / f"{in_path.name}{best_ext(algo)}"
        fn = ALGO_SINGLE[algo][1]
        t0 = time.perf_counter()
        fn(in_path, out_path)
        elapsed = time.perf_counter() - t0
        out_size = out_path.stat().st_size
        return Result(
            algo=algo,
            input_path=str(in_path),
            out_path=str(out_path),
            out_size=out_size,
            elapsed_s=elapsed,
            ok=True,
        )
    except Exception as e:
        logger.exception(f"[{algo}] failed: {e}")
        return Result(
            algo=algo,
            input_path=str(in_path),
            out_path="",
            out_size=0,
            elapsed_s=0.0,
            ok=False,
            error=str(e),
        )


WORKER_ALGOS = {"gz", "bz2", "lzma", "zstd", "brotli", "snappy"}


def _chunk_compressor(algo: str):
    if algo == "gz":

        def f(chunk: bytes) -> bytes:
            import gzip
            import io

            out = io.BytesIO()
            with gzip.GzipFile(fileobj=out, mode="wb", compresslevel=9) as g:
                g.write(chunk)
            return out.getvalue()

        return f
    if algo == "bz2":

        def f(chunk: bytes) -> bytes:
            import io

            out = io.BytesIO()
            with bz2.BZ2File(out, mode="wb", compresslevel=9) as b:
                b.write(chunk)
            return out.getvalue()

        return f
    if algo == "lzma":

        def f(chunk: bytes) -> bytes:
            import io

            out = io.BytesIO()
            with lzma.LZMAFile(out, mode="wb", preset=9 | lzma.PRESET_EXTREME) as l:
                l.write(chunk)
            return out.getvalue()

        return f
    if algo == "zstd":

        def f(chunk: bytes) -> bytes:
            return zstd.ZstdCompressor(level=22).compress(chunk)

        return f
    if algo == "brotli":

        def f(chunk: bytes) -> bytes:
            return brotli.compress(chunk, quality=11, lgwin=22)

        return f
    if algo == "snappy":

        def f(chunk: bytes) -> bytes:
            return snappy_compress(chunk)

        return f
    raise ValueError(algo)


def _worker(arg):
    algo, chunk = arg
    return _chunk_compressor(algo)(chunk)


def mp_compress_chunks(
    algo: str, in_path: Path, tmpdir: Path, chunk_size: int, processes: int | None
) -> Result:
    if algo not in WORKER_ALGOS:
        return Result(
            algo=f"mp_{algo}",
            input_path=str(in_path),
            out_path="",
            out_size=0,
            elapsed_s=0.0,
            ok=False,
            error="Chunk mode not supported",
        )
    try:
        out_path = tmpdir / f"{in_path.name}.mp_{algo}{best_ext(algo)}"
        t0 = time.perf_counter()
        chunks = []
        with in_path.open("rb") as f:
            while True:
                b = f.read(chunk_size)
                if not b:
                    break
                chunks.append(b)
        with mp.Pool(processes=processes or mp.cpu_count()) as pool:
            compressed_parts = pool.map(_worker, [(algo, c) for c in chunks])
        with out_path.open("wb") as fout:
            for part in compressed_parts:
                fout.write(part)
        elapsed = time.perf_counter() - t0
        out_size = out_path.stat().st_size
        return Result(
            algo=f"mp_{algo}",
            input_path=str(in_path),
            out_path=str(out_path),
            out_size=out_size,
            elapsed_s=elapsed,
            ok=True,
        )
    except Exception as e:
        logger.exception(f"[mp_{algo}] failed: {e}")
        return Result(
            algo=f"mp_{algo}",
            input_path=str(in_path),
            out_path="",
            out_size=0,
            elapsed_s=0.0,
            ok=False,
            error=str(e),
        )


def choose_best(results: list[Result]) -> Result | None:
    ok = [r for r in results if r.ok and r.out_path]
    if not ok:
        return None
    ok.sort(key=lambda r: (r.out_size, r.elapsed_s))
    return ok[0]


def copy_file(src: Path, dst: Path, chunk_size: int = 1024 * 1024) -> None:
    with src.open("rb") as fin, dst.open("wb") as fout:
        copy_chunks(fin, fout, chunk_size)


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <filename>", file=sys.stderr)
        sys.exit(1)
    in_path = Path(sys.argv[1]).expanduser()
    if not in_path.exists() or not in_path.is_file():
        print(f"Error: file not found: {in_path}", file=sys.stderr)
        sys.exit(1)
    print(f"Input: {in_path} ({fsz(in_path.stat().st_size)})")
    try:
        print(f"SHA256(input)={file_sha256(in_path)}")
    except Exception:
        logger.warning("Could not compute SHA256")
    with tempfile.TemporaryDirectory(prefix="compress_bench_") as td:
        tmpdir = Path(td)
        single_algos = [
            "7z",
            "gz",
            "lzma",
            "bz2",
            "zip",
            "brotli",
            "huffman",
            "snappy",
            "zstd",
        ]
        results_single: list[Result] = []
        print("=== Single-process benchmark ===")
        for algo in single_algos:
            print(f"Compressing {algo} ...")
            r = run_single(algo, in_path, tmpdir)
            results_single.append(r)
            if r.ok:
                print(
                    f"[{algo}] OK size={fsz(r.out_size)} time={r.elapsed_s:.4f}s out={Path(r.out_path).name}"
                )
            else:
                logger.error(f"[{algo}] FAIL {r.error}")
        mp_algos = ["gz", "bz2", "lzma", "zstd", "brotli", "snappy"]
        chunk_size = 4 * 1024 * 1024
        processes = None
        print("=== Multiprocessing chunk benchmark (reporting only) ===")
        mp_results: list[Result] = []
        for algo in mp_algos:
            print(f"MP chunk compress {algo} (chunk_size={fsz(chunk_size)}) ...")
            r = mp_compress_chunks(
                algo, in_path, tmpdir, chunk_size=chunk_size, processes=processes
            )
            mp_results.append(r)
            if r.ok:
                print(
                    f"[mp_{algo}] OK size={fsz(r.out_size)} time={r.elapsed_s:.4f}s out={Path(r.out_path).name}"
                )
            else:
                logger.error(f"[mp_{algo}] FAIL {r.error}")
        best_overall = choose_best(results_single + mp_results)
        if not best_overall:
            print("Could not determine best compressed output.", file=sys.stderr)
            sys.exit(3)
        print("\nSingle-process results:")
        ok_single = [r for r in results_single if r.ok]
        ok_single.sort(key=lambda r: (r.out_size, r.elapsed_s))
        print(f"{'Algo':<10} {'Size':>15} {'Time(s)':>12}")
        print("-" * 40)
        for r in ok_single:
            print(f"{r.algo:<10} {fsz(r.out_size):>15} {r.elapsed_s:>12.4f}")
        print(
            f"\nBest overall: {best_overall.algo} size={fsz(best_overall.out_size)} time={best_overall.elapsed_s:.4f}s"
        )
        if best_overall.algo.startswith("mp_"):
            base_algo = best_overall.algo[len("mp_") :]
        else:
            base_algo = best_overall.algo
        out_final = in_path.with_name(in_path.name + best_ext(base_algo))
        copy_file(Path(best_overall.out_path), out_final)
        print(f"Saved best output to: {out_final}")


if __name__ == "__main__":
    raise SystemExit(main())
