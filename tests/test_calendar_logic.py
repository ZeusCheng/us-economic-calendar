import importlib.util
import sys
from datetime import datetime
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "generate_calendar.py"
spec = importlib.util.spec_from_file_location("calendar_module", MODULE_PATH)
calendar = importlib.util.module_from_spec(spec)

# dataclasses resolves the module through sys.modules during import.
sys.modules[spec.name] = calendar
assert spec.loader is not None
spec.loader.exec_module(calendar)


def test_cpi_variants_are_distinct():
    assert calendar.event_variant("CPI", "Core CPI m/m") == "core"
    assert calendar.event_variant("CPI", "CPI m/m") == "mm"
    assert calendar.event_variant("CPI", "CPI y/y") == "yy"


def test_retail_variants_are_distinct():
    assert calendar.event_variant("RETAIL", "Core Retail Sales m/m") == "core"
    assert calendar.event_variant("RETAIL", "Retail Sales m/m") == "headline"


def test_housing_variants_are_distinct():
    assert calendar.event_variant("HOUSING_STARTS", "Building Permits") == "permits"
    assert calendar.event_variant("HOUSING_STARTS", "Housing Starts") == "starts"


def test_market_titles():
    assert "Core CPI" in calendar.canonical_market_title("CPI", "Core CPI m/m", "")
    assert "Core Retail" in calendar.canonical_market_title(
        "RETAIL", "Core Retail Sales m/m", ""
    )
    assert "Building Permits" in calendar.canonical_market_title(
        "HOUSING_STARTS", "Building Permits", ""
    )


def test_xml_time_is_converted_from_utc_to_new_york():
    result = calendar.parse_ff_datetime("07-14-2026", "12:30pm")
    assert result is not None
    assert result.hour == 8
    assert result.minute == 30


def test_2027_june_fomc_is_june_9():
    events = calendar.get_fomc_events()
    june = [
        e for e in events
        if e.key == "FOMC" and e.start.year == 2027 and e.start.month == 6
    ]
    assert len(june) == 1
    assert june[0].start.day == 9
