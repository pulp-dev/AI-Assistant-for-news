#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Full MOEX RUB fixed-rate bond screen for investor events in 2027-2028.

Rules:
- universe: all bonds present in moex-bridge/data/market.jsonl (TQCB/TQOB);
- RUB/SUR face currency only;
- fixed coupon = no MOEX benchmark/spread linkage in security description;
- investor horizon = nearest future PUT (investor sell-back right), otherwise maturity;
- CALL is reported/ignored as an exit horizon;
- event year must be 2027 or 2028;
- no rating floor and no yield floor;
- purchase price hierarchy: OFFER -> LAST -> previous/market cache fallback; never BID;
- simple yield uses dirty price and no reinvestment;
- effective yield is XIRR of dated cash flows to the selected event.
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import json
import math
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
MARKET = DATA / "market.jsonl"
OUT_JSON = DATA / "fixed_2027_2028.json"
OUT_TSV = DATA / "fixed_2027_2028.tsv"
BASE = "https://iss.moex.com/iss"
UA = "moex-github-bridge/fixed-2027-2028"
WORKERS = 16
EVENT_YEARS = {2027, 2028}
RUB_UNITS = {"SUR", "RUB", "RUR"}


def f(v, default=None):
    try:
        if v in (None, ""): return default
        return float(v)
    except Exception:
        return default


def d(v):
    if not v: return None
    try: return dt.date.fromisoformat(str(v)[:10])
    except Exception: return None


def get(path: str, **params):
    params.setdefault("iss.meta", "off")
    url = f"{BASE}{path}.json?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=40) as r:
        return json.load(r)


def rows(payload, block):
    x = payload.get(block) or {}
    cols = x.get("columns") or []
    return [dict(zip(cols, r)) for r in (x.get("data") or [])]


def description(secid):
    p = get(f"/securities/{quote(secid)}")
    return {r.get("name"): r.get("value") for r in rows(p, "description") if r.get("name")}


def bondization(secid):
    p = get(f"/securities/{quote(secid)}/bondization", limit=500)
    return {
        "coupons": rows(p, "coupons"),
        "amortizations": rows(p, "amortizations"),
        "offers": rows(p, "offers"),
    }


def amort_value(row):
    low = {str(k).lower(): v for k, v in row.items()}
    for k in ("value", "value_rub", "amortvalue"):
        v = f(low.get(k))
        if v is not None: return v
    return None


def xirr(flows, price, t0):
    if not flows or price <= 0: return None
    def npv(rate):
        if rate <= -0.999999: return math.inf
        return sum(v / (1 + rate) ** ((dd - t0).days / 365.0) for dd, v in flows) - price
    lo, hi = -0.95, 20.0
    flo, fhi = npv(lo), npv(hi)
    if not math.isfinite(flo) or not math.isfinite(fhi) or flo * fhi > 0:
        return None
    for _ in range(180):
        mid = (lo + hi) / 2
        fm = npv(mid)
        if flo * fm <= 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2 * 100


def norm_offer_type(v):
    s = str(v or "").strip().lower()
    if not s: return None
    if "put" in s or "пут" in s or "право владель" in s or "право инвест" in s:
        return "PUT"
    if "call" in s or "колл" in s or "право эмит" in s:
        return "CALL"
    if s == "put": return "PUT"
    if s == "call": return "CALL"
    return None


def metadata_offers(row, settle):
    out = []
    for o in (row.get("offers") or []):
        od = d(o.get("date") or o.get("offerdate") or o.get("buybackdate"))
        if not od or od <= settle: continue
        typ = norm_offer_type(o.get("type") or o.get("type_label") or o.get("type_raw"))
        out.append({"date": od, "type": typ, "price_pct": f(o.get("price") or o.get("price_pct")), "source": "metadata"})
    nd = d(row.get("next_offer_date"))
    nt = norm_offer_type(row.get("next_offer_type"))
    if nd and nd > settle and not any(x["date"] == nd for x in out):
        out.append({"date": nd, "type": nt, "price_pct": f(row.get("buyback_price")), "source": "market-cache"})
    return out


def official_offers(bnd, settle):
    out = []
    for o in bnd.get("offers", []):
        low = {str(k).lower(): v for k, v in o.items()}
        od = d(low.get("offerdate") or low.get("date") or low.get("buybackdate") or low.get("enddate") or low.get("begindate"))
        if not od or od <= settle: continue
        typ = norm_offer_type(low.get("offertype") or low.get("type") or low.get("eventtype") or low.get("kind") or low.get("name"))
        price = f(low.get("price") or low.get("buybackprice") or low.get("offerprice") or low.get("value"))
        out.append({"date": od, "type": typ, "price_pct": price, "source": "MOEX-bondization"})
    return out


def merge_offers(meta, official):
    by = {}
    for x in meta + official:
        key = x["date"]
        cur = by.get(key, {"date": key, "type": None, "price_pct": None, "sources": []})
        if x.get("type") in ("PUT", "CALL"): cur["type"] = x["type"]
        if x.get("price_pct") is not None: cur["price_pct"] = x["price_pct"]
        cur["sources"].append(x.get("source"))
        by[key] = cur
    return sorted(by.values(), key=lambda x: x["date"])


def analyse(row):
    secid = row.get("secid")
    face = f(row.get("face"))
    nkd = f(row.get("nkd"), 0) or 0
    settle = d(row.get("settle_date")) or dt.date.today()
    maturity = d(row.get("maturity"))
    faceunit = str(row.get("faceunit") or "").upper()
    if not secid or face is None or face <= 0 or not maturity or maturity <= settle:
        return None
    if faceunit and faceunit not in RUB_UNITS:
        return None

    px = f(row.get("offer")); price_source = "OFFER"
    if px is None:
        px = f(row.get("last")); price_source = "LAST"
    if px is None:
        px = f(row.get("purchase_price_pct")); price_source = "PREV/LAST FALLBACK"
    if px is None or px <= 0:
        return None

    coupon_rate = f(row.get("coupon_pct"))
    if coupon_rate is None or coupon_rate <= 0:
        return None

    try:
        desc = description(secid)
        bnd = bondization(secid)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "secid": secid, "name": row.get("name")}

    benchmark = str(desc.get("COUPON_BENCHMARK") or "").strip()
    margin = desc.get("COUPON_BENCHMARK_SPREAD")
    if benchmark or margin not in (None, "", "0", 0, 0.0):
        return None

    offers = merge_offers(metadata_offers(row, settle), official_offers(bnd, settle))
    puts = [o for o in offers if o.get("type") == "PUT"]
    calls = [o for o in offers if o.get("type") == "CALL"]
    put = puts[0] if puts else None
    event_date = put["date"] if put and put["date"] < maturity else maturity
    event_type = "PUT" if put and put["date"] < maturity else "MATURITY"
    if event_date.year not in EVENT_YEARS:
        return None
    days = (event_date - settle).days
    if days <= 0:
        return None

    clean = face * px / 100.0
    dirty = clean + nkd
    cash = []
    coupon_cash = 0.0
    coupon_count = 0
    estimated_count = 0
    freq = max(1, int(f(desc.get("COUPONFREQUENCY"), 2) or 2))

    for c in bnd.get("coupons", []):
        low = {str(k).lower(): v for k, v in c.items()}
        cd = d(low.get("coupondate"))
        if not cd or not (settle < cd <= event_date):
            continue
        val = f(low.get("value")); est = False
        if val is None:
            cface = f(low.get("facevalue"), face) or face
            start = d(low.get("startdate"))
            pdays = (cd - start).days if start and cd > start else max(1, round(365 / freq))
            # Safe only for non-benchmark fixed coupons; mark as estimated.
            val = cface * coupon_rate / 100.0 * pdays / 365.0
            est = True
        coupon_cash += val
        coupon_count += 1
        estimated_count += int(est)
        cash.append((cd, val))

    amort_cash = 0.0
    amort_count = 0
    amort_schedule = []
    for a in bnd.get("amortizations", []):
        low = {str(k).lower(): v for k, v in a.items()}
        ad = d(low.get("amortdate"))
        val = amort_value(a)
        if not ad or val is None or val <= 0 or not (settle < ad <= event_date):
            continue
        amort_cash += val
        amort_count += 1
        amort_schedule.append({"date": ad.isoformat(), "amount": round(val, 6)})
        cash.append((ad, val))

    remaining = max(0.0, face - amort_cash)
    event_price_pct = None
    if event_type == "PUT":
        event_price_pct = put.get("price_pct") or 100.0
        redemption = remaining * event_price_pct / 100.0
        if redemption > 0.005:
            cash.append((event_date, redemption))
    else:
        if remaining > 0.005:
            cash.append((maturity, remaining))

    by = {}
    for dd, v in cash:
        by[dd] = by.get(dd, 0.0) + v
    cash = sorted(by.items())
    total = sum(v for _, v in cash)
    if total <= 0:
        return None
    profit = total - dirty
    simple = profit / dirty * 365 / days * 100
    irr = xirr(cash, dirty, settle)
    current_coupon_yield = coupon_rate / px * 100 if px else None

    rating = row.get("rating") or "NR"
    call_dates = [x["date"].isoformat() for x in calls]
    unknown_offer_dates = [x["date"].isoformat() for x in offers if x.get("type") is None]

    return {
        "secid": secid,
        "isin": row.get("isin"),
        "name": row.get("name"),
        "shortname": row.get("shortname"),
        "rating": rating,
        "rating_rank": row.get("rating_rank"),
        "faceunit": faceunit or None,
        "current_face": round(face, 6),
        "price_pct": round(px, 4),
        "price_source": price_source,
        "nkd_rub": round(nkd, 4),
        "clean_rub": round(clean, 4),
        "dirty_rub": round(dirty, 4),
        "coupon_pct": round(coupon_rate, 6),
        "current_coupon_yield_pct": round(current_coupon_yield, 4) if current_coupon_yield is not None else None,
        "event_date": event_date.isoformat(),
        "event_type": event_type,
        "event_price_pct": event_price_pct,
        "maturity": maturity.isoformat(),
        "days_to_event": days,
        "amortization_count": amort_count,
        "amortizations": amort_schedule,
        "coupon_count_to_event": coupon_count,
        "estimated_coupon_count": estimated_count,
        "future_cash_rub": round(total, 4),
        "profit_per_bond_rub": round(profit, 4),
        "simple_yield_pct": round(simple, 4),
        "effective_xirr_pct": round(irr, 4) if irr is not None else None,
        "moex_yield_pct": row.get("moex_yield"),
        "put_date": put["date"].isoformat() if put else None,
        "put_price_pct": put.get("price_pct") if put else None,
        "call_dates_ignored": call_dates,
        "unknown_offer_dates_ignored": unknown_offer_dates,
        "num_trades": row.get("num_trades"),
        "value_today": row.get("value_today"),
    }


def main():
    market = []
    for line in MARKET.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try: market.append(json.loads(line))
            except Exception: pass

    # Broad preselection only to reduce MOEX requests. Do not filter by rating/yield.
    prelim = []
    for r in market:
        faceunit = str(r.get("faceunit") or "").upper()
        if faceunit and faceunit not in RUB_UNITS: continue
        mat = d(r.get("maturity"))
        sett = d(r.get("settle_date")) or dt.date.today()
        if not mat or mat <= sett: continue
        cp = f(r.get("coupon_pct"))
        if cp is None or cp <= 0: continue
        if f(r.get("purchase_price_pct")) is None: continue
        # Include maturities in 2027/28 and every issue with an offer metadata flag,
        # because a PUT in 2027/28 may precede a later maturity.
        if mat.year in EVENT_YEARS or r.get("has_offer"):
            prelim.append(r)

    results = []
    errors = []
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(analyse, r): r.get("secid") for r in prelim}
        for fut in cf.as_completed(futs):
            try:
                x = fut.result()
                if not x: continue
                if x.get("error"): errors.append(x)
                else: results.append(x)
            except Exception as e:
                errors.append({"secid": futs[fut], "error": f"{type(e).__name__}: {e}"})

    results.sort(key=lambda x: (x["event_date"], x["name"] or "", x["secid"]))
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "generated_at_utc": now.isoformat(timespec="seconds"),
        "generated_at_msk": now.astimezone(dt.timezone(dt.timedelta(hours=3))).isoformat(timespec="seconds"),
        "source": "MOEX bridge market.jsonl + MOEX ISS bondization/description",
        "criteria": {
            "currency": "RUB/SUR",
            "coupon_type": "fixed / non-benchmark-linked",
            "event_years": [2027, 2028],
            "horizon_rule": "nearest investor PUT if known, otherwise maturity; CALL ignored",
            "rating_min": None,
            "yield_min": None,
            "price": "OFFER, else LAST, else previous/market-cache fallback; BID never used",
            "simple_yield": "no reinvestment; annualized total cash profit / dirty purchase price",
            "effective_yield": "XIRR of dated cash flows to selected event",
        },
        "market_rows": len(market),
        "preliminary_count": len(prelim),
        "count": len(results),
        "errors": errors,
        "candidates": results,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    cols = [
        "event_date","event_type","name","isin","rating","coupon_pct","price_pct","price_source",
        "current_face","nkd_rub","dirty_rub","days_to_event","simple_yield_pct","effective_xirr_pct",
        "moex_yield_pct","maturity","put_date","put_price_pct","amortization_count","estimated_coupon_count",
        "call_dates_ignored","unknown_offer_dates_ignored","num_trades","value_today"
    ]
    lines = ["\t".join(cols)]
    for r in results:
        vals=[]
        for c in cols:
            v=r.get(c)
            if isinstance(v,(list,dict)): v=json.dumps(v,ensure_ascii=False,separators=(",",":"))
            vals.append("" if v is None else str(v))
        lines.append("\t".join(vals))
    OUT_TSV.write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(json.dumps({"market_rows":len(market),"preliminary":len(prelim),"results":len(results),"errors":len(errors)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
