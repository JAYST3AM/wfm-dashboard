#!/usr/bin/env python3
"""Rank-lane orderbook snapshot -> data/price_lanes.json.

Why: an item-level "sell 15p / buy 55p" is meaningless for mods - the 15p was a
rank-0 listing and the 55p a rank-10 bid. Every price shown to a user must be read
from the lane of the rank they actually hold.

One pass over owned.json: for each owned item with ranked copies (WFM maxRank > 0)
fetch the FULL orderbook (`/v2/orders/item/{id}`, visible orders only) and reduce it
per rank:

  lanes["<rank>"] = {
    "ask":     cheapest sell order  (what you pay to buy now;
                                     list YOUR copy just UNDER this - undercut by 1p)
    "n_ask":   how many sell orders sit at that rank
    "bid":     highest buy order    (what you get selling now;
                                     bid just OVER this - outbid by 1p)
    "bid_low": lowest buy order     (the floor of the bidding range)
    "n_bid":   how many buy orders sit at that rank
  }

Rows with rank null count as rank 0. Unranked tradeables (prime parts, relics,
arcanes) carry no lanes - their price is item-level and stays in prices.json;
relic refinements are handled by the trader's own lane logic.

Resumable: items already in the file are skipped unless --force. Rate: ~0.35s per
item (same discipline as fetch_prices.py). UA identifies the tool, per ToS.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
OUT = os.path.join(DATA, 'price_lanes.json')
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'
SLEEP = 0.35


def load(name, default=None):
    try:
        with open(os.path.join(DATA, name), encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def lane_summary(orders):
    """Reduce a WFM orderbook (list of order dicts) to per-rank lanes.

    Visible sell/buy orders only; a missing rank counts as 0. Returns
    {rank: {'ask', 'n_ask', 'bid', 'bid_low', 'n_bid'}} - keys with no data
    on a side are omitted for that side.
    """
    lanes = {}
    for o in orders or []:
        if not isinstance(o, dict) or not o.get('visible'):
            continue
        side = o.get('type')
        if side not in ('sell', 'buy'):
            continue
        price = o.get('platinum')
        if not isinstance(price, (int, float)):
            continue
        rank = o.get('rank')
        rank = 0 if rank is None else int(rank)
        cell = lanes.setdefault(rank, {'n_ask': 0, 'n_bid': 0})
        if side == 'sell':
            cell['n_ask'] += 1
            if 'ask' not in cell or price < cell['ask']:
                cell['ask'] = price
        else:
            cell['n_bid'] += 1
            if 'bid' not in cell or price > cell['bid']:
                cell['bid'] = price
            if 'bid_low' not in cell or price < cell['bid_low']:
                cell['bid_low'] = price
    return lanes


def _get(url, tries=4):
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503):
                time.sleep(4 + 3 * a)
                continue
            return {'error': 'http %d' % e.code}
        except Exception:
            time.sleep(2 + 2 * a)
    return {'error': 'failed'}


def ranked_slugs():
    """Owned slugs whose WFM item has ranks (mods), with their max rank."""
    owned = load('owned.json', []) or []
    wfm = (load('wfm_items_v2.json', {}) or {}).get('data') or []
    byslug = {it.get('slug'): it for it in wfm if it.get('slug')}
    out, seen = [], set()
    for o in owned:
        slug = o.get('slug')
        if not slug or slug in seen:
            continue
        it = byslug.get(slug)
        if not it or not it.get('maxRank'):
            continue
        seen.add(slug)
        out.append((slug, int(it['maxRank'])))
    return out, byslug


def atomic_write(path, doc):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, indent=1)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description='rank-lane orderbook snapshot for owned mods')
    ap.add_argument('--force', action='store_true', help='re-fetch items already in the file')
    ap.add_argument('--slug', default=None, help='fetch one slug only (debug)')
    ap.add_argument('--limit', type=int, default=0, help='stop after N fetches (debug)')
    args = ap.parse_args(argv)

    doc = load('price_lanes.json', None) or {'version': 1, 'items': {}}
    items = doc.setdefault('items', {})
    pairs, byslug = ranked_slugs()
    if args.slug:
        pairs = [p for p in pairs if p[0] == args.slug] or \
                [(args.slug, int((byslug.get(args.slug) or {}).get('maxRank') or 0))]
    todo = [(s, mr) for s, mr in pairs if args.force or s not in items]
    if args.limit:
        todo = todo[:args.limit]
    print('lanes: %d ranked owned slugs | done %d | to fetch %d'
          % (len(pairs), len(pairs) - len(todo), len(todo)), flush=True)

    done, t0, fails = 0, time.time(), []
    for slug, max_rank in todo:
        it = byslug.get(slug) or {}
        if not it.get('id'):
            continue
        d = _get('https://api.warframe.market/v2/orders/item/%s' % it['id'])
        if isinstance(d, dict) and d.get('error'):
            if '404' in str(d['error']):
                # the item has no order book (untradeable / not listed) - remember that
                # instead of retrying a permanent 404 on every run
                items[slug] = {'max_rank': max_rank, 'fetched': int(time.time()),
                               'lanes': {}, 'no_book': True}
                done += 1
            else:
                fails.append('%s: %s' % (slug, d['error']))
            continue
        lanes = lane_summary(d.get('data') if isinstance(d, dict) else d)
        items[slug] = {'max_rank': max_rank, 'fetched': int(time.time()),
                       'lanes': {str(k): v for k, v in sorted(lanes.items())}}
        done += 1
        if done % 25 == 0:
            doc['generated'] = int(time.time())
            atomic_write(OUT, doc)
            el = time.time() - t0
            print('%d/%d done, elapsed %.0fs, eta %.0fs' % (done, len(todo), el, el / done * (len(todo) - done)), flush=True)
        time.sleep(SLEEP)

    doc['version'] = 1
    doc['generated'] = int(time.time())
    doc['ua'] = UA
    doc['count'] = len(items)
    if fails:
        doc['last_failures'] = fails[-10:]
    atomic_write(OUT, doc)
    print('lanes done: %d items in %s%s' % (len(items), OUT.replace('\\', '/'),
          (' | %d failures' % len(fails)) if fails else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
