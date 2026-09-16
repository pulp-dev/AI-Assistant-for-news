#!/usr/bin/env python3
import json
from pathlib import Path
D=Path(__file__).resolve().parent/'data'
p=json.loads((D/'fixed_shortlist.json').read_text(encoding='utf-8'))
lines=['secid\tisin\tname\trating\trating_rank\tprice\tcoupon\tmaturity\tdays\tsimple0\tytm\thas_offer\tnext_offer_date\tnext_offer_type\toffers']
for r in p.get('candidates',[]):
    def g(*keys):
        for k in keys:
            if k in r: return r.get(k)
        return ''
    offers=json.dumps(g('offers') or [],ensure_ascii=False,separators=(',',':'))
    vals=[g('secid'),g('isin'),g('name'),g('rating'),g('rating_rank'),g('price','price_pct'),g('coupon','coupon_pct'),g('maturity'),g('days'),g('simple0','approx_simple_pct'),g('ytm','moex_yield_pct'),g('has_offer'),g('next_offer_date'),g('next_offer_type'),offers]
    lines.append('\t'.join(str(x if x is not None else '') for x in vals))
(D/'fixed_shortlist.tsv').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(len(lines)-1)
