"""Validate the page parser against three real HTML fixtures.

Fixtures live in ``tests/fixtures/`` — captured from live Creden pages
during development. They cover three shapes the parser must handle:
private 5-year, brand-new 2-year, and a 10-year listed company.
"""

from __future__ import annotations

from pathlib import Path

from creden_mcp.page_parser import parse_html

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_ad_hero_has_5_years():
    parsed = parse_html(_load("ad_hero.html"))
    assert "AD HERO" in (parsed["company"].get("en") or "")
    years = [y["FISCAL_YEAR"] for y in parsed["fiscal_years"]]
    assert years == [2563, 2564, 2565, 2566, 2567]
    latest = parsed["fiscal_years"][-1]
    assert latest["BAL_IN09"] == 1720000
    assert latest["BAL_IN21"] == -995869
    assert latest["BAL_BS22_BAL_BS99"] == 1199657.29


def test_cloud_tech_has_2_years():
    parsed = parse_html(_load("cloud_tech.html"))
    assert "CLOUD TECH" in (parsed["company"].get("en") or "")
    years = sorted(y["FISCAL_YEAR"] for y in parsed["fiscal_years"])
    assert 2566 in years and 2567 in years
    latest = next(y for y in parsed["fiscal_years"] if y["FISCAL_YEAR"] == 2567)
    assert latest["BAL_IN09"] == 6050758


def test_mcs_steel_has_10_years():
    parsed = parse_html(_load("mcs_steel.html"))
    years = [y["FISCAL_YEAR"] for y in parsed["fiscal_years"]]
    assert len(years) == 10
    assert years[0] == 2558 and years[-1] == 2567
    latest = parsed["fiscal_years"][-1]
    assert latest["BAL_IN09"] == 5664991757
