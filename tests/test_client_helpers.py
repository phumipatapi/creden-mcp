"""Lightweight unit tests for pure helpers (no network)."""

from creden_mcp.client import _wildcard_q


def test_wildcard_q_thai():
    # 'ทดสอบ' → 'ท *ด *ส *อ *บ'
    assert _wildcard_q("ทดสอบ") == "ท *ด *ส *อ *บ"


def test_wildcard_q_single_char():
    assert _wildcard_q("A") == "A"


def test_wildcard_q_empty():
    assert _wildcard_q("") == ""


def test_wildcard_q_english():
    assert _wildcard_q("CP") == "C *P"
