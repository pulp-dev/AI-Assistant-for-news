# MOEX → GitHub → ChatGPT bridge

This folder keeps a read-only snapshot of selected Moscow Exchange bonds using the official MOEX ISS API.

## Files

- `watchlist.json` — SECID/ISIN codes to track.
- `fetch_moex.py` — downloads official MOEX ISS quote/static/cash-flow data.
- `data/latest.json` — latest generated snapshot.
- `.github/workflows/moex-bridge.yml` — updates the snapshot automatically.

## Update frequency

The workflow runs every 30 minutes on weekdays from 06:00 through 18:59 UTC, and can also be started manually from GitHub Actions.

## Add a bond

Add its MOEX SECID/ISIN to `watchlist.json`, for example:

```json
{
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

## Important

This is public/read-only market data. MOEX ISS public data may be delayed and is not an exchange trading terminal or order-entry connection.
