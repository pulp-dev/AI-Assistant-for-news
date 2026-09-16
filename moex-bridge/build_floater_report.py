#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a compact 2026-2027 floater screening report from data/latest.json.

Rules:
- purchase price: the bridge purchase price (OFFER -> LAST -> previous close);
- scenario: key rate from floater_targets.json + issue spread;
- announced coupons: use MOEX amount as published;
- unannounced coupons: project with the scenario rate and actual coupon-period days;
- entitlement: exclude a coupon when SETTLEDATE is later than its record date;
- horizon: target event date; if it is a PUT, buy back residual face at PUT price;
- CALL is reported but is never treated as an investor exit;
- simple yield: no reinvestment, annualized from dirty price.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
LATEST = DATA / "latest.json"
META = DATA / "bond_metadata.json"
TARGETS = ROOT / "floater_targets.json"
OUT_JSON = DATA / "floater_report.json"
OUT_TSV = DATA / "floater_report.tsv"


def fnum(x, default=None):
    try:
        if x in (None, ""):
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def dte(x):
    if not x:
        return None
    try:
        return dt.date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


def xirr(flows, dirty, settle):
    if not flows or not dirty or dirty <= 0:
        return None
    agg = {}
    for d, v in flows:
        agg[d] = agg.get(d, 0.0) + v
    flows = sorted(agg.items())

    def npv(rate):
        if rate <= -0.999999:
            return math.inf
        return sum(v / (1.0 + rate) ** ((d - settle).days / 365.0) for d, v in flows) - dirty

    lo, hi = -0.95, 10.0
    flo, fhi = npv(lo), npv(hi)
    if not math.isfinite(flo) or not math.isfinite(fhi) or flo * fhi > 0:
        return None
    for _ in range(180):
        mid = (lo + hi) / 2.0
        fm = npv(mid)
        if flo * fm <= 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2.0 * 100.0


def amort_value(row):
    for k in ("value", "value_rub", "amortvalue"):
        v = fnum(row.get(k))
        if v is not None:
            return v
    return None


def fmt_offer(o):
    date = o.get("date") or o.get("offerdate")
    typ = str(o.get("type") or o.get("offertype") or "").upper()
    price = fnum(o.get("price"))
    return date, typ, price


def main():
    latest = json.loads(LATEST.read_text(encoding="utf-8"))
    targets_doc = json.loads(TARGETS.read_text(encoding="utf-8"))
    meta_doc = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {"bonds": {}}
    metadata = meta_doc.get("bonds") or {}
    by_isin = {str(b.get("secid")): b for b in latest.get("bonds", []) if b.get("secid")}
    key_rate = fnum(targets_doc.get("key_rate_pct"), 14.0)
    rows = []

    for t in targets_doc.get("targets", []):
        isin = t["isin"]
        b = by_isin.get(isin)
        if not b or not b.get("ok"):
            rows.append({"isin": isin, "name": t.get("name"), "event_date": t.get("event_date"), "error": (b or {}).get("error", "not_in_snapshot")})
            continue

        sec = b.get("security") or {}
        market = b.get("market") or {}
        metrics = b.get("metrics") or {}
        buy = metrics.get("purchase") or {}
        cf = b.get("cashflows") or {}
        m = metadata.get(isin) or {}

        settle = dte(buy.get("settlement_date") or sec.get("SETTLEDATE"))
        event = dte(t.get("event_date"))
        maturity = dte(sec.get("MATDATE"))
        face = fnum(buy.get("face_value"), fnum(sec.get("FACEVALUE")))
        clean = fnum(buy.get("clean_price_rub"))
        nkd = fnum(buy.get("accrued_interest_rub"), fnum(sec.get("ACCRUEDINT"), 0.0)) or 0.0
        dirty = fnum(buy.get("dirty_price_rub"))
        price_pct = fnum(buy.get("price_pct"))
        price_source = buy.get("price_source")
        if clean is None and face is not None and price_pct is not None:
            clean = face * price_pct / 100.0
        if dirty is None and clean is not None:
            dirty = clean + nkd

        spread = fnum(t.get("spread_pp"), 0.0) or 0.0
        scenario_rate = key_rate + spread
        formula = f"КС + {spread:.2f} п.п."

        initial_face = None
        for item in (cf.get("coupons") or []) + (cf.get("amortizations") or []):
            initial_face = fnum(item.get("initialfacevalue"), initial_face)
            if initial_face is not None:
                break
        if initial_face is None:
            initial_face = face

        meta_offers = m.get("offers") or []
        raw_offers = cf.get("offers") or []
        puts, calls = [], []
        exact_put_price = None
        exact_put = False
        for o in meta_offers:
            od, typ, op = fmt_offer(o)
            if typ == "PUT":
                puts.append((od, op))
                if od == t.get("event_date"):
                    exact_put, exact_put_price = True, op
            elif typ == "CALL":
                calls.append((od, op))
        # MOEX raw offers usually do not distinguish PUT/CALL. Use them only to
        # recover an exact price when metadata already identifies the date as PUT.
        if exact_put and exact_put_price is None:
            for o in raw_offers:
                if str(o.get("offerdate"))[:10] == t.get("event_date"):
                    exact_put_price = fnum(o.get("price"))
                    break

        if maturity and event == maturity:
            event_type = "Погашение"
        elif exact_put:
            event_type = "PUT"
        else:
            # The target list was curated by the analyst. If its date is earlier
            # than maturity and MOEX shows an offer on that date, treat it as a
            # PUT only when it is not identified as CALL in metadata.
            raw_exact = [o for o in raw_offers if str(o.get("offerdate"))[:10] == t.get("event_date")]
            call_exact = any(od == t.get("event_date") for od, _ in calls)
            if event and maturity and event < maturity and raw_exact and not call_exact:
                event_type = "PUT*"
                exact_put = True
                exact_put_price = fnum(raw_exact[0].get("price"), 100.0)
            else:
                event_type = "Погашение" if maturity and event == maturity else "Целевая дата"

        flows = []
        coupon_total = 0.0
        coupon_rows = []
        excluded = []
        estimated_count = 0
        for c in cf.get("coupons") or []:
            cd = dte(c.get("coupondate"))
            if not cd or not settle or not event or not (settle < cd <= event):
                continue
            record = dte(c.get("recorddate"))
            if record and settle > record:
                excluded.append({"coupondate": cd.isoformat(), "recorddate": record.isoformat()})
                continue
            val = fnum(c.get("value"), fnum(c.get("value_rub")))
            estimated = False
            if val is None:
                cface = fnum(c.get("facevalue"), face) or face
                start = dte(c.get("startdate"))
                days = (cd - start).days if start and cd > start else 0
                if not days:
                    days = 30
                val = cface * scenario_rate / 100.0 * days / 365.0
                estimated = True
                estimated_count += 1
            coupon_total += val
            flows.append((cd, val))
            coupon_rows.append({"date": cd.isoformat(), "amount": round(val, 6), "estimated": estimated, "recorddate": record.isoformat() if record else None})

        amort_total = 0.0
        amort_rows = []
        for a in cf.get("amortizations") or []:
            ad = dte(a.get("amortdate"))
            av = amort_value(a)
            if not ad or av is None or av <= 0 or not settle or not event or not (settle < ad <= event):
                continue
            amort_total += av
            flows.append((ad, av))
            amort_rows.append({"date": ad.isoformat(), "amount": round(av, 6)})

        redemption = 0.0
        put_price = None
        if event_type.startswith("PUT"):
            put_price = exact_put_price if exact_put_price is not None else 100.0
            residual = max(0.0, (face or 0.0) - amort_total)
            redemption = residual * put_price / 100.0
            if redemption > 0:
                flows.append((event, redemption))
        else:
            # At maturity ISS normally has a final amortization row. If not,
            # synthesize return of any residual current face.
            residual = max(0.0, (face or 0.0) - amort_total)
            if maturity and event == maturity and residual > 0.005:
                redemption = residual
                flows.append((event, redemption))

        total_future = coupon_total + amort_total + redemption
        days_to_event = (event - settle).days if settle and event else None
        profit = total_future - dirty if dirty is not None else None
        simple_yield = None
        if profit is not None and dirty and days_to_event and days_to_event > 0:
            simple_yield = profit / dirty * 365.0 / days_to_event * 100.0
        eff = xirr(flows, dirty, settle) if settle and dirty else None
        current_coupon_yield = (face * scenario_rate / 100.0) / clean * 100.0 if face and clean else None
        moex_yield = fnum((metrics.get("yields") or {}).get("moex_yield_pct"), fnum(market.get("YIELD")))

        notes = []
        if excluded:
            notes.append("исключен купон из-за record date")
        if estimated_count:
            notes.append(f"{estimated_count} куп. рассчитано по КС=14%+спред")
        if event_type == "PUT*":
            notes.append("тип PUT восстановлен по MOEX offer; metadata не классифицировала")
        if event_type == "Целевая дата":
            notes.append("дата не совпадает с погашением и не подтверждена как PUT")

        row = {
            "snapshot_msk": latest.get("generated_at_msk"),
            "event_date": event.isoformat() if event else t.get("event_date"),
            "event_type": event_type,
            "name": t.get("name"),
            "isin": isin,
            "rating_input": t.get("rating"),
            "formula": formula,
            "scenario_coupon_rate_pct": round(scenario_rate, 6),
            "price_pct": round(price_pct, 6) if price_pct is not None else None,
            "price_source": price_source,
            "current_face": round(face, 6) if face is not None else None,
            "initial_face": round(initial_face, 6) if initial_face is not None else None,
            "nkd": round(nkd, 6),
            "clean_rub": round(clean, 6) if clean is not None else None,
            "dirty_rub": round(dirty, 6) if dirty is not None else None,
            "current_coupon_yield_pct": round(current_coupon_yield, 6) if current_coupon_yield is not None else None,
            "amortizations_to_event": amort_rows,
            "put_offers": [{"date": d, "price": p} for d, p in puts],
            "call_offers": [{"date": d, "price": p} for d, p in calls],
            "put_price_at_event": round(put_price, 6) if put_price is not None else None,
            "maturity": maturity.isoformat() if maturity else None,
            "settle_date": settle.isoformat() if settle else None,
            "days": days_to_event,
            "coupon_cash_to_event": round(coupon_total, 6),
            "principal_cash_to_event": round(amort_total + redemption, 6),
            "total_future_cash": round(total_future, 6),
            "profit_rub": round(profit, 6) if profit is not None else None,
            "simple_yield_pct": round(simple_yield, 6) if simple_yield is not None else None,
            "xirr_pct": round(eff, 6) if eff is not None else None,
            "moex_yield_pct": moex_yield,
            "excluded_coupons": excluded,
            "projected_coupons": coupon_rows,
            "note": "; ".join(notes),
        }
        rows.append(row)

    out = {
        "generated_from_snapshot_msk": latest.get("generated_at_msk"),
        "generated_from_snapshot_utc": latest.get("generated_at_utc"),
        "key_rate_scenario_pct": key_rate,
        "count": len(rows),
        "rows": rows,
    }
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    cols = [
        "event_date","event_type","name","isin","rating_input","formula","scenario_coupon_rate_pct",
        "price_pct","price_source","current_face","initial_face","nkd","clean_rub","dirty_rub",
        "current_coupon_yield_pct","amortizations_to_event","put_offers","call_offers","maturity",
        "settle_date","days","simple_yield_pct","xirr_pct","moex_yield_pct","profit_rub","note"
    ]
    lines = ["\t".join(cols)]
    for r in rows:
        vals = []
        for c in cols:
            v = r.get(c)
            if isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
            vals.append("" if v is None else str(v).replace("\t", " ").replace("\n", " "))
        lines.append("\t".join(vals))
    OUT_TSV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"rows {len(rows)} -> {OUT_TSV}")


if __name__ == "__main__":
    main()
