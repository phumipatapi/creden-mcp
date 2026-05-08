# Project: Creden Data MCP Server

## เป้าหมาย
สร้าง MCP server ให้ AI agent (Claude) ดึงข้อมูลจาก data.creden.co ได้

## API Endpoints ที่ค้นพบแล้ว

### Auth
- `POST /sapi/authen/login`
  - Payload: `{email, password, mode: "creden"}`
  - ⚠️ ยังไม่ทราบ response structure (token/cookie?)

### Search
- `POST /sapi/search/get_suggestion` — autocomplete
  - Payload: `{type_search: "prefix", text, lang}`
  - Response: `{data: {result: [{id, company_name: {en, th}}]}}`

- `POST /sapi/get_search` — full search with filters
  - Payload: `{text, q, start, lang, type_search, jp_type, jp_status, region, province, big_type, big_type_code, start_cap_amt, end_cap_amt}`
  - หมายเหตุ: `q` ใช้ Thai wildcard pattern → `" *".join(text)`

### Company Detail
- `POST /sapi/company/get_detail_sub_general`
  - Payload: `{id, lang}`
  - Returns: financial summary, fs_score, auditor info, directors

- `POST /sapi/company/get_detail_minor_general`
  - Payload: `{id, lang}`
  - Returns: history changes, shareholders %, partners, credit term

## ที่ยังต้องค้น (Discovery Task)
- 📊 Endpoint ของกราฟงบการเงิน (รายได้/กำไร/สินทรัพย์ 9 ปี) — **คาดว่ามี lazy loading**
- 👥 Endpoint รายชื่อผู้ถือหุ้นทั้งหมด
- 🔗 Endpoint บริษัทในเครือ / network graph

## Architecture Plan
- Hybrid approach: httpx (API direct) + Playwright (fallback + discovery)
- MCP server (Python + mcp SDK)
- Session management with cookie persistence

## Tech Stack
- Python 3.11+
- httpx (async HTTP)
- pydantic (validation)
- playwright (discovery + fallback)
- mcp (Anthropic SDK)

## Task ลำดับแรกใน Claude Code
1. สร้าง project structure
2. เขียน Playwright discovery script เพื่อหา endpoint งบการเงิน
3. Build CredenClient class
4. Wrap เป็น MCP tools
5. Test กับ Claude Desktop

## ⚠️ Security Notes
- Credentials ต้องอยู่ใน `.env` file (ห้าม commit)
- Rate limit: เพิ่ม delay 1-2s ระหว่าง requests
- ระวังเรื่อง point/coupon ของ Creden หมดเร็ว