# Creden MCP Server

MCP server ให้ AI agent (Claude Desktop / Claude Code) ค้นหาข้อมูลบริษัทจาก [data.creden.co](https://data.creden.co) โดยใช้ชื่อภาษาไทย — ไม่ต้อง login, ไม่กิน API quota

## ทำอะไรได้

```
"คลาวด์เทค"  →  บริษัท คลาวด์เทค จำกัด (id=0105566076008)
              ทุน 1,000,000 บาท · จดทะเบียน 10 เม.ย. 2566 · ICT
              งบ 2 ปี: 2566 รายได้ 2.2M ขาดทุน 41K
                     2567 รายได้ 6.0M กำไร 342K (+169% YoY)
```

ทำงานด้วย 2 step ที่เป็น **public** ทั้งคู่ (ไม่ต้อง credentials):

1. `POST /sapi/search/get_suggestion` — ชื่อ → company_id
2. `GET /company/general/<id>` — HTML ที่ Nuxt hydrate ข้อมูลทั้งหมดมาแล้ว → parse

ข้อมูลที่ได้ต่อบริษัท:
- ชื่อ TH/EN, juristic id, จดทะเบียน, ทุน, อุตสาหกรรม, ที่อยู่, วัตถุประสงค์
- งบการเงิน 2-10 ปี (ขึ้นกับว่าบริษัทยื่นไว้กี่ปี): รายได้รวม, กำไร/ขาดทุน, สินทรัพย์, หนี้สิน, ส่วนผู้ถือหุ้น, NET_PROFIT_MARGIN, YoY %
- chart data (สำหรับ visualization)

## Setup (Claude Code)

```bash
# 1. Install
python3 -m venv .venv
.venv/bin/pip install -e .

# 2. Register with Claude Code (user scope = available in all projects)
claude mcp add creden --scope user $(pwd)/.venv/bin/creden-mcp

# 3. Verify
claude mcp list | grep creden        # → ✓ Connected
```

จากนั้นใน Claude Code ใหม่ พิมพ์ขอข้อมูลได้เลย เช่น:
- "งบการเงิน 5 ปีย้อนหลังของบริษัท แอด ฮีโร่"
- "ค้นบริษัทชื่อ คลาวด์เทค"
- "ดู MCS Steel"

ถ้าจะใช้กับ **Claude Desktop** แทน:

```json
// ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "creden": {
      "command": "/absolute/path/to/.venv/bin/creden-mcp"
    }
  }
}
```

## ถอนการติดตั้ง

```bash
claude mcp remove creden
```

## Note

ไม่ต้อง config อะไร — `.env` มีไว้เผื่อใช้ authenticated endpoints (filter search) เท่านั้น, ไม่จำเป็น

## MCP Tools

| Tool | Purpose |
|---|---|
| `creden_lookup(query)` | **Main tool**: รับชื่อหรือ id 13 หลัก → profile + งบ + กรรมการ ครบ |
| `creden_search(text)` | คืน list ของ candidates (ใช้เมื่อชื่อซ้ำกัน) |

`creden_lookup` รวมทุกอย่างใน call เดียว:
- **Profile** (no auth) — ชื่อ, juristic id, จดทะเบียน, ทุน, อุตสาหกรรม, ที่อยู่
- **Fiscal years** (no auth) — รายได้, กำไร, สินทรัพย์, หนี้สิน, equity, NPM, YoY%
- **Directors** (auth) — กรรมการ/ผู้มีอำนาจลงนาม. ต้องตั้ง `CREDEN_EMAIL`/
  `CREDEN_PASSWORD` ใน `.env`. ผลถูก cache 30 วันต่อบริษัท → กิน point ครั้งแรก
  เท่านั้น. ถ้าไม่ตั้ง credentials, lookup ยังทำงานได้ปกติ — `directors` จะเป็น
  `null` พร้อม `directors_status` บอกเหตุผล.

`creden_lookup(query, full=True)` คืน DBD codes ทุก field (~50 fields/ปี).

## Tests

```bash
pytest
```

Tests รัน parser กับ HTML ของบริษัทจริง 3 รูปแบบ (5 ปี / 2 ปี / 10 ปี + มหาชน)

## Architecture

```
src/creden_mcp/
  page_parser.py   # Nuxt HTML → dict (regex-driven, var-name agnostic)
  client.py        # async httpx — public flow + optional auth flow
  server.py        # FastMCP — 2 tools wrapping client.lookup
  config.py        # env loading (.env optional)
  discovery.py     # Playwright capture (สำหรับหา endpoint ใหม่)
  models.py        # Pydantic shapes (loose)
```

## Authenticated path (optional)

มี `client.search_full()` + `client.login()` สำหรับ filter search (ทุนจดทะเบียน, จังหวัด, ฯลฯ) — ต้องการ `CREDEN_EMAIL` + `CREDEN_PASSWORD` ใน `.env`. ไม่จำเป็นถ้าใช้แค่ lookup ตามชื่อ

## ที่ยังไม่ได้ทำ

- รายชื่อผู้ถือหุ้นเต็ม (parsed page มีแค่ summary)
- network/affiliates graph
- credit term details

discovery script (`python -m creden_mcp.discovery <id>`) ใช้ Playwright capture XHR ถ้าต้องการหา endpoint เพิ่ม
