from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import httpx

from .cache import ProductCache
from .models import Product, SearchResult
from .parser import parse_product, parse_product_links

BASE_URL = "https://www.f-tk.ru"
ALLOWED_HOSTS = {"www.f-tk.ru", "f-tk.ru"}


class FTKClient:
    def __init__(self) -> None:
        self.timeout = float(os.getenv("FTK_TIMEOUT_SECONDS", "25"))
        self.delay = float(os.getenv("FTK_CRAWL_DELAY_SECONDS", "3"))
        self.max_bytes = int(os.getenv("FTK_MAX_RESPONSE_BYTES", "6000000"))
        self.user_agent = os.getenv(
            "FTK_USER_AGENT",
            "ftk-mcp/0.1 (+read-only public catalog connector; contact: set FTK_USER_AGENT)",
        )
        self.site_search_enabled = os.getenv("FTK_SITE_SEARCH", "true").lower() in {"1", "true", "yes"}
        self.cache = ProductCache(os.getenv("FTK_CACHE_PATH", "/tmp/ftk-mcp/products.sqlite3"))
        self._rate_lock = asyncio.Lock()
        self._last_request = 0.0

    async def _throttle(self) -> None:
        async with self._rate_lock:
            elapsed = time.monotonic() - self._last_request
            if elapsed < self.delay:
                await asyncio.sleep(self.delay - elapsed)
            self._last_request = time.monotonic()

    @staticmethod
    def _validate_url(url: str, allow_search: bool = False) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise ValueError("Only https://f-tk.ru URLs are allowed")
        if "/personal/" in parsed.path:
            raise ValueError("Personal account pages are intentionally blocked")
        if parsed.query and not (allow_search and parsed.path.rstrip("/") == "/search"):
            raise ValueError("Query-string URLs are blocked except the public search endpoint")
        return url

    async def _get(self, url: str, *, allow_search: bool = False) -> str:
        url = self._validate_url(url, allow_search=allow_search)
        await self._throttle()
        headers = {"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml"}
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()
            final = urlparse(str(response.url))
            if final.hostname not in ALLOWED_HOSTS:
                raise ValueError("Redirected outside f-tk.ru")
            content = response.content
            if len(content) > self.max_bytes:
                raise ValueError("Response is larger than FTK_MAX_RESPONSE_BYTES")
            return response.text

    async def search_products(self, query: str, limit: int = 10) -> list[SearchResult]:
        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")
        limit = max(1, min(limit, 30))

        cached = self.cache.search(query, limit)
        if len(cached) >= limit or not self.site_search_enabled:
            return cached[:limit]

        url = f"{BASE_URL}/search/?q={quote(query)}"
        try:
            html = await self._get(url, allow_search=True)
            live = parse_product_links(html, BASE_URL, limit=limit)
        except Exception:
            if cached:
                return cached[:limit]
            raise

        merged: list[SearchResult] = []
        seen: set[str] = set()
        for item in [*cached, *live]:
            if item.url not in seen:
                merged.append(item)
                seen.add(item.url)
            if len(merged) >= limit:
                break
        return merged

    async def resolve_product_url(self, ref: str) -> str:
        ref = ref.strip()
        if ref.startswith("https://"):
            self._validate_url(ref)
            if not re.search(r"/catalog/item-\d+/", ref):
                raise ValueError("URL must point to an f-tk.ru product card")
            return ref
        if re.fullmatch(r"item-\d+", ref):
            return f"{BASE_URL}/catalog/{ref}/"
        if re.fullmatch(r"\d{5,12}", ref):
            cached = self.cache.get_by_sku(ref)
            if cached:
                return cached
            matches = await self.search_products(ref, limit=10)
            exact = next((x for x in matches if x.sku == ref), None)
            if exact:
                return exact.url
            raise ValueError(f"No product with article {ref} was found")
        raise ValueError("Use a product URL, item-123456 identifier, or article/SKU number")

    async def get_product(self, ref: str) -> Product:
        url = await self.resolve_product_url(ref)
        html = await self._get(url)
        product = parse_product(html, url)
        product.fetched_at = datetime.now(timezone.utc).isoformat()
        self.cache.put(product)
        return product

    async def list_category(self, category_url: str, limit: int = 20) -> list[SearchResult]:
        limit = max(1, min(limit, 50))
        if category_url.startswith("/"):
            category_url = f"{BASE_URL}{category_url}"
        parsed = urlparse(category_url)
        if not parsed.path.startswith("/catalog/") or "/item-" in parsed.path:
            raise ValueError("category_url must be a public f-tk.ru catalog category URL")
        html = await self._get(category_url)
        return parse_product_links(html, BASE_URL, limit=limit)
