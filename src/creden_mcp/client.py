"""Async client for data.creden.co.

Two paths exist:

* **Public** — ``/sapi/search/get_suggestion`` and the HTML route
  ``/company/general/<id>`` work without authentication. This is the primary
  flow used by :meth:`lookup`.
* **Authenticated** — login + the other ``/sapi/*`` endpoints. Kept for
  completeness but not required for normal use.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from .config import Settings
from .page_parser import parse_html

log = logging.getLogger(__name__)


class CredenError(RuntimeError):
    """Upstream call failed."""


def _wildcard_q(text: str) -> str:
    """Reproduce Creden's Thai-search wildcard pattern: ``' *'.join(text)``."""
    return " *".join(text)


class CredenClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self._http = httpx.AsyncClient(
            base_url=self.settings.base_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "th,en;q=0.9",
                "Origin": self.settings.base_url,
                "Referer": f"{self.settings.base_url}/",
            },
            follow_redirects=True,
        )
        self._lock = asyncio.Lock()
        self._last_call = 0.0
        self._logged_in = False
        self._restore_session()

    # ---- session persistence (auth path only) ------------------------------

    def _restore_session(self) -> None:
        path = self.settings.session_file
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            for c in data.get("cookies", []):
                self._http.cookies.set(
                    name=c["name"], value=c["value"],
                    domain=c.get("domain"), path=c.get("path", "/"),
                )
            if data.get("cookies"):
                self._logged_in = True
        except (OSError, ValueError, KeyError) as e:
            log.warning("Could not restore session: %s", e)

    def _persist_session(self) -> None:
        cookies = [
            {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
            for c in self._http.cookies.jar
        ]
        try:
            self.settings.session_file.write_text(json.dumps({"cookies": cookies}, indent=2))
        except OSError as e:
            log.warning("Could not persist session: %s", e)

    # ---- low-level HTTP -----------------------------------------------------

    async def _throttle(self) -> None:
        elapsed = asyncio.get_event_loop().time() - self._last_call
        if elapsed < self.settings.request_delay:
            await asyncio.sleep(self.settings.request_delay - elapsed)

    async def _post(self, path: str, payload: dict[str, Any], *, _retry: bool = True) -> Any:
        """POST a JSON payload. If the server signals an expired session
        (HTTP 401, or 200 with ``success=False`` + session-related error),
        and we have credentials, re-login once and retry."""
        async with self._lock:
            await self._throttle()
            try:
                resp = await self._http.post(path, json=payload)
            finally:
                self._last_call = asyncio.get_event_loop().time()

        body_text = resp.text
        session_expired = (
            resp.status_code == 401 or "session expired" in body_text.lower()
        )

        if (
            session_expired
            and _retry
            and self.settings.email
            and self.settings.password
            and path != "/sapi/authen/login"  # avoid login-on-login loops
        ):
            log.info("session expired on %s — re-authenticating", path)
            self._logged_in = False
            await self.login(force=True)
            return await self._post(path, payload, _retry=False)

        if resp.status_code >= 400:
            raise CredenError(f"{path} → HTTP {resp.status_code}: {body_text[:300]}")
        try:
            return resp.json()
        except ValueError as e:
            raise CredenError(f"{path} returned non-JSON: {body_text[:200]}") from e

    async def _get_html(self, path: str) -> str:
        async with self._lock:
            await self._throttle()
            try:
                resp = await self._http.get(
                    path, headers={"Accept": "text/html,application/xhtml+xml"}
                )
            finally:
                self._last_call = asyncio.get_event_loop().time()
        if resp.status_code >= 400:
            raise CredenError(f"{path} → HTTP {resp.status_code}")
        return resp.text

    # ---- public flows -------------------------------------------------------

    async def suggest(self, text: str, lang: str | None = None) -> list[dict[str, Any]]:
        """Autocomplete by name/prefix. Public — no login needed.

        Returns a list of ``{id, name_th, name_en}`` dicts.
        """
        result = await self._post(
            "/sapi/search/get_suggestion",
            {"type_search": "prefix", "text": text, "lang": lang or self.settings.default_lang},
        )
        items = (result or {}).get("data", {}).get("result", []) or []
        out = []
        for it in items:
            out.append({
                "id": it.get("id"),
                "name_th": (it.get("company_name") or {}).get("th"),
                "name_en": (it.get("company_name") or {}).get("en"),
            })
        return out

    async def fetch_company_page(self, company_id: str | int) -> dict[str, Any]:
        """Fetch + parse a company HTML page. Public — no login needed.

        Returns the parsed dict from :func:`page_parser.parse_html`. The
        ``company.juristic_id`` field is set from the URL we requested,
        which is more reliable than scraping it from the page (the page
        contains JP_NOs of partner companies too).
        """
        html = await self._get_html(f"/company/general/{company_id}")
        parsed = parse_html(html)
        parsed["company"]["juristic_id"] = str(company_id)
        return parsed

    async def lookup(
        self, query: str, *, lang: str | None = None, include_directors: bool = True
    ) -> dict[str, Any]:
        """High-level: name OR id → company profile + financials + directors.

        Always includes the no-auth data (profile, fiscal years). Tries to
        include directors too — fetches via the authenticated endpoint if
        ``CREDEN_EMAIL``/``CREDEN_PASSWORD`` are set. Result is cached on
        disk for 30 days, so subsequent calls don't burn extra Creden points.

        If credentials aren't set or login fails, ``directors`` is ``None``
        and ``directors_status`` explains why — the rest of the lookup still
        succeeds.
        """
        candidates: list[dict[str, Any]]
        digits = re.sub(r"\D", "", query)
        if len(digits) == 13:
            company_id = digits
            candidates = []
        else:
            candidates = await self.suggest(query, lang=lang)
            if not candidates:
                return {
                    "query": query, "candidates": [], "match": None,
                    "company": None, "fiscal_years": [], "directors": None,
                    "directors_status": "ไม่พบบริษัท",
                }
            company_id = candidates[0]["id"]

        page = await self.fetch_company_page(company_id)

        auth_block = await self._collect_auth_data(company_id, lang) if include_directors else {
            "directors": None,
            "director_history": None,
            "shareholders_summary": None,
            "authorized_signers": None,
            "signing_rule": None,
            "share_info": None,
            "auth_data_status": "skipped",
        }

        return {
            "query": query,
            "match": {"id": company_id, **(candidates[0] if candidates else {})},
            "candidates": candidates,
            "company": page["company"],
            "fiscal_years": page["fiscal_years"],
            "charts_count": len(page["charts"]),
            **auth_block,
        }

    @staticmethod
    def _project_minor(minor_payload: dict[str, Any]) -> dict[str, Any]:
        """Project the cached ``minor_general`` payload to the public shape."""
        msrc = (minor_payload or {}).get("data") or {}
        ds = msrc.get("data_share") or {}
        shareholders = (
            {
                "percentages": ds.get("pct_data") or [],
                "names_masked": ds.get("name_share") or [],
                "by_nationality": ds.get("data_nationa_pct") or [],
                "total_count_visible": len(ds.get("pct_data") or []),
            }
            if ds
            else None
        )
        pps = (minor_payload or {}).get("price_per_share") or {}
        return {
            "director_history": msrc.get("hist_data") or None,
            "shareholders_summary": shareholders,
            "authorized_signers": msrc.get("partner") or None,
            "signing_rule": msrc.get("PARTNER_MANAGER") or None,
            "share_info": (
                {
                    "total_shares": pps.get("total_count_share"),
                    "price_per_share": pps.get("price_per_share"),
                }
                if pps
                else None
            ),
        }

    async def _collect_auth_data(self, company_id: str, lang: str | None) -> dict[str, Any]:
        """Fetch directors + minor_general; gracefully degrade if no creds.

        Order matters: ``minor_general`` is hit *first* because it returns
        HTTP 401 on a stale session (which triggers auto re-login). After
        that ``sub_general`` is guaranteed to see a fresh session — without
        this ordering, ``sub_general`` could silently return anonymous
        masked data (HTTP 200) before the 401 from ``minor_general`` had
        a chance to surface and re-authenticate.
        """
        if not (self.settings.email and self.settings.password):
            return {
                "directors": None,
                "auth_data_status": (
                    "ต้องตั้ง CREDEN_EMAIL/CREDEN_PASSWORD ใน .env "
                    "เพื่อดึงกรรมการ/ประวัติ/ผู้ถือหุ้น/ผู้ลงนาม"
                ),
                **self._project_minor({}),
            }
        try:
            minor_payload = await self.get_minor_general(company_id, lang=lang)
            directors = await self.get_directors(company_id, lang=lang)
            return {
                "directors": directors,
                "auth_data_status": "fetched",
                **self._project_minor(minor_payload),
            }
        except CredenError as e:
            return {
                "directors": None,
                "auth_data_status": f"login failed: {e}",
                **self._project_minor({}),
            }

    # ---- authenticated: directors -----------------------------------------

    async def get_directors(
        self, company_id: str | int, *, lang: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetch director list via the authenticated ``sub_general`` endpoint."""
        if not self._logged_in:
            await self.login()
        result = await self._post(
            "/sapi/company/get_detail_sub_general",
            {"id": str(company_id), "lang": lang or self.settings.default_lang},
        )
        data = (result or {}).get("data", {}) or {}
        directors_raw = data.get("data_director", [])
        return directors_raw if isinstance(directors_raw, list) else []

    # ---- authenticated: minor_general (director history, share %, signers) -

    async def get_minor_general(
        self, company_id: str | int, *, lang: str | None = None
    ) -> dict[str, Any]:
        """Fetch ``minor_general`` (auth) → director history, share %,
        authorized signers, signing rule, share count + price."""
        if not self._logged_in:
            await self.login()
        result = await self._post(
            "/sapi/company/get_detail_minor_general",
            {"id": str(company_id), "lang": lang or self.settings.default_lang},
        )
        return {
            "data": (result or {}).get("data") or {},
            "price_per_share": (result or {}).get("get_price_per_share") or {},
        }

    # ---- authenticated path (kept for completeness) ------------------------

    async def login(self, force: bool = False) -> dict[str, Any]:
        if self._logged_in and not force:
            return {"status": "cached"}
        email, password = self.settings.require_credentials()
        result = await self._post(
            "/sapi/authen/login",
            {"email": email, "password": password, "mode": "creden"},
        )
        self._logged_in = True
        self._persist_session()
        return result if isinstance(result, dict) else {"status": "ok", "raw": result}

    async def search_full(self, text: str, *, start: int = 0, lang: str | None = None) -> dict[str, Any]:
        """Authenticated full search (filters available). Calls :meth:`login` first."""
        if not self._logged_in:
            await self.login()
        return await self._post(
            "/sapi/get_search",
            {
                "text": text,
                "q": _wildcard_q(text),
                "start": start,
                "lang": lang or self.settings.default_lang,
                "type_search": "general",
            },
        )

    # ---- lifecycle ----------------------------------------------------------

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "CredenClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()


# late import to avoid circular reference at module load
import re  # noqa: E402
