from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .models import Product, SearchResult

_PRICE_RE = re.compile(r"([\d\s]+(?:[.,]\d+)?)\s*₽")
_ITEM_RE = re.compile(r"/catalog/item-(\d+)/")
_SKU_RE = re.compile(r"(?:Артикул:\s*)?(\d{6,10})")


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _price(text: str | None) -> float | None:
    if not text:
        return None
    match = _PRICE_RE.search(text)
    if not match:
        return None
    normalized = match.group(1).replace(" ", "").replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def _heading(soup: BeautifulSoup, label: str) -> Tag | None:
    target = label.casefold()
    for tag in soup.find_all(["h2", "h3", "h4", "div", "span"]):
        if _clean(tag.get_text(" ", strip=True)).casefold() == target:
            return tag
    return None


def _section_text(soup: BeautifulSoup, start_label: str, stop_labels: set[str]) -> str | None:
    start = _heading(soup, start_label)
    if not start:
        return None
    parts: list[str] = []
    for node in start.next_siblings:
        if not isinstance(node, Tag):
            continue
        heading_text = _clean(node.get_text(" ", strip=True))
        if node.name in {"h2", "h3", "h4"} and heading_text.casefold() in {
            x.casefold() for x in stop_labels
        }:
            break
        if heading_text:
            parts.append(heading_text)
    text = _clean(" ".join(parts))
    return text or None


def _table_after_heading(soup: BeautifulSoup, label: str) -> Tag | None:
    heading = _heading(soup, label)
    if not heading:
        return None
    return heading.find_next("table")


def _table_to_rows(table: Tag | None) -> list[list[str]]:
    if not table:
        return []
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [_clean(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    return rows


def parse_product(html: str, url: str) -> Product:
    soup = BeautifulSoup(html, "html.parser")
    text = _clean(soup.get_text(" ", strip=True))

    h1 = soup.find("h1")
    title = _clean(h1.get_text(" ", strip=True) if h1 else None)
    if not title and soup.title:
        title = _clean(soup.title.get_text(" ", strip=True))
    if not title:
        raise ValueError("Product title was not found")

    sku_match = re.search(r"Артикул:\s*(\d{4,12})", text, flags=re.I)
    sku = sku_match.group(1) if sku_match else None

    segment_match = re.search(
        r"Ценовой\s+сегмент:\s*([^\n]+?)(?=\s+(?:Розничная\s+цена|Для\s+добавления|Особенность:|$))",
        text,
        flags=re.I,
    )
    segment = _clean(segment_match.group(1)) if segment_match else None
    if segment and len(segment) > 40:
        segment = segment.split()[0]

    price_match = re.search(r"Розничная\s+цена\s*([\d\s]+(?:[.,]\d+)?)\s*₽", text, flags=re.I)
    retail_price = None
    if price_match:
        retail_price = float(price_match.group(1).replace(" ", "").replace(",", "."))

    description = _section_text(soup, "Описание", {"Характеристики", "Сертификаты"})

    characteristics: dict[str, str] = {}
    char_rows = _table_to_rows(_table_after_heading(soup, "Характеристики"))
    for row in char_rows:
        if len(row) >= 2:
            key = row[0].rstrip(":").strip()
            value = " | ".join(row[1:]).strip()
            if key and value:
                characteristics[key] = value

    # Fallback for layouts that use adjacent blocks instead of a table.
    if not characteristics:
        heading = _heading(soup, "Характеристики")
        cert_heading = _heading(soup, "Сертификаты")
        if heading:
            node = heading.find_next()
            seen = 0
            pending: str | None = None
            while node and node is not cert_heading and seen < 160:
                seen += 1
                value = _clean(node.get_text(" ", strip=True)) if isinstance(node, Tag) else ""
                if value and value not in {"Характеристики", "Сертификаты"}:
                    if value.endswith(":") and len(value) < 100:
                        pending = value[:-1].strip()
                    elif pending and len(value) < 500:
                        characteristics.setdefault(pending, value)
                        pending = None
                node = node.find_next() if isinstance(node, Tag) else None

    variants: list[dict[str, str]] = []
    for table in soup.find_all("table"):
        rows = _table_to_rows(table)
        if not rows:
            continue
        headers = [x.casefold() for x in rows[0]]
        joined = " ".join(headers)
        if "розничная цена" in joined and ("доступно" in joined or "параметры" in joined):
            original_headers = rows[0]
            for row in rows[1:]:
                if len(row) < 2:
                    continue
                variants.append(
                    {
                        original_headers[i]: row[i]
                        for i in range(min(len(original_headers), len(row)))
                        if original_headers[i]
                    }
                )
            break

    certificates: list[dict[str, str]] = []
    for a in soup.find_all("a", href=True):
        label = _clean(a.get_text(" ", strip=True))
        href = urljoin(url, a["href"])
        if "сертифик" in label.casefold() or "pdf" in label.casefold() or href.lower().endswith(".pdf"):
            if "/personal/" not in href:
                certificates.append({"name": label or "certificate", "url": href})

    images: list[str] = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy")
        if not src:
            continue
        absolute = urljoin(url, src)
        lowered = absolute.lower()
        if "/upload/" in lowered or lowered.endswith((".jpg", ".jpeg", ".png", ".webp")):
            if absolute not in images:
                images.append(absolute)

    item_match = _ITEM_RE.search(url)
    return Product(
        url=url,
        item_id=item_match.group(1) if item_match else None,
        title=title,
        sku=sku,
        price_segment=segment,
        retail_price_rub=retail_price,
        description=description,
        characteristics=characteristics,
        variants=variants,
        certificates=certificates,
        images=images[:20],
    )


def parse_product_links(html: str, base_url: str, limit: int = 20) -> list[SearchResult]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[SearchResult] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if not _ITEM_RE.search(href) or href in seen:
            continue

        title = _clean(a.get_text(" ", strip=True))
        if not title:
            parent = a.parent
            if parent:
                candidate = parent.find(["h2", "h3", "h4", "a"], string=True)
                if candidate:
                    title = _clean(candidate.get_text(" ", strip=True))
        if not title:
            continue

        container: Tag | None = a
        for _ in range(4):
            if container and container.parent and isinstance(container.parent, Tag):
                container = container.parent
            else:
                break
            ctext = _clean(container.get_text(" ", strip=True)) if container else ""
            if "Розничная цена" in ctext or "Доступно:" in ctext:
                break

        snippet = _clean(container.get_text(" ", strip=True)) if container else title
        sku = None
        for match in _SKU_RE.finditer(snippet):
            value = match.group(1)
            if value not in href:
                sku = value
                break

        availability_match = re.search(r"Доступно:\s*([\d\s]+\s*\S+)", snippet, flags=re.I)
        availability = _clean(availability_match.group(1)) if availability_match else None

        found.append(
            SearchResult(
                title=title,
                url=href,
                sku=sku,
                price_rub=_price(snippet),
                availability=availability,
                snippet=snippet[:600] or None,
                source="live",
            )
        )
        seen.add(href)
        if len(found) >= limit:
            break

    return found
