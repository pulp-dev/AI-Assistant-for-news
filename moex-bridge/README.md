# MOEX → GitHub → ChatGPT bridge

This folder keeps a read-only snapshot of selected Moscow Exchange bonds using the official MOEX ISS API.

## Files

- `watchlist.json` — SECID/ISIN codes to track and benchmark assumptions (`key_rate_pct`, `ruonia_pct`).
- `fetch_moex.py` — downloads official MOEX ISS quote/static/cash-flow data and calculates transparent bond metrics.
- `data/latest.json` — latest generated snapshot.
- `.github/workflows/moex-bridge.yml` — updates the snapshot automatically.

## Update frequency

The workflow runs every 30 minutes on weekdays from 06:00 through 18:59 UTC, and can also be started manually from GitHub Actions.

## Add a bond

Add its MOEX SECID/ISIN to `watchlist.json`, for example:

```json
{
  "assumptions": {
    "key_rate_pct": 14.00,
    "ruonia_pct": 13.57
  },
  "secids": [
    "RU000A10CC24"
  ]
}
```

A push that changes the watchlist automatically starts a fresh snapshot.

## What is stored

For each bond the snapshot includes, when available:

- BID / OFFER / LAST;
- MOEX YIELD;
- accrued interest (НКД);
- face value;
- current coupon rate and coupon value;
- next coupon date;
- maturity and offer fields;
- issue size / listing level;
- coupon schedule;
- amortization schedule;
- offer schedule;
- direct MOEX ISS source URLs.

## Calculated metrics

The `metrics` block is calculated from the current MOEX snapshot. For a purchase calculation the bridge uses `OFFER` first, then `LAST`, then the previous close as fallback.

It stores:

- `current_coupon_yield_pct` — current published annual coupon divided by the clean purchase price;
- `simple_yield_to_maturity_pct` — `(all future cash flows - dirty purchase price) / dirty purchase price × 365 / days to maturity`, with **no coupon reinvestment**;
- `profit_per_bond_rub` — total future cash flows minus dirty purchase price;
- `body_discount_premium_result_rub` — profit/loss from buying the current face value below/above par;
- `xirr_effective_pct` — effective annual IRR of the dated future cash flows;
- `moex_yield_pct` — MOEX's own YIELD field for cross-checking;
- `spread_to_key_rate_simple_pp` — simple yield to maturity minus the configured key-rate scenario.

For floating-rate bonds, already announced coupon amounts are taken directly from MOEX. Future unannounced coupons are projected using the benchmark assumptions in `watchlist.json` and are flagged as estimates. If the calculated XIRR materially differs from MOEX YIELD, a warning is added to the snapshot.

For amortizing bonds, the bridge stores each principal repayment separately. The simple annualized yield intentionally ignores the timing benefit of early principal returns, so `xirr_effective_pct` should be used for apples-to-apples comparison of amortizing issues.

## Important

This is public/read-only market data. MOEX ISS public data may be delayed and is not an exchange trading terminal or order-entry connection. Scenario calculations for unannounced floating coupons are estimates, not guaranteed future payments.
