#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Produce a small practical pre-screen for ~1–1.5y fixed-coupon bonds."""
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
    clean=face*price/100; dirty=clean+nkd
    simple=(face+face*c/100*days/365-dirty)/dirty*365/days*100
    if not (14.7 <= simple <= 30): continue
    size=r.get('issue_size') or 0
    if size and size < 500000: continue
    name=(r.get('name') or '')
    if any(x in name for x in ('СО-', 'структур', 'ипотеч')): continue
    rows.append({
      'secid':r.get('secid'),'name':name,'shortname':r.get('shortname'),'price_pct':price,
      'coupon_pct':c,'nkd':nkd,'maturity':r.get('maturity'),'days':days,
      'approx_simple_pct':round(simple,3),'moex_yield_pct':r.get('moex_yield'),
      'issue_size':r.get('issue_size'),'value_today':r.get('value_today'),'num_trades':r.get('num_trades'),
      'list_level':r.get('list_level')})
rows.sort(key=lambda x:(-x['approx_simple_pct'],x['days']))
rows=rows[:80]
(D/'fixed_shortlist.json').write_text(json.dumps({'count':len(rows),'candidates':rows},ensure_ascii=False,indent=2),encoding='utf-8')
print('shortlist',len(rows))
