#!/usr/bin/env python3
"""Generate a US high-impact economic calendar for Apple Calendar.

Sources:
- Fair Economy ICS feeds: primary rolling current/next-week calendar,
  filtered to USD / United States events only.
- Forex Factory / Fair Economy XML feeds: secondary rolling source with
  impact, forecast, previous and actual values when available.
- BEA release schedule: PCE and GDP longer-term dates.
- US Census economic indicators calendar: retail sales, durable goods,
  housing and trade releases.
- Federal Reserve FOMC calendar.

The generated ICS uses America/New_York; Apple Calendar converts it to the
device timezone, including daylight-saving changes.
"""
from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ETXML
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dtparser

ET = ZoneInfo("America/New_York")
CT = ZoneInfo("America/Chicago")
TPE = ZoneInfo("Asia/Taipei")
UTC = timezone.utc

OUT_DIR = Path("docs")
OUT_ICS = OUT_DIR / "us-economic-calendar.ics"
OUT_HTML = OUT_DIR / "index.html"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 Chrome/126 Safari/537.36 "
    "Roy-US-Economic-Calendar/6.0"
)

FF_ICS_FEEDS = (
    "https://nfs.faireconomy.media/ff_calendar_thisweek.ics",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.ics",
)

FF_FEEDS = (
    "https://nfs.faireconomy.media/ff_calendar_thisweek.xml",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.xml",
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
    description_extra: str = ""

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.duration_minutes)


RELEASES: list[tuple[str, tuple[str, ...], str, int]] = [
    ("NFP", ("non-farm employment change", "nonfarm payroll", "non-farm payroll", "employment situation"),
     "🇺🇸 NFP／失業率／平均時薪 ★★★★★", 5),
    ("UNEMPLOYMENT", ("unemployment rate",), "🇺🇸 美國失業率 ★★★★★", 5),
    ("EARNINGS", ("average hourly earnings",), "🇺🇸 平均時薪 ★★★★★", 5),
    ("CPI", ("core cpi", "consumer price index", "cpi m/m", "cpi y/y"),
     "🇺🇸 CPI／Core CPI ★★★★★", 5),
    ("PPI", ("core ppi", "producer price index", "ppi m/m", "ppi y/y"),
     "🇺🇸 PPI／Core PPI ★★★★★", 5),
    ("PCE", ("core pce", "pce price index", "personal income and outlays"),
     "🇺🇸 PCE／Core PCE ★★★★★", 5),
    ("GDP", ("advance gdp", "prelim gdp", "final gdp", "gross domestic product", "gdp q/q"),
     "🇺🇸 GDP ★★★★★", 5),
    ("FOMC", ("federal funds rate", "fomc statement", "fomc economic projections"),
     "🇺🇸 FOMC 利率決議 ★★★★★", 5),
    ("FOMC_MINUTES", ("fomc meeting minutes",), "🇺🇸 FOMC 會議紀要 ★★★★", 4),
    ("POWELL", ("fed chair powell speaks", "fed chair powell press conference"),
     "🇺🇸 Fed 主席記者會／談話 ★★★★★", 5),
    ("RETAIL", ("core retail sales", "retail sales", "advance monthly sales"),
     "🇺🇸 零售銷售 Retail Sales ★★★★★", 5),
    ("ISM_MFG", ("ism manufacturing pmi", "ism manufacturing"), "🇺🇸 ISM 製造業 PMI ★★★★★", 5),
    ("ISM_SERVICES", ("ism services pmi", "ism non-manufacturing pmi", "ism services"), "🇺🇸 ISM 服務業 PMI ★★★★★", 5),
    ("JOLTS", ("jolts job openings", "job openings and labor turnover"),
     "🇺🇸 JOLTS 職缺數 ★★★★", 4),
    ("ADP", ("adp non-farm employment change",), "🇺🇸 ADP 就業人數 ★★★★", 4),
    ("CLAIMS", ("unemployment claims", "initial jobless claims"),
     "🇺🇸 初領失業救濟金 ★★★★", 4),
    ("DURABLE", ("core durable goods orders", "durable goods orders", "advance report on durable goods"),
     "🇺🇸 耐久財訂單 ★★★★", 4),
    ("CONSUMER_CONF", ("cb consumer confidence", "consumer confidence"),
     "🇺🇸 消費者信心指數 ★★★★", 4),
    ("UOM", ("prelim uom consumer sentiment", "revised uom consumer sentiment"),
     "🇺🇸 密大消費者信心 ★★★★", 4),
    ("TRADE", ("trade balance", "international trade in goods and services"),
     "🇺🇸 美國貿易收支 ★★★★", 4),
    ("HOUSING_STARTS", ("housing starts", "building permits", "new residential construction"),
     "🇺🇸 新屋開工／營建許可 ★★★★", 4),
    ("NEW_HOME", ("new home sales", "new residential sales"),
     "🇺🇸 新屋銷售 ★★★★", 4),
]



def canonical_market_title(key: str, raw_title: str, default_title: str) -> str:
    """Return clear Chinese labels while preserving headline/core variants."""
    raw = clean(raw_title).lower()

    if key == "CPI":
        if "core" in raw:
            return "🇺🇸 Core CPI（核心消費者物價）★★★★★"
        if "y/y" in raw:
            return "🇺🇸 CPI 年增率 ★★★★★"
        if "m/m" in raw:
            return "🇺🇸 CPI 月增率 ★★★★★"
        return "🇺🇸 CPI（消費者物價指數）★★★★★"

    if key == "PPI":
        if "core" in raw:
            return "🇺🇸 Core PPI（核心生產者物價）★★★★★"
        if "y/y" in raw:
            return "🇺🇸 PPI 年增率 ★★★★★"
        if "m/m" in raw:
            return "🇺🇸 PPI 月增率 ★★★★★"
        return "🇺🇸 PPI（生產者物價指數）★★★★★"

    if key == "PCE":
        if "core" in raw:
            return "🇺🇸 Core PCE（核心個人消費支出物價）★★★★★"
        return "🇺🇸 PCE（個人消費支出物價）★★★★★"

    if key == "RETAIL":
        if "core" in raw:
            return "🇺🇸 Core Retail Sales（核心零售銷售）★★★★★"
        return "🇺🇸 Retail Sales（零售銷售）★★★★★"

    if key == "DURABLE":
        if "core" in raw:
            return "🇺🇸 Core Durable Goods（核心耐久財訂單）★★★★"
        return "🇺🇸 Durable Goods Orders（耐久財訂單）★★★★"

    if key == "HOUSING_STARTS":
        if "building permit" in raw:
            return "🇺🇸 Building Permits（營建許可）★★★★"
        if "housing start" in raw:
            return "🇺🇸 Housing Starts（新屋開工）★★★★"
        return "🇺🇸 新屋開工／營建許可 ★★★★"

    if key == "NFP":
        return "🇺🇸 Non-Farm Payrolls（非農就業）★★★★★"

    if key == "UNEMPLOYMENT":
        return "🇺🇸 Unemployment Rate（失業率）★★★★★"

    if key == "EARNINGS":
        return "🇺🇸 Average Hourly Earnings（平均時薪）★★★★★"

    if key == "ADP":
        return "🇺🇸 ADP Employment（ADP 就業）★★★★"

    return default_title


def event_variant(key: str, raw_title: str) -> str:
    """Stable subtype used for deduplication without merging headline/core data."""
    raw = clean(raw_title).lower()

    if key in {"CPI", "PPI"}:
        if "core" in raw:
            return "core"
        if "y/y" in raw:
            return "yy"
        if "m/m" in raw:
            return "mm"
        return "headline"

    if key == "PCE":
        return "core" if "core" in raw else "headline"

    if key in {"RETAIL", "DURABLE"}:
        return "core" if "core" in raw else "headline"

    if key == "HOUSING_STARTS":
        if "building permit" in raw:
            return "permits"
        if "housing start" in raw:
            return "starts"
        return "combined"

    if key == "GDP":
        if "advance" in raw:
            return "advance"
        if "prelim" in raw or "second estimate" in raw:
            return "second"
        if "final" in raw or "third estimate" in raw:
            return "final"
        return "generic"

    return "default"


def attach_variant(key: str, raw_title: str) -> str:
    return f"{key}:{event_variant(key, raw_title)}:{clean(raw_title).lower()}"

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



def parse_ics_property(line: str) -> tuple[str, str, dict[str, str]]:
    left, value = line.split(":", 1)
    parts = left.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            key, param_value = part.split("=", 1)
            params[key.upper()] = param_value
    return name, value, params


def parse_feed_datetime(raw_value: str, params: dict[str, str]) -> datetime | None:
    value = raw_value.strip()
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", value):
        # All-day / tentative releases cannot provide a useful trading timestamp.
        return None

    try:
        if value.endswith("Z"):
            parsed = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            return parsed.astimezone(ET)

        parsed = datetime.strptime(value, "%Y%m%dT%H%M%S")
        tzid = params.get("TZID", "America/New_York").strip('"')
        try:
            zone = ZoneInfo(tzid)
        except Exception:
            zone = ET
        return parsed.replace(tzinfo=zone).astimezone(ET)
    except ValueError:
        return None


def event_is_usd(properties: dict[str, list[tuple[str, dict[str, str]]]]) -> bool:
    searchable_names = (
        "SUMMARY",
        "DESCRIPTION",
        "CATEGORIES",
        "LOCATION",
        "X-CURRENCY",
        "X-COUNTRY",
    )
    searchable = " ".join(
        value
        for name in searchable_names
        for value, _params in properties.get(name, [])
    )
    normalized = clean(unescape_ics(searchable)).lower()

    usd_patterns = (
        r"(?<![a-z])usd(?![a-z])",
        r"\bunited states\b",
        r"\bu\.s\.\b",
        r"\bus economic\b",
        r"\bcountry\s*[:=-]\s*us(?:a)?\b",
        r"\bcurrency\s*[:=-]\s*usd\b",
    )
    return any(re.search(pattern, normalized, re.I) for pattern in usd_patterns)


def feed_impact(properties: dict[str, list[tuple[str, dict[str, str]]]]) -> str:
    searchable = " ".join(
        value
        for name in ("DESCRIPTION", "CATEGORIES", "SUMMARY")
        for value, _params in properties.get(name, [])
    )
    normalized = clean(unescape_ics(searchable)).lower()

    if re.search(r"\b(high|red|3[- ]?star|three[- ]?star)\b", normalized):
        return "High"
    if re.search(r"\b(medium|orange|2[- ]?star|two[- ]?star)\b", normalized):
        return "Medium"
    if re.search(r"\b(low|yellow|1[- ]?star|one[- ]?star)\b", normalized):
        return "Low"
    return "Unknown"


def first_ics_value(
    properties: dict[str, list[tuple[str, dict[str, str]]]],
    name: str,
) -> tuple[str, dict[str, str]]:
    values = properties.get(name, [])
    return values[0] if values else ("", {})


def parse_fair_economy_ics(feed_text: str, source_url: str) -> list[Event]:
    events: list[Event] = []
    properties: dict[str, list[tuple[str, dict[str, str]]]] | None = None

    for line in unfold_ics(feed_text):
        if line == "BEGIN:VEVENT":
            properties = {}
            continue

        if line == "END:VEVENT":
            if not properties or not event_is_usd(properties):
                properties = None
                continue

            summary_raw, _ = first_ics_value(properties, "SUMMARY")
            description_raw, _ = first_ics_value(properties, "DESCRIPTION")
            start_raw, start_params = first_ics_value(properties, "DTSTART")
            url_raw, _ = first_ics_value(properties, "URL")

            raw_title = clean(unescape_ics(summary_raw))
            description = unescape_ics(description_raw)
            start = parse_feed_datetime(start_raw, start_params)
            info = classify(f"{raw_title} {description}")
            impact = feed_impact(properties)

            # Only retain events in Roy's important-event list. This removes
            # minor US releases even when the source calendar contains all USD events.
            if start is None or info is None or impact == "Low":
                properties = None
                continue

            key, title, configured_importance = info
            title = canonical_market_title(key, raw_title, title)
            importance = 5 if impact == "High" else min(configured_importance, 4)
            details = [
                f"原始事件：{raw_title}",
                f"Impact：{impact}",
                "此事件由全球行事曆中依 USD／United States 自動過濾。",
            ]
            if description:
                details.append(f"來源內容：{clean(description)}")

            events.append(
                Event(
                    attach_variant(key, raw_title),
                    title,
                    start,
                    "Fair Economy ICS（USD filtered）",
                    clean(unescape_ics(url_raw)) or source_url,
                    importance,
                    30,
                    "\n".join(details),
                )
            )
            properties = None
            continue

        if properties is not None and ":" in line:
            try:
                name, value, params = parse_ics_property(line)
            except ValueError:
                continue
            properties.setdefault(name, []).append((value, params))

    return events


def get_fair_economy_ics_events() -> tuple[list[Event], int]:
    events: list[Event] = []
    successful_feeds = 0

    for url in FF_ICS_FEEDS:
        try:
            feed_text = fetch(url, accept="text/calendar,text/plain,*/*")
            batch = parse_fair_economy_ics(feed_text, url)
            successful_feeds += 1
            events.extend(batch)
            print(f"Fair Economy ICS: {url}: {len(batch)} matched USD events")
        except Exception as exc:
            print(f"Fair Economy ICS failed: {url}: {exc}")

    return events, successful_feeds

def ff_value(node: ETXML.Element, tag: str) -> str:
    child = node.find(tag)
    return clean(child.text if child is not None and child.text else "")


def parse_ff_datetime(date_text: str, time_text: str) -> datetime | None:
    date_text = clean(date_text)
    time_text = clean(time_text).lower()

    if not date_text or time_text in {"", "all day", "tentative"}:
        return None

    # The public feed uses mm-dd-yyyy and New York market time.
    for date_format in ("%m-%d-%Y", "%m/%d/%Y"):
        try:
            day = datetime.strptime(date_text, date_format)
            break
        except ValueError:
            day = None
    if day is None:
        return None

    normalized_time = time_text.replace(" ", "")
    for time_format in ("%I:%M%p", "%I%p", "%H:%M"):
        try:
            tm = datetime.strptime(normalized_time, time_format).time()
            # Fair Economy / Forex Factory XML times are GMT/UTC.
            # Convert to New York so Apple can later convert correctly to Taiwan.
            return datetime.combine(day.date(), tm, tzinfo=UTC).astimezone(ET)
        except ValueError:
            continue
    return None


def get_forex_factory_events() -> tuple[list[Event], int]:
    events: list[Event] = []
    successful_feeds = 0

    for url in FF_FEEDS:
        try:
            text = fetch(url, accept="application/xml,text/xml,text/plain,*/*")
            root = ETXML.fromstring(text)
            successful_feeds += 1
        except Exception as exc:
            print(f"Forex Factory feed failed: {url}: {exc}")
            continue

        matched = 0
        for node in root.findall(".//event"):
            country = ff_value(node, "country").upper()
            if country != "USD":
                continue

            raw_title = ff_value(node, "title")
            info = classify(raw_title)
            if not info:
                continue

            impact_text = ff_value(node, "impact").lower()
            if impact_text == "low":
                continue

            start = parse_ff_datetime(ff_value(node, "date"), ff_value(node, "time"))
            if start is None:
                continue

            key, title, configured_importance = info
            title = canonical_market_title(key, raw_title, title)
            importance = 5 if impact_text == "high" else min(configured_importance, 4)

            actual = ff_value(node, "actual")
            forecast = ff_value(node, "forecast")
            previous = ff_value(node, "previous")
            detail_url = ff_value(node, "url") or url

            details = [f"原始事件：{raw_title}"]
            if actual:
                details.append(f"Actual：{actual}")
            if forecast:
                details.append(f"Forecast：{forecast}")
            if previous:
                details.append(f"Previous：{previous}")
            details.append(f"Impact：{ff_value(node, 'impact') or 'Unknown'}")

            # Keep separate releases such as headline/core CPI while giving them
            # stable unique IDs via the original title.
            unique_key = attach_variant(key, raw_title)
            events.append(
                Event(
                    unique_key,
                    title,
                    start,
                    "Forex Factory / Fair Economy",
                    detail_url,
                    importance,
                    30,
                    "\n".join(details),
                )
            )
            matched += 1

        print(f"Forex Factory: {url}: {matched} matched US events")

    return events, successful_feeds


def rows(soup: BeautifulSoup) -> Iterable[list[str]]:
    for tr in soup.select("tr"):
        cells = [clean(c.get_text(" ", strip=True)) for c in tr.select("th,td")]
        cells = [c for c in cells if c]
        if len(cells) >= 2:
            yield cells


def parse_date_time_from_cells(cells: list[str], default=(8, 30)) -> datetime | None:
    joined = " | ".join(cells)
    date_match = re.search(
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
        r"Dec(?:ember)?)\s+\d{1,2}(?:,\s*20\d{2})?",
        joined,
        re.I,
    )
    if not date_match:
        return None

    time_match = re.search(r"\b\d{1,2}:\d{2}\s*(?:AM|PM)\b", joined, re.I)
    value = date_match.group(0)
    if time_match:
        value += " " + time_match.group(0)

    try:
        parsed = dtparser.parse(
            value,
            fuzzy=True,
            default=datetime(CURRENT_YEAR, 1, 1, *default),
        )
        if parsed.year < CURRENT_YEAR - 1 or parsed.year > CURRENT_YEAR + 2:
            return None
        return parsed.replace(tzinfo=ET)
    except (ValueError, TypeError, OverflowError):
        return None


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
            joined = " | ".join(cells)
            info = classify(joined)
            if not info:
                continue
            start = parse_date_time_from_cells(cells)
            if not start:
                continue
            key, title, importance = info
            found.append(Event(key, title, start, source, url, importance))
        print(f"{source}: {url}: {len(found) - before} matched rows")
    return found



FRED_RELEASES = (
    ("CPI", 10, "🇺🇸 CPI／Core CPI ★★★★★", 5),
    ("PPI", 46, "🇺🇸 PPI／Core PPI ★★★★★", 5),
    ("NFP", 50, "🇺🇸 NFP／失業率／平均時薪 ★★★★★", 5),
    ("PCE", 54, "🇺🇸 PCE／Core PCE ★★★★★", 5),
    ("GDP", 53, "🇺🇸 GDP ★★★★★", 5),
)


def parse_fred_calendar_text(
    page_text: str,
    key: str,
    title: str,
    importance: int,
    source_url: str,
) -> list[Event]:
    """Parse a FRED release calendar.

    FRED displays release times in US Central Time. The page text typically
    contains entries in either:
      DATE [Updated] TIME RELEASE
    or:
      TIME RELEASE DATE [Updated]
    order. Both forms are supported.
    """
    normalized = clean(page_text)
    month = (
        r"(?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)"
    )
    weekday = r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
    date_pat = rf"{weekday}\s+{month}\s+\d{{1,2}},\s+20\d{{2}}"
    time_pat = r"(?:\d{1,2}:\d{2}\s*(?:am|pm)|N/A)"
    release_names = {
        "CPI": "Consumer Price Index",
        "PPI": "Producer Price Index",
        "NFP": "Employment Situation",
        "PCE": "Personal Income and Outlays",
        "GDP": "Gross Domestic Product",
    }
    release_name = release_names[key]

    patterns = (
        rf"(?P<date>{date_pat})(?:\s+Updated)?\s+(?P<time>{time_pat})\s+{re.escape(release_name)}",
        rf"(?P<time>{time_pat})\s+{re.escape(release_name)}\s+(?P<date>{date_pat})(?:\s+Updated)?",
    )

    matches: list[tuple[str, str]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, normalized, re.I):
            pair = (match.group("date"), match.group("time"))
            if pair not in matches:
                matches.append(pair)

    events: list[Event] = []
    for date_text, time_text in matches:
        if time_text.upper() == "N/A":
            continue
        try:
            local_ct = dtparser.parse(f"{date_text} {time_text}", fuzzy=True)
            local_ct = local_ct.replace(tzinfo=CT)
            start = local_ct.astimezone(ET)
        except (ValueError, TypeError, OverflowError):
            continue

        events.append(
            Event(
                key,
                title,
                start,
                "FRED / Federal Reserve Bank of St. Louis",
                source_url,
                importance,
                30,
                f"FRED 發布日曆原始項目：{release_name}\n"
                "FRED 頁面時間為美國中部時間，程式已轉成美東時間。",
            )
        )
    return events


def get_fred_events() -> tuple[list[Event], dict[str, int]]:
    events: list[Event] = []
    counts: dict[str, int] = {}
    start_year = CURRENT_YEAR
    end_year = CURRENT_YEAR + 1

    for key, release_id, title, importance in FRED_RELEASES:
        url = (
            "https://fred.stlouisfed.org/releases/calendar"
            f"?od=asc&rid={release_id}&view=year"
            f"&vs={start_year}-01-01&ve={end_year}-12-31"
        )
        try:
            soup = BeautifulSoup(fetch(url), "lxml")
            batch = parse_fred_calendar_text(
                soup.get_text(" ", strip=True),
                key,
                title,
                importance,
                url,
            )
        except Exception as exc:
            print(f"FRED {key} fetch failed: {url}: {exc}")
            batch = []

        counts[key] = len(batch)
        events.extend(batch)
        print(f"FRED {key}: {len(batch)} events")

    return events, counts

def get_bea_events() -> list[Event]:
    return parse_schedule(
        (
            "https://www.bea.gov/news/schedule",
            "https://www.bea.gov/news/schedule/next-year",
        ),
        "BEA",
    )


def get_census_events() -> list[Event]:
    return parse_schedule(
        ("https://www.census.gov/economic-indicators/calendar-listview.html",),
        "US Census",
    )


def get_fomc_events() -> list[Event]:
    """Return only verified FOMC decision dates.

    The old parser searched a large flattened Fed webpage section and could
    accidentally interpret unrelated dates as meetings. This strict map is
    intentionally conservative: only checked meeting-end dates are emitted.
    Update the next-year list once the Federal Reserve publishes it.
    """
    url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
    verified_dates = {
        2026: (
            "January 28",
            "March 18",
            "April 29",
            "June 17",
            "July 29",
            "September 16",
            "October 28",
            "December 9",
        ),
        2027: (
            "January 27",
            "March 17",
            "April 28",
            "June 9",
            "July 28",
            "September 15",
            "October 27",
            "December 8",
        ),
    }

    events: list[Event] = []
    for year in YEARS:
        items = verified_dates.get(year, ())
        if not items:
            print(f"WARNING: no verified FOMC dates configured for {year}")
            continue

        for item in items:
            day = dtparser.parse(f"{item}, {year}").date()
            events.extend(
                (
                    Event(
                        "FOMC",
                        "🇺🇸 FOMC 利率決議 ★★★★★",
                        datetime(day.year, day.month, day.day, 14, 0, tzinfo=ET),
                        "Federal Reserve",
                        url,
                        5,
                        30,
                        "日期依聯準會官方會議行事曆核對。",
                    ),
                    Event(
                        "FOMC_PRESS",
                        "🇺🇸 Fed 主席記者會 ★★★★★",
                        datetime(day.year, day.month, day.day, 14, 30, tzinfo=ET),
                        "Federal Reserve",
                        url,
                        5,
                        60,
                        "記者會時間固定排在利率決議後 30 分鐘。",
                    ),
                )
            )

    print(f"get_fomc_events: {len(events)} verified events")
    return events

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
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def parse_existing_datetime(name: str, value: str) -> datetime | None:
    try:
        if value.endswith("Z"):
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).astimezone(ET)
        parsed = datetime.strptime(value, "%Y%m%dT%H%M%S")
        tz_match = re.search(r"TZID=([^;:]+)", name, re.I)
        zone = ET
        if tz_match:
            try:
                zone = ZoneInfo(tz_match.group(1))
            except Exception:
                pass
        return parsed.replace(tzinfo=zone).astimezone(ET)
    except ValueError:
        return None


def load_existing_events() -> list[Event]:
    """Keep only safe future events from the previously published ICS.

    Old v3 files may contain false FOMC dates and duplicate raw official titles.
    FOMC/Fed events are always rebuilt from the verified date map, while other
    events are retained only when they have a recognized canonical key.
    """
    if not OUT_ICS.exists():
        return []

    try:
        source_text = OUT_ICS.read_text(encoding="utf-8")
    except OSError:
        return []

    now = datetime.now(ET)
    events: list[Event] = []
    block: dict[str, str] | None = None

    for line in unfold_ics(source_text):
        if line == "BEGIN:VEVENT":
            block = {}
            continue

        if line == "END:VEVENT":
            if not block:
                block = None
                continue

            dt_entry = next(
                ((k, v) for k, v in block.items() if k.startswith("DTSTART")),
                None,
            )
            start = parse_existing_datetime(*dt_entry) if dt_entry else None
            summary = unescape_ics(block.get("SUMMARY", ""))
            key = unescape_ics(block.get("X-ROY-KEY", ""))
            base = base_key(key)

            if not start or start < now - timedelta(days=2):
                block = None
                continue

            # Never retain old Fed/FOMC entries; rebuild from verified dates.
            if base in {"FOMC", "FOMC_PRESS", "FOMC_MINUTES", "POWELL"}:
                block = None
                continue

            # Drop old raw-title copies such as "EXISTING:美國 ...".
            if not key or base == "EXISTING":
                block = None
                continue

            recognized = {item[0] for item in RELEASES}
            if base not in recognized:
                block = None
                continue

            description = unescape_ics(block.get("DESCRIPTION", ""))
            source_match = re.search(r"來源：([^\n]+)", description)
            source = source_match.group(1).strip() if source_match else "Existing calendar"
            url = unescape_ics(block.get("URL", ""))
            importance = 5 if "★★★★★" in summary else 4
            events.append(Event(key, summary, start, source, url, importance))
            block = None
            continue

        if block is not None and ":" in line:
            name, value = line.split(":", 1)
            block[name if name.startswith("DTSTART") else name.split(";", 1)[0]] = value

    print(f"Loaded {len(events)} safe events from existing ICS")
    return events

def escape_ics(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("\n", r"\n")
    )


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
    description_parts = [
        f"來源：{event.source}",
        f"重要程度：{'★' * event.importance}",
    ]
    if event.description_extra:
        description_parts.append(event.description_extra)
    description_parts.extend(
        (
            "時間以美東時區發布，Apple 行事曆會自動換算台灣時間。",
            f"來源網址：{event.url}",
        )
    )
    description = "\n".join(description_parts)

    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid(event)}",
        f"X-ROY-KEY:{escape_ics(event.key)}",
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
        lines.extend(
            (
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{escape_ics(event.title)}",
                f"TRIGGER:-PT{minutes}M",
                "END:VALARM",
            )
        )
    lines.append("END:VEVENT")
    return lines


def base_key(key: str) -> str:
    return key.split(":", 1)[0]


def key_variant(key: str) -> str:
    parts = key.split(":")
    return parts[1] if len(parts) >= 2 else "generic"

def validate(
    events: list[Event],
    ics_successful_feeds: int,
    ics_events: list[Event],
    ff_successful_feeds: int,
    ff_events: list[Event],
    fred_counts: dict[str, int],
) -> None:
    now = datetime.now(ET)
    future = [e for e in events if e.start >= now - timedelta(days=2)]
    counts: dict[str, int] = {}
    for event in future:
        key = base_key(event.key)
        counts[key] = counts.get(key, 0) + 1

    print("Calendar validation:")
    for key in ("CPI", "PPI", "NFP", "PCE", "GDP", "FOMC", "RETAIL", "ISM_MFG", "ISM_SERVICES"):
        print(f"  {key}: {counts.get(key, 0)}")
    print(f"  Fair Economy ICS feeds fetched: {ics_successful_feeds}/{len(FF_ICS_FEEDS)}")
    print(f"  Fair Economy ICS matched USD events: {len(ics_events)}")
    print(f"  Forex Factory XML feeds fetched: {ff_successful_feeds}/{len(FF_FEEDS)}")
    print(f"  Forex Factory matched US events: {len(ff_events)}")
    print(f"  Total future events: {len(future)}")
    print("  FRED source counts:")
    for key in ("CPI", "PPI", "NFP", "PCE", "GDP"):
        print(f"    {key}: {fred_counts.get(key, 0)}")

    # Critical distinction: CPI/PPI/NFP are monthly and will legitimately not
    # appear in a given two-week feed. Validate source health, not the presence
    # of every monthly release on every run.
    fred_critical_ok = all(fred_counts.get(key, 0) > 0 for key in ("CPI", "PPI", "NFP"))
    ics_ok = ics_successful_feeds > 0 and len(ics_events) > 0
    ff_ok = ff_successful_feeds > 0 and len(ff_events) > 0

    if not ics_ok and not ff_ok and not fred_critical_ok:
        raise RuntimeError(
            "Calendar validation failed: Fair Economy ICS, Forex Factory XML, "
            "and critical FRED calendars were all unavailable; refusing to "
            "overwrite the existing ICS."
        )
    fomc_events = [e for e in future if base_key(e.key) == "FOMC"]
    if not fomc_events:
        raise RuntimeError("Calendar validation failed: no future FOMC decision found.")

    if any(event.start.weekday() >= 5 for event in fomc_events):
        raise RuntimeError("Calendar validation failed: a FOMC decision was placed on a weekend.")

    fomc_dates = [event.start.date() for event in fomc_events]
    if len(fomc_dates) != len(set(fomc_dates)):
        raise RuntimeError("Calendar validation failed: duplicate FOMC decision dates found.")
    if len(future) < 10:
        raise RuntimeError(f"Calendar validation failed: only {len(future)} future events found.")


def source_priority(event: Event) -> int:
    """Higher wins when two sources describe the same release."""
    if "Forex Factory" in event.source:
        return 50  # usually contains actual / forecast / previous
    if "Fair Economy ICS" in event.source:
        return 40
    if event.source == "Federal Reserve":
        return 45
    if event.source in {"BEA", "US Census"}:
        return 35
    if "FRED" in event.source:
        return 30
    if event.source == "Existing calendar":
        return 10
    return 20


def dedupe_bucket(event: Event) -> tuple[str, str, str, int]:
    """Group only the same subtype occurring within a 15-minute window."""
    family = base_key(event.key)
    variant = key_variant(event.key)
    day = event.start.strftime("%Y-%m-%d")
    quarter_hour = round((event.start.hour * 60 + event.start.minute) / 15)
    return family, variant, day, quarter_hour


def merge_events(
    existing: list[Event],
    fetched: list[Event],
    rolling_events: list[Event],
) -> list[Event]:
    now = datetime.now(ET)
    lower = now - timedelta(days=2)
    upper = now + timedelta(days=550)
    refresh_end = now + timedelta(days=16)

    kept_existing = [
        event
        for event in existing
        if lower <= event.start <= upper
        and event.start > refresh_end
    ]

    rolling_family_days = {
        (base_key(event.key), event.start.date())
        for event in rolling_events
    }

    filtered_fetched: list[Event] = []
    for event in fetched:
        family_day = (base_key(event.key), event.start.date())
        if (
            event.start <= refresh_end
            and family_day in rolling_family_days
            and base_key(event.key) not in {"FOMC", "FOMC_PRESS"}
        ):
            continue
        filtered_fetched.append(event)

    all_events = kept_existing + filtered_fetched + rolling_events
    unique: dict[tuple[str, str, str, int], Event] = {}
    duplicates_removed = 0

    for event in all_events:
        if not (lower <= event.start <= upper):
            continue

        # FOMC and press conference are accepted only from the Fed source.
        if base_key(event.key) in {"FOMC", "FOMC_PRESS"} and event.source != "Federal Reserve":
            duplicates_removed += 1
            continue

        bucket = dedupe_bucket(event)
        current = unique.get(bucket)

        if current is None:
            unique[bucket] = event
            continue

        duplicates_removed += 1
        if source_priority(event) > source_priority(current):
            unique[bucket] = event

    result = sorted(unique.values(), key=lambda event: (event.start, event.title))
    print(f"Duplicates / unsafe entries removed: {duplicates_removed}")
    print(f"Final merged events: {len(result)}")
    by_family: dict[str, int] = {}
    for item in result:
        family = base_key(item.key)
        by_family[family] = by_family.get(family, 0) + 1
    print("Final event counts:")
    for family in sorted(by_family):
        print(f"  {family}: {by_family[family]}")
    return result

def write(
    events: list[Event],
    ics_successful_feeds: int,
    ics_events: list[Event],
    ff_successful_feeds: int,
    ff_events: list[Event],
    fred_counts: dict[str, int],
) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    validate(
        events,
        ics_successful_feeds,
        ics_events,
        ff_successful_feeds,
        ff_events,
        fred_counts,
    )

    now = datetime.now(UTC)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Roy Cheng//US Economic Calendar v6.0//ZH-TW",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:美國重大經濟數據",
        "X-WR-CALDESC:美國四星／五星重要數據；自動去重並正確換算台灣時間",
        "X-WR-TIMEZONE:Asia/Taipei",
    ]
    for event in events:
        lines.extend(to_ics(event, now))
    lines.append("END:VCALENDAR")

    OUT_ICS.write_text(
        "\r\n".join(fold(line) for line in lines) + "\r\n",
        encoding="utf-8",
    )

    updated = now.astimezone(TPE).strftime("%Y-%m-%d %H:%M:%S")
    OUT_HTML.write_text(
        f"""<!doctype html>
<html lang="zh-Hant">
<head><meta charset="utf-8"><title>美國重大經濟數據行事曆</title></head>
<body>
<h1>美國重大經濟數據行事曆</h1>
<p>最後更新：{updated}（台灣時間）</p>
<p><a href="us-economic-calendar.ics">下載／訂閱 ICS</a></p>
<p>包含 CPI、Core CPI、PPI、Core PPI、PCE、Core PCE、NFP、GDP、FOMC 等。</p>
</body>
</html>
""",
        encoding="utf-8",
    )
    print(f"Wrote {len(events)} validated events to {OUT_ICS}")


def main() -> None:
    existing = load_existing_events()
    print(f"Loaded {len(existing)} events from existing ICS")

    ics_events, ics_successful_feeds = get_fair_economy_ics_events()
    ff_events, ff_successful_feeds = get_forex_factory_events()
    fred_events, fred_counts = get_fred_events()

    official_events: list[Event] = list(fred_events)
    for getter in (get_bea_events, get_census_events, get_fomc_events):
        try:
            batch = getter()
            print(f"{getter.__name__}: {len(batch)} events")
            official_events.extend(batch)
        except Exception as exc:
            print(f"{getter.__name__} failed: {exc}")

    # ICS is the primary near-term source; XML enriches the same releases
    # with Forecast / Previous / Actual when available.
    rolling_events = ics_events + ff_events
    merged = merge_events(existing, official_events, rolling_events)
    write(
        merged,
        ics_successful_feeds,
        ics_events,
        ff_successful_feeds,
        ff_events,
        fred_counts,
    )


if __name__ == "__main__":
    main()
