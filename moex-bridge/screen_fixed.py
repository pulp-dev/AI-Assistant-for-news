#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Screen the compact MOEX bond snapshot for fixed-coupon candidates.

This is a *pre-screen*. It deliberately uses only compact market fields and an
approximate no-amortization cash-flow model. Final candidates must be checked
with bondization (coupon/amortization/offer schedule) before quoting an exact
simple yield.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
INPUT = DATA / "market.jsonl"
OUTPUT = DATA / "fixed_screen.json"

# Broad enough to cover the user's ~1.5 year horizon without missing issues
# because of a few weeks either side.
MIN_DAYS = 270
MAX_DAYS = 550
MIN_APPROX_SIMPLE = 14.5


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def d(s):
    try:
        return dt.date.fromisoformat(s)
    except Exception:
        return None


def main():
    candidates = []
    for raw in INPUT.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        r = json.loads(raw)
        face = f(r.get("face"))
        offer = f(r.get("offer"))
        coupon = f(r.get("coupon_pct"))
        nkd = f(r.get("nkd")) or 0.0
        maturity = d(r.get("maturity"))
        settle = d(r.get("settle_date"))
        if not all((face, offer, coupon, maturity, settle)):
            continue
        days = (maturity - settle).days
        if days < MIN_DAYS or days > MAX_DAYS:
            continue

        clean = face * offer / 100.0
        dirty = clean + nkd
        # Approximate remaining coupon accrual. Exact final screen uses MOEX
        # bondization to account for payment dates/amortization/offers.
        coupon_cash = face * coupon / 100.0 * days / 365.0
        future = face + coupon_cash
        simple = (future - dirty) / dirty * 365.0 / days * 100.0
        if simple < MIN_APPROX_SIMPLE:
            continue

        candidates.append({
            "secid": r.get("secid"),
            "isin": r.get("isin"),
            "shortname": r.get("shortname"),
            "name": r.get("name"),
            "board": r.get("board"),
            "offer_pct": offer,
            "nkd_rub": nkd,
            "dirty_rub": round(dirty, 4),
            "coupon_pct": coupon,
            "maturity": r.get("maturity"),
            "days": days,
            "approx_simple_pct": round(simple, 4),
            "moex_yield_pct": f(r.get("moex_yield")),
            "issue_size": r.get("issue_size"),
            "value_today": r.get("value_today"),
            "num_trades": r.get("num_trades"),
            "offer_date": r.get("offer_date"),
            "buyback_price": r.get("buyback_price"),
            "list_level": r.get("list_level"),
        })

    candidates.sort(key=lambda x: (-x["approx_simple_pct"], x["days"], x["secid"] or ""))
    payload = {
        "generated_from": "moex-bridge/data/market.jsonl",
        "criteria": {
            "days_to_maturity_min": MIN_DAYS,
            "days_to_maturity_max": MAX_DAYS,
            "approx_simple_yield_min_pct": MIN_APPROX_SIMPLE,
            "requires_offer": True,
            "requires_coupon_pct": True,
            "note": "Pre-screen only. Fixed/floater type, ratings, amortizations and exact simple yield require detailed verification."
        },
        "count": len(candidates),
        "candidates": candidates,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(candidates)} pre-screen candidates")


if __name__ == "__main__":
    main()
