"""Parse Creden's Nuxt-hydrated company page into structured data.

Creden hydrates the entire company record (5-10 yrs of financials, metadata,
shareholders, etc.) into ``window.__NUXT__`` in the HTML, so a single GET on
the public ``/company/general/<id>`` route yields everything — no API calls,
no quota.

The parser is regex-driven and pattern-based: minified variable names shift
between pages so we match the *shape* of records, not their location.
Validated against AD HERO (5 yrs), CLOUD TECH (2 yrs), MCS STEEL (10 yrs).
"""

from __future__ import annotations

import re
from typing import Any

_NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")


def _split_iife_args(s: str) -> list[str]:
    """Split top-level commas in an IIFE argument string."""
    out: list[str] = []
    depth = 0
    buf: list[str] = []
    in_str: str | None = None
    for ch in s:
        if in_str:
            buf.append(ch)
            if ch == in_str and (len(buf) < 2 or buf[-2] != "\\"):
                in_str = None
            continue
        if ch in "\"'":
            in_str = ch
            buf.append(ch)
            continue
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if buf:
        out.append("".join(buf).strip())
    return out


_JS_UNICODE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")


def _decode_js_string(s: str) -> str:
    """Decode JS-escaped chars (``\\u002F`` etc.) without breaking UTF-8 bytes."""
    out = _JS_UNICODE_RE.sub(lambda m: chr(int(m.group(1), 16)), s)
    return (
        out.replace("\\/", "/")
        .replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .replace("\\\\", "\\")
    )


def _coerce(token: str, env: dict[str, str]) -> Any:
    token = token.strip()
    if token in env:
        token = env[token]
    if token.startswith('"') and token.endswith('"'):
        return _decode_js_string(token[1:-1])
    if token.startswith("'") and token.endswith("'"):
        return _decode_js_string(token[1:-1])
    if _NUM_RE.match(token):
        return float(token) if "." in token else int(token)
    if token in ("null", "undefined"):
        return None
    if token in ("true", "false"):
        return token == "true"
    return token


def parse_html(html: str) -> dict[str, Any]:
    """Parse a Creden ``/company/general/<id>`` HTML page → dict.

    Returns
    -------
    {
        "company": {th, en, juristic_id, register_date_th, ...},
        "fiscal_years": [{FISCAL_YEAR, BAL_IN09, BAL_IN21, ...}, ...],  # sorted asc
        "charts": [{var, index, year, data_raw}, ...],
    }
    """
    m = re.search(
        r"window\.__NUXT__\s*=\s*\(function\(([^)]+)\)\{(.+)\}\((.+)\)\);",
        html,
        re.DOTALL,
    )
    if not m:
        raise ValueError("page does not contain window.__NUXT__ IIFE")

    params = [p.strip() for p in m.group(1).split(",")]
    body = m.group(2)
    env = dict(zip(params, _split_iife_args(m.group(3))))

    company: dict[str, Any] = {}

    # Main company name: scan env (IIFE args) for strings starting with
    # "บริษัท" — partner names in C[N] blocks omit that prefix, so this
    # disambiguates reliably. English: must contain CO./LIMITED/PCL.
    th_candidates: list[str] = []
    en_candidates: list[str] = []
    for v in env.values():
        if not (v.startswith('"') and v.endswith('"')):
            continue
        s = _decode_js_string(v[1:-1])
        if s.startswith("บริษัท") and ("จำกัด" in s or "มหาชน" in s) and len(s) < 200:
            th_candidates.append(s)
        elif (
            ("CO." in s or "LIMITED" in s.upper() or "PCL" in s.upper())
            and len(s) < 200
        ):
            en_candidates.append(s)
        elif "ถนน" in s and "แขวง" in s and "address_th" not in company:
            company["address_th"] = s
        elif "ประกอบกิจการ" in s and "objective" not in company:
            company["objective"] = s
    if th_candidates:
        # Prefer the longest one (often the most complete name)
        company["th"] = max(th_candidates, key=len)
    if en_candidates:
        company["en"] = max(en_candidates, key=len)

    # Other scalar metadata fields (single occurrence in the page)
    body_fields = {
        "REG_DATE_TH": "register_date_th",
        "CAP_AMT": "register_capital",
        "tsic_desc_th": "industry_th",
        "tsic_desc_en": "industry_en",
    }
    for js_key, out_key in body_fields.items():
        match = re.search(rf'\b{js_key}\s*[:=]\s*([^,;}}\n]+)', body)
        if match and out_key not in company:
            value = _coerce(match.group(1), env)
            if value not in (None, "", 0) or out_key == "register_capital":
                company[out_key] = value

    # ---- latest-year record: <var>.FISCAL_YEAR=... -------------------------
    latest_year: dict[str, Any] | None = None
    for mm in re.finditer(r"\b([A-Za-z]+)\.FISCAL_YEAR\s*=\s*([^;]+);", body):
        var = mm.group(1)
        rec: dict[str, Any] = {}
        for am in re.finditer(rf"\b{re.escape(var)}\.(\w+)\s*=\s*([^;]+);", body):
            rec[am.group(1)] = _coerce(am.group(2), env)
        if rec.get("BAL_IN09") not in (0, None):
            latest_year = rec
            break

    # ---- historical years: inline {FISCAL_YEAR:..., ...} -------------------
    fiscal_years: list[dict[str, Any]] = []
    seen_years: set[Any] = set()
    for mm in re.finditer(r"\{[^{}]*\bFISCAL_YEAR\s*:[^{}]*\}", body):
        obj = mm.group(0)
        if len(obj) > 3000:
            continue
        rec: dict[str, Any] = {}
        depth = 0
        buf: list[str] = []
        kvs: list[str] = []
        for ch in obj[1:-1]:
            if ch in "({[":
                depth += 1
            elif ch in ")}]":
                depth -= 1
            if ch == "," and depth == 0:
                kvs.append("".join(buf))
                buf = []
                continue
            buf.append(ch)
        if buf:
            kvs.append("".join(buf))
        for kv in kvs:
            if ":" not in kv:
                continue
            k, v = kv.split(":", 1)
            rec[k.strip()] = _coerce(v, env)
        if rec.get("FISCAL_YEAR") in (None, 0):
            continue
        if rec.get("BAL_IN09") in (0, None):
            continue
        if rec["FISCAL_YEAR"] in seen_years:
            continue
        seen_years.add(rec["FISCAL_YEAR"])
        fiscal_years.append(rec)

    if latest_year and latest_year.get("FISCAL_YEAR") not in seen_years:
        fiscal_years.append(latest_year)

    fiscal_years.sort(
        key=lambda r: r["FISCAL_YEAR"] if isinstance(r["FISCAL_YEAR"], (int, float)) else 0
    )

    # ---- chart blocks: <var>[N]={year:..., data:[[...],...]} ---------------
    charts: list[dict[str, Any]] = []
    for cm in re.finditer(
        r"\b([A-Za-z]+)\[(\d+)\]\s*=\s*\{year:([^,]+),data:(\[\[.+?\]\])\}",
        body,
    ):
        charts.append({
            "var": cm.group(1),
            "index": int(cm.group(2)),
            "year": _coerce(cm.group(3), env),
            "data_raw": cm.group(4),
        })

    return {
        "company": company,
        "fiscal_years": fiscal_years,
        "charts": charts,
    }


def summary_table(parsed: dict[str, Any]) -> str:
    """Render a parsed page as a small Thai-labelled table."""
    c = parsed["company"]
    head = c.get("th") or c.get("en") or "(unknown)"
    out = [f"=== {head} ==="]
    if c.get("en") and c.get("th"):
        out.append(f"    {c['en']}")
    bits = [
        f"id={c['juristic_id']}" if c.get("juristic_id") else None,
        f"จดทะเบียน {c['register_date_th']}" if c.get("register_date_th") else None,
        f"ทุน {c['register_capital']:,.0f}" if isinstance(c.get("register_capital"), (int, float)) else None,
        c.get("industry_th"),
    ]
    line = "  •  ".join(b for b in bits if b)
    if line:
        out.append(f"    {line}")
    out.append("")
    out.append(f"{'ปี':<8}{'รายได้รวม':>18}{'กำไรสุทธิ':>18}{'สินทรัพย์รวม':>22}{'YoY%':>10}")

    def f(v: Any) -> str:
        if isinstance(v, (int, float)):
            return f"{v:,.0f}"
        return str(v) if v is not None else "-"

    for y in parsed["fiscal_years"]:
        out.append(
            f"{y.get('FISCAL_YEAR', '?')!s:<8}"
            f"{f(y.get('BAL_IN09')):>18}"
            f"{f(y.get('BAL_IN21')):>18}"
            f"{f(y.get('BAL_BS22_BAL_BS99')):>22}"
            f"{f(y.get('BAL_IN09_perchange')):>10}"
        )
    return "\n".join(out)
