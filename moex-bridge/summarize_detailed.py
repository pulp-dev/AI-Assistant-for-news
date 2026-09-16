#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
from pathlib import Path
D=Path(__file__).resolve().parent/'data'
p=json.loads((D/'latest.json').read_text(encoding='utf-8'))
lines=['secid\tname\tformula\tfloater\tprice\tprice_source\tnkd\tdirty\tmaturity\tdays\tcurrent_coupon\tsimple\txirr\tmoex_yield\tamort_before_maturity\toffers']
for b in p.get('bonds',[]):
    if not b.get('ok'): continue
    m=b.get('metrics') or {}; sec=b.get('security') or {}; cf=b.get('cashflows') or {}; coupon=m.get('coupon') or {}; buy=m.get('purchase') or {}; mat=m.get('maturity') or {}; y=m.get('yields') or {}
    maturity=mat.get('date') or sec.get('MATDATE')
    am=cf.get('amortizations') or []
    intermediate=sum(1 for a in am if a.get('amortdate') and a.get('amortdate') != maturity)
    offers=len(cf.get('offers') or [])
    vals=[b.get('secid'),sec.get('SECNAME') or sec.get('SHORTNAME'),coupon.get('formula'),coupon.get('is_floater'),buy.get('price_pct'),buy.get('price_source'),buy.get('accrued_interest_rub'),buy.get('dirty_price_rub'),maturity,mat.get('days'),y.get('current_coupon_yield_pct'),y.get('simple_yield_to_maturity_pct'),y.get('xirr_effective_pct'),y.get('moex_yield_pct'),intermediate,offers]
    lines.append('\t'.join('' if v is None else str(v) for v in vals))
(D/'detailed_summary.tsv').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('rows',len(lines)-1)
