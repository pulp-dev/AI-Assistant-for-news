#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch selected Moscow Exchange bond data from the official MOEX ISS API.

The script intentionally performs no trading and requires no credentials.
It writes a compact snapshot to moex-bridge/data/latest.json.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

BASE = "https://iss.moex.com/iss"
ROOT = pathlib.Path(__file__).resolve().parent
WATCHLIST = ROOT / "watchlist.json"
OUT = ROOT / "data" / "latest.json"
USER_AGENT = "moex-github-bridge/1.0"


def get(path: str, **params):
    params.setdefault("iss.meta", "off")
    url = f"{BASE}{path}.json?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=45) as r:
        return json.load(r), url


def table(payload, block: str):
    b = payload.get(block) or {}
    columns = b.get("columns") or []
    rows = b.get("data") or []
    return [dict(zip(columns, row)) for row in rows]


def find_board(secid: str):
    """Try the main bond boards used for corporate/municipal bonds and OFZ."""
    attempts = []
    for board in ("TQCB", "TQOB"):
        path = f"/engines/stock/markets/bonds/boards/{board}/securities/{quote(secid)}"
        payload, url = get(path)
        attempts.append(url)
        sec = table(payload, "securities")
        if sec:
            return board, payload, attempts
    return None, None, attempts


def description(secid: str):
    payload, url = get(f"/securities/{quote(secid)}")
    rows = table(payload, "description")
    kv = {r.get("name"): r.get("value") for r in rows if r.get("name")}
    return kv, url


def bondization(secid: str):
    payload, url = get(f"/securities/{quote(secid)}/bondization", limit=400)
    return {
        "coupons": table(payload, "coupons"),
        "amortizations": table(payload, "amortizations"),
        "offers": table(payload, "offers"),
        "source": url,
    }


def pick(d: dict, *keys):
    return {k: d.get(k) for k in keys if k in d}


def fetch_one(secid: str):
    board, payload, attempts = find_board(secid)
    if not payload:
        return {
            "secid": secid,
            "ok": False,
            "error": "security_not_found_on_TQCB_or_TQOB",
            "attempted_urls": attempts,
        }

    sec = table(payload, "securities")[0]
    md = (table(payload, "marketdata") or [{}])[0]
    desc, desc_url = description(secid)
    bnd = bondization(secid)

    return {
        "secid": secid,
        "ok": True,
        "board": board,
        "security": pick(
            sec,
            "SECID", "SHORTNAME", "SECNAME", "ISIN", "REGNUMBER",
            "FACEVALUE", "FACEUNIT", "ACCRUEDINT", "COUPONPERCENT",
            "COUPONVALUE", "NEXTCOUPON", "MATDATE", "OFFERDATE",
            "BUYBACKPRICE", "LOTVALUE", "LOTSIZE", "LISTLEVEL",
            "ISSUESIZE", "PREVPRICE", "PREVLEGALCLOSEPRICE", "SETTLEDATE",
        ),
        "market": pick(
            md,
            "BID", "OFFER", "LAST", "MARKETPRICE", "MARKETPRICE2",
            "YIELD", "LASTCHANGE", "NUMTRADES", "VALTODAY", "VOLTODAY",
            "SYSTIME", "UPDATETIME", "SEQNUM",
        ),
        "description": {
            k: desc.get(k)
            for k in (
                "NAME", "SHORTNAME", "ISIN", "REGNUMBER", "ISSUESIZE",
                "FACEVALUE", "FACEUNIT", "MATDATE", "COUPONFREQUENCY",
                "COUPON_BENCHMARK", "COUPON_BENCHMARK_SPREAD",
                "ISQUALIFIEDINVESTORS", "LISTLEVEL", "EARLYREPAYMENT",
            )
            if k in desc
        },
        "cashflows": {
            "coupons": bnd["coupons"],
            "amortizations": bnd["amortizations"],
            "offers": bnd["offers"],
        },
        "sources": {
            "quote": attempts[-1],
            "description": desc_url,
            "bondization": bnd["source"],
        },
    }


def main():
    watch = json.loads(WATCHLIST.read_text(encoding="utf-8"))
    secids = watch.get("secids", [])
    if not secids:
        raise SystemExit("watchlist.json contains no secids")

    now = dt.datetime.now(dt.timezone.utc)
    result = {
        "generated_at_utc": now.isoformat(timespec="seconds"),
        "generated_at_msk": now.astimezone(dt.timezone(dt.timedelta(hours=3))).isoformat(timespec="seconds"),
        "source": "MOEX ISS",
        "source_base": BASE,
        "note": "Public MOEX ISS data may be delayed. This snapshot is read-only market data, not a trading feed.",
        "count": len(secids),
        "bonds": [],
    }

    for secid in secids:
        try:
            result["bonds"].append(fetch_one(str(secid).strip()))
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as e:
            result["bonds"].append({
                "secid": secid,
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
            })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT} with {len(result['bonds'])} securities")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"fatal: {type(e).__name__}: {e}", file=sys.stderr)
        raise
