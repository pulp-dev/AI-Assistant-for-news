#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parallel wrapper around fetch_moex.py; same fetch_one/calculation logic."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import json

from fetch_moex import WATCHLIST, OUT, BASE, fetch_one, fnum


def main():
    watch = json.loads(WATCHLIST.read_text(encoding="utf-8"))
    secids = [str(x).strip() for x in watch.get("secids", [])]
    assumptions = watch.get("assumptions", {})
    if not secids:
        raise SystemExit("watchlist.json contains no secids")

    now = dt.datetime.now(dt.timezone.utc)
    bonds = [None] * len(secids)
    with ThreadPoolExecutor(max_workers=10) as ex:
        future_to_idx = {ex.submit(fetch_one, secid, assumptions): i for i, secid in enumerate(secids)}
        for fut in as_completed(future_to_idx):
            i = future_to_idx[fut]
            secid = secids[i]
            try:
                bonds[i] = fut.result()
            except Exception as e:
                bonds[i] = {"secid": secid, "ok": False, "error": f"{type(e).__name__}: {e}"}

    result = {
        "generated_at_utc": now.isoformat(timespec="seconds"),
        "generated_at_msk": now.astimezone(dt.timezone(dt.timedelta(hours=3))).isoformat(timespec="seconds"),
        "source": "MOEX ISS",
        "source_base": BASE,
        "note": "Public MOEX ISS data may be delayed. Calculated yields are transparent analytical fields, not exchange trading signals.",
        "assumptions": {
            "key_rate_pct": fnum(assumptions.get("key_rate_pct"), 14.0),
            "ruonia_pct": fnum(assumptions.get("ruonia_pct"), 13.57),
        },
        "count": len(secids),
        "bonds": bonds,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT} with {len(bonds)} securities")


if __name__ == "__main__":
    main()
