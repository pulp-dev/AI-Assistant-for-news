from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Product, SearchResult


class ProductCache:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    url TEXT PRIMARY KEY,
                    item_id TEXT,
                    title TEXT NOT NULL,
                    sku TEXT,
                    price_segment TEXT,
                    retail_price_rub REAL,
                    description TEXT,
                    characteristics_json TEXT NOT NULL,
                    variants_json TEXT NOT NULL,
                    certificates_json TEXT NOT NULL,
                    images_json TEXT NOT NULL,
                    fetched_at TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_products_title ON products(title)")

    def put(self, product: Product) -> None:
        data = product.model_dump()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO products (
                    url,item_id,title,sku,price_segment,retail_price_rub,description,
                    characteristics_json,variants_json,certificates_json,images_json,fetched_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(url) DO UPDATE SET
                    item_id=excluded.item_id,
                    title=excluded.title,
                    sku=excluded.sku,
                    price_segment=excluded.price_segment,
                    retail_price_rub=excluded.retail_price_rub,
                    description=excluded.description,
                    characteristics_json=excluded.characteristics_json,
                    variants_json=excluded.variants_json,
                    certificates_json=excluded.certificates_json,
                    images_json=excluded.images_json,
                    fetched_at=excluded.fetched_at
                """,
                (
                    data["url"], data["item_id"], data["title"], data["sku"],
                    data["price_segment"], data["retail_price_rub"], data["description"],
                    json.dumps(data["characteristics"], ensure_ascii=False),
                    json.dumps(data["variants"], ensure_ascii=False),
                    json.dumps(data["certificates"], ensure_ascii=False),
                    json.dumps(data["images"], ensure_ascii=False), data["fetched_at"],
                ),
            )

    def search(self, query: str, limit: int) -> list[SearchResult]:
        like = f"%{query}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT title,url,sku,retail_price_rub,description,characteristics_json
                FROM products
                WHERE title LIKE ? COLLATE NOCASE
                   OR sku LIKE ? COLLATE NOCASE
                   OR description LIKE ? COLLATE NOCASE
                   OR characteristics_json LIKE ? COLLATE NOCASE
                ORDER BY CASE WHEN sku = ? THEN 0 ELSE 1 END, title
                LIMIT ?
                """,
                (like, like, like, like, query, limit),
            ).fetchall()
        return [
            SearchResult(
                title=row["title"], url=row["url"], sku=row["sku"],
                price_rub=row["retail_price_rub"],
                snippet=(row["description"] or row["characteristics_json"] or "")[:600] or None,
                source="cache",
            )
            for row in rows
        ]

    def get_by_sku(self, sku: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT url FROM products WHERE sku = ? LIMIT 1", (sku,)).fetchone()
        return row["url"] if row else None

    def count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM products").fetchone()[0])
