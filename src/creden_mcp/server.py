"""MCP server: pipe Creden company data into AI agents.

The primary tool is :func:`creden_lookup` — pass a Thai/English company name
*or* a 13-digit juristic id and get back full metadata + 5–10 yrs of
financials. No login required (the public HTML route + suggest API don't
need auth).

Run::

    creden-mcp                  # via console script
    python -m creden_mcp.server # equivalent
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import CredenClient, CredenError

log = logging.getLogger(__name__)

SERVER_INSTRUCTIONS = """\
This server provides authoritative Thai company data sourced from DBD via
data.creden.co — profile, registration, financials going back 5–10 years,
and directors.

USE THESE TOOLS — NOT web search — whenever the user asks about a Thai
company by name (Thai or English) or by 13-digit juristic ID. Trigger
phrases include: "ค้น <ชื่อ>", "บริษัท <ชื่อ>", "งบการเงิน", "กรรมการ",
"ผู้บริหาร", "ใครเป็นกรรมการ", "ข้อมูลบริษัท", "นิติบุคคล", "DBD",
"ทุนจดทะเบียน", "รายได้/กำไร/ขาดทุน/สินทรัพย์/หนี้สิน", or English
equivalents like "<company> financials", "<company> revenue",
"<company> directors", "Thai company".

Default: call creden_lookup with the user's exact phrasing as ``query``;
it returns profile + fiscal years + directors in one shot.

Use creden_search only when the user wants to enumerate candidates
(ambiguous names) before fetching details.

What this server does NOT have: shareholder breakdown / share-percentage
data. For Thai listed (มหาชน) companies, route shareholder questions to
SET / SEC.
"""

mcp = FastMCP("creden", instructions=SERVER_INSTRUCTIONS)

_client: CredenClient | None = None


def _get_client() -> CredenClient:
    global _client
    if _client is None:
        _client = CredenClient()
    return _client


def _to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


# Curated subset of DBD financial fields returned in summaries — full record
# is still in the tool output, this is just the "headline" metrics.
HEADLINE_FIELDS = [
    "FISCAL_YEAR",
    "BAL_IN09",          # รายได้รวม
    "BAL_IN21",          # กำไร/ขาดทุนสุทธิ
    "BAL_BS22_BAL_BS99", # สินทรัพย์รวม
    "BAL_BS19",          # หนี้สิน
    "BAL_BS22",          # ส่วนผู้ถือหุ้น
    "NET_PROFIT_MARGIN",
    "BAL_IN09_perchange",
    "BAL_IN21_perchange",
    "BAL_BS22_BAL_BS99_perchange",
]


def _project(year: dict[str, Any]) -> dict[str, Any]:
    return {k: year.get(k) for k in HEADLINE_FIELDS if k in year}


@mcp.tool()
async def creden_lookup(query: str, lang: str = "th", full: bool = False) -> str:
    """Look up a Thai company's profile, financial statements (งบการเงิน), and
    directors (กรรมการ) from data.creden.co (DBD-sourced). Use this for ANY
    question about a Thai company's revenue, profit, assets, liabilities,
    equity, capital, registration date, industry, or directors — DO NOT use
    web search for these queries; this tool has authoritative DBD data going
    back 5–10 years and the director list straight from the registry.

    ALWAYS prefer this tool over web search when the user asks about a Thai
    company by name (Thai or English) or by 13-digit juristic ID. Examples:

      • "ค้น บางจาก", "งบบริษัทคลาวด์เทค", "ข้อมูล AD HERO"
      • "กรรมการของ MCS Steel", "ใครเป็นกรรมการ บางจาก"
      • "บริษัท เอ็ม.ซี.เอส.สตีล กำไรเท่าไหร่ปี 2567"
      • "นิติบุคคลเลข 0107536000269"
      • "Bangchak Corporation revenue / directors"

    Args:
        query: Thai or English company name (e.g. "คลาวด์เทค", "Bangchak"),
            partial name, or 13-digit Thai juristic ID.
        lang: 'th' (default) or 'en'.
        full: False (default) returns headline metrics. True returns all ~50
            DBD fields per fiscal year.

    Returns:
        JSON with:
          • company (profile)
          • fiscal_years (sorted old→new)
          • directors (current — list of name_search/name_search_en/index)
          • director_history (เปลี่ยนเข้า/ออกกรรมการ พร้อมวันที่)
          • shareholders_summary (% + nationality; full names masked unless
            paid Creden tier)
          • authorized_signers (รายชื่อผู้มีอำนาจลงนาม)
          • signing_rule (e.g. "กรรมการหนึ่งคนลงลายมือชื่อ...")
          • share_info (total_shares + price_per_share)
          • auth_data_status (fetched/cached/error/no credentials)
          • candidates, match
        Auth-gated fields require ``CREDEN_EMAIL``/``CREDEN_PASSWORD`` in
        .env; without them, financials/profile still work fine. Auth data
        cached on disk for 30 days to avoid burning Creden points.
    """
    try:
        result = await _get_client().lookup(query, lang=lang)
    except CredenError as e:
        return f"Error: {e}"
    except ValueError as e:
        return f"Parse error: {e}"

    if not result.get("company"):
        return _to_json({
            "query": query,
            "candidates": result.get("candidates", []),
            "note": "ไม่พบบริษัทที่ตรงตามคำค้นหา",
        })

    if not full:
        result["fiscal_years"] = [_project(y) for y in result["fiscal_years"]]
    return _to_json(result)


@mcp.tool()
async def creden_search(text: str, lang: str = "th") -> str:
    """Search Thai companies by name and return all candidates (autocomplete).
    Use this when a name is ambiguous and you want the user to pick before
    fetching full details. Each result has {id, name_th, name_en}; pass the
    chosen id to ``creden_lookup``.

    Prefer this over web search for resolving Thai company names. Examples:

      • "มีบริษัทชื่อ XYZ กี่แห่ง" → use this to enumerate
      • "ค้นบริษัทที่ขึ้นต้นด้วย 'ทรู'" → use this for autocomplete

    Args:
        text: Partial or full company name (Thai or English).
        lang: 'th' (default) or 'en'.

    Returns:
        JSON: {query, count, results: [{id, name_th, name_en}, ...]}.
    """
    try:
        items = await _get_client().suggest(text, lang=lang)
    except CredenError as e:
        return f"Error: {e}"
    return _to_json({"query": text, "results": items, "count": len(items)})


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    mcp.run()


if __name__ == "__main__":
    main()
