#!/usr/bin/env python3
"""
Generate an auto-updating US economic calendar (.ics) from public official sources.
Designed for GitHub Actions + GitHub Pages.

Default included sources:
- BLS: CPI, PPI, Employment Situation, JOLTS, Productivity and Costs
- BEA: GDP, Personal Income and Outlays / PCE, International Trade
- Census: Retail Sales, Durable Goods, Housing Starts, New Home Sales, Construction Spending
- Federal Reserve: FOMC decisions (official meeting dates; decision time assumed 14:00 ET)
"""
from __future__ import annotations

import hashlib
import html
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dtparser
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
OUT_DIR = Path("docs")
OUT_ICS = OUT_DIR / "us-economic-calendar.ics"
OUT_HTML = OUT_DIR / "index.html"
USER_AGENT = "Roy-US-Economic-Calendar/1.0 (+https://github.com/)"

# Only keep trading-relevant releases. Add/remove keywords here.
BLS_KEEP = [
    "Employment Situation",
    "Consumer Price Index",
    "Producer Price Index",
    "Job Openings and Labor Turnover Survey",
    "Productivity and Costs",
]
BEA_KEEP = [
    "Gross Domestic Product",
    "GDP",
    "Personal Income and Outlays",
    "Personal Income",
    "Corporate Profits",
    "U.S. International Trade in Goods and Services",
]
CENSUS_KEEP = [
    "Advance Monthly Sales for Retail and Food Services",
    "Advance Report on Durable Goods",
    "New Residential Construction",
    "New Residential Sales",
    "Construction Spending",
    "Advance Economic Indicators Report",
]

@dataclass(frozen=True)
class Event:
    title: str
    start: datetime
    end: datetime
    source: str
    url: str
    description: str = ""
    priority: str = "High"


def fetch(url: str) -> str:
    resp = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.text


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def keep(title: str, keywords: list[str]) -> bool:
    t = title.lower()
    return any(k.lower() in t for k in keywords)


def parse_datetime(date_text: str, time_text: str, default_hour: int = 8, default_minute: int = 30) -> datetime | None:
    date_text = clean(date_text).replace("\xa0", " ")
    time_text = clean(time_text).replace("\xa0", " ")
    if not date_text:
        return None
    try:
        d = dtparser.parse(date_text, fuzzy=True).date()
    except Exception:
        return None
    hour, minute = default_hour, default_minute
    if time_text and not re.search(r"holiday|closed|day$", time_text, re.I):
        try:
            tt = dtparser.parse(time_text, fuzzy=True)
            hour, minute = tt.hour, tt.minute
        except Exception:
            pass
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=ET)


def table_rows(soup: BeautifulSoup) -> Iterable[list[str]]:
    for tr in soup.find_all("tr"):
        cells = [clean(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
        if len(cells) >= 3:
            yield cells


def get_bls_events() -> list[Event]:
    url = "https://www.bls.gov/schedule/"
    events: list[Event] = []
    for source_url in [url, "https://www.bls.gov/schedule/2026/home.htm", "https://www.bls.gov/schedule/2027/home.htm"]:
        try:
            soup = BeautifulSoup(fetch(source_url), "lxml")
        except Exception as e:
            print(f"BLS fetch failed {source_url}: {e}")
            continue
        for cells in table_rows(soup):
            joined = " | ".join(cells)
            if not keep(joined, BLS_KEEP):
                continue
            # Common BLS row shape: Date | Time | Release
            dt = None
            title = ""
            for i in range(min(3, len(cells) - 2)):
                candidate = parse_datetime(cells[i], cells[i + 1])
                if candidate:
                    dt = candidate
                    title = cells[i + 2]
                    break
            if not dt or not title or not keep(title, BLS_KEEP):
                continue
            events.append(Event(
                title=f"美國 {title}",
                start=dt,
                end=dt + timedelta(minutes=30),
                source="BLS",
                url=source_url,
                description="Source: U.S. Bureau of Labor Statistics release schedule.",
            ))
    return events


def get_bea_events() -> list[Event]:
    urls = ["https://www.bea.gov/news/schedule", "https://www.bea.gov/news/schedule/next-year"]
    events: list[Event] = []
    for source_url in urls:
        try:
            soup = BeautifulSoup(fetch(source_url), "lxml")
        except Exception as e:
            print(f"BEA fetch failed {source_url}: {e}")
            continue
        for cells in table_rows(soup):
            joined = " | ".join(cells)
            if not keep(joined, BEA_KEEP):
                continue
            dt = None
            title = ""
            # BEA often: Date | Time | Type | Release
            for i in range(min(3, len(cells) - 2)):
                candidate = parse_datetime(cells[i], cells[i + 1])
                if candidate:
                    dt = candidate
                    title = " ".join(cells[i + 2:]).replace("News", "").replace("Data", "")
                    title = clean(title)
                    break
            if not dt or not title or not keep(title, BEA_KEEP):
                continue
            events.append(Event(
                title=f"美國 {title}",
                start=dt,
                end=dt + timedelta(minutes=30),
                source="BEA",
                url=source_url,
                description="Source: U.S. Bureau of Economic Analysis release schedule.",
            ))
    return events


def get_census_events() -> list[Event]:
    source_url = "https://www.census.gov/economic-indicators/calendar-listview.html"
    events: list[Event] = []
    try:
        soup = BeautifulSoup(fetch(source_url), "lxml")
    except Exception as e:
        print(f"Census fetch failed: {e}")
        return events
    for cells in table_rows(soup):
        joined = " | ".join(cells)
        if not keep(joined, CENSUS_KEEP):
            continue
        dt = None
        title = ""
        # Census commonly: Release | Date | Time | Period | ID...
        for i in range(len(cells) - 2):
            candidate = parse_datetime(cells[i], cells[i + 1])
            if candidate:
                dt = candidate
                title = cells[0] if i > 0 else cells[i + 2]
                break
        if not dt or not title or not keep(title, CENSUS_KEEP):
            continue
        events.append(Event(
            title=f"美國 {title}",
            start=dt,
            end=dt + timedelta(minutes=30),
            source="Census",
            url=source_url,
            description="Source: U.S. Census Bureau Economic Indicators release schedule.",
        ))
    return events


def get_fomc_events() -> list[Event]:
    source_url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
    events: list[Event] = []
    try:
        soup = BeautifulSoup(fetch(source_url), "lxml")
        text = clean(soup.get_text(" "))
    except Exception as e:
        print(f"FOMC fetch failed: {e}")
        text = ""

    # Robust fallback; update this dictionary if the Fed changes the format heavily.
    fallback = {
        2026: ["January 27-28", "March 17-18", "April 28-29", "June 16-17", "July 28-29", "September 15-16", "October 27-28", "December 8-9"],
        2027: ["January 26-27", "March 16-17", "April 27-28", "June 15-16", "July 27-28", "September 14-15", "October 26-27", "December 7-8"],
    }

    # Try to infer meeting date ranges from the official page text for current and next year.
    current_year = datetime.now(ET).year
    years = [current_year, current_year + 1]
    found: dict[int, list[str]] = {y: [] for y in years}
    if text:
        month_names = "January|February|March|April|May|June|July|August|September|October|November|December"
        for y in years:
            # Search snippets around the year section; fallback will cover misses.
            section_match = re.search(rf"{y} FOMC Meetings(.+?)(?:{y+1} FOMC Meetings|$)", text, re.I)
            section = section_match.group(1) if section_match else text
            for m in re.finditer(rf"\b({month_names})\s+(\d{{1,2}})(?:\s*[-–]\s*(\d{{1,2}}))?\*?", section):
                found[y].append(f"{m.group(1)} {m.group(2)}" + (f"-{m.group(3)}" if m.group(3) else ""))

    for y in years:
        ranges = found.get(y) or fallback.get(y, [])
        for rng in ranges:
            m = re.match(r"([A-Za-z]+)\s+(\d{1,2})(?:-(\d{1,2}))?", rng)
            if not m:
                continue
            month, start_day, end_day = m.group(1), int(m.group(2)), int(m.group(3) or m.group(2))
            try:
                d = dtparser.parse(f"{month} {end_day}, {y}").date()
            except Exception:
                continue
            # FOMC statement normally releases at 14:00 ET; December may be 14:00 too in most years.
            dt = datetime(d.year, d.month, d.day, 14, 0, tzinfo=ET)
            events.append(Event(
                title="美國 FOMC 利率決議 / Statement",
                start=dt,
                end=dt + timedelta(minutes=30),
                source="Federal Reserve",
                url=source_url,
                description="Source: Federal Reserve FOMC meeting calendar. Decision time is set to the standard 14:00 ET release time; confirm around meeting weeks.",
            ))
    return events


def escape_ics(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\n", r"\n")


def fold_line(line: str) -> str:
    # RFC 5545: lines should be folded at 75 octets. Keep simple UTF-8 safe fold.
    out = []
    while len(line.encode("utf-8")) > 73:
        cut = 73
        while len(line[:cut].encode("utf-8")) > 73:
            cut -= 1
        out.append(line[:cut])
        line = " " + line[cut:]
    out.append(line)
    return "\r\n".join(out)


def uid_for(e: Event) -> str:
    raw = f"{e.source}|{e.title}|{e.start.isoformat()}"
    return hashlib.sha1(raw.encode()).hexdigest() + "@roy-us-economic-calendar"


def event_to_ics(e: Event, generated_at: datetime) -> list[str]:
    dtstart = e.start.strftime("%Y%m%dT%H%M%S")
    dtend = e.end.strftime("%Y%m%dT%H%M%S")
    dtstamp = generated_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    desc = f"{e.description}\\nURL: {e.url}\\nPriority: {e.priority}"
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid_for(e)}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART;TZID=America/New_York:{dtstart}",
        f"DTEND;TZID=America/New_York:{dtend}",
        f"SUMMARY:{escape_ics(e.title)}",
        f"DESCRIPTION:{escape_ics(desc)}",
        f"URL:{escape_ics(e.url)}",
        "TRANSP:TRANSPARENT",
    ]
    for minutes in [60, 30]:
        lines.extend([
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{escape_ics(e.title)}",
            f"TRIGGER:-PT{minutes}M",
            "END:VALARM",
        ])
    lines.append("END:VEVENT")
    return lines


def write_ics(events: list[Event]) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    now = datetime.now(UTC)
    # keep only future and recent events; Apple subscriptions can get bloated otherwise
    lower = datetime.now(ET) - timedelta(days=14)
    upper = datetime.now(ET) + timedelta(days=550)
    dedup: dict[str, Event] = {}
    for e in events:
        if lower <= e.start <= upper:
            dedup[uid_for(e)] = e
    events = sorted(dedup.values(), key=lambda x: x.start)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Roy Cheng//US Economic Calendar//ZH-TW",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:美國重要經濟數據",
        "X-WR-CALDESC:Auto-updated US economic releases for trading. Sources: BLS, BEA, Census, Federal Reserve.",
        "X-WR-TIMEZONE:Asia/Taipei",
        "BEGIN:VTIMEZONE",
        "TZID:America/New_York",
        "X-LIC-LOCATION:America/New_York",
        "END:VTIMEZONE",
    ]
    for e in events:
        lines.extend(event_to_ics(e, now))
    lines.append("END:VCALENDAR")
    OUT_ICS.write_text("\r\n".join(fold_line(line) for line in lines) + "\r\n", encoding="utf-8")

    last = now.astimezone(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M:%S %Z")
    OUT_HTML.write_text(f"""<!doctype html>
<html lang="zh-Hant">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>美國重要經濟數據行事曆</title></head>
<body>
<h1>美國重要經濟數據行事曆</h1>
<p>Last updated: {last}</p>
<p><a href="us-economic-calendar.ics">Download / Subscribe ICS</a></p>
<p>Apple Calendar 訂閱網址通常是：<code>webcal://你的帳號.github.io/你的repo/us-economic-calendar.ics</code></p>
</body></html>
""", encoding="utf-8")
    print(f"Wrote {len(events)} events to {OUT_ICS}")


def main() -> None:
    events: list[Event] = []
    for getter in [get_bls_events, get_bea_events, get_census_events, get_fomc_events]:
        try:
            got = getter()
            print(f"{getter.__name__}: {len(got)} events")
            events.extend(got)
        except Exception as e:
            print(f"{getter.__name__} failed: {e}")
    write_ics(events)


if __name__ == "__main__":
    main()
