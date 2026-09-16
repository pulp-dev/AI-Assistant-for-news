#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build slowly-changing rating and offer metadata for the MOEX bond cache."""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import html
from html.parser import HTMLParser
import json
import pathlib
import re
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = DATA / "bond_metadata.json"
SMART_BASE = "https://smart-lab.ru/q/bonds/order_by_val_to_day/desc/"
SMART_DETAIL = "https://smart-lab.ru/q/bonds/{isin}/"
MOEX_BONDIZATION = "https://iss.moex.com/iss/securities/{isin}/bondization.json?iss.meta=off&limit=400"
UA = "Mozilla/5.0 (compatible; bond-metadata-bridge/1.1)"
MAX_PAGES = 60
WORKERS = 10

RATING_LEVELS = [
    "D", "C", "CC", "CCC", "B-", "B", "B+", "BB-", "BB", "BB+",
    "BBB-", "BBB", "BBB+", "A-", "A", "A+", "AA-", "AA", "AA+", "AAA",
]
RATING_RANK = {r: i for i, r in enumerate(RATING_LEVELS)}


def fetch_text(url: str, timeout: int = 30) -> str:
    req = Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json"})
    with urlopen(req, timeout=timeout) as r:
        raw = r.read(); enc = r.headers.get_content_charset() or "utf-8"
    return raw.decode(enc, errors="replace")


def fetch_json(url: str, timeout: int = 30):
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as r: return json.load(r)


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.in_tr=False; self.in_td=False; self.cell_buf=[]; self.cells=[]; self.hrefs=[]; self.rows=[]
    def handle_starttag(self, tag, attrs):
        if tag == "tr": self.in_tr=True; self.cells=[]; self.hrefs=[]
        elif tag in ("td","th") and self.in_tr: self.in_td=True; self.cell_buf=[]
        elif tag == "a" and self.in_tr:
            href=dict(attrs).get("href")
            if href: self.hrefs.append(href)
    def handle_data(self, data):
        if self.in_td:
            s=data.strip()
            if s: self.cell_buf.append(s)
    def handle_endtag(self, tag):
        if tag in ("td","th") and self.in_tr and self.in_td:
            self.cells.append(" ".join(self.cell_buf).strip()); self.in_td=False; self.cell_buf=[]
        elif tag == "tr" and self.in_tr:
            self.rows.append((self.cells[:],self.hrefs[:])); self.in_tr=False


class FlatTextParser(HTMLParser):
    def __init__(self): super().__init__(); self.tokens=[]
    def handle_data(self, data):
        s=" ".join(html.unescape(data).split())
        if s: self.tokens.append(s)


def iso_date(v):
    if not v: return None
    s=str(v).strip()
    if s in {"-","—","нет","Нет","None"}: return None
    for fmt in ("%d.%m.%y","%d.%m.%Y","%d-%m-%Y","%Y-%m-%d"):
        try: return dt.datetime.strptime(s,fmt).date().isoformat()
        except ValueError: pass
    m=re.search(r"(\d{2})[.\-](\d{2})[.\-](\d{2,4})",s)
    if m:
        y=int(m.group(3)); y=y+2000 if y<100 else y
        try: return dt.date(y,int(m.group(2)),int(m.group(1))).isoformat()
        except ValueError: return None
    return None


def normalize_rating(v):
    if not v: return None
    s=str(v).upper().strip().replace("(RU)","").replace("RU","").replace(" ","")
    return s if s in RATING_RANK else None


def smart_page_url(page): return SMART_BASE if page==1 else f"{SMART_BASE}page{page}/"


def parse_listing_page(text):
    p=TableParser(); p.feed(text); out=[]; today=dt.date.today().isoformat()
    for cells,hrefs in p.rows:
        isin=None
        for href in hrefs:
            m=re.search(r"/q/bonds/([A-Z0-9]{12})/?",href)
            if m: isin=m.group(1); break
        if not isin or len(cells)<19: continue
        rating=normalize_rating(cells[7]); offer_date=iso_date(cells[18])
        if offer_date and offer_date < today: offer_date=None
        out.append({"isin":isin,"rating":rating,"smartlab_offer_date":offer_date})
    return out


def moex_rows(payload,block):
    x=payload.get(block) or {}; cols=x.get("columns") or []
    return [dict(zip(cols,row)) for row in (x.get("data") or [])]


def pick_ci(d,names):
    low={str(k).lower():v for k,v in d.items()}
    for name in names:
        if name.lower() in low and low[name.lower()] not in (None,""): return low[name.lower()]
    return None


def normalize_offer_type(raw):
    if raw in (None,""): return None
    s=str(raw).upper().strip()
    if "BPUT" in s or re.search(r"\bPUT\b",s): return "PUT"
    if "MCAL" in s or "CALL" in s: return "CALL"
    return "OTHER"


def fetch_moex_offers(isin):
    payload=fetch_json(MOEX_BONDIZATION.format(isin=quote(isin)),25)
    today=dt.date.today().isoformat(); offers=[]
    for r in moex_rows(payload,"offers"):
        raw_date=pick_ci(r,("offerdate","date","buybackdate","enddate","begindate")); d=iso_date(raw_date)
        if not d or d<today: continue
        typ_raw=pick_ci(r,("offertype","type","eventtype","event_type","kind")); price=pick_ci(r,("price","buybackprice","offerprice","value"))
        try: price=float(price) if price not in (None,"") else None
        except Exception: price=None
        offers.append({"date":d,"type":normalize_offer_type(typ_raw),"type_raw":None if typ_raw in (None,"") else str(typ_raw),"price":price})
    offers.sort(key=lambda x:x["date"]); uniq=[]; seen=set()
    for x in offers:
        key=(x["date"],x.get("type"),x.get("type_raw"),x.get("price"))
        if key not in seen: seen.add(key); uniq.append(x)
    return uniq


def smartlab_offer_type(isin):
    p=FlatTextParser(); p.feed(fetch_text(SMART_DETAIL.format(isin=quote(isin)),25)); tokens=p.tokens
    for i,t in enumerate(tokens):
        if t.startswith("Тип оферты"):
            for cand in tokens[i+1:i+8]:
                if cand in {"(?)","?","—","-"}: continue
                if cand.startswith("Дюрация"): break
                if "Оферты отсутствуют" in cand: return "NONE",cand
                return normalize_offer_type(cand),cand
    return None,None


def enrich_offer(item):
    isin=item["isin"]; offers=[]; err=None
    try: offers=fetch_moex_offers(isin)
    except Exception as e: err=f"MOEX: {type(e).__name__}: {e}"
    sl_type=sl_label=None
    need=item.get("smartlab_offer_date") and (not offers or offers[0].get("type") in (None,"OTHER"))
    if need:
        try: sl_type,sl_label=smartlab_offer_type(isin)
        except Exception as e: err=(err+"; " if err else "")+f"SmartLab: {type(e).__name__}: {e}"
    if offers and sl_type not in (None,"NONE") and offers[0].get("type") in (None,"OTHER"):
        offers[0]["type"]=sl_type; offers[0]["type_label"]=sl_label; offers[0]["type_source"]="smart-lab detail"
    elif not offers and item.get("smartlab_offer_date") and sl_type not in (None,"NONE"):
        offers=[{"date":item["smartlab_offer_date"],"type":sl_type,"type_label":sl_label,"type_source":"smart-lab detail","price":None}]
    return isin,offers,err


def main():
    DATA.mkdir(parents=True,exist_ok=True); now=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    listing={}; page_stats=[]; empty_streak=0
    for page in range(1,MAX_PAGES+1):
        try: items=parse_listing_page(fetch_text(smart_page_url(page),35))
        except Exception as e:
            page_stats.append({"page":page,"count":0,"error":f"{type(e).__name__}: {e}"}); break
        page_stats.append({"page":page,"count":len(items)})
        if not items:
            empty_streak+=1
            if empty_streak>=2: break
            continue
        empty_streak=0
        for x in items: listing[x["isin"]]=x
        if len(items)<100: break
        time.sleep(0.08)

    offer_items=[x for x in listing.values() if x.get("smartlab_offer_date")]; offer_results={}; errors=[]
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs={ex.submit(enrich_offer,x):x["isin"] for x in offer_items}
        for fut in cf.as_completed(futs):
            isin=futs[fut]
            try:
                i,offers,err=fut.result(); offer_results[i]=offers
                if err: errors.append({"isin":i,"error":err})
            except Exception as e: errors.append({"isin":isin,"error":f"{type(e).__name__}: {e}"})

    bonds={}
    for isin,x in listing.items():
        offers=offer_results.get(isin,[]); nxt=offers[0] if offers else None
        bonds[isin]={
          "rating":x.get("rating"),"rating_rank":RATING_RANK.get(x.get("rating")) if x.get("rating") else None,
          "rating_source":"Smart-Lab normalized public bond screener","rating_checked_at":now,
          "offers":offers,"next_offer_date":nxt.get("date") if nxt else None,"next_offer_type":nxt.get("type") if nxt else None,"next_offer_type_label":nxt.get("type_label") if nxt else None,
          "offer_source":"MOEX ISS bondization; Smart-Lab fallback for type label","offer_checked_at":now if x.get("smartlab_offer_date") else None
        }
    payload={
      "generated_at_utc":now,
      "sources":{"ratings":"https://smart-lab.ru/q/bonds/","offers":"https://iss.moex.com/iss/securities/{ISIN}/bondization","offer_type_fallback":"https://smart-lab.ru/q/bonds/{ISIN}/"},
      "rating_levels":RATING_LEVELS,"rating_rank_note":"Higher integer = stronger normalized grade; A- rank is 13.",
      "stats":{"listing_pages":page_stats,"bonds":len(bonds),"with_rating":sum(1 for b in bonds.values() if b.get("rating")),"with_offer_date":sum(1 for b in bonds.values() if b.get("next_offer_date")),"with_offer_type":sum(1 for b in bonds.values() if b.get("next_offer_type") in {"PUT","CALL","OTHER"}),"offer_errors":len(errors)},
      "errors":errors[:100],"bonds":bonds
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print(json.dumps(payload["stats"],ensure_ascii=False))

if __name__=="__main__": main()
