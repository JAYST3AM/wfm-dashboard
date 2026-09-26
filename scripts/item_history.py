#!/usr/bin/env python3
"""Intraday per-item price series store -> data/item_history.json (stdlib only).

data/price_history.json keeps ONE point per item per day, which is fine for the
Movers list but draws a flat line for a sparkline and hides everything that
happens inside a session. This script keeps the fast series: each sweep appends
[unix_ts, ask, bid] for the tracked slugs - owned items UNION rank-lane items
UNION items with a recorded sale - and a resumable meta.cursor walks the whole
set in --limit-sized chunks, so a 15-minute cron can cover everything without
ever re-fetching the same block twice in a row.

Honesty rules (the dashboard draws these points, so they have to mean something):
  * one request per slug to /v2/orders/item/{id}/top, 0.35s apart; a 404 on the id
    route is retried once with the slug, which is the route that resolves items the
    v2 id index does not know (about one in eight live);
  * a failed fetch adds NO point - that slug's series stays exactly as it was;
  * an empty side of the book is stored as null, never as 0;
  * the first time a slug gets points they are seeded from the daily rows already
    in data/price_history.json (00:00 local time, ask=wts, bid=wtb) and src.ask
    reads 'history' until a live top-order point exists;
  * a rank-lane snapshot (data/price_lanes.json) is appended as one point at its
    real 'fetched' timestamp, but only when that is newer than the last point;
  * sales come from data/trade_log.json events with kind='sale'; trade rows that
    carry no 'slug' resolve through the WFM catalogue NAME - nothing is guessed;
  * at most CAP points per item: the newest survive.

Store (written atomically via tmp + os.replace, indent=2, trailing newline):
  schema, updated, updated_iso, count, fields=["ts","ask","bid"], items, meta
  items[slug] = {name, first, last, points: [[ts, ask, bid], ...],
                 sales: [[ts, price, qty], ...],
                 src: {ask: 'top_order'|'history', sales: 'trade_log'}}
  meta = {tracked, fetched, from_history, failures, rate_s, cursor, slugs}

Env: ITEM_HISTORY_PATH overrides the store path; nothing else is read from the
environment.

Usage:
  python scripts/item_history.py --once                 # one sweep (default mode)
  python scripts/item_history.py --limit 40             # short manual sweep
  python scripts/item_history.py --slugs blind_rage     # single item (debug)
  python scripts/item_history.py --dry-run              # print the plan, write nothing
  python scripts/item_history.py --selftest             # offline fixture check
"""
import argparse
import io
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
OUT = os.environ.get('ITEM_HISTORY_PATH') or os.path.join(DATA, 'item_history.json')
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'
API = 'https://api.warframe.market/v2/orders/item/%s/top'
SCHEMA = 1
FIELDS = ['ts', 'ask', 'bid']
CAP = 2000          # points kept per item (newest win)
SLEEP = 0.35        # seconds between API calls (meta.rate_s records it)
THROTTLE = 55 * 60  # a sweep does nothing while the store is younger than this


# ------------------------------------------------------------------ io helpers

def load(name, default=None):
    """Read data/<name>; a missing or unreadable file is a soft default, never fatal."""
    try:
        with open(os.path.join(DATA, name), encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def load_store():
    """(items, meta) from the existing store; empty when missing/unreadable."""
    if not os.path.exists(OUT):
        return {}, {}
    try:
        with open(OUT, encoding='utf-8') as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print('item_history: store unreadable (%s) - starting a fresh series' % e)
        return {}, {}
    if not isinstance(doc, dict) or not isinstance(doc.get('items'), dict):
        print('item_history: store shape unexpected - starting a fresh series')
        return {}, {}
    return doc['items'], (doc.get('meta') if isinstance(doc.get('meta'), dict) else {})


def atomic_write(path, doc):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as fh:
        json.dump(doc, fh, indent=2)
        fh.write('\n')
    os.replace(tmp, path)


def store_age():
    """Age of the store in seconds, or None when it does not exist yet."""
    try:
        return max(0.0, time.time() - os.path.getmtime(OUT))
    except OSError:
        return None


def rel(p):
    try:
        return os.path.relpath(p, ROOT).replace('\\', '/')
    except ValueError:
        return p.replace('\\', '/')


def _get(url, tries=4):
    """GET JSON with the tool's UA; retries throttles, returns {'error': ...} otherwise."""
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


# ------------------------------------------------------------------ series maths

def append_point(points, ts, ask, bid):
    """Insert/replace one [ts, ask, bid] point, keeping the list ascending by ts.

    Same ts -> the newest values win (two sweeps inside one second must not become
    two points). An older ts (a lane snapshot from before the last point) is placed
    where it belongs instead of being dropped. Returns 'appended' or 'replaced'.
    """
    pt = [int(ts), ask, bid]
    i = len(points)
    while i and points[i - 1][0] > pt[0]:
        i -= 1
    if i and points[i - 1][0] == pt[0]:
        points[i - 1] = pt
        return 'replaced'
    points.insert(i, pt)
    return 'appended'


def cap_points(points):
    """Keep at most CAP points, dropping the oldest."""
    if len(points) > CAP:
        del points[:-CAP]
    return len(points)


def orders_of(doc):
    """Order list from the v2 /top shape ({data:{sell,buy}}) or a legacy payload."""
    if not isinstance(doc, dict):
        return []
    data = doc.get('data')
    if isinstance(data, dict):
        return [o for side in ('sell', 'buy') for o in (data.get(side) or [])]
    if isinstance(data, list):
        return data
    payload = doc.get('payload')
    return ((payload or {}) if isinstance(payload, dict) else {}).get('orders') or []


def best_prices(doc):
    """(ask, bid): cheapest visible sell order, highest visible buy order.

    A side with no visible orders comes back None - the book really is empty there,
    and a 0 would read as a price.
    """
    ask = bid = None
    for o in orders_of(doc):
        if not isinstance(o, dict) or o.get('visible') is False:
            continue
        p = o.get('platinum')
        if isinstance(p, bool) or not isinstance(p, (int, float)):
            continue
        if o.get('type') == 'sell' and (ask is None or p < ask):
            ask = p
        elif o.get('type') == 'buy' and (bid is None or p > bid):
            bid = p
    return ask, bid


def history_points(slug):
    """Seed points for slug from data/price_history.json: [00:00 local, wts, wtb] rows.

    Rows are [dateISO, wts, wtb, median, vol48]; median/vol48 are not part of this
    series and are dropped, unparseable rows are skipped (never invent a timestamp).
    """
    rows = ((load('price_history.json', {}) or {}).get('items') or {}).get(slug) or []
    out = []
    for row in rows:
        try:
            ts = int(datetime.strptime(str(row[0]), '%Y-%m-%d').timestamp())
        except (TypeError, ValueError, IndexError):
            continue
        out.append([ts, row[1], row[2]])
    out.sort(key=lambda p: p[0])
    return out


def lane_point(entry):
    """(ts, ask, bid) from a data/price_lanes.json item, or None when unusable.

    Uses the max_rank lane (the copy the save proves is owned); a lane with no
    price on either side is not a reading, so it contributes nothing.
    """
    if not isinstance(entry, dict):
        return None
    fetched = entry.get('fetched')
    if isinstance(fetched, bool) or not isinstance(fetched, (int, float)):
        return None
    lane = (entry.get('lanes') or {}).get(str(entry.get('max_rank')))
    if not isinstance(lane, dict):
        return None
    ask, bid = lane.get('ask'), lane.get('bid')
    if ask is None and bid is None:
        return None
    return int(fetched), ask, bid


# ------------------------------------------------------------------ universe

def items_index():
    """(slug -> {'id','name'}, item NAME -> slug) from the WFM catalogue + owned.json."""
    by_slug, by_name = {}, {}
    for it in ((load('wfm_items_v2.json', {}) or {}).get('data') or []):
        slug = it.get('slug')
        if not slug:
            continue
        en = (it.get('i18n') or {}).get('en') or {}
        name = en.get('name')
        by_slug[slug] = {'id': it.get('id'), 'name': name or slug}
        if name:
            by_name.setdefault(name, slug)
    for o in (load('owned.json', []) or []):
        if isinstance(o, dict) and o.get('slug'):
            if o['slug'] not in by_slug:
                by_slug[o['slug']] = {'id': None, 'name': o.get('name') or o['slug']}
            if o.get('name'):
                by_name.setdefault(o['name'], o['slug'])
    return by_slug, by_name


def sale_rows(by_name):
    """[slug, ts, price, qty] for every kind='sale' trade-log event that resolves.

    A row keeps its own 'slug' when present; older rows only carry the item NAME,
    which resolves through the WFM catalogue. Unresolvable events are skipped.
    Price is the row's total (falls back to plat when total is absent).
    """
    tl = load('trade_log.json', []) or []
    events = (tl.get('events') if isinstance(tl, dict) else tl) or []
    out = []
    for e in events:
        if not isinstance(e, dict) or e.get('kind') != 'sale' or e.get('ts') is None:
            continue
        slug = e.get('slug') or by_name.get(e.get('name'))
        if not slug:
            continue
        price = e.get('total')
        if price is None:
            price = e.get('plat')
        out.append([slug, int(e['ts']), price, e.get('qty')])
    out.sort(key=lambda r: r[1])
    return out


def tracked_slugs(sales):
    """Sorted owned UNION lane-covered UNION sold slugs."""
    tracked = set()
    for o in (load('owned.json', []) or []):
        if isinstance(o, dict) and o.get('slug'):
            tracked.add(o['slug'])
    tracked.update((load('price_lanes.json', {}) or {}).get('items') or {})
    tracked.update(r[0] for r in sales)
    return sorted(tracked)


def new_entry(slug, by_slug):
    return {'name': (by_slug.get(slug) or {}).get('name') or slug,
            'first': None, 'last': None, 'points': [], 'sales': [],
            'src': {'ask': None, 'sales': 'trade_log'}}


def add_sales(ent, rows):
    """Append sale rows missing from ent['sales'] (idempotent: keyed on ts)."""
    have = {s[0] for s in ent['sales']}
    added = 0
    for _, ts, price, qty in rows:
        if ts in have:
            continue
        ent['sales'].append([ts, price, qty])
        have.add(ts)
        added += 1
    ent['sales'].sort(key=lambda s: s[0])
    return added


# ------------------------------------------------------------------ sweep

def fetch_prices(slug, iid=None):
    """(ask, bid) for a slug, or the error string when both routes fail.

    Tries the item-id route first, then the slug route: live, the v2 id index misses
    some items (app.item.notFound) that their slug still resolves, so a 404 by id is
    retried once by slug before it counts as a failure.
    """
    urls = ([API % iid] if iid and iid != slug else []) + [API % slug]
    err = 'failed'
    for url in urls:
        doc = _get(url)
        time.sleep(SLEEP)
        if not (isinstance(doc, dict) and doc.get('error')):
            return best_prices(doc)
        err = doc.get('error')
        if '404' not in str(err):
            break            # a network/throttle error will not fix itself by slug
    return err


def fmt_num(v):
    return '-' if v is None else v


def fmt_pt(pt):
    return '[%d, %s, %s]' % (pt[0], fmt_num(pt[1]), fmt_num(pt[2]))


def main(argv=None):
    t0 = time.time()
    ap = argparse.ArgumentParser(description='intraday per-item price series -> data/item_history.json')
    ap.add_argument('--once', action='store_true', help='one sweep of the tracked set (the default mode)')
    ap.add_argument('--limit', type=int, default=300, help='slugs fetched per run (default 300; 0 or less = all)')
    ap.add_argument('--slugs', default=None, help='comma-separated slugs to sweep instead of the tracked set (debug)')
    ap.add_argument('--force', action='store_true', help='ignore the 55-minute self-throttle')
    ap.add_argument('--dry-run', action='store_true', help='print the planned changes and write nothing')
    ap.add_argument('--selftest', action='store_true', help='offline fixture check (no network, no repo data)')
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.dry_run:
        args.force = True                       # a dry run must be able to show a plan

    age = store_age()
    if not args.force and age is not None and age < THROTTLE:
        print('item_history: skipped: fresh (%dm old)' % int(age // 60.0))
        return 0

    items, old_meta = load_store()
    by_slug, by_name = items_index()
    rows = sale_rows(by_name)
    lanes_items = (load('price_lanes.json', {}) or {}).get('items') or {}

    # --- sweep window -------------------------------------------------------
    try:
        cursor = int(old_meta.get('cursor') or 0)
    except (TypeError, ValueError):
        cursor = 0                                     # a hand-edited store never breaks a sweep
    if args.slugs:
        tracked = sorted({s.strip() for s in args.slugs.split(',') if s.strip()})
        window, new_cursor = tracked, cursor          # an explicit list never moves the cursor
    else:
        tracked = tracked_slugs(rows)
        if not tracked:
            print('item_history: no tracked slugs (owned.json / price_lanes.json / trade_log.json all empty)')
            return 1
        if cursor < 0 or cursor >= len(tracked):
            cursor = 0
        cap = len(tracked) if args.limit <= 0 else args.limit
        window = tracked[cursor:cursor + cap]
        new_cursor = (cursor + len(window)) % len(tracked)

    # --- sales are cheap (no network): keep every sold item in sync --------
    sales_by_slug = {}
    for slug, ts, price, qty in rows:
        sales_by_slug.setdefault(slug, []).append([slug, ts, price, qty])
    sales_added = 0
    for slug, srows in sales_by_slug.items():
        ent = items.get(slug)
        if ent is None:
            ent = items[slug] = new_entry(slug, by_slug)
        sales_added += add_sales(ent, srows)

    # --- one sweep of the window -------------------------------------------
    fetched = backfilled = failures = written = 0
    fails, plan = [], []
    for slug in window:
        notes = []
        created = slug not in items
        ent = items[slug] if not created else new_entry(slug, by_slug)

        if not ent['points']:                        # first sight of this slug
            seed = history_points(slug)
            if seed:
                ent['points'] = seed
                ent['src']['ask'] = 'history'
                backfilled += 1
                notes.append('backfill %d' % len(seed))

        lp = lane_point(lanes_items.get(slug))       # honest lane snapshot, if newer
        if lp and lp[0] > (ent['points'][-1][0] if ent['points'] else 0):
            if append_point(ent['points'], lp[0], lp[1], lp[2]) == 'appended':
                written += 1
            notes.append('lane %s' % fmt_pt(lp))

        res = fetch_prices(slug, (by_slug.get(slug) or {}).get('id'))
        if isinstance(res, tuple):
            ask, bid = res
            now = int(time.time())
            if append_point(ent['points'], now, ask, bid) == 'appended':
                written += 1
            ent['src']['ask'] = 'top_order'
            fetched += 1
            notes.append('live %s' % fmt_pt([now, ask, bid]))
        else:
            failures += 1                         # series untouched; no fake point
            fails.append('%s: %s' % (slug, res))
            notes.append('FAILED %s' % res)

        if not created or ent['points'] or ent['sales']:
            items[slug] = ent                      # nothing known about it yet: no stub entry
        plan.append((slug, notes))

    # --- refresh the derived fields of everything touched -------------------
    for slug in sorted(set(window) | set(sales_by_slug)):
        ent = items.get(slug)
        if not ent:
            continue
        cap_points(ent['points'])
        name = (by_slug.get(slug) or {}).get('name')
        if name:
            ent['name'] = name
        stamps = [p[0] for p in ent['points']] or [s[0] for s in ent['sales']]
        if stamps:
            ent['first'], ent['last'] = min(stamps), max(stamps)
        else:
            items.pop(slug, None)                  # nothing honest to describe

    # --- write --------------------------------------------------------------
    doc = {
        'schema': SCHEMA,
        'updated': int(time.time()),
        'updated_iso': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'count': len(items),
        'fields': list(FIELDS),
        'items': {k: items[k] for k in sorted(items)},
        'meta': {
            'tracked': len(tracked),
            'fetched': fetched,
            'from_history': backfilled,
            'failures': failures,
            'rate_s': SLEEP,
            'cursor': new_cursor,
            'slugs': list(window),
        },
    }
    if not args.dry_run:
        atomic_write(OUT, doc)

    # --- summary ------------------------------------------------------------
    # the summary line comes first so a cron wrapper can log exactly one useful line
    size = os.path.getsize(OUT) if os.path.exists(OUT) else 0
    if args.dry_run:
        changed = [(s, n) for s, n in plan if n]
        print('dry run - planned changes (%d of %d swept slugs), nothing written:' % (len(changed), len(plan)))
        for slug, notes in changed[:60]:
            print('   %-44s %s' % (slug, ', '.join(notes)))
        if len(changed) > 60:
            print('   ... %d more' % (len(changed) - 60))
    print('item_history : tracked %d | swept %d | fetched %d | backfilled %d | failures %d'
          ' | points written %d | sales added %d | cursor %d'
          % (len(tracked), len(window), fetched, backfilled, failures, written, sales_added, new_cursor))
    print('store        : %s  (%.1f KB)%s' % (rel(OUT), size / 1024.0,
                                              '  [dry run: untouched]' if args.dry_run else ''))
    print('runtime      : %.1fs' % (time.time() - t0))
    if fails and not args.dry_run:
        print('failures     : %s%s' % (' | '.join(fails[-10:]),
                                       ' (+%d more)' % (len(fails) - 10) if len(fails) > 10 else ''))
    return 0


# ------------------------------------------------------------------ selftest

def selftest():
    """Offline end-to-end check in a throwaway dir: no network, no repo data.

    Redirects DATA/OUT at a tmp fixture tree, stubs the HTTP layer, runs one real
    sweep and checks the store it produced. Prints 'selftest: N checks, M failed'.
    """
    checks = [0, 0]
    def check(name, ok):
        checks[0] += 1
        if not ok:
            checks[1] += 1
            print('  FAIL %s' % name)

    tmp = tempfile.mkdtemp(prefix='item_history_selftest_')
    keep = {k: globals()[k] for k in ('DATA', 'OUT', 'SLEEP', '_get')}
    try:
        data = os.path.join(tmp, 'data')
        os.makedirs(data)
        globals()['DATA'] = data
        globals()['OUT'] = os.path.join(data, 'item_history.json')
        globals()['SLEEP'] = 0.0                        # keep the selftest instant

        def fixture(name, obj):
            with open(os.path.join(data, name), 'w', encoding='utf-8', newline='') as fh:
                json.dump(obj, fh, indent=2)

        fixture('owned.json', [{'slug': 'alpha', 'name': 'Alpha'}, {'slug': 'beta', 'name': 'Beta'},
                               {'slug': 'delta', 'name': 'Delta'}, {'slug': 'gamma', 'name': 'Gamma'}])
        fixture('wfm_items_v2.json', {'data': [                 # gamma: deliberately no catalogue row
            {'id': 'id-alpha', 'slug': 'alpha', 'i18n': {'en': {'name': 'Alpha Prime'}}},
            {'id': 'id-beta', 'slug': 'beta', 'i18n': {'en': {'name': 'Beta Prime'}}},
            {'id': 'id-delta', 'slug': 'delta', 'i18n': {'en': {'name': 'Delta Prime'}}},
        ]})
        fixture('price_history.json', {'schema': 1, 'items': {'alpha': [['2026-01-01', 10, 4, 9, 3]]}})
        fixture('price_lanes.json', {'items': {'beta': {'max_rank': 0, 'fetched': 100,
                                                        'lanes': {'0': {'ask': 30, 'bid': 20}}}}})
        fixture('trade_log.json', [{'kind': 'sale', 'name': 'Alpha Prime', 'ts': 50, 'qty': 2,
                                    'plat': 7, 'total': 14},
                                   {'kind': 'purchase', 'name': 'Alpha Prime', 'ts': 60, 'qty': 1,
                                    'plat': 3, 'total': 3}])

        def fake_get(url, tries=4):
            if '/item/id-delta/top' in url:
                return {'error': 'http 404'}                    # id index misses it ...
            if '/item/delta/top' in url:                        # ... the slug route answers
                return {'data': {'sell': [{'type': 'sell', 'platinum': 44, 'visible': True}], 'buy': []}}
            if 'beta' in url:
                return {'data': {'sell': [], 'buy': []}}        # empty book -> nulls
            if 'gamma' in url:
                return {'data': {'sell': [{'type': 'sell', 'platinum': 9, 'visible': True}],
                                 'buy': [{'type': 'buy', 'platinum': 7, 'visible': True}]}}
            return {'data': {'sell': [{'type': 'sell', 'platinum': 12, 'visible': True}],
                             'buy': [{'type': 'buy', 'platinum': 5, 'visible': True}]}}
        globals()['_get'] = fake_get

        rc = main(['--once', '--force'])
        check('sweep exit 0', rc == 0)
        with open(OUT, encoding='utf-8') as fh:
            raw = fh.read()
        doc = json.loads(raw)
        check('trailing newline, no CRLF', raw.endswith('}\n') and '\r' not in raw)
        check('top-level keys', set(doc) == {'schema', 'updated', 'updated_iso', 'count', 'fields', 'items', 'meta'})
        check('schema/fields', doc['schema'] == 1 and doc['fields'] == ['ts', 'ask', 'bid'])
        check('count matches items', doc['count'] == len(doc['items']) == 4)
        check('updated_iso is UTC Z', doc['updated_iso'].endswith('Z') and 'T' in doc['updated_iso'])
        check('meta keys', set(doc['meta']) == {'tracked', 'fetched', 'from_history', 'failures',
                                                'rate_s', 'cursor', 'slugs'})
        check('meta counters', doc['meta']['tracked'] == 4 and doc['meta']['fetched'] == 4
              and doc['meta']['failures'] == 0 and doc['meta']['from_history'] == 1
              and doc['meta']['cursor'] == 0
              and sorted(doc['meta']['slugs']) == ['alpha', 'beta', 'delta', 'gamma'])

        a = doc['items'].get('alpha') or {}
        seed_ts = int(datetime.strptime('2026-01-01', '%Y-%m-%d').timestamp())
        check('alpha backfilled from the daily row', a.get('points', [None])[0] == [seed_ts, 10, 4])
        check('alpha live point + src top_order', len(a.get('points') or []) == 2
              and a['points'][-1][1:] == [12, 5] and a['src']['ask'] == 'top_order')
        check('alpha sales resolved by NAME', a.get('sales') == [[50, 14, 2]])
        check('alpha first/last follow the points', a.get('first') == seed_ts and a.get('last') == a['points'][-1][0])

        b = doc['items'].get('beta') or {}
        check('beta lane point at its real ts', b.get('points', [None])[0] == [100, 30, 20])
        check('beta empty book stays null in the JSON', b.get('points', [None, [0, 1, 1]])[-1][1:] == [None, None]
              and 'null' in raw)

        d = doc['items'].get('delta') or {}
        check('an item whose id 404s is retried by slug',
              d.get('points', [None])[-1][1:] == [44, None] and d.get('src', {}).get('ask') == 'top_order')
        g = doc['items'].get('gamma') or {}
        check('a slug missing from the catalogue still fetches',
              g.get('points', [None])[-1][1:] == [9, 7] and g.get('name') == 'Gamma')

        pts = [[100, 5, 2]]
        append_point(pts, 100, 7, 3)
        append_point(pts, 200, 8, 4)
        append_point(pts, 150, 6, 1)
        check('append_point dedupes and stays sorted', pts == [[100, 7, 3], [150, 6, 1], [200, 8, 4]])
        big = [[i, 1, 1] for i in range(CAP + 20)]
        cap_points(big)
        check('CAP trims the oldest', len(big) == CAP and big[0][0] == 20 and big[-1][0] == CAP + 19)

        out = io.StringIO()
        with redirect_stdout(out):
            rc2 = main(['--once'])                            # fresh store -> throttled
        check('self-throttle skips a fresh store', rc2 == 0 and 'skipped: fresh' in out.getvalue())
    finally:
        globals().update(keep)
        shutil.rmtree(tmp, ignore_errors=True)
    print('selftest: %d checks, %d failed' % (checks[0], checks[1]))
    return 0 if checks[1] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
