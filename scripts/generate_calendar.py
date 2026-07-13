#!/usr/bin/env python3
"""Generate a US high-impact economic calendar for Apple Calendar.

Sources are official release schedules from BLS, BEA, Census and the Federal
Reserve. Times are stored with America/New_York timezone so Apple Calendar
automatically displays them in Asia/Taipei, including US daylight saving time.
"""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dtparser

ET = ZoneInfo("America/New_York")
TPE = ZoneInfo("Asia/Taipei")
UTC = timezone.utc
OUT_DIR = Path("docs")
OUT_ICS = OUT_DIR / "us-economic-calendar.ics"
OUT_HTML = OUT_DIR / "index.html"
USER_AGENT = "Roy-US-Economic-Calendar/2.0 (GitHub Actions; economic calendar)"
CURRENT_YEAR = datetime.now(ET).year
YEARS = (CURRENT_YEAR, CURRENT_YEAR + 1)


@dataclass(frozen=True)
class Event:
    key: str
    title: str
    start: datetime
    source: str
    url: str
    importance: int = 5
    duration_minutes: int = 30

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.duration_minutes)


# Match official long release names and normalize them for a trading calendar.
RELEASES: list[tuple[str, tuple[str, ...], str, int]] = [
    ("NFP", ("employment situation",), "🔴 NFP／失業率／平均時薪 ★★★★★", 5),
    ("CPI", ("consumer price index",), "🔴 CPI／Core CPI ★★★★★", 5),
    ("PPI", ("producer price index",), "🔴 PPI／Core PPI ★★★★★", 5),
    ("JOLTS", ("job openings and labor turnover", "jolts"), "🟠 JOLTS 職缺數 ★★★★", 4),
    ("PRODUCTIVITY", ("productivity and costs",), "🟠 生產力與單位勞動成本 ★★★★", 4),
    ("PCE", ("personal income and outlays",), "🔴 PCE／Core PCE ★★★★★", 5),
    ("GDP", ("gross domestic product", "gdp"), "🔴 GDP ★★★★★", 5),
    ("TRADE", ("international trade in goods and services",), "🟠 美國貿易收支 ★★★★", 4),
    ("RETAIL", ("advance monthly sales for retail and food services", "retail sales"), "🔴 零售銷售 Retail Sales ★★★★★", 5),
    ("DURABLE", ("advance report on durable goods", "durable goods"), "🟠 耐久財訂單 ★★★★", 4),
    ("HOUSING_STARTS", ("new residential construction", "housing starts"), "🟠 新屋開工／營建許可 ★★★★", 4),
    ("NEW_HOME", ("new residential sales", "new home sales"), "🟠 新屋銷售 ★★★★", 4),
    ("CONSTRUCTION", ("construction spending",), "🟠 營建支出 ★★★★", 4),
]


def fetch(url: str) -> str:
    r = requests.get(url, timeout=45, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.text


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def classify(text: str) -> tuple[str, str, int] | None:
    normalized = clean(text).lower()
    for key, aliases, title, importance in RELEASES:
        if any(alias in normalized for alias in aliases):
            return key, title, importance
    return None


def rows(soup: BeautifulSoup) -> Iterable[list[str]]:
    for tr in soup.select("tr"):
        cells = [clean(c.get_text(" ", strip=True)) for c in tr.select("th,td")]
        cells = [c for c in cells if c]
        if len(cells) >= 2:
            yield cells


def parse_date_time(date_text: str, time_text: str = "", default=(8, 30)) -> datetime | None:
    date_text, time_text = clean(date_text), clean(time_text)
    if not date_text:
        return None
    try:
        d = dtparser.parse(date_text, fuzzy=True, default=datetime(CURRENT_YEAR, 1, 1)).date()
    except (ValueError, TypeError, OverflowError):
        return None
    hour, minute = default
    if time_text and not re.search(r"holiday|closed|all day", time_text, re.I):
        try:
            t = dtparser.parse(time_text, fuzzy=True)
            hour, minute = t.hour, t.minute
        except (ValueError, TypeError, OverflowError):
            pass
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=ET)


def event_from_cells(cells: list[str], source: str, url: str) -> Event | None:
    joined = " | ".join(cells)
    info = classify(joined)
    if not info:
        return None
    key, title, importance = info

    # Try every adjacent pair as date/time. This works across BLS/BEA/Census
    # even when the agencies reorder the columns.
    dt = None
    for i, value in enumerate(cells):
        if not re.search(r"\b(20\d{2}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", value, re.I):
            continue
        next_value = cells[i + 1] if i + 1 < len(cells) else ""
        candidate = parse_date_time(value, next_value)
        if candidate and CURRENT_YEAR - 1 <= candidate.year <= CURRENT_YEAR + 2:
            dt = candidate
            break
    if not dt:
        return None
    return Event(key, title, dt, source, url, importance)


def parse_schedule(urls: Iterable[str], source: str) -> list[Event]:
    found: list[Event] = []
    for url in urls:
        try:
            soup = BeautifulSoup(fetch(url), "lxml")
        except Exception as exc:
            print(f"{source} fetch failed: {url}: {exc}")
            continue
        count_before = len(found)
        for cells in rows(soup):
            event = event_from_cells(cells, source, url)
            if event:
                found.append(event)
        print(f"{source}: {url}: {len(found) - count_before} matched rows")
    return found


def get_bls_events() -> list[Event]:
    urls = [f"https://www.bls.gov/schedule/{year}/home.htm" for year in YEARS]
    # Release-specific pages provide a second path if the annual page changes.
    urls += [
        "https://www.bls.gov/schedule/news_release/cpi.htm",
        "https://www.bls.gov/schedule/news_release/ppi.htm",
        "https://www.bls.gov/schedule/news_release/empsit.htm",
        "https://www.bls.gov/schedule/news_release/jolts.htm",
        "https://www.bls.gov/schedule/news_release/prod2.htm",
    ]
    return parse_schedule(urls, "BLS")


def get_bea_events() -> list[Event]:
    return parse_schedule(
        ["https://www.bea.gov/news/schedule", "https://www.bea.gov/news/schedule/next-year"],
        "BEA",
    )


def get_census_events() -> list[Event]:
    return parse_schedule(
        ["https://www.census.gov/economic-indicators/calendar-listview.html"],
        "Census",
    )


def get_fomc_events() -> list[Event]:
    url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
    fallback = {
        2026: ["January 28", "March 18", "April 29", "June 17", "July 29", "September 16", "October 28", "December 9"],
        2027: ["January 27", "March 17", "April 28", "June 16", "July 28", "September 15", "October 27", "December 8"],
    }
    text = ""
    try:
        text = clean(BeautifulSoup(fetch(url), "lxml").get_text(" "))
    except Exception as exc:
        print(f"FOMC fetch failed, using checked fallback dates: {exc}")

    events: list[Event] = []
    months = "January|February|March|April|May|June|July|August|September|October|November|December"
    for year in YEARS:
        dates: list[str] = []
        if text:
            section_match = re.search(rf"{year}\s+FOMC Meetings(.+?)(?:{year + 1}\s+FOMC Meetings|$)", text, re.I)
            section = section_match.group(1) if section_match else ""
            for m in re.finditer(rf"\b({months})\s+(\d{{1,2}})(?:\s*[-–]\s*(\d{{1,2}}))?\*?", section):
                dates.append(f"{m.group(1)} {m.group(3) or m.group(2)}")
        dates = dates or fallback.get(year, [])
        for item in dates:
            try:
                d = dtparser.parse(f"{item}, {year}").date()
            except ValueError:
                continue
            decision = datetime(d.year, d.month, d.day, 14, 0, tzinfo=ET)
            press = datetime(d.year, d.month, d.day, 14, 30, tzinfo=ET)
            events.extend([
                Event("FOMC", "🔴 FOMC 利率決議 ★★★★★", decision, "Federal Reserve", url, 5),
                Event("FOMC_PRESS", "🔴 Fed 主席記者會 ★★★★★", press, "Federal Reserve", url, 5, 60),
            ])
    return events


def escape_ics(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\n", r"\n")


def fold(line: str, limit: int = 73) -> str:
    parts: list[str] = []
    while len(line.encode("utf-8")) > limit:
        cut = min(len(line), limit)
        while cut > 1 and len(line[:cut].encode("utf-8")) > limit:
            cut -= 1
        parts.append(line[:cut])
        line = " " + line[cut:]
    parts.append(line)
    return "\r\n".join(parts)


def uid(event: Event) -> str:
    # Stable across title wording changes, which prevents Apple duplicates.
    raw = f"{event.key}|{event.start.isoformat()}"
    return hashlib.sha1(raw.encode()).hexdigest() + "@roy-us-economic-calendar"


def to_ics(event: Event, stamp: datetime) -> list[str]:
    description = (
        f"官方來源：{event.source}\\n"
        f"重要程度：{'★' * event.importance}\\n"
        f"時間以美東時區發布，Apple 行事曆會自動換算台灣時間。\\n"
        f"來源網址：{event.url}"
    )
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid(event)}",
        f"DTSTAMP:{stamp.astimezone(UTC):%Y%m%dT%H%M%SZ}",
        f"DTSTART;TZID=America/New_York:{event.start:%Y%m%dT%H%M%S}",
        f"DTEND;TZID=America/New_York:{event.end:%Y%m%dT%H%M%S}",
        f"SUMMARY:{escape_ics(event.title)}",
        f"DESCRIPTION:{escape_ics(description)}",
        f"URL:{escape_ics(event.url)}",
        "TRANSP:TRANSPARENT",
    ]
    reminders = (60, 30) if event.importance >= 5 else (30,)
    for minutes in reminders:
        lines += [
            "BEGIN:VALARM", "ACTION:DISPLAY",
            f"DESCRIPTION:{escape_ics(event.title)}",
            f"TRIGGER:-PT{minutes}M", "END:VALARM",
        ]
    lines.append("END:VEVENT")
    return lines


def validate(events: list[Event]) -> None:
    future = [e for e in events if e.start >= datetime.now(ET) - timedelta(days=7)]
    keys = {e.key for e in future}
    required = {"CPI", "PPI", "NFP", "PCE", "GDP", "FOMC"}
    missing = sorted(required - keys)
    if missing:
        raise RuntimeError(
            "Calendar validation failed; refusing to overwrite the existing ICS. "
            f"Missing required releases: {', '.join(missing)}"
        )
    if len(future) < 20:
        raise RuntimeError(f"Calendar validation failed: only {len(future)} future events found")


def write(events: list[Event]) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    lower = datetime.now(ET) - timedelta(days=14)
    upper = datetime.now(ET) + timedelta(days=550)
    unique = {uid(e): e for e in events if lower <= e.start <= upper}
    ordered = sorted(unique.values(), key=lambda e: (e.start, e.title))
    validate(ordered)

    now = datetime.now(UTC)
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//Roy Cheng//US Economic Calendar v2//ZH-TW",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "X-WR-CALNAME:美國重大經濟數據",
        "X-WR-CALDESC:CPI、PPI、PCE、NFP、GDP、FOMC 等美國高影響數據",
        "X-WR-TIMEZONE:Asia/Taipei",
    ]
    for event in ordered:
        lines.extend(to_ics(event, now))
    lines.append("END:VCALENDAR")
    OUT_ICS.write_text("\r\n".join(fold(x) for x in lines) + "\r\n", encoding="utf-8")

    updated = now.astimezone(TPE).strftime("%Y-%m-%d %H:%M:%S")
    OUT_HTML.write_text(
        f"""<!doctype html><html lang=\"zh-Hant\"><meta charset=\"utf-8\">
<title>美國重大經濟數據行事曆</title><body>
<h1>美國重大經濟數據行事曆</h1><p>最後更新：{updated}（台灣時間）</p>
<p><a href=\"us-economic-calendar.ics\">下載／訂閱 ICS</a></p>
<p>包含 CPI、Core CPI、PPI、Core PPI、PCE、Core PCE、NFP、GDP、FOMC 等。</p>
</body></html>""",
        encoding="utf-8",
    )
    print(f"Wrote {len(ordered)} validated events to {OUT_ICS}")
    for key in sorted({e.key for e in ordered}):
        print(f"  {key}: {sum(e.key == key for e in ordered)}")


def main() -> None:
    events: list[Event] = []
    for getter in (get_bls_events, get_bea_events, get_census_events, get_fomc_events):
        try:
            batch = getter()
            print(f"{getter.__name__}: {len(batch)} events")
            events.extend(batch)
        except Exception as exc:
            print(f"{getter.__name__} failed: {exc}")
    write(events)


if __name__ == "__main__":
    main()
