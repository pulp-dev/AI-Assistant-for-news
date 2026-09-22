from __future__ import annotations

import os
from typing import Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .client import BASE_URL, FTKClient

mcp = MCPServer(
    "FTK Catalog",
    instructions=(
        "Read-only connector for the public product catalog on f-tk.ru. "
        "Use search_products to find products, get_product for current card details, "
        "list_category for a category page, and compare_products to compare exact models. "
        "Retail prices on the site are informational and are not a public offer."
    ),
)
client = FTKClient()


@mcp.tool()
async def search_products(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search public f-tk.ru products by name, article, material, protection or other terms."""
    results = await client.search_products(query, limit)
    return [x.model_dump() for x in results]


@mcp.tool()
async def get_product(ref: str) -> dict[str, Any]:
    """Get a current public product card by f-tk.ru URL, item-123 id, or article/SKU."""
    return (await client.get_product(ref)).model_dump()


@mcp.tool()
async def list_category(category_url: str = f"{BASE_URL}/catalog/", limit: int = 20) -> list[dict[str, Any]]:
    """List products visible on a public f-tk.ru catalog/category page (first page only)."""
    results = await client.list_category(category_url, limit)
    return [x.model_dump() for x in results]


@mcp.tool()
async def compare_products(refs: list[str]) -> dict[str, Any]:
    """Fetch and compare 2-8 exact f-tk.ru product cards."""
    if not 2 <= len(refs) <= 8:
        raise ValueError("Provide between 2 and 8 product references")
    products = [await client.get_product(ref) for ref in refs]
    characteristic_names = sorted({k for p in products for k in p.characteristics})
    return {
        "products": [
            {
                "title": p.title,
                "sku": p.sku,
                "url": p.url,
                "retail_price_rub": p.retail_price_rub,
                "price_segment": p.price_segment,
                "characteristics": p.characteristics,
            }
            for p in products
        ],
        "characteristic_names": characteristic_names,
        "note": "Prices are public retail prices from f-tk.ru and may differ from authenticated/contract prices.",
    }


@mcp.tool()
def catalog_status() -> dict[str, Any]:
    """Show connector configuration and the number of detailed product cards cached locally."""
    return {
        "site": BASE_URL,
        "mode": "read-only public catalog",
        "cached_product_cards": client.cache.count(),
        "crawl_delay_seconds": client.delay,
        "site_search_enabled": client.site_search_enabled,
        "personal_account_access": False,
    }


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> Response:
    """Unauthenticated liveness probe for deployment platforms."""
    return JSONResponse({"status": "ok", "service": "ftk-mcp"})


def _transport_security() -> TransportSecuritySettings:
    """Build an explicit Host/Origin allowlist for local and deployed use."""
    allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    allowed_origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]

    render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
    configured_hosts = [
        h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()
    ]
    for hostname in ([render_host] if render_host else []) + configured_hosts:
        if hostname.startswith("http://") or hostname.startswith("https://"):
            hostname = hostname.split("://", 1)[1].rstrip("/")
        allowed_hosts.extend([hostname, f"{hostname}:*"])

    configured_origins = [
        o.strip() for o in os.getenv("MCP_ALLOWED_ORIGINS", "").split(",") if o.strip()
    ]
    if render_host:
        allowed_origins.append(f"https://{render_host}")
    allowed_origins.extend(configured_origins)

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(dict.fromkeys(allowed_hosts)),
        allowed_origins=list(dict.fromkeys(allowed_origins)),
    )


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=_transport_security(),
    )


if __name__ == "__main__":
    main()
