#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Produce a compact practical pre-screen for ~1–1.5y coupon bonds."""
import datetime as dt, json
from pathlib import Path
D=Path(__file__).resolve().parent/'data'
rows=[]
for line in (D/'market.jsonl').read_text(encoding='utf-8').splitlines():
    if not line.strip(): continue
    r=json.loads(line)
    try:
        face=float(r.get('face')); price=float(r.get('purchase_price_pct')); c=float(r.get('coupon_pct')); nkd=float(r.get('nkd') or 0)
        mat=dt.date.fromisoformat(r.get('maturity')); days=(mat-dt.date.today()).days
    except Exception: continue
    if not (300 <= days <= 550): continue
    if not (85 <= price <= 115): continue
    if c < 5: continue
    dirty=face*price/100+nkd
    simple=(face+face*c/100*days/365-dirty)/dirty*365/days*100
    if not (14.7 <= simple <= 30): continue
    size=r.get('issue_size') or 0
    if size and size < 500000: continue
    name=(r.get('name') or '')
    if any(x in name for x in ('СО-', 'структур', 'ипотеч')): continue
    rows.append({'secid':r.get('secid'),'name':name,'price':price,'coupon':c,'nkd':nkd,'maturity':r.get('maturity'),'days':days,'simple0':round(simple,3),'ytm':r.get('moex_yield')})
rows.sort(key=lambda x:(-x['simple0'],x['days']))
(D/'fixed_shortlist.json').write_text(json.dumps({'count':len(rows),'candidates':rows},ensure_ascii=False,indent=2),encoding='utf-8')
print('shortlist',len(rows))
