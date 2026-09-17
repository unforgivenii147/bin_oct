#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ctypes
import ctypes.util
from datetime import UTC, datetime


class StatxTimestamp(ctypes.Structure):
    _fields_ = [
        ("tv_sec", ctypes.c_int64),
        ("tv_nsec", ctypes.c_uint32),
        ("__reserved", ctypes.c_int32),
    ]


class Statx(ctypes.Structure):
    _fields_ = [
        ("stx_mask", ctypes.c_uint32),
        ("stx_blksize", ctypes.c_uint32),
        ("stx_attributes", ctypes.c_uint64),
        ("stx_nlink", ctypes.c_uint32),
        ("stx_uid", ctypes.c_uint32),
        ("stx_gid", ctypes.c_uint32),
        ("stx_mode", ctypes.c_uint16),
        ("__spare0", ctypes.c_uint16 * 1),
        ("stx_ino", ctypes.c_uint64),
        ("stx_size", ctypes.c_uint64),
        ("stx_blocks", ctypes.c_uint64),
        ("stx_attributes_mask", ctypes.c_uint64),
        ("stx_atime", StatxTimestamp),
        ("stx_btime", StatxTimestamp),
        ("stx_ctime", StatxTimestamp),
        ("stx_mtime", StatxTimestamp),
        ("stx_rdev_major", ctypes.c_uint32),
        ("stx_rdev_minor", ctypes.c_uint32),
        ("stx_dev_major", ctypes.c_uint32),
        ("stx_dev_minor", ctypes.c_uint32),
        ("__spare2", ctypes.c_uint64 * 14),
    ]


libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
AT_FDCWD = -100
STATX_BTIME = 2048


def get_creation_time_statx(path: str) -> datetime | None:
    statx_buf = Statx()
    result = libc.statx(
        AT_FDCWD, path.encode(), 0, STATX_BTIME, ctypes.byref(statx_buf)
    )
    if result == 0 and statx_buf.stx_mask & STATX_BTIME:
        timestamp = statx_buf.stx_btime.tv_sec
        return datetime.fromtimestamp(timestamp, tz=UTC)
    return None


creation_time = get_creation_time_statx("filename.txt")
print(f"Creation time: {creation_time}")
