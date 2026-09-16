#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
latest = json.loads((ROOT/'data/latest.json').read_text(encoding='utf-8'))
targets = json.loads((ROOT/'floater_targets.json').read_text(encoding='utf-8'))['targets']
by = {b.get('secid'): b for b in latest.get('bonds', [])}
lines = ['isin\tname\tmatdate\tsecurity_offerdate\tbuybackprice\traw_offers']
for t in targets:
    b = by.get(t['isin']) or {}
    sec = b.get('security') or {}
    offers = (b.get('cashflows') or {}).get('offers') or []
    compact=[]
    for o in offers:
        compact.append({k:o.get(k) for k in ('offerdate','offertype','price','buybackprice','facevalue','value') if o.get(k) is not None})
    lines.append('\t'.join([
        t['isin'], t.get('name',''), str(sec.get('MATDATE') or ''), str(sec.get('OFFERDATE') or ''), str(sec.get('BUYBACKPRICE') or ''),
        json.dumps(compact, ensure_ascii=False, separators=(',',':'))
    ]))
out=ROOT/'data/floater_offers.tsv'
out.write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('wrote',out)
