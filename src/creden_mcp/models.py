"""Pydantic response models for Creden endpoints.

These mirror the JSON shapes observed from the spec in CLAUDE.md. Fields are
intentionally permissive (Optional + extra=allow) because the upstream API is
undocumented and may include unknown keys.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class CompanyName(_Loose):
    en: str | None = None
    th: str | None = None


class SuggestionItem(_Loose):
    id: str | int | None = None
    company_name: CompanyName | None = None


class SuggestionResult(_Loose):
    result: list[SuggestionItem] = Field(default_factory=list)


class SuggestionResponse(_Loose):
    data: SuggestionResult | None = None


class SearchHit(_Loose):
    id: str | int | None = None
    company_name: CompanyName | None = None
    big_type: str | None = None
    province: str | None = None
    region: str | None = None
    jp_status: str | None = None
    jp_type: str | None = None
    register_capital: float | int | str | None = None


class SearchResponse(_Loose):
    data: dict[str, Any] | list[Any] | None = None


class CompanyDetailResponse(_Loose):
    """Generic detail wrapper — the upstream returns nested ``data`` fields
    that vary by endpoint. We expose the raw dict and let callers project."""

    data: dict[str, Any] | None = None
