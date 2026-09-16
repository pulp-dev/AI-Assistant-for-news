#!/usr/bin/env python3
import json
from pathlib import Path
D=Path(__file__).resolve().parent/'data'
p=json.loads((D/'exact_fixed_screen.json').read_text(encoding='utf-8'))
rows=[]
for r in p.get('candidates',[]):
    name=(r.get('name') or '')
    # Ordinary coupon bonds only; omit structured/investment notes from the
    # user-facing shortlist. Keep normal fixed coupons, including discounted
    # older issues with low but genuine fixed coupons.
    if (r.get('coupon_pct') or 0) < 1: continue
    if any(x in name.lower() for x in ('инвестиционн', 'иос ', 'структур')): continue
    rows.append(r)
cols=['secid','name','rating','price_pct','coupon_pct','event_date','event_type','days_to_event','simple_yield_to_event_pct','xirr_to_event_pct','moex_yield_pct','num_trades','value_today']
lines=[f"count\t{len(rows)}",'\t'.join(cols)]
for r in rows:
    lines.append('\t'.join(str(r.get(c) if r.get(c) is not None else '') for c in cols))
(D/'exact_fixed_screen_compact.tsv').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(len(rows))
