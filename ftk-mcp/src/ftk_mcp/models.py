from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    title: str
    url: str
    sku: str | None = None
    price_rub: float | None = None
    availability: str | None = None
    snippet: str | None = None
    source: str = "live"


class Product(BaseModel):
    url: str
    item_id: str | None = None
    title: str
    sku: str | None = None
    price_segment: str | None = None
    retail_price_rub: float | None = None
    description: str | None = None
    characteristics: dict[str, str] = Field(default_factory=dict)
    variants: list[dict[str, Any]] = Field(default_factory=list)
    certificates: list[dict[str, str]] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    fetched_at: str | None = None
