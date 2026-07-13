#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

URL = "https://hk.investing.com/economic-calendar/Service/getCalendarFilteredData"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-HK,zh-TW;q=0.9,en-US;q=0.8,en;q=0.7",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://hk.investing.com",
    "Referer": "https://hk.investing.com/economic-calendar",
    "X-Requested-With": "XMLHttpRequest",
}

KEYWORDS = (
    "cpi",
    "consumer price index",
    "消費者物價",
    "居民消費價格",
    "消費物價",
)

def main() -> int:
    start = date.today()
    end = start + timedelta(days=14)

    payload = [
        ("dateFrom", start.isoformat()),
        ("dateTo", end.isoformat()),
        ("timeZone", "55"),
        ("timeFilter", "timeOnly"),
        ("currentTab", "custom"),
        ("submitFilters", "1"),
        ("limit_from", "0"),
        ("country[]", "5"),       # United States
        ("importance[]", "2"),    # medium
        ("importance[]", "3"),    # high
    ]

    session = requests.Session()

    # Establish cookies first. A failure here is not fatal; the POST may still work.
    try:
        landing = session.get(
            "https://hk.investing.com/economic-calendar",
            headers=HEADERS,
            timeout=30,
        )
        print(f"Landing page HTTP: {landing.status_code}")
    except Exception as exc:
        print(f"Landing page request warning: {exc}")

    response = session.post(URL, headers=HEADERS, data=payload, timeout=45)
    print(f"Calendar endpoint HTTP: {response.status_code}")
    print(f"Content-Type: {response.headers.get('content-type', '')}")
    response.raise_for_status()

    try:
        body = response.json()
    except json.JSONDecodeError:
        print("ERROR: response was not JSON.")
        print(response.text[:1000])
        return 2

    html = body.get("data", "")
    if not html:
        print("ERROR: JSON did not contain calendar HTML.")
        print(str(body)[:1000])
        return 3

    soup = BeautifulSoup(html, "lxml")
    rows = soup.select('tr[id^="eventRowId_"]')
    print(f"US medium/high-impact rows returned: {len(rows)}")

    cpi_rows = []
    for row in rows:
        text = " ".join(row.stripped_strings)
        normalized = text.lower()
        if any(keyword in normalized for keyword in KEYWORDS):
            cpi_rows.append(text)

    print(f"CPI-like rows found: {len(cpi_rows)}")
    for item in cpi_rows:
        print("CPI MATCH:", item)

    if not rows:
        print("ERROR: endpoint returned no matching US rows.")
        return 4
    if not cpi_rows:
        print(
            "WARNING: endpoint works, but no CPI was found in the next 14 days. "
            "This is only a warning because CPI is monthly."
        )
        return 0

    print("PASS: Investing.com endpoint is reachable and CPI is present.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
