# ftk-mcp

Read-only **Model Context Protocol (MCP)** server for the public product catalog at **https://www.f-tk.ru/** (Факел-спецодежда).

It is designed for ChatGPT/other MCP hosts that need to search the public catalog, read exact product cards and compare PPE/workwear products without giving the model credentials to the supplier account.

This project lives in the `ftk-mcp/` folder of `pulp-dev/AI-Assistant-for-news`.

## What it exposes

- `search_products(query, limit=10)` — public catalog search, with a local SQLite cache as the first source.
- `get_product(ref)` — exact product card by URL, `item-...` id or article/SKU.
- `list_category(category_url, limit=20)` — products visible on a public category page.
- `compare_products(refs)` — structured comparison of 2–8 exact cards.
- `catalog_status()` — connector mode/cache status.

A product card can return:

- name and article;
- public retail price and price segment;
- description;
- material and protection properties;
- GOST / TR CU values and other characteristics;
- size/variant rows and public stock values shown on the card;
- certificate links;
- product image URLs.

## Safety / scope

This project is intentionally **read-only** and **public-catalog-only**:

- no `/personal/` access;
- no login/password or cookie handling;
- no cart/order actions;
- only `https://f-tk.ru` / `https://www.f-tk.ru` are allowed;
- arbitrary query-string URLs are rejected;
- the connector throttles requests (3 seconds by default).

The website states that prices shown publicly are informational and are not a public offer. Authenticated/contract prices may differ.

## Requirements

Python 3.10+ (Docker image uses Python 3.12).

The project targets the current **MCP Python SDK v2** and Streamable HTTP transport.

## Run locally

```bash
cd ftk-mcp
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
ftk-mcp
```

Health check: `GET /health`.

The MCP endpoint will be:

```text
http://127.0.0.1:8000/mcp
```

For development with the MCP CLI you can also use:

```bash
pip install "mcp[cli]>=2,<3"
mcp dev src/ftk_mcp/server.py
```

## Docker

```bash
cd ftk-mcp
docker build -t ftk-mcp .
docker run --rm -p 8000:8000 ftk-mcp
```

Then connect to:

```text
http://localhost:8000/mcp
```

## Deploy as a remote MCP server

Any HTTPS host that can run Docker/Python works (Render, Railway, Fly.io, VPS, etc.). When deploying this monorepo, set the service root directory to `ftk-mcp`.

On Render, `RENDER_EXTERNAL_HOSTNAME` is used automatically for MCP Host protection. On another platform, set `MCP_ALLOWED_HOSTS` to the public hostname.

After deployment your MCP URL will look like:

```text
https://YOUR-HOST/mcp
```

Use that URL when adding a custom remote MCP server in an MCP-compatible client.

## Environment variables

Copy `.env.example` and adjust as needed.

| Variable | Default | Purpose |
|---|---:|---|
| `HOST` | `0.0.0.0` | MCP listen address |
| `PORT` | `8000` | MCP port |
| `FTK_TIMEOUT_SECONDS` | `25` | upstream request timeout |
| `FTK_CRAWL_DELAY_SECONDS` | `3` | minimum spacing between upstream requests |
| `FTK_MAX_RESPONSE_BYTES` | `6000000` | upper bound for fetched HTML |
| `FTK_SITE_SEARCH` | `true` | allow on-demand use of the site's public search page |
| `FTK_CACHE_PATH` | `/tmp/ftk-mcp/products.sqlite3` | SQLite cache |
| `FTK_USER_AGENT` | project default | identify your integration/contact |
| `MCP_ALLOWED_HOSTS` | empty | comma-separated public hostnames outside Render |
| `MCP_ALLOWED_ORIGINS` | empty | comma-separated browser origins, if needed |

## Example tool calls

Search:

```json
{"query": "антистатический костюм", "limit": 10}
```

Exact card by article:

```json
{"ref": "87489497"}
```

Exact card by URL:

```json
{"ref": "https://www.f-tk.ru/catalog/item-1541945/"}
```

Compare:

```json
{"refs": ["87489497", "87491008"]}
```

## Notes about search and robots.txt

`f-tk.ru/robots.txt` declares a 3-second crawl delay and blocks crawler traversal of query-string URLs and `/personal/`. This connector does not crawl the personal area and uses a 3-second throttle by default. `search_products` can make an **on-demand** request to the site's public search UI for the user's specific query; set `FTK_SITE_SEARCH=false` if you want a stricter cache-only mode.

For a production integration with high request volume, ask the supplier for an official API/feed (XML/YML/1C/etc.) and replace the HTML adapter with that source.

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

The parser tests use local HTML fixtures and do not hit the supplier site.

## License

MIT. This project is an independent connector and is not affiliated with ООО «Факел-спецодежда».
