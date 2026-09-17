#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'
SRC=DATA/'fixed_2027_2028.json'
OUT=DATA/'fixed_2027_2028_summary.json'
RANKED=DATA/'fixed_2027_2028_ranked.tsv'

RATING_RANK={'D':0,'C':1,'CC':2,'CCC':3,'B-':4,'B':5,'B+':6,'BB-':7,'BB':8,'BB+':9,'BBB-':10,'BBB':11,'BBB+':12,'A-':13,'A':14,'A+':15,'AA-':16,'AA':17,'AA+':18,'AAA':19}

def slim(r):
    return {k:r.get(k) for k in ('event_date','event_type','name','isin','rating','coupon_pct','price_pct','price_source','current_face','nkd_rub','dirty_rub','days_to_event','simple_yield_pct','effective_xirr_pct','moex_yield_pct','maturity','put_date','amortization_count','estimated_coupon_count','num_trades')}

def main():
    p=json.loads(SRC.read_text(encoding='utf-8'))
    rows=p.get('candidates') or []
    ranked=sorted(rows,key=lambda r: (-(r.get('simple_yield_pct') if r.get('simple_yield_pct') is not None else -1e99),r.get('event_date') or '',r.get('name') or ''))
    cols=['rank','event_date','event_type','name','isin','rating','coupon_pct','price_pct','price_source','current_face','nkd_rub','dirty_rub','days_to_event','simple_yield_pct','effective_xirr_pct','moex_yield_pct','maturity','put_date','amortization_count','estimated_coupon_count','num_trades','value_today']
    lines=['\t'.join(cols)]
    for i,r in enumerate(ranked,1):
        vals=[]
        for c in cols:
            v=i if c=='rank' else r.get(c)
            vals.append('' if v is None else str(v))
        lines.append('\t'.join(vals))
    RANKED.write_text('\n'.join(lines)+'\n',encoding='utf-8')

    rated=[r for r in rows if r.get('rating') not in (None,'NR','')]
    aplus=[r for r in rated if RATING_RANK.get(r.get('rating'),-1)>=14]
    invgrade=[r for r in rated if RATING_RANK.get(r.get('rating'),-1)>=10]
    top=lambda xs,key,n=40: [slim(r) for r in sorted([r for r in xs if r.get(key) is not None],key=lambda r:-r[key])[:n]]
    anomaly=sorted([r for r in rows if r.get('simple_yield_pct') is not None and r.get('effective_xirr_pct') is not None],key=lambda r:abs(r['effective_xirr_pct']-r['simple_yield_pct']),reverse=True)[:40]
    out={
      'generated_at_msk':p.get('retry_generated_at_msk') or p.get('generated_at_msk'),
      'total':len(rows),
      'year_counts':dict(Counter((r.get('event_date') or '')[:4] for r in rows)),
      'event_type_counts':dict(Counter(r.get('event_type') or 'UNKNOWN' for r in rows)),
      'rating_counts':dict(Counter(r.get('rating') or 'NR' for r in rows)),
      'price_source_counts':dict(Counter(r.get('price_source') or 'UNKNOWN' for r in rows)),
      'rated_count':len(rated),'rating_A_or_higher_count':len(aplus),'rating_BBBminus_or_higher_count':len(invgrade),
      'amortizing_count':sum(1 for r in rows if (r.get('amortization_count') or 0)>0),
      'estimated_coupon_count_issues':sum(1 for r in rows if (r.get('estimated_coupon_count') or 0)>0),
      'top_simple_all':top(rows,'simple_yield_pct'),
      'top_effective_all':top(rows,'effective_xirr_pct'),
      'top_simple_rating_A_or_higher':top(aplus,'simple_yield_pct'),
      'top_effective_rating_A_or_higher':top(aplus,'effective_xirr_pct'),
      'largest_simple_vs_effective_spread':[dict(slim(r),spread_pct=round(r['effective_xirr_pct']-r['simple_yield_pct'],4)) for r in anomaly]
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:out[k] for k in ('total','year_counts','event_type_counts','rated_count','rating_A_or_higher_count','amortizing_count','estimated_coupon_count_issues')},ensure_ascii=False))

if __name__=='__main__':main()
