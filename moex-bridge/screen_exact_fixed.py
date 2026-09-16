#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exact screen for fixed-rate bonds with rating A- or higher.

Criteria used for the user's search:
- normalized rating >= A- (rating_rank >= 13);
- fixed coupon: no MOEX coupon benchmark and all cashflows to the event are
  either published or computable from the current fixed coupon;
- horizon is to the nearest future offer or maturity, whichever comes first;
- horizon <= 1.5 years (548 days);
- user's simple annualized yield to the event >= 15%.

The script uses current/last market price from market.jsonl and official MOEX
bondization/description for cashflows and offer schedule.
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
OUT_JSON = DATA / "exact_fixed_screen.json"
OUT_TSV = DATA / "exact_fixed_screen.tsv"
BASE = "https://iss.moex.com/iss"
UA = "moex-github-bridge/exact-fixed-screen"
RATING_MIN = 13  # A-
MAX_DAYS = 548   # ~1.5 years
MIN_SIMPLE = 15.0
WORKERS = 14


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
    with urlopen(req, timeout=35) as r:
        return json.load(r)


def rows(payload, block):
    x = payload.get(block) or {}; cols = x.get("columns") or []
    return [dict(zip(cols, r)) for r in (x.get("data") or [])]


def description(secid):
    p = get(f"/securities/{quote(secid)}")
    return {r.get("name"): r.get("value") for r in rows(p, "description") if r.get("name")}


def bondization(secid):
    p = get(f"/securities/{quote(secid)}/bondization", limit=400)
    return {"coupons": rows(p, "coupons"), "amortizations": rows(p, "amortizations"), "offers": rows(p, "offers")}


def amort_value(row):
    for k in ("value", "value_rub", "amortvalue"):
        v = f(row.get(k))
        if v is not None: return v
    return None


def xirr(flows, price, t0):
    if not flows or price <= 0: return None
    def npv(rate):
        if rate <= -0.999999: return math.inf
        return sum(v / (1 + rate) ** ((dd - t0).days / 365.0) for dd, v in flows) - price
    lo, hi = -0.95, 10.0
    flo, fhi = npv(lo), npv(hi)
    if not math.isfinite(flo) or not math.isfinite(fhi) or flo * fhi > 0: return None
    for _ in range(160):
        mid=(lo+hi)/2; fm=npv(mid)
        if flo*fm <= 0: hi=mid; fhi=fm
        else: lo=mid; flo=fm
    return (lo+hi)/2*100


def official_offer_map(bnd):
    out = {}
    for o in bnd.get("offers", []):
        low = {str(k).lower(): v for k,v in o.items()}
        rawd = low.get("offerdate") or low.get("date") or low.get("buybackdate") or low.get("enddate") or low.get("begindate")
        dd = d(rawd)
        if not dd: continue
        price = f(low.get("price") or low.get("buybackprice") or low.get("offerprice") or low.get("value"))
        typ = low.get("offertype") or low.get("type") or low.get("eventtype") or low.get("kind")
        out[dd.isoformat()] = {"price_pct": price, "type_raw": typ}
    return out


def analyse(row):
    secid=row.get("secid"); face=f(row.get("face")); nkd=f(row.get("nkd"),0) or 0
    settle=d(row.get("settle_date")) or dt.date.today(); maturity=d(row.get("maturity"))
    if not secid or face is None or face <= 0 or not maturity or maturity <= settle: return None
    rating_rank=row.get("rating_rank")
    try: rating_rank=int(rating_rank)
    except Exception: return None
    if rating_rank < RATING_MIN: return None

    # nearest future offer from enriched market cache
    offer_date=d(row.get("next_offer_date"))
    if offer_date and offer_date <= settle: offer_date=None
    event_date=min([x for x in (maturity, offer_date) if x is not None])
    days=(event_date-settle).days
    if days <= 0 or days > MAX_DAYS: return None

    px=f(row.get("offer"))
    price_source="OFFER"
    if px is None:
        px=f(row.get("last")); price_source="LAST"
    if px is None:
        px=f(row.get("purchase_price_pct")); price_source="PREV/LAST FALLBACK"
    if px is None or px <= 0: return None

    try:
        desc=description(secid); bnd=bondization(secid)
    except Exception as e:
        return {"error":f"{type(e).__name__}: {e}","secid":secid,"name":row.get("name")}

    benchmark=str(desc.get("COUPON_BENCHMARK") or "").strip()
    margin=desc.get("COUPON_BENCHMARK_SPREAD")
    if benchmark or margin not in (None, "", "0", 0, 0.0):
        return None  # floater / benchmark-linked

    coupon_rate=f(row.get("coupon_pct"),0) or 0
    if coupon_rate <= 0: return None

    clean=face*px/100.0; dirty=clean+nkd
    cash=[]; coupon_cash=0.0; coupon_count=0; estimated_count=0
    freq=max(1,int(f(desc.get("COUPONFREQUENCY"), 2) or 2))
    for c in bnd.get("coupons", []):
        cd=d(c.get("coupondate"))
        if not cd or not (settle < cd <= event_date): continue
        val=f(c.get("value")); est=False
        if val is None:
            cface=f(c.get("facevalue"), face) or face
            start=d(c.get("startdate"))
            pdays=(cd-start).days if start and cd>start else max(1, round(365/freq))
            val=cface*coupon_rate/100.0*pdays/365.0; est=True; estimated_count+=1
        coupon_cash+=val; coupon_count+=1; cash.append((cd,val))

    amort_cash=0.0; amort_count=0
    for a in bnd.get("amortizations", []):
        ad=d(a.get("amortdate")); val=amort_value(a)
        if not ad or val is None or val <= 0 or not (settle < ad <= event_date): continue
        amort_cash+=val; amort_count+=1; cash.append((ad,val))

    remaining=max(0.0, face-amort_cash)
    event_type="MATURITY"
    event_price_pct=None
    if offer_date and offer_date <= maturity and event_date == offer_date:
        event_type=row.get("next_offer_type") or "OFFER"
        official=official_offer_map(bnd).get(event_date.isoformat(),{})
        event_price_pct=f(official.get("price_pct"))
        # metadata cache stores offer prices in its offers list too
        if event_price_pct is None:
            for o in (row.get("offers") or []):
                if o.get("date") == event_date.isoformat():
                    event_price_pct=f(o.get("price")); break
        if event_price_pct is None: event_price_pct=100.0
        redemption=remaining*event_price_pct/100.0
        cash.append((event_date, redemption))
    else:
        # at maturity, ensure remaining principal is returned even when ISS lacks
        # a separate final amortization row
        redemption=remaining
        if redemption > 0.005: cash.append((maturity,redemption))

    # aggregate dates
    by={}
    for dd,v in cash: by[dd]=by.get(dd,0)+v
    cash=sorted(by.items())
    total=sum(v for _,v in cash)
    profit=total-dirty
    simple=profit/dirty*365/days*100 if dirty>0 else None
    if simple is None or simple < MIN_SIMPLE: return None
    irr=xirr(cash,dirty,settle)
    current_coupon=(face*coupon_rate/100)/clean*100 if clean>0 else None

    return {
        "secid":secid,"isin":row.get("isin"),"name":row.get("name"),"shortname":row.get("shortname"),
        "rating":row.get("rating"),"rating_rank":rating_rank,
        "price_pct":round(px,4),"price_source":price_source,"nkd":round(nkd,4),"dirty_rub":round(dirty,4),
        "coupon_pct":round(coupon_rate,6),"current_coupon_yield_pct":round(current_coupon,4) if current_coupon is not None else None,
        "event_date":event_date.isoformat(),"event_type":event_type,"event_price_pct":event_price_pct,
        "maturity":maturity.isoformat(),"days_to_event":days,
        "amortizations_before_event":amort_count,"coupon_count_to_event":coupon_count,"estimated_coupon_count":estimated_count,
        "future_cash_rub":round(total,4),"profit_per_bond_rub":round(profit,4),
        "simple_yield_to_event_pct":round(simple,4),"xirr_to_event_pct":round(irr,4) if irr is not None else None,
        "moex_yield_pct":row.get("moex_yield"),"num_trades":row.get("num_trades"),"value_today":row.get("value_today"),
    }


def main():
    market=[]
    for line in MARKET.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try: market.append(json.loads(line))
            except Exception: pass
    prelim=[]
    today=dt.date.today()
    for r in market:
        try: rr=int(r.get("rating_rank"))
        except Exception: continue
        if rr < RATING_MIN: continue
        mat=d(r.get("maturity")); sett=d(r.get("settle_date")) or today
        od=d(r.get("next_offer_date"))
        if od and od <= sett: od=None
        ev=min([x for x in (mat,od) if x is not None], default=None)
        if not ev: continue
        dd=(ev-sett).days
        if 0 < dd <= MAX_DAYS and r.get("coupon_pct") is not None and r.get("purchase_price_pct") is not None:
            prelim.append(r)

    results=[]; errors=[]
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs={ex.submit(analyse,r):r.get("secid") for r in prelim}
        for fut in cf.as_completed(futs):
            try:
                x=fut.result()
                if not x: continue
                if x.get("error"): errors.append(x)
                else: results.append(x)
            except Exception as e:
                errors.append({"secid":futs[fut],"error":f"{type(e).__name__}: {e}"})

    results.sort(key=lambda x:(-x["simple_yield_to_event_pct"], x["days_to_event"], x["secid"]))
    payload={
        "generated_at_utc":dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "criteria":{"rating_min":"A-","rating_rank_min":RATING_MIN,"coupon_type":"fixed","max_days_to_offer_or_maturity":MAX_DAYS,"simple_yield_min_pct":MIN_SIMPLE},
        "price_note":"OFFER when present; otherwise LAST / prior close fallback",
        "count":len(results),"preliminary_count":len(prelim),"errors":errors,"candidates":results,
    }
    OUT_JSON.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    cols=["secid","name","rating","price_pct","price_source","coupon_pct","event_date","event_type","days_to_event","maturity","amortizations_before_event","current_coupon_yield_pct","simple_yield_to_event_pct","xirr_to_event_pct","moex_yield_pct","profit_per_bond_rub","num_trades","value_today"]
    lines=["\t".join(cols)]
    for r in results:
        lines.append("\t".join(str(r.get(c) if r.get(c) is not None else "") for c in cols))
    OUT_TSV.write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({"preliminary":len(prelim),"results":len(results),"errors":len(errors)},ensure_ascii=False))

if __name__=="__main__": main()
