# creden-mcp

MCP server ที่ให้ AI agent (Claude Code / Claude Desktop) ดึงข้อมูลบริษัทไทยจาก [data.creden.co](https://data.creden.co) ได้ — ค้นด้วยชื่อภาษาไทย/อังกฤษ หรือเลขนิติบุคคล แล้วได้ profile, งบการเงิน 5–10 ปี, กรรมการ, % ผู้ถือหุ้น, ผู้มีอำนาจลงนาม ในการเรียกเดียว

```
"<ชื่อบริษัท>"
   ↓ creden_lookup
   ↓
บริษัท ABC จำกัด (id=0123456789012)
จดทะเบียน <date> · ทุน <amount> บาท · <industry>

ปี (พ.ศ.)    รายได้รวม    กำไรสุทธิ    สินทรัพย์รวม    YoY%
<year>          ...           ...           ...          ...
<year>          ...           ...           ...          ...

กรรมการ:               <list>
ผู้มีอำนาจลงนาม:        <list>
ผู้ถือหุ้น:              <pct1>% / <pct2>% (ไทย 100%)
ราคาต่อหุ้น:            <shares> หุ้น × ...
```

## ทำไมใช้ตัวนี้

- **ไม่ต้อง login** สำหรับข้อมูลส่วนใหญ่ — profile + งบการเงิน 5–10 ปี ใช้ public HTML route
- **กรรมการ / ผู้ถือหุ้น %** อยู่หลัง free-tier login (ใส่ credentials ใน `.env`)
- **Auto re-login** ถ้า session หมด ระบบ detect 401 → login ใหม่ → retry อัตโนมัติ
- **Single tool** — call เดียวได้ทุกอย่าง agent ไม่ต้องตัดสินใจระหว่างหลาย tool
- ทำงานกับ **Claude Code, Claude Desktop**, หรือ MCP client อื่นๆ ที่ speak stdio

## Install

```bash
git clone https://github.com/<your-username>/creden-mcp.git
cd creden-mcp
python3 -m venv .venv
.venv/bin/pip install -e .
```

ต้องการ Python ≥ 3.11

## Setup กับ Claude Code

```bash
claude mcp add creden --scope user $(pwd)/.venv/bin/creden-mcp
claude mcp list | grep creden       # → ✓ Connected
```

ใน session ใหม่ของ Claude Code ถามได้เลย:

```
"งบการเงิน 5 ปีของ <ชื่อบริษัท>"
"ใครเป็นกรรมการบริษัท <ชื่อ>"
"ค้นบริษัท <ชื่อ>"
"นิติบุคคลเลข <id 13 หลัก> ทำธุรกิจอะไร"
```

### Setup กับ Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "creden": {
      "command": "/absolute/path/to/.venv/bin/creden-mcp"
    }
  }
}
```

### Credentials (optional แต่แนะนำ)

```bash
cp .env.example .env
# แก้ไข .env ใส่ CREDEN_EMAIL / CREDEN_PASSWORD
```

ไม่ใส่ก็ใช้ได้ — แค่ field ที่ gate (กรรมการ/ผู้ถือหุ้น/ผู้ลงนาม) จะเป็น `null` พร้อม `auth_data_status` บอกเหตุผล

ใส่แล้ว register แบบ inline ก็ได้ (ไม่ต้องมี `.env` ในโปรเจกต์):

```bash
claude mcp add creden --scope user \
  --env CREDEN_EMAIL=you@example.com \
  --env CREDEN_PASSWORD=secret \
  /path/to/.venv/bin/creden-mcp
```

## Tools

| Tool | Purpose |
|---|---|
| `creden_lookup(query)` | **Main**: ชื่อ หรือ id 13 หลัก → ข้อมูลครบในการเรียกเดียว |
| `creden_search(text)` | คืน list candidates สำหรับชื่อที่ ambiguous |

ผลที่ได้จาก `creden_lookup` (โครงสร้างตัวอย่าง):

```jsonc
{
  "company": {
    "th": "บริษัท ... จำกัด",
    "en": "... CO., LTD.",
    "juristic_id": "0123456789012",
    "register_date_th": "...",
    "register_capital": 1000000,
    "industry_th": "<TSIC code> : <description>",
    "address_th": "...",
    "objective": "..."
  },
  "fiscal_years": [
    { "FISCAL_YEAR": 2566, "BAL_IN09": 0, "BAL_IN21": 0, "BAL_BS22_BAL_BS99": 0 },
    { "FISCAL_YEAR": 2567, "BAL_IN09": 0, "BAL_IN21": 0, "BAL_BS22_BAL_BS99": 0 }
  ],
  "directors": [{ "name_search": "...", "name_search_en": "...", "index": 1 }],
  "director_history": [/* เข้า/ออก กรรมการ พร้อมวันที่ */],
  "shareholders_summary": {
    "percentages": [50.0, 50.0],
    "names_masked": ["A", "B"],
    "by_nationality": [{ "nationality": "TH", "pct": 100 }]
  },
  "authorized_signers": ["..."],
  "signing_rule": "...",
  "share_info": { "total_shares": 0, "price_per_share": 0 },
  "auth_data_status": "fetched"
}
```

`creden_lookup(query, full=True)` คืน DBD codes ทุก field (~50 fields/ปี)

## Architecture

```
src/creden_mcp/
  config.py        env / .env loading (pure dataclass)
  page_parser.py   parse window.__NUXT__ → dict (regex-based, var-name agnostic)
  client.py        async httpx client; auto re-login on session expiry
  server.py        FastMCP — 2 tools wrapping client.lookup
  models.py        loose Pydantic shapes
  discovery.py     Playwright XHR capture (สำหรับหา endpoint ใหม่)
```

**Public flow** (no auth):
```
suggest /sapi/search/get_suggestion           →  company_id
GET     /company/general/<id>                 →  HTML with full Nuxt-hydrated state
                                                 → parse profile + fiscal years
```

**Auth flow** (`.env` credentials):
```
POST /sapi/authen/login                       →  cookie session
POST /sapi/company/get_detail_minor_general   →  director history,
                                                 shareholders %, signers, shares
POST /sapi/company/get_detail_sub_general     →  current directors
```

Session expiry → ถ้า 401 หรือ body มี `"session expired"` → auto re-login → retry ครั้งเดียว

## Limitations

ไม่มี (และไม่สามารถดึงได้ด้วย free Creden tier):
- **ชื่อผู้ถือหุ้นเต็ม** — masked เป็น "A", "B", … เห็นแค่ % และสัญชาติ
- **ผู้สอบบัญชี (ชื่อจริง)** — masked
- **Email/phone บริษัท** — masked
- **fs_score / credit term / value per share precise** — masked, paid tier
- **บริษัทมหาชน + ข้อมูล realtime** — สำหรับ listed companies (มหาชน) ใช้ SET/SEC สำหรับข้อมูลผู้ถือหุ้นเต็มและงบไตรมาสล่าสุด

## Tests

```bash
pip install -e ".[dev]"
pytest
```

## Disclaimer

- โครงการนี้เรียก data.creden.co API + scrape Nuxt-hydrated HTML. ผู้ใช้ต้องรับผิดชอบในการปฏิบัติตาม [Terms of Service ของ Creden](https://data.creden.co)
- Credentials ของคุณส่งตรงไปที่ Creden — โครงการนี้ไม่ proxy ผ่าน server กลาง
- Default request delay = 1.5 วินาที (ปรับใน `.env` ได้) — ปรับลงด้วยความระมัดระวังเพื่อไม่กระทบ Creden quota
- เครื่องมือนี้ใช้สำหรับการเข้าถึงข้อมูลที่ผู้ใช้มีสิทธิ์เข้าถึงอยู่แล้วผ่าน Creden อย่าใช้เพื่อรวบรวมข้อมูลส่วนบุคคลของบุคคลที่สามโดยไม่ได้รับอนุญาต

## License

[MIT](LICENSE) © 2026 phpgng
