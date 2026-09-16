#!/usr/bin/env python3
import json, pathlib, datetime as dt
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE='https://iss.moex.com/iss'; ROOT=pathlib.Path(__file__).resolve().parent; DATA=ROOT/'data'
BOARDS=('TQCB','TQOB')
META_FILE=DATA/'bond_metadata.json'

def get(path, **p):
    p.setdefault('iss.meta','off'); u=f'{BASE}{path}.json?{urlencode(p)}'
    with urlopen(Request(u,headers={'User-Agent':'moex-github-bridge/market'}),timeout=90) as r: return json.load(r)

def rows(p,b):
    x=p.get(b) or {}; c=x.get('columns') or []; return [dict(zip(c,r)) for r in (x.get('data') or [])]

def num(x):
    try:return None if x in (None,'') else float(x)
    except:return None

def load_metadata():
    if not META_FILE.exists(): return {}, None
    try:
        p=json.loads(META_FILE.read_text(encoding='utf-8'))
        return p.get('bonds') or {}, p.get('generated_at_utc')
    except Exception:
        return {}, None

def compact(board,s,m,meta):
    face=num(s.get('FACEVALUE')); ask=num(m.get('OFFER')); last=num(m.get('LAST')); prev=num(s.get('PREVLEGALCLOSEPRICE')) or num(s.get('PREVPRICE')); px=ask or last or prev; nkd=num(s.get('ACCRUEDINT')) or 0; cp=num(s.get('COUPONPERCENT')); clean=face*px/100 if face is not None and px is not None else None
    offers=meta.get('offers') or []
    return {
      'board':board,'secid':s.get('SECID'),'isin':s.get('ISIN'),'shortname':s.get('SHORTNAME'),'name':s.get('SECNAME'),'regnumber':s.get('REGNUMBER'),
      'face':face,'faceunit':s.get('FACEUNIT'),'nkd':nkd,'coupon_pct':cp,'coupon_value':num(s.get('COUPONVALUE')),'next_coupon':s.get('NEXTCOUPON'),'maturity':s.get('MATDATE'),
      'offer_date':s.get('OFFERDATE'),'buyback_price':num(s.get('BUYBACKPRICE')),'has_offer':bool(offers or meta.get('next_offer_date')),'next_offer_date':meta.get('next_offer_date') or s.get('OFFERDATE'),'next_offer_type':meta.get('next_offer_type'),'offers':offers,
      'rating':meta.get('rating'),'rating_rank':meta.get('rating_rank'),'rating_source':meta.get('rating_source'),'rating_checked_at':meta.get('rating_checked_at'),
      'list_level':s.get('LISTLEVEL'),'issue_size':s.get('ISSUESIZE'),'settle_date':s.get('SETTLEDATE'),
      'bid':num(m.get('BID')),'offer':ask,'last':last,'moex_yield':num(m.get('YIELD')),'num_trades':m.get('NUMTRADES'),'value_today':m.get('VALTODAY'),'volume_today':m.get('VOLTODAY'),'system_time':m.get('SYSTIME'),
      'purchase_price_pct':px,'clean_price_rub':round(clean,6) if clean is not None else None,'dirty_price_rub':round(clean+nkd,6) if clean is not None else None,'current_coupon_yield_pct':round(cp/px*100,6) if cp is not None and px else None
    }

def main():
    DATA.mkdir(parents=True,exist_ok=True); allr=[]; counts={}; metadata,metadata_at=load_metadata()
    for b in BOARDS:
        p=get(f'/engines/stock/markets/bonds/boards/{b}/securities')
        ss=rows(p,'securities'); md={x.get('SECID'):x for x in rows(p,'marketdata') if x.get('SECID')}
        rr=[]
        for s in ss:
            if not s.get('SECID'): continue
            isin=s.get('ISIN') or s.get('SECID')
            rr.append(compact(b,s,md.get(s.get('SECID'),{}),metadata.get(isin,{}) if isin else {}))
        counts[b]=len(rr); allr+=rr
    allr.sort(key=lambda r:(r['board'],r['secid']))
    (DATA/'market.jsonl').write_text('\n'.join(json.dumps(r,ensure_ascii=False,separators=(',',':')) for r in allr)+'\n',encoding='utf-8')
    idx=[{k:r.get(k) for k in ('secid','isin','shortname','name','board','rating','rating_rank','has_offer','next_offer_date','next_offer_type')} for r in allr]
    (DATA/'market_index.json').write_text(json.dumps(idx,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    now=dt.datetime.now(dt.timezone.utc); meta={'generated_at_utc':now.isoformat(timespec='seconds'),'generated_at_msk':now.astimezone(dt.timezone(dt.timedelta(hours=3))).isoformat(timespec='seconds'),'source':'MOEX ISS','coverage':list(BOARDS),'board_counts':counts,'total':len(allr),'bond_metadata_generated_at_utc':metadata_at,'with_rating':sum(1 for r in allr if r.get('rating')),'with_offer_metadata':sum(1 for r in allr if r.get('has_offer'))}
    (DATA/'market_meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8'); print(meta)
if __name__=='__main__':main()
