#!/usr/bin/env python3
"""Live orderbook for one item (warframe.market v2) - the Trade page's Orders tab.

Jay (2026-09-28): *"is there a list on trade that shows real buy orders and sell orders?
with usernames"* + *"the app needs to understand values of different ranks for a mod"*.

The Trade page used to carry only the item-level best price, which on a mod mixes a rank-0
listing with a rank-10 bid. This module is the access layer for the real book: who is
selling or buying, at which rank, for how much, right now.

  * fetch(slug) -> (orders, fetched_ts): answers from data/orders_cache/<slug>.json while it
    is younger than 45s (no network call at all), else GETs /v2/orders/item/<slug> with the
    repo UA, at most 2 retries and 0.35s spacing between API calls, then rewrites the raw
    cache atomically. A failed live fetch falls back to the stale cache when there is one.
  * live(orders): the one visibility rule - visible is true and quantity > 0.
  * book(orders, rank=None) -> {'sell': [...], 'buy': [...]}: rows shaped for the tab
    ({platinum, quantity, rank, user, reputation, status, updated_ts}, user = ingameName);
    sell ascends (cheapest first), buy descends; equal prices break toward players who can
    actually be traded with (ingame > online > offline); at most 40 rows a side.
  * values(orders): the per-rank ladder (fetch_lanes.lane_summary) - the exact reduction
    scripts/fetch_lanes.py writes to data/price_lanes.json, so a rank's worth shown next to
    an order agrees with the ladder shown everywhere else.

CLI:
  python scripts/orders.py --selftest      fixture-driven checks, no network
  python scripts/orders.py <slug>          human summary of the current book
  python scripts/orders.py <slug> --json   the payload the server serves
"""
import argparse
import calendar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'
API = 'https://api.warframe.market/v2/orders/item/%s'
TTL = 45            # seconds a cache file answers without a network call
SLEEP = 0.35        # spacing between API calls (same discipline as fetch_lanes.py)
BACKOFF = 0.6       # retry backoff seconds x attempt
TRIES = 3           # one try + at most 2 retries
TIMEOUT = 6.0       # wall-clock budget for one fetch; the server route answers inside it
MAX_ROWS = 40       # rows a side the Orders tab shows
SLUG_RE = re.compile(r'^[a-z0-9_]+$')
STATUS_RANK = {'ingame': 0, 'online': 1, 'offline': 2}

try:
    from fetch_lanes import lane_summary             # same folder, same reduction
except Exception:                                    # loaded by path (tests): scripts/ not importable
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from fetch_lanes import lane_summary

_last_call = [0.0]


# ------------------------------------------------------------------ the raw cache

def valid_slug(slug):
    """wfm slugs are lowercase letters/digits/underscores - anything else cannot be fetched."""
    return bool(SLUG_RE.match(str(slug or '')))


def cache_dir():
    """data/orders_cache (computed per call so a caller can point DATA elsewhere)."""
    return os.path.join(DATA, 'orders_cache')


def cache_path(slug):
    return os.path.join(cache_dir(), str(slug) + '.json')


def age_s(fetched_ts, now=None):
    """Whole seconds since a fetch stamp; None when there is no stamp."""
    if not fetched_ts:
        return None
    try:
        return max(0, int((time.time() if now is None else now) - float(fetched_ts)))
    except (TypeError, ValueError):
        return None


def read_cache(slug):
    """(orders, fetched_ts) from data/orders_cache/<slug>.json; (None, None) when unusable."""
    try:
        with open(cache_path(slug), encoding='utf-8') as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None, None
    if not isinstance(doc, dict):
        return None, None
    orders, ts = doc.get('orders'), doc.get('fetched')
    if not isinstance(orders, list) or not isinstance(ts, (int, float)):
        return None, None
    return orders, int(ts)


def write_cache(slug, orders, fetched_ts):
    """Atomic raw cache write; a cache failure never fails the fetch. -> bool."""
    path = cache_path(slug)
    tmp = '%s.tmp-%d' % (path, os.getpid())
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump({'slug': str(slug), 'fetched': int(fetched_ts), 'ua': UA,
                       'count': len(orders), 'orders': orders}, fh)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


# ------------------------------------------------------------------ network

def _pace():
    """Keep >= SLEEP between API calls (the rate discipline every fetcher here follows)."""
    gap = SLEEP - (time.time() - _last_call[0])
    if gap > 0:
        time.sleep(gap)
    _last_call[0] = time.time()


def _get(url, budget=TIMEOUT):
    """GET one JSON document: <=2 retries, inside a wall-clock budget. -> (data|None, err|str)."""
    deadline = time.time() + max(0.0, float(budget))
    err = 'failed'
    for attempt in range(TRIES):
        _pace()
        left = deadline - time.time()
        if left <= 0:
            break
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=min(left, TIMEOUT)) as r:
                return json.loads(r.read().decode()), None
        except urllib.error.HTTPError as e:
            err = 'http %d' % e.code
            if e.code not in (429, 502, 503, 504):      # a 404 is permanent, do not retry it
                return None, err
        except Exception as e:
            err = str(e)[:80] or type(e).__name__
        rest = deadline - time.time()
        if rest > 0:
            time.sleep(min(BACKOFF * (attempt + 1), rest))
    return None, err


def fetch_book(slug, budget=TIMEOUT):
    """One network read of /v2/orders/item/<slug>. -> (orders|None, err|None)."""
    data, err = _get(API % slug, budget=budget)
    if data is None:
        return None, err
    orders = data.get('data') if isinstance(data, dict) else data
    if not isinstance(orders, list):
        return None, 'unexpected payload'
    return orders, None


def snapshot(slug, budget=TIMEOUT):
    """Serve one orderbook: fresh cache, else network, else the stale cache.

    -> {'orders': list, 'fetched_ts': int|None, 'age_s': int|None,
        'source': 'live'|'cache'|None, 'error': str|None}
    A fresh cache (< TTL seconds) answers without touching the network; when the live
    fetch fails the stale cache is served with the error attached, and only a first-ever
    failure leaves orders empty.
    """
    slug = str(slug or '').strip().lower()
    blank = {'orders': [], 'fetched_ts': None, 'age_s': None, 'source': None,
             'error': 'bad slug'}
    if not valid_slug(slug):
        return blank
    now = time.time()
    cached, ts = read_cache(slug)
    if cached is not None and ts is not None and (now - ts) < TTL:
        return {'orders': cached, 'fetched_ts': ts, 'age_s': age_s(ts, now),
                'source': 'cache', 'error': None}
    orders, err = fetch_book(slug, budget=budget)
    if orders is not None:
        fetched_ts = int(time.time())
        write_cache(slug, orders, fetched_ts)
        return {'orders': orders, 'fetched_ts': fetched_ts, 'age_s': 0,
                'source': 'live', 'error': None}
    if cached is not None and ts is not None:
        return {'orders': cached, 'fetched_ts': ts, 'age_s': age_s(ts, now), 'source': 'cache',
                'error': 'live fetch failed (%s); showing cache' % (err or 'failed')}
    return {'orders': [], 'fetched_ts': None, 'age_s': None, 'source': None,
            'error': str(err or 'fetch failed')}


def fetch(slug, budget=TIMEOUT):
    """The contract entry point: (orders, fetched_ts); ([], None) when nothing could be read."""
    snap = snapshot(slug, budget=budget)
    return snap['orders'], snap['fetched_ts']


# ------------------------------------------------------------------ reduction

def live(orders):
    """The shared visibility rule: only orders that can actually be traded with."""
    out = []
    for o in orders or []:
        if not isinstance(o, dict) or not o.get('visible'):
            continue
        try:
            qty = int(o.get('quantity') or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty < 1:
            continue
        out.append(o)
    return out


def rank_of(order):
    """A missing rank is rank 0 - the same rule fetch_lanes.lane_summary uses."""
    r = (order or {}).get('rank')
    if r is None:
        return 0
    try:
        return int(r)
    except (TypeError, ValueError):
        return 0


def _ts(value):
    """ISO stamp (wfm sends ...Z) -> epoch int; None when it cannot be read."""
    s = str(value or '').strip()
    if not s:
        return None
    if s.endswith('Z'):
        s = s[:-1]
    elif s.endswith('+00:00'):
        s = s[:-6]
    for fmt in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S'):
        try:
            return int(calendar.timegm(time.strptime(s, fmt)))
        except ValueError:
            continue
    return None


def _row(order):
    user = order.get('user') if isinstance(order.get('user'), dict) else {}
    rank = order.get('rank')
    return {
        'platinum': int(order['platinum']),
        'quantity': int(order.get('quantity') or 0),
        'rank': int(rank) if isinstance(rank, (int, float)) and not isinstance(rank, bool) else None,
        'user': str(user.get('ingameName') or ''),
        'reputation': user.get('reputation') if isinstance(user.get('reputation'), (int, float)) else None,
        'status': str(user.get('status') or 'offline'),
        'updated_ts': _ts(order.get('updatedAt') or order.get('createdAt')),
    }


def counts(orders, rank=None):
    """Live orders per side, for one rank or the whole book. -> {'sell', 'buy'}."""
    out = {'sell': 0, 'buy': 0}
    for o in live(orders):
        if o.get('type') not in out:
            continue
        if rank is not None and rank_of(o) != rank:
            continue
        out[o['type']] += 1
    return out


def ranks(orders):
    """Every rank that has a live order, ascending (drives the tab's rank selector)."""
    return sorted({rank_of(o) for o in live(orders) if o.get('type') in ('sell', 'buy')})


def book(orders, rank=None, limit=MAX_ROWS):
    """The orderbook as the Orders tab shows it. -> {'sell': [...], 'buy': [...]}.

    Rows are {platinum, quantity, rank, user, reputation, status, updated_ts} (user is the
    ingameName). sell ascends, buy descends; equal prices break ingame > online > offline;
    at most `limit` rows a side, capped at MAX_ROWS. `rank` filters one lane, a missing
    rank counting as 0 (the lane rule of fetch_lanes.lane_summary).
    """
    try:
        limit = max(1, min(MAX_ROWS, int(limit)))
    except (TypeError, ValueError):
        limit = MAX_ROWS
    sides = {'sell': [], 'buy': []}
    for o in live(orders):
        side = o.get('type')
        if side not in sides:
            continue
        price = o.get('platinum')
        if isinstance(price, bool) or not isinstance(price, (int, float)) or price < 1:
            continue
        if rank is not None and rank_of(o) != rank:
            continue
        sides[side].append(_row(o))

    def key(row, descending):
        # price first (ascending for sell, descending for buy), then who can actually be
        # traded with now, then the freshest listing, then the name (a stable last word)
        return ((-row['platinum']) if descending else row['platinum'],
                STATUS_RANK.get(row['status'], 3), -(row['updated_ts'] or 0), row['user'])

    sides['sell'].sort(key=lambda r: key(r, False))
    sides['buy'].sort(key=lambda r: key(r, True))
    return {'sell': sides['sell'][:limit], 'buy': sides['buy'][:limit]}


def values(orders):
    """The per-rank ladder via fetch_lanes.lane_summary, rank keys as strings (JSON-ready).

    Deliberately the same reduction that builds data/price_lanes.json: hidden rows are
    dropped and a quantity-0 row is kept, exactly as fetch_lanes counts them, so the ladder
    served here can never disagree with the ladder shown elsewhere.
    """
    return {str(k): v for k, v in sorted(lane_summary(orders).items())}


# ------------------------------------------------------------------ CLI

def ago(ts, now=None):
    """'3d' / '5h' / '12m' / 'now' for a stamp; 'never' when there is none."""
    if not ts:
        return 'never'
    d = max(0, int((time.time() if now is None else now) - ts))
    if d >= 86400:
        return '%dd' % (d // 86400)
    if d >= 3600:
        return '%dh' % (d // 3600)
    if d >= 60:
        return '%dm' % (d // 60)
    return 'now'


def summary_lines(slug, rank=None, limit=8, budget=TIMEOUT):
    """The human block `python scripts/orders.py <slug>` prints."""
    snap = snapshot(slug, budget=budget)
    orders = snap['orders']
    head = 'orders: %s | %s' % (slug, snap['source'] or 'unavailable')
    if snap['fetched_ts']:
        head += ' | %ds old' % (age_s(snap['fetched_ts']) or 0)
    if snap['error']:
        head += ' | ' + snap['error']
    lines = [head]
    if not orders:
        return lines
    c = counts(orders)
    lines.append('book: %d live orders | sell %d / buy %d | ranks %s'
                 % (len(live(orders)), c['sell'], c['buy'],
                    ','.join(str(r) for r in ranks(orders)) or '-'))
    vals = values(orders)
    if vals:
        lines.append('%5s %6s %5s %6s %5s %8s' % ('rank', 'n_ask', 'ask', 'n_bid', 'bid', 'low'))
        for rk in sorted(vals, key=int):
            v = vals[rk]
            lines.append('%5s %6d %5s %6d %5s %8s' % (
                rk, v.get('n_ask', 0), v.get('ask', '-'), v.get('n_bid', 0),
                v.get('bid', '-'), v.get('bid_low', '-')))
    rows = book(orders, rank=rank, limit=limit)
    for side in ('sell', 'buy'):
        lines.append('%s (top %d):' % (side, len(rows[side])))
        for r in rows[side]:
            lines.append('  %4dp x%-3d rank %-4s %-18s %-8s rep %-4s updated %s' % (
                r['platinum'], r['quantity'], '-' if r['rank'] is None else r['rank'],
                r['user'] or '?', r['status'],
                '-' if r['reputation'] is None else r['reputation'], ago(r['updated_ts'])))
    return lines


def payload(slug, rank=None, limit=MAX_ROWS, budget=TIMEOUT):
    """The JSON shape GET /api/orders serves (server.py composes the same fields)."""
    snap = snapshot(slug, budget=budget)
    return {'ok': True, 'item': slug, 'age_s': snap['age_s'], 'source': snap['source'],
            'counts': counts(snap['orders'], rank=rank), 'ranks': ranks(snap['orders']),
            'sell': book(snap['orders'], rank=rank, limit=limit)['sell'],
            'buy': book(snap['orders'], rank=rank, limit=limit)['buy'],
            'values': values(snap['orders']),
            **({'error': snap['error']} if snap['error'] else {})}


# ------------------------------------------------------------------ selftest

_SELFTEST_ORDERS = [
    {'type': 'sell', 'platinum': 15, 'quantity': 1, 'rank': 0, 'visible': True,
     'updatedAt': '2026-09-28T02:00:00Z',
     'user': {'ingameName': 'OfflineAnn', 'reputation': 3, 'status': 'offline'}},
    {'type': 'sell', 'platinum': 15, 'quantity': 2, 'rank': 0, 'visible': True,
     'updatedAt': '2026-09-28T02:00:00Z',
     'user': {'ingameName': 'IngameBob', 'reputation': 9, 'status': 'ingame'}},
    {'type': 'sell', 'platinum': 12, 'quantity': 1, 'rank': 0, 'visible': True,
     'updatedAt': '2026-09-28T02:00:00Z',
     'user': {'ingameName': 'OnlineCat', 'reputation': 1, 'status': 'online'}},
    {'type': 'sell', 'platinum': 1, 'quantity': 1, 'rank': 0, 'visible': False,
     'updatedAt': '2026-09-28T02:00:00Z',
     'user': {'ingameName': 'HiddenDan', 'reputation': 0, 'status': 'ingame'}},
    {'type': 'sell', 'platinum': 1, 'quantity': 0, 'rank': 0, 'visible': True,
     'updatedAt': '2026-09-28T02:00:00Z',
     'user': {'ingameName': 'EmptyEve', 'reputation': 0, 'status': 'ingame'}},
    {'type': 'buy', 'platinum': 8, 'quantity': 1, 'rank': 0, 'visible': True,
     'updatedAt': '2026-09-28T02:00:00Z',
     'user': {'ingameName': 'OffBuyer', 'reputation': 4, 'status': 'offline'}},
    {'type': 'buy', 'platinum': 8, 'quantity': 3, 'rank': 0, 'visible': True,
     'updatedAt': '2026-09-28T02:00:00Z',
     'user': {'ingameName': 'IngBuyer', 'reputation': 7, 'status': 'ingame'}},
    {'type': 'buy', 'platinum': 6, 'quantity': 1, 'rank': 0, 'visible': True,
     'updatedAt': '2026-09-28T02:00:00Z',
     'user': {'ingameName': 'OnlBuyer', 'reputation': 2, 'status': 'online'}},
    {'type': 'sell', 'platinum': 40, 'quantity': 1, 'rank': 10, 'visible': True,
     'updatedAt': '2026-09-28T02:00:00Z',
     'user': {'ingameName': 'R10Seller', 'reputation': 5, 'status': 'ingame'}},
    {'type': 'buy', 'platinum': 30, 'quantity': 1, 'rank': 10, 'visible': True,
     'updatedAt': '2026-09-28T02:00:00Z',
     'user': {'ingameName': 'R10Buyer', 'reputation': 6, 'status': 'ingame'}},
]


def selftest():
    """Fixture-driven checks of the reduction + the 45s cache. No network, no repo data."""
    import tempfile
    checks = []

    def check(name, ok):
        checks.append((name, bool(ok)))

    orders = _SELFTEST_ORDERS
    lv = live(orders)
    names = [str(((o.get('user') or {}).get('ingameName'))) for o in lv]
    check('live() drops visible:false', 'HiddenDan' not in names)
    check('live() drops quantity:0', 'EmptyEve' not in names)
    check('live() keeps the rest', len(lv) == 8)

    b = book(orders)
    check('sell ascends by platinum', [r['platinum'] for r in b['sell']] == [12, 15, 15, 40])
    check('buy descends by platinum', [r['platinum'] for r in b['buy']] == [30, 8, 8, 6])
    check('status breaks a tie (ingame > online > offline)',
          [r['user'] for r in b['sell'] if r['platinum'] == 15] == ['IngameBob', 'OfflineAnn']
          and [r['user'] for r in b['buy'] if r['platinum'] == 8] == ['IngBuyer', 'OffBuyer'])
    check('row shape', set(b['sell'][0]) == {'platinum', 'quantity', 'rank', 'user',
                                             'reputation', 'status', 'updated_ts'})
    check('rank filter', [r['platinum'] for r in book(orders, rank=10)['sell']] == [40]
          and counts(orders, rank=10) == {'sell': 1, 'buy': 1})
    check('ranks() lists the lanes', ranks(orders) == [0, 10])
    many = [dict(_SELFTEST_ORDERS[0], platinum=100 + i) for i in range(45)]
    check('at most %d rows a side' % MAX_ROWS, len(book(many)['sell']) == MAX_ROWS
          and book(many)['buy'] == [])
    check('values() == lane_summary()',
          values(orders) == {str(k): v for k, v in sorted(lane_summary(orders).items())})

    saved_data, saved_fetch = DATA, fetch_book
    with tempfile.TemporaryDirectory() as tmp:
        globals()['DATA'] = tmp
        calls = []

        def stub(slug, budget=TIMEOUT):
            calls.append(slug)
            return orders, None

        globals()['fetch_book'] = stub
        try:
            snap = snapshot('fixture_item')
            check('first read is live', snap['source'] == 'live' and calls == ['fixture_item'])
            check('raw cache file written', os.path.isfile(cache_path('fixture_item'))
                  and read_cache('fixture_item')[0] == orders)
            snap2 = snapshot('fixture_item')
            check('fresh cache answers with no network call',
                  snap2['source'] == 'cache' and len(calls) == 1
                  and (snap2['age_s'] or 0) < TTL)
            check('fetch() exposes the stamp', fetch('fixture_item')[1] == snap2['fetched_ts'])
            _expire('fixture_item')
            snap3 = snapshot('fixture_item')
            check('expired cache refetches', snap3['source'] == 'live' and len(calls) == 2)
            globals()['fetch_book'] = lambda slug, budget=TIMEOUT: (None, 'timeout')
            _expire('fixture_item')
            snap4 = snapshot('fixture_item')
            check('stale cache survives a failed fetch',
                  snap4['source'] == 'cache' and 'timeout' in (snap4['error'] or ''))
            os.remove(cache_path('fixture_item'))
            snap5 = snapshot('fixture_item')
            check('nothing cached + failed fetch -> empty + error',
                  snap5['orders'] == [] and snap5['fetched_ts'] is None and snap5['error'])
            check('bad slug is refused', snapshot('Not A Slug')['error'] == 'bad slug'
                  and snapshot('../etc')['error'] == 'bad slug')
        finally:
            globals()['fetch_book'] = saved_fetch
            globals()['DATA'] = saved_data

    for name, ok in checks:
        print('  %-46s %s' % (name, 'ok' if ok else 'FAIL'))
    bad = [n for n, ok in checks if not ok]
    print('selftest: %s (%d checks)' % ('FAIL: ' + ', '.join(bad) if bad else 'PASS', len(checks)))
    return 1 if bad else 0


def _expire(slug):
    """Age a cache file past the TTL (selftest only)."""
    path = cache_path(slug)
    with open(path, encoding='utf-8') as fh:
        doc = json.load(fh)
    doc['fetched'] = int(time.time()) - (TTL + 5)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh)


def main(argv=None):
    ap = argparse.ArgumentParser(description='live wfm orderbook for one item (Trade > Orders)')
    ap.add_argument('slug', nargs='?', help='item slug, e.g. primed_continuity')
    ap.add_argument('--selftest', action='store_true', help='fixture-driven checks, no network')
    ap.add_argument('--rank', default='all', help='one rank, or all (default)')
    ap.add_argument('--limit', type=int, default=8, help='rows a side to print (max %d)' % MAX_ROWS)
    ap.add_argument('--budget', type=float, default=TIMEOUT, help='network budget in seconds')
    ap.add_argument('--json', action='store_true', help='print the payload the server serves')
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.slug:
        ap.print_usage(sys.stderr)
        print('orders: give a slug, or --selftest', file=sys.stderr)
        return 2
    slug = args.slug.strip().lower()
    if not valid_slug(slug):
        print('orders: %r is not a wfm slug' % args.slug, file=sys.stderr)
        return 2
    rank = None
    if str(args.rank).strip().lower() not in ('', 'all'):
        try:
            rank = int(args.rank)
        except ValueError:
            print('orders: --rank must be a number or all', file=sys.stderr)
            return 2
    if args.json:
        print(json.dumps(payload(slug, rank=rank, limit=min(MAX_ROWS, max(1, args.limit)),
                                 budget=args.budget), indent=1))
        return 0
    lines = summary_lines(slug, rank=rank, limit=min(MAX_ROWS, max(1, args.limit)),
                          budget=args.budget)
    print('\n'.join(lines))
    return 1 if lines and 'unavailable' in lines[0] else 0


if __name__ == '__main__':
    sys.exit(main())
