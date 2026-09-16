#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pre-screen MOEX bond snapshot for fixed-coupon candidates."""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
INPUT = DATA / "market.jsonl"
OUTPUT = DATA / "fixed_screen.json"
MIN_DAYS = 270
MAX_DAYS = 550
MIN_APPROX_SIMPLE = 14.5

def f(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def d(s):
    try: return dt.date.fromisoformat(s)
    except Exception: return None

def main():
    candidates=[]
    fallback_settle=dt.date.today()
    stats={"rows":0,"face":0,"offer":0,"last":0,"coupon_pct":0,"maturity":0,"in_horizon":0,"calculable":0}
    samples=[]
    for raw in INPUT.read_text(encoding="utf-8").splitlines():
        if not raw.strip(): continue
        stats["rows"]+=1
        r=json.loads(raw)
        face=f(r.get("face")); offer=f(r.get("offer")); last=f(r.get("last")); coupon=f(r.get("coupon_pct")); nkd=f(r.get("nkd")) or 0.0
        maturity=d(r.get("maturity")); settle=d(r.get("settle_date")) or fallback_settle
        if face is not None: stats["face"]+=1
        if offer is not None: stats["offer"]+=1
        if last is not None: stats["last"]+=1
        if coupon is not None: stats["coupon_pct"]+=1
        if maturity is not None: stats["maturity"]+=1
        if not maturity: continue
        days=(maturity-settle).days
        if MIN_DAYS <= days <= MAX_DAYS:
            stats["in_horizon"]+=1
            if len(samples)<20:
                samples.append({"secid":r.get("secid"),"name":r.get("name"),"offer":offer,"last":last,"coupon_pct":coupon,"maturity":r.get("maturity"),"days":days})
        if face is None or offer is None or coupon is None: continue
        if not (MIN_DAYS <= days <= MAX_DAYS): continue
        stats["calculable"]+=1
        clean=face*offer/100.0; dirty=clean+nkd
        coupon_cash=face*coupon/100.0*days/365.0
        future=face+coupon_cash
        simple=(future-dirty)/dirty*365.0/days*100.0
        if simple < MIN_APPROX_SIMPLE: continue
        candidates.append({"secid":r.get("secid"),"isin":r.get("isin"),"shortname":r.get("shortname"),"name":r.get("name"),"board":r.get("board"),"offer_pct":offer,"nkd_rub":nkd,"dirty_rub":round(dirty,4),"coupon_pct":coupon,"maturity":r.get("maturity"),"days":days,"approx_simple_pct":round(simple,4),"moex_yield_pct":f(r.get("moex_yield")),"issue_size":r.get("issue_size"),"value_today":r.get("value_today"),"num_trades":r.get("num_trades"),"offer_date":r.get("offer_date"),"buyback_price":r.get("buyback_price"),"list_level":r.get("list_level")})
    candidates.sort(key=lambda x:(-x["approx_simple_pct"],x["days"],x["secid"] or ""))
    payload={"generated_from":"moex-bridge/data/market.jsonl","criteria":{"days_to_maturity_min":MIN_DAYS,"days_to_maturity_max":MAX_DAYS,"approx_simple_yield_min_pct":MIN_APPROX_SIMPLE,"requires_offer":True,"requires_coupon_pct":True,"note":"Pre-screen only. Verify fixed/floater, ratings, amortizations and exact simple yield."},"stats":stats,"horizon_samples":samples,"count":len(candidates),"candidates":candidates}
    OUTPUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(stats,ensure_ascii=False)); print(f"Saved {len(candidates)} pre-screen candidates")
if __name__=="__main__": main()
