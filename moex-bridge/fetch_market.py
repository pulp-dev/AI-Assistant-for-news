#!/usr/bin/env python3
import json, pathlib, datetime as dt
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE='https://iss.moex.com/iss'
ROOT=pathlib.Path(__file__).resolve().parent
DATA=ROOT/'data'
BOARDS=('TQCB','TQOB')
SEC_FIELDS='SECID,SHORTNAME,SECNAME,ISIN,REGNUMBER,FACEVALUE,FACEUNIT,ACCRUEDINT,COUPONPERCENT,COUPONVALUE,NEXTCOUPON,MATDATE,OFFERDATE,BUYBACKPRICE,LISTLEVEL,ISSUESIZE,PREVPRICE,PREVLEGALCLOSEPRICE,SETTLEDATE'
MD_FIELDS='SECID,BID,OFFER,LAST,YIELD,MARKETPRICE,MARKETPRICE2,NUMTRADES,VALTODAY,VOLTODAY,SYSTIME,UPDATETIME,SEQNUM'

def get(path, **p):
    p.setdefault('iss.meta','off')
    u=f'{BASE}{path}.json?{urlencode(p)}'
    with urlopen(Request(u,headers={'User-Agent':'moex-github-bridge/market'}),timeout=60) as r:
        return json.load(r)

def rows(p, block):
    b=p.get(block) or {}; c=b.get('columns') or []
    return [dict(zip(c,x)) for x in (b.get('data') or [])]

def page(board, block, fields):
    out=[]; start=0
    while True:
        p=get(f'/engines/stock/markets/bonds/boards/{board}/securities', **{'iss.only':block,f'{block}.columns':fields,'start':start})
        x=rows(p,block)
        if not x: break
        out+=x; start+=len(x)
        if len(x)<100: break
    return out

def num(x):
    try: return None if x in (None,'') else float(x)
    except: return None

def compact(board,s,m):
    face=num(s.get('FACEVALUE')); ask=num(m.get('OFFER')); last=num(m.get('LAST'))
    prev=num(s.get('PREVLEGALCLOSEPRICE')) or num(s.get('PREVPRICE'))
    px=ask or last or prev; nkd=num(s.get('ACCRUEDINT')) or 0; cp=num(s.get('COUPONPERCENT'))
    clean=face*px/100 if face is not None and px is not None else None
    return {'board':board,'secid':s.get('SECID'),'isin':s.get('ISIN'),'shortname':s.get('SHORTNAME'),'name':s.get('SECNAME'),'regnumber':s.get('REGNUMBER'),'face':face,'faceunit':s.get('FACEUNIT'),'nkd':nkd,'coupon_pct':cp,'coupon_value':num(s.get('COUPONVALUE')),'next_coupon':s.get('NEXTCOUPON'),'maturity':s.get('MATDATE'),'offer_date':s.get('OFFERDATE'),'buyback_price':num(s.get('BUYBACKPRICE')),'list_level':s.get('LISTLEVEL'),'issue_size':s.get('ISSUESIZE'),'settle_date':s.get('SETTLEDATE'),'bid':num(m.get('BID')),'offer':ask,'last':last,'moex_yield':num(m.get('YIELD')),'num_trades':m.get('NUMTRADES'),'value_today':m.get('VALTODAY'),'volume_today':m.get('VOLTODAY'),'system_time':m.get('SYSTIME'),'purchase_price_pct':px,'clean_price_rub':round(clean,6) if clean is not None else None,'dirty_price_rub':round(clean+nkd,6) if clean is not None else None,'current_coupon_yield_pct':round(cp/px*100,6) if cp is not None and px else None}

def main():
    DATA.mkdir(parents=True,exist_ok=True); allr=[]; counts={}
    for b in BOARDS:
        ss=page(b,'securities',SEC_FIELDS); mm=page(b,'marketdata',MD_FIELDS); md={x.get('SECID'):x for x in mm}
        rr=[compact(b,s,md.get(s.get('SECID'),{})) for s in ss if s.get('SECID')]
        counts[b]=len(rr); allr+=rr
    allr.sort(key=lambda r:(r['board'],r['secid']))
    (DATA/'market.jsonl').write_text('\n'.join(json.dumps(r,ensure_ascii=False,separators=(',',':')) for r in allr)+'\n',encoding='utf-8')
    idx=[{k:r.get(k) for k in ('secid','isin','shortname','name','board')} for r in allr]
    (DATA/'market_index.json').write_text(json.dumps(idx,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    now=dt.datetime.now(dt.timezone.utc)
    meta={'generated_at_utc':now.isoformat(timespec='seconds'),'generated_at_msk':now.astimezone(dt.timezone(dt.timedelta(hours=3))).isoformat(timespec='seconds'),'source':'MOEX ISS','coverage':list(BOARDS),'board_counts':counts,'total':len(allr)}
    (DATA/'market_meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print(meta)
if __name__=='__main__': main()
