#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import datetime
import string

weekdays = ["دوشنبه", "سه\u200cشنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]
months = [
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
]


def gregorian_to_jalali(g: int, m: int, d: int):
    g_days = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy = g - 1600
    gm = m - 1
    gd = d - 1
    g_day_no = 365 * gy + (gy + 3) // 4 - (gy + 99) // 100 + (gy + 399) // 400
    g_day_no += g_days[gm] + gd
    jy = 979
    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy += 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365
    for i in range(11):
        if j_day_no < (31 if i < 6 else 30):
            jm = i + 1
            jd = j_day_no + 1
            break
        j_day_no -= 31 if i < 6 else 30
    return jy, jm, jd


now = datetime.datetime.now()
jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
weekday = weekdays[now.weekday()]
month = months[jm - 1]
time_str = f"{now.hour:02d}:{now.minute:02d}"


def to_persian(s: str):
    return s.translate(str.maketrans(string.digits, "۰۱۲۳۴۵۶۷۸۹"))


result = f"{weekday}  {to_persian(str(jd))}  {month}  {to_persian(str(jy))}  {to_persian(time_str)} "
