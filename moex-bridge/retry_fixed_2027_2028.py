#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Retry transient MOEX errors from fixed_2027_2028.json and merge results."""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import json
import time

import screen_fixed_2027_2028 as s

ORIG_GET = s.get


def retry_get(path: str, **params):
    last = None
    for i in range(6):
        try:
            return ORIG_GET(path, **params)
        except Exception as e:
            last = e
            time.sleep(1.0 + i * 1.5)
    raise last


s.get = retry_get


def main():
    payload = json.loads(s.OUT_JSON.read_text(encoding="utf-8"))
    err_ids = {x.get("secid") for x in (payload.get("errors") or []) if x.get("secid")}
    if not err_ids:
        print(json.dumps({"retry": 0, "recovered_candidates": 0, "remaining_errors": 0}, ensure_ascii=False))
        return

    market = []
    for line in s.MARKET.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("secid") in err_ids:
            market.append(r)

    recovered = []
    remaining = []
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(s.analyse, r): r.get("secid") for r in market}
        for fut in cf.as_completed(futs):
            secid = futs[fut]
            try:
                x = fut.result()
                if x and x.get("error"):
                    remaining.append(x)
                elif x:
                    recovered.append(x)
                # None means the request succeeded but the issue is not a qualifying fixed bond.
            except Exception as e:
                remaining.append({"secid": secid, "error": f"{type(e).__name__}: {e}"})

    by = {x.get("secid"): x for x in (payload.get("candidates") or []) if x.get("secid")}
    for x in recovered:
        by[x.get("secid")] = x
    results = list(by.values())
    results.sort(key=lambda x: (x["event_date"], x.get("name") or "", x["secid"]))

    now = dt.datetime.now(dt.timezone.utc)
    payload["retry_generated_at_utc"] = now.isoformat(timespec="seconds")
    payload["retry_generated_at_msk"] = now.astimezone(dt.timezone(dt.timedelta(hours=3))).isoformat(timespec="seconds")
    payload["errors"] = remaining
    payload["count"] = len(results)
    payload["candidates"] = results
    s.OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    cols = [
        "event_date","event_type","name","isin","rating","coupon_pct","price_pct","price_source",
        "current_face","nkd_rub","dirty_rub","days_to_event","simple_yield_pct","effective_xirr_pct",
        "moex_yield_pct","maturity","put_date","put_price_pct","amortization_count","estimated_coupon_count",
        "call_dates_ignored","unknown_offer_dates_ignored","num_trades","value_today"
    ]
    lines = ["\t".join(cols)]
    for r in results:
        vals = []
        for c in cols:
            v = r.get(c)
            if isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
            vals.append("" if v is None else str(v))
        lines.append("\t".join(vals))
    s.OUT_TSV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"retry": len(err_ids), "recovered_candidates": len(recovered), "remaining_errors": len(remaining), "total_candidates": len(results)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
