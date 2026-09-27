# WFM Trader chat relay

One Cloudflare Worker + one SQLite-backed Durable Object: the room where different people's
dashboards meet. The dashboard itself is a local server on each player's PC, so it needs somewhere
shared for the chat dock on HOME to be more than a personal log.

**Free tier, no card, no login for the players:** Workers Free gives 100,000 requests/day and
SQLite Durable Objects are part of the free plan (5M rows read + 100k rows written a day, 5 GB) —
a mates' room polling every 10 seconds sits far inside that.

## Deploy your own

```bash
cd chat-relay
npx wrangler login                       # or set CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID
npx wrangler deploy                      # prints https://wfm-chat.<your-subdomain>.workers.dev
```

Then in the dashboard: **Settings → Updates → Shared chat room** (or
`python scripts/config.py --set chat_relay_url=https://wfm-chat.<you>.workers.dev`).
Everyone who sets the same URL shares the same room. Add `/r/<name>` to the URL for a second,
separate room (`.../r/lepub` and `.../tav` are different rooms).

## What it does and does not do

- `GET /messages?since=<id>` → `{rows:[{id, ts, who:{name, mr, platform, clan}, text}]}` (newest 500
  kept, 200 per pull).
- `POST /messages {text, who}` → `{ok:true, row:{...}}`; empty text → 400, posting faster than
  1.5 s from one IP → 429.
- CORS is open, because every dashboard runs on a different `http://127.0.0.1:<port>` origin.
- **No accounts and no verification.** A message carries the profile stamp the sender's dashboard
  put on it, and each dashboard shows exactly what it is about to send. Anyone with the URL can
  read and post: it is a mates' room, not a secret one. Don't post anything private in it.
- The dashboard keeps its own copy of the conversation locally too (`data/chat.json`), so the dock
  still works with no relay configured at all.
