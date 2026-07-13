import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "generate_calendar.py"
spec = importlib.util.spec_from_file_location("calendar_module", MODULE_PATH)
calendar = importlib.util.module_from_spec(spec)
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
    assert "Core Retail" in calendar.canonical_market_title("RETAIL", "Core Retail Sales m/m", "")
    assert "Building Permits" in calendar.canonical_market_title("HOUSING_STARTS", "Building Permits", "")
