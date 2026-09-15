#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch selected Moscow Exchange bond data from official MOEX ISS.

The bridge is read-only. Besides raw MOEX fields it calculates a transparent
set of bond metrics used in ChatGPT comparisons:
  * current coupon yield;
  * profit per bond to maturity;
  * simple annualized yield to maturity (no coupon reinvestment);
  * cash-flow IRR/XIRR;
  * spread of the simple yield to a configured key-rate scenario.

For floating-rate coupons that have not yet been announced, the script uses the
benchmark scenario from watchlist.json. Such estimates are explicitly marked.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import pathlib
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

BASE = "https://iss.moex.com/iss"
ROOT = pathlib.Path(__file__).resolve().parent
WATCHLIST = ROOT / "watchlist.json"
OUT = ROOT / "data" / "latest.json"
USER_AGENT = "moex-github-bridge/2.0"


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


def fnum(value, default=None):
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def date_of(value):
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def cashflow_irr(flows, dirty_price, t0):
    """Annual effective XIRR from dated positive cashflows and initial price."""
    if not flows or dirty_price <= 0:
        return None

    def npv(rate):
        if rate <= -0.999999:
            return math.inf
        return sum(v / (1 + rate) ** ((d - t0).days / 365.0) for d, v in flows) - dirty_price

    lo, hi = -0.95, 10.0
    flo, fhi = npv(lo), npv(hi)
    if not math.isfinite(flo) or not math.isfinite(fhi) or flo * fhi > 0:
        return None
    for _ in range(180):
        mid = (lo + hi) / 2
        fm = npv(mid)
        if flo * fm <= 0:
            hi = mid
            fhi = fm
        else:
            lo = mid
            flo = fm
    return (lo + hi) / 2 * 100


def coupon_projection(desc, sec, assumptions):
    """Return scenario coupon rate and a human-readable formula."""
    key_rate = fnum(assumptions.get("key_rate_pct"), 14.0)
    ruonia = fnum(assumptions.get("ruonia_pct"), 13.57)
    benchmark = str(desc.get("COUPON_BENCHMARK") or "").strip().upper()
    margin = fnum(desc.get("COUPON_BENCHMARK_SPREAD"))
    current_rate = fnum(sec.get("COUPONPERCENT"), 0.0)
    warnings = []

    if benchmark and margin is not None:
        if benchmark in {"RREFKEYR", "KEYRATE", "KEY_RATE", "CBR_KEYRATE"}:
            base = key_rate
            base_name = "КС"
        elif benchmark == "RUONIA":
            base = ruonia
            base_name = "RUONIA"
        elif benchmark == "RUONIA_IND":
            # Exact compounded-index conventions differ by issue; use RUONIA only
            # as a scenario approximation and flag it visibly.
            base = ruonia
            base_name = "RUONIA_IND≈RUONIA"
            warnings.append("RUONIA_IND projected approximately from the configured RUONIA scenario; verify issue convention")
        else:
            # Do not invent CPI/other benchmark mechanics. Fall back to the
            # currently published coupon rate for unannounced periods.
            warnings.append(f"Unsupported coupon benchmark {benchmark}; unannounced coupons use current published coupon rate")
            return current_rate, f"{benchmark} + {margin:.2f} п.п.", True, warnings
        return base + margin, f"{base_name} + {margin:.2f} п.п.", True, warnings

    return current_rate, f"фикс {current_rate:.4g}%", False, warnings


def amort_value(row):
    """MOEX amortization amount in currency units, tolerating schema variants."""
    for key in ("value", "value_rub", "amortvalue"):
        v = fnum(row.get(key))
        if v is not None:
            return v
    return None


def calculate_metrics(sec, md, desc, bnd, assumptions):
    warnings = []
    face = fnum(sec.get("FACEVALUE"))
    nkd = fnum(sec.get("ACCRUEDINT"), 0.0) or 0.0
    mat = date_of(sec.get("MATDATE") or desc.get("MATDATE"))
    settle = date_of(sec.get("SETTLEDATE")) or dt.date.today()

    # For a purchase "now", ASK/OFFER is the economically relevant quote.
    ask = fnum(md.get("OFFER"))
    bid = fnum(md.get("BID"))
    last = fnum(md.get("LAST"))
    fallback = fnum(sec.get("PREVLEGALCLOSEPRICE")) or fnum(sec.get("PREVPRICE"))
    px = ask or last or fallback
    price_source = "OFFER" if ask else "LAST" if last else "PREVLEGALCLOSEPRICE/PREVPRICE"

    if face is None or face <= 0 or px is None or mat is None or mat <= settle:
        return {
            "ok": False,
            "reason": "insufficient_price_face_or_maturity_data",
            "price_source": price_source,
        }

    clean = face * px / 100.0
    dirty = clean + nkd
    days = (mat - settle).days

    projected_rate, formula, is_floater, projection_warnings = coupon_projection(desc, sec, assumptions)
    warnings.extend(projection_warnings)
    current_rate = fnum(sec.get("COUPONPERCENT"), projected_rate) or projected_rate

    # Current coupon yield: currently published annual coupon / current clean price.
    current_yield = (face * current_rate / 100.0) / clean * 100.0 if clean > 0 else None

    # Build cashflows independently: coupon dates and amortization dates need not coincide.
    flows = []
    coupon_cash = 0.0
    estimated_coupons = 0
    future_coupons = []
    for c in bnd.get("coupons", []):
        d = date_of(c.get("coupondate"))
        if not d or not (settle < d <= mat):
            continue
        value = fnum(c.get("value"))
        estimated = False
        if value is None:
            c_face = fnum(c.get("facevalue"), face) or face
            start = date_of(c.get("startdate"))
            period_days = (d - start).days if start and d > start else max(1, round(365 / max(1, int(fnum(desc.get("COUPONFREQUENCY"), 12)))))
            value = c_face * projected_rate / 100.0 * period_days / 365.0
            estimated = True
            estimated_coupons += 1
        coupon_cash += value
        flows.append((d, value))
        future_coupons.append({
            "date": d.isoformat(),
            "amount": round(value, 6),
            "estimated": estimated,
        })

    amort_cash = 0.0
    future_amort = []
    for a in bnd.get("amortizations", []):
        d = date_of(a.get("amortdate"))
        value = amort_value(a)
        if not d or value is None or value <= 0 or not (settle < d <= mat):
            continue
        amort_cash += value
        flows.append((d, value))
        future_amort.append({"date": d.isoformat(), "amount": round(value, 6)})

    # Some issues have no explicit final amortization row in ISS. Return any
    # residual current face value at maturity, but never double-count it.
    residual = max(0.0, face - amort_cash)
    if residual > 0.005:
        flows.append((mat, residual))
        future_amort.append({"date": mat.isoformat(), "amount": round(residual, 6), "synthetic_residual": True})
        amort_cash += residual

    # Aggregate same-date flows for XIRR and auditability.
    by_date = {}
    for d, v in flows:
        by_date[d] = by_date.get(d, 0.0) + v
    flows = sorted(by_date.items())

    total_future = sum(v for _, v in flows)
    profit = total_future - dirty
    total_return_pct = profit / dirty * 100.0 if dirty > 0 else None
    simple_annual = total_return_pct * 365.0 / days if total_return_pct is not None and days > 0 else None
    xirr = cashflow_irr(flows, dirty, settle)
    moex_yield = fnum(md.get("YIELD"))
    key_rate = fnum(assumptions.get("key_rate_pct"), 14.0)
    spread = simple_annual - key_rate if simple_annual is not None else None
    body_result = face - clean

    if moex_yield is not None and xirr is not None and abs(xirr - moex_yield) > 0.35:
        warnings.append(f"Calculated XIRR differs from MOEX YIELD by {xirr - moex_yield:+.2f} pp; verify convention/cashflows")
    if estimated_coupons:
        warnings.append(
            f"{estimated_coupons} future coupon(s) are not announced and were projected using scenario rate {projected_rate:.4g}%"
        )
    if len(future_amort) > 1:
        warnings.append("Bond amortizes principal; simple annualized return ignores timing benefit of early principal repayments—use XIRR for comparison")

    return {
        "ok": True,
        "definitions": {
            "current_coupon_yield_pct": "current published annual coupon divided by clean purchase price",
            "simple_yield_to_maturity_pct": "(all future cashflows - dirty purchase price) / dirty purchase price * 365 / days to maturity; no reinvestment",
            "xirr_effective_pct": "annual effective IRR of dated cashflows",
            "spread_to_key_rate_simple_pp": "simple yield to maturity minus configured key-rate scenario",
        },
        "assumptions": {
            "key_rate_pct": key_rate,
            "ruonia_pct": fnum(assumptions.get("ruonia_pct"), 13.57),
            "unannounced_coupon_projection_pct": round(projected_rate, 6),
        },
        "coupon": {
            "formula": formula,
            "is_floater": is_floater,
            "current_published_rate_pct": round(current_rate, 6),
            "projected_rate_pct": round(projected_rate, 6),
            "estimated_future_coupon_count": estimated_coupons,
        },
        "purchase": {
            "price_pct": round(px, 6),
            "price_source": price_source,
            "bid_pct": bid,
            "ask_pct": ask,
            "last_pct": last,
            "face_value": round(face, 6),
            "clean_price_rub": round(clean, 6),
            "accrued_interest_rub": round(nkd, 6),
            "dirty_price_rub": round(dirty, 6),
            "settlement_date": settle.isoformat(),
        },
        "maturity": {
            "date": mat.isoformat(),
            "days": days,
            "coupon_cash_rub": round(coupon_cash, 6),
            "principal_cash_rub": round(amort_cash, 6),
            "total_future_cash_rub": round(total_future, 6),
            "profit_per_bond_rub": round(profit, 6),
            "body_discount_premium_result_rub": round(body_result, 6),
            "total_return_pct": round(total_return_pct, 6) if total_return_pct is not None else None,
        },
        "yields": {
            "current_coupon_yield_pct": round(current_yield, 6) if current_yield is not None else None,
            "simple_yield_to_maturity_pct": round(simple_annual, 6) if simple_annual is not None else None,
            "xirr_effective_pct": round(xirr, 6) if xirr is not None else None,
            "moex_yield_pct": moex_yield,
            "spread_to_key_rate_simple_pp": round(spread, 6) if spread is not None else None,
        },
        "projected_cashflows": {
            "coupons": future_coupons,
            "principal": future_amort,
        },
        "warnings": warnings,
    }


def fetch_one(secid: str, assumptions: dict):
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
    metrics = calculate_metrics(sec, md, desc, bnd, assumptions)

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
        "metrics": metrics,
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
    assumptions = watch.get("assumptions", {})
    if not secids:
        raise SystemExit("watchlist.json contains no secids")

    now = dt.datetime.now(dt.timezone.utc)
    result = {
        "generated_at_utc": now.isoformat(timespec="seconds"),
        "generated_at_msk": now.astimezone(dt.timezone(dt.timedelta(hours=3))).isoformat(timespec="seconds"),
        "source": "MOEX ISS",
        "source_base": BASE,
        "note": "Public MOEX ISS data may be delayed. Calculated yields are transparent analytical fields, not exchange trading signals.",
        "assumptions": {
            "key_rate_pct": fnum(assumptions.get("key_rate_pct"), 14.0),
            "ruonia_pct": fnum(assumptions.get("ruonia_pct"), 13.57),
        },
        "count": len(secids),
        "bonds": [],
    }

    for secid in secids:
        try:
            result["bonds"].append(fetch_one(str(secid).strip(), assumptions))
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError, TypeError) as e:
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
