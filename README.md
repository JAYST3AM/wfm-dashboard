# WFM Trader

A local dashboard for **your Warframe inventory** and **warframe.market** data.
Runs on your own PC — no account needed to start, nothing is uploaded anywhere.

## What it shows

- **Dashboard** — your platinum over time, market KPIs, and your best sells right now (ranked by profit × how fast they sell)
- **Inventory** — every tradeable you own, searchable, with live prices and total value
- **History** — your own trade log. warframe.market has no public trade-history API, so the dashboard keeps the record itself as you trade
- 30 colour themes, dark by default

## The two things to connect

### 1. AlecaFrame → your inventory (required)

Your inventory is read directly from [AlecaFrame](https://alecaframe.com)'s local cache — no login, no server, nothing leaves your machine.

1. Install AlecaFrame (Windows/Overwolf) and open Warframe once so it syncs.
2. Run `python scripts/setup.py` — it does the rest (read cache → build inventory → fetch market data).

### 2. Your warframe.market account → orders & trading (optional)

Only needed for anything that touches your warframe.market orders. The base dashboard works without it.

1. Copy `secrets.example.json` to `secrets.json` and fill in your login.
2. Run `python scripts/wfm_check.py` — it signs in once and prints your account, so you know it works.

## Quick start

```bash
pip install cryptography     # the only dependency (reads your local AlecaFrame cache)
python scripts/setup.py      # first run: ~20-30 min, fetches market data for every item you own
start.bat                    # or: python server.py
```

Open **http://127.0.0.1:8787**

## Keeping it fresh

- Click **Refresh** in the dashboard header after you've played — re-syncs inventory and re-reads prices.
- Optional: schedule `scripts/snapshot_plat.py` every 15 minutes (Task Scheduler) so your platinum chart builds history continuously.

## Notes

- Windows-only for the inventory side (AlecaFrame is Windows). The server itself is plain Python.
- `scripts/refresh.py` reads AlecaFrame's save with the key its own app uses; keep AlecaFrame installed for updates.
- Everything is stdlib Python + vanilla JS — no frameworks, no build step.

MIT licensed.
