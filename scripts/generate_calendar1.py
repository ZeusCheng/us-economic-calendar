#!/usr/bin/env python3
"""Generate a US high-impact economic calendar for Apple Calendar.

Official sources:
- BLS official iCalendar feed (preferred), HTML pages only as fallback
- BEA release schedule
- Census economic indicators calendar
- Federal Reserve FOMC calendar

Times are stored in America/New_York. Apple Calendar converts them to Taiwan
local time automatically, including daylight-saving changes.
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
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 Chrome/126 Safari/537.36 "
    "Roy-US-Economic-Calendar/2.1"
)
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


def fetch(url: str, *, accept: str = "text/html,*/*") -> str:
    response = requests.get(
        url,
        timeout=45,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    response.raise_for_status()
    return response.text


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def classify(text: str) -> tuple[str, str, int] | None:
    normalized = clean(text).lower()
    for key, aliases, title, importance in RELEASES:
        if any(alias in normalized for alias in aliases):
            return key, title, importance
    return None


def unfold_ics(text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    unfolded: list[str] = []
    for line in lines:
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def unescape_ics(value: str) -> str:
    return (
        value.replace("\\n", " ")
        .replace("\\N", " ")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def parse_ics_datetime(property_name: str, value: str) -> datetime | None:
    value = value.strip()
    try:
        if re.fullmatch(r"\d{8}", value):
            d = datetime.strptime(value, "%Y%m%d")
            return d.replace(hour=8, minute=30, tzinfo=ET)
        if value.endswith("Z"):
            d = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            return d.astimezone(ET)
        d = datetime.strptime(value, "%Y%m%dT%H%M%S")
        tz_match = re.search(r"TZID=([^;:]+)", property_name, re.I)
        if tz_match:
            try:
                return d.replace(tzinfo=ZoneInfo(tz_match.group(1)))
            except Exception:
                pass
        return d.replace(tzinfo=ET)
    except ValueError:
        return None


def parse_bls_ics(text: str, source_url: str) -> list[Event]:
    events: list[Event] = []
    block: dict[str, str] | None = None
    for line in unfold_ics(text):
        if line == "BEGIN:VEVENT":
            block = {}
            continue
        if line == "END:VEVENT":
            if block:
                summary = unescape_ics(block.get("SUMMARY", ""))
                info = classify(summary)
                dt_entry = next(
                    ((name, value) for name, value in block.items() if name.startswith("DTSTART")),
                    None,
                )
                if info and dt_entry:
                    dt = parse_ics_datetime(*dt_entry)
                    if dt:
                        key, title, importance = info
                        events.append(Event(key, title, dt.astimezone(ET), "BLS", source_url, importance))
            block = None
            continue
        if block is not None and ":" in line:
            name, value = line.split(":", 1)
            # Preserve DTSTART parameters, normalize other property names.
            block[name if name.startswith("DTSTART") else name.split(";", 1)[0]] = value
    return events


def get_bls_events() -> list[Event]:
    """Use BLS's official ICS feed first.

    GitHub-hosted runners are frequently denied access to BLS HTML pages with
    HTTP 403. BLS itself publishes this ICS subscription URL, which is also
    simpler and less brittle than scraping its HTML tables.
    """
    ics_url = "https://www.bls.gov/schedule/news_release/bls.ics"
    try:
        text = fetch(ics_url, accept="text/calendar,text/plain,*/*")
        events = parse_bls_ics(text, ics_url)
        if events:
            print(f"BLS ICS: {len(events)} matched events")
            return events
        print("BLS ICS returned no matched releases; trying HTML fallback")
    except Exception as exc:
        print(f"BLS ICS fetch failed: {exc}; trying HTML fallback")

    urls = [f"https://www.bls.gov/schedule/{year}/home.htm" for year in YEARS]
    return parse_schedule(urls, "BLS")


def rows(soup: BeautifulSoup) -> Iterable[list[str]]:
    for tr in soup.select("tr"):
        cells = [clean(c.get_text(" ", strip=True)) for c in tr.select("th,td")]
        cells = [c for c in cells if c]
        if len(cells) >= 2:
            yield cells


def parse_date_time_from_cells(cells: list[str], default=(8, 30)) -> datetime | None:
    # Try an individual cell first. This handles "July 30, 2026 8:30 AM".
    for value in cells:
        if not re.search(r"\b(20\d{2}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", value, re.I):
            continue
        try:
            parsed = dtparser.parse(value, fuzzy=True, default=datetime(CURRENT_YEAR, 1, 1, *default))
            if CURRENT_YEAR - 1 <= parsed.year <= CURRENT_YEAR + 2:
                return parsed.replace(tzinfo=ET)
        except (ValueError, TypeError, OverflowError):
            pass

    # Then try date + adjacent time columns.
    for i, value in enumerate(cells):
        if not re.search(r"\b(20\d{2}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", value, re.I):
            continue
        combined = value
        if i + 1 < len(cells) and re.search(r"\b\d{1,2}:\d{2}\s*(?:AM|PM)\b", cells[i + 1], re.I):
            combined += " " + cells[i + 1]
        try:
            parsed = dtparser.parse(combined, fuzzy=True, default=datetime(CURRENT_YEAR, 1, 1, *default))
            if CURRENT_YEAR - 1 <= parsed.year <= CURRENT_YEAR + 2:
                return parsed.replace(tzinfo=ET)
        except (ValueError, TypeError, OverflowError):
            pass
    return None


def event_from_cells(cells: list[str], source: str, url: str) -> Event | None:
    joined = " | ".join(cells)
    info = classify(joined)
    if not info:
        return None
    dt = parse_date_time_from_cells(cells)
    if not dt:
        return None
    key, title, importance = info
    return Event(key, title, dt, source, url, importance)


def parse_schedule(urls: Iterable[str], source: str) -> list[Event]:
    found: list[Event] = []
    for url in urls:
        try:
            soup = BeautifulSoup(fetch(url), "lxml")
        except Exception as exc:
            print(f"{source} fetch failed: {url}: {exc}")
            continue
        before = len(found)
        for cells in rows(soup):
            event = event_from_cells(cells, source, url)
            if event:
                found.append(event)
        print(f"{source}: {url}: {len(found) - before} matched rows")
    return found


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
            section_match = re.search(
                rf"{year}\s+FOMC Meetings(.+?)(?:{year + 1}\s+FOMC Meetings|$)",
                text,
                re.I,
            )
            section = section_match.group(1) if section_match else ""
            for match in re.finditer(
                rf"\b({months})\s+(\d{{1,2}})(?:\s*[-–]\s*(\d{{1,2}}))?\*?",
                section,
            ):
                dates.append(f"{match.group(1)} {match.group(3) or match.group(2)}")
        dates = dates or fallback.get(year, [])
        for item in dates:
            try:
                d = dtparser.parse(f"{item}, {year}").date()
            except ValueError:
                continue
            decision = datetime(d.year, d.month, d.day, 14, 0, tzinfo=ET)
            press = datetime(d.year, d.month, d.day, 14, 30, tzinfo=ET)
            events.extend(
                [
                    Event("FOMC", "🔴 FOMC 利率決議 ★★★★★", decision, "Federal Reserve", url, 5),
                    Event("FOMC_PRESS", "🔴 Fed 主席記者會 ★★★★★", press, "Federal Reserve", url, 5, 60),
                ]
            )
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
    raw = f"{event.key}|{event.start.isoformat()}"
    return hashlib.sha1(raw.encode()).hexdigest() + "@roy-us-economic-calendar"


def to_ics(event: Event, stamp: datetime) -> list[str]:
    description = (
        f"官方來源：{event.source}\\n"
        f"重要程度：{'★' * event.importance}\\n"
        "時間以美東時區發布，Apple 行事曆會自動換算台灣時間。\\n"
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
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{escape_ics(event.title)}",
            f"TRIGGER:-PT{minutes}M",
            "END:VALARM",
        ]
    lines.append("END:VEVENT")
    return lines


def validate(events: list[Event]) -> None:
    future = [e for e in events if e.start >= datetime.now(ET) - timedelta(days=7)]
    counts = {key: sum(e.key == key for e in future) for key in {e.key for e in future}}
    required = {"CPI", "PPI", "NFP", "PCE", "GDP", "FOMC"}
    missing = sorted(required - set(counts))
    print("Calendar validation:")
    for key in sorted(required):
        print(f"  {key}: {counts.get(key, 0)}")
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
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Roy Cheng//US Economic Calendar v2.1//ZH-TW",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:美國重大經濟數據",
        "X-WR-CALDESC:CPI、PPI、PCE、NFP、GDP、FOMC 等美國高影響數據",
        "X-WR-TIMEZONE:Asia/Taipei",
    ]
    for event in ordered:
        lines.extend(to_ics(event, now))
    lines.append("END:VCALENDAR")

    OUT_ICS.write_text("\r\n".join(fold(line) for line in lines) + "\r\n", encoding="utf-8")
    updated = now.astimezone(TPE).strftime("%Y-%m-%d %H:%M:%S")
    OUT_HTML.write_text(
        f"""<!doctype html><meta charset="utf-8"><title>美國重大經濟數據行事曆</title>
<h1>美國重大經濟數據行事曆</h1>
<p>最後更新：{updated}（台灣時間）</p>
<p><a href="us-economic-calendar.ics">下載／訂閱 ICS</a></p>
<p>包含 CPI、Core CPI、PPI、Core PPI、PCE、Core PCE、NFP、GDP、FOMC 等。</p>
""",
        encoding="utf-8",
    )
    print(f"Wrote {len(ordered)} validated events to {OUT_ICS}")


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
