#!/usr/bin/env python3
"""Watchlist + alert feed (#12): "tell me when this item is cheap / expensive".

Inputs : data/watchlist_config.json  (user-editable rows; created once, NEVER overwritten)
         data/prices.json            (local snapshot: sell floor per slug -> wts)
         data/stats.json             (med48 / median / vol48 per slug)
         data/wfm_items_v2.json      (catalog: names)
         data/flip_digest.json       (suggested rows: buy_at / sell_at)
         data/deals.json             (suggested rows fallback: floor_sell / target_price)
Output : data/watchlist.json

Config rows (see data/watchlist_config.json):
    {"slug": "archon_flow", "max_buy": 28, "min_sell": 70, "note": "restock"}
  max_buy / min_sell are platinum caps; either side may be missing (that side is then
  simply not watched). A row with neither, a bad slug or a duplicate slug is reported
  as a config warning and skipped - never silently dropped.

Status (per row, precedence is buy first - a buy trigger is the cheaper action):
    HIT_BUY   floor <= max_buy
    HIT_SELL  floor >= min_sell
    WAIT      neither (or no floor available this run)
  There is no UNKNOWN status: a row with no floor stays WAIT, keeps floor null, and says
  exactly why through two provenance fields, so a missing quote is visible and never guessed:
    floor_note  outcome of the live attempt when there is still no floor - 'offline',
                'fetch_cap', 'network_error', 'no_live_sell_orders', 'http_404', 'fetch_failed';
                null when a floor was found (prices.json or live)
    cache_note  state of the local snapshot - 'cached', 'cached_floor_null', 'not_cached', plus
                a '_suggested' suffix for cache-only candidate rows (which never fetch)
distance_p: plat gap to the nearest trigger. 0 when the floor sits exactly on it, null when
  the floor is unknown. HIT_BUY -> max_buy - floor, HIT_SELL -> floor - min_sell,
  WAIT -> min(floor - max_buy, min_sell - floor).

alerts[] is the machine-readable feed a later notifier consumes:
    {"level": "buy"|"sell", "slug", "name", "floor", "target", "distance_p", "vol48", "message"}
  level buy  -> target is max_buy, level sell -> target is min_sell. messages are one line.
  Ordering is deterministic: buy alerts (cheapest floor first), then sell alerts (priciest
  first). Suggested rows never alert - they are proposals, not your watchlist.

Floors come from prices.json; a config slug with no cached quote is fetched live
(v2 /orders/item/{slug}/top, one call, 0.35s spacing, honest WFMTrader UA) unless --offline
or the live budget is exhausted. Suggested rows always use the cache only.

Flags  : --offline        skip every network call (pure cache mode)
         --sleep S        seconds between API calls (floor 0.35)
         --max-live N     live fallback budget (hard cap 60)
         --suggested-limit N  max suggested rows (0 = none)
         --selftest       offline fixture run of every rule (no repo data, no network)

Stdlib only. Atomic write: tmp file + os.replace.
Usage: python scripts/watchlist.py [--offline] [--sleep 0.35] [--selftest]
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
OUT_PATH = os.path.join(DATA, 'watchlist.json')
CONFIG_PATH = os.path.join(DATA, 'watchlist_config.json')

VERSION = 1
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'
TOP_URL = 'https://api.warframe.market/v2/orders/item/%s/top'
CONFIG_COMMENT = ('edit me: add rows like {"slug":"archon_flow","max_buy":28,"min_sell":70,'
                  '"note":"restock"} - this file is created once and never rewritten')
STAMP = '%Y-%m-%d %H:%M'
STATUSES = ('HIT_BUY', 'HIT_SELL', 'WAIT')
LEVELS = ('buy', 'sell')
ENTRY_KEYS = ('slug', 'name', 'floor', 'median', 'vol48', 'max_buy', 'min_sell', 'status',
              'distance_p', 'alerts', 'note')
ALERT_KEYS = ('level', 'slug', 'name', 'floor', 'target', 'distance_p', 'vol48', 'message')
DEFAULT_SLEEP = 0.35          # seconds between live calls
MIN_SLEEP = 0.35
MAX_LIVE_FETCHES = 60         # safety cap per run
TOP_SUGGESTED = 20            # cap on computed candidate rows
RETRY_CODES = (429, 502, 503)
MAX_MSG = 200                 # one-line alert messages stay well under this


# ---------------------------------------------------------------- helpers
def jload(path, default=None):
    """Load JSON; return default when missing or unreadable. Never raises."""
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return default


def jload_input(data_dir, name, default=None):
    return jload(os.path.join(data_dir, name), default)


def atomic_write(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, indent=1)
    os.replace(tmp, path)


def as_num(value):
    """Float or None; bools and junk never raise."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def pos_num(value):
    """Float > 0 or None (0 / negative / junk -> None)."""
    num = as_num(value)
    return num if num is not None and num > 0 else None


def as_plat(value):
    """Platinum figure as an int (rounded), or None."""
    num = as_num(value)
    return None if num is None else int(round(num))


def r1(value):
    num = as_num(value)
    return None if num is None else round(num, 1)


def ascii_s(value):
    """ASCII-only text for stdout (Windows console safety)."""
    return str(value).encode('ascii', 'replace').decode('ascii')


def one_line(value):
    """Collapse any newline/whitespace run into single spaces (alert feed contract)."""
    return ' '.join(str(value or '').split())


def pretty(slug):
    """Fallback display name when the catalog has no entry for the slug."""
    return ' '.join(str(slug or '').replace('_', ' ').split()).title()


def med_of(stats_row):
    """Median: med48 preferred, then median, then avg48 (price_history/data convention)."""
    if not isinstance(stats_row, dict):
        return None
    for key in ('med48', 'median', 'avg48'):
        val = as_num(stats_row.get(key))
        if val is not None:
            return r1(val)
    return None


def vol_of(stats_row):
    if not isinstance(stats_row, dict):
        return None
    num = as_num(stats_row.get('vol48'))
    return None if num is None else int(num)


def band_text(max_buy, min_sell):
    """One-line description of the configured band."""
    if max_buy is None and min_sell is None:
        return 'no band'
    if max_buy is None:
        return 'sell at or above %sp' % min_sell
    if min_sell is None:
        return 'buy at or below %sp' % max_buy
    return 'buy at or below %sp / sell at or above %sp' % (max_buy, min_sell)


def config_comment():
    return CONFIG_COMMENT


# ---------------------------------------------------------------- config
def ensure_config(config_path):
    """Create the user config once. Never overwrite it on later runs.

    Returns (config_dict, created_bool). An unreadable / non-dict config is reported as
    empty instead of being clobbered - the file on disk is left exactly as it is.
    """
    if os.path.exists(config_path):
        cfg = jload(config_path, None)
        if isinstance(cfg, dict):
            return cfg, False
        return {'_comment': CONFIG_COMMENT, 'entries': []}, False
    empty = {'_comment': CONFIG_COMMENT, 'entries': []}
    atomic_write(config_path, empty)
    return empty, True


def parse_config(cfg):
    """Validated config rows + warnings. Bad rows are reported, never silently dropped."""
    rows, warns = [], []
    entries = cfg.get('entries')
    if entries is None:
        warns.append('no "entries" list in config; treated as empty')
        return rows, warns
    if not isinstance(entries, list):
        warns.append('"entries" is %s, expected a list; ignored' % type(entries).__name__)
        return rows, warns
    seen = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            warns.append('entry #%d is %s, expected an object' % (i, type(entry).__name__))
            continue
        slug = entry.get('slug')
        if not isinstance(slug, str) or not slug.strip():
            warns.append('entry #%d has no usable slug' % i)
            continue
        slug = slug.strip()
        max_buy, min_sell = as_plat(pos_num(entry.get('max_buy'))), as_plat(pos_num(entry.get('min_sell')))
        if max_buy is None and min_sell is None:
            warns.append('%s: max_buy and min_sell both missing or <= 0; row skipped' % slug)
            continue
        if slug in seen:
            warns.append('%s: duplicate config row; first one kept' % slug)
            continue
        seen.add(slug)
        if max_buy is not None and min_sell is not None and max_buy >= min_sell:
            warns.append('%s: max_buy %d >= min_sell %d (inverted band); both triggers kept, '
                         'HIT_BUY wins the status' % (slug, max_buy, min_sell))
        rows.append(dict(slug=slug, max_buy=max_buy, min_sell=min_sell,
                         note=one_line(entry.get('note')), source='config',
                         suggested_from=None))
    return rows, warns


# ---------------------------------------------------------------- suggestions
def suggested_rows(flip_doc, deals_doc, limit):
    """Candidate rows derived from already-computed local data (cache only, never alerts).

    flip_digest flips are already ranked (best first) and carry buy_at/sell_at; deals rows
    fill the rest by score. Config rows always win for the same slug.
    """
    if not limit or limit <= 0:
        return []
    rows, seen = [], set()

    def add(slug, name, buy, sell, origin, basis):
        slug = str(slug or '').strip()
        buy, sell = pos_num(buy), pos_num(sell)
        if not slug or slug in seen or buy is None or sell is None:
            return
        if int(round(sell)) <= int(round(buy)):
            return
        seen.add(slug)
        rows.append(dict(slug=slug, max_buy=int(round(buy)), min_sell=int(round(sell)),
                         note='', source='suggested', suggested_from=origin,
                         basis=basis, name=one_line(name)))

    flips = flip_doc.get('flips') if isinstance(flip_doc, dict) else None
    for flip in (flips or []):
        if isinstance(flip, dict):
            add(flip.get('slug'), flip.get('name'), flip.get('buy_at'), flip.get('sell_at'),
                'flip_digest', 'buy_at/sell_at')
    deals = deals_doc.get('deals') if isinstance(deals_doc, dict) else None
    deals = [d for d in (deals or []) if isinstance(d, dict)]
    deals.sort(key=lambda d: (-(as_num(d.get('score')) or 0.0), str(d.get('slug') or '')))
    for deal in deals:
        add(deal.get('slug'), deal.get('name'), deal.get('floor_sell'), deal.get('target_price'),
            'deals', 'floor_sell/target_price')
    return rows[:limit]


# ---------------------------------------------------------------- status + alerts
def status_for(floor, max_buy, min_sell):
    """(status, distance_p) for one row. Buy precedence, documented in the module docstring."""
    if floor is None:
        return 'WAIT', None
    if max_buy is not None and floor <= max_buy:
        return 'HIT_BUY', int(max_buy - floor)
    if min_sell is not None and floor >= min_sell:
        return 'HIT_SELL', int(floor - min_sell)
    gaps = []
    if max_buy is not None:
        gaps.append(floor - max_buy)
    if min_sell is not None:
        gaps.append(min_sell - floor)
    return 'WAIT', (int(min(gaps)) if gaps else None)


def fmt_context(entry):
    med = 'med48 %sp' % entry['median'] if entry.get('median') is not None else 'no med48'
    vol = 'vol48 %s' % entry['vol48'] if entry.get('vol48') is not None else 'vol48 n/a'
    return '%s | %s' % (med, vol)


def entry_alerts(entry):
    """Alert dicts whose triggers the current floor satisfies (0, 1 or 2 for an inverted band)."""
    out = []
    floor = entry.get('floor')
    if floor is None:
        return out
    if entry.get('max_buy') is not None and floor <= entry['max_buy']:
        out.append(dict(level='buy', slug=entry['slug'], name=entry['name'], floor=int(floor),
                        target=int(entry['max_buy']), distance_p=int(entry['max_buy'] - floor),
                        vol48=entry.get('vol48'),
                        message=one_line('BUY %s: floor %dp <= max_buy %dp (%dp under your cap) | %s'
                                         % (entry['name'], floor, entry['max_buy'],
                                            entry['max_buy'] - floor, fmt_context(entry)))[:MAX_MSG]))
    if entry.get('min_sell') is not None and floor >= entry['min_sell']:
        out.append(dict(level='sell', slug=entry['slug'], name=entry['name'], floor=int(floor),
                        target=int(entry['min_sell']), distance_p=int(floor - entry['min_sell']),
                        vol48=entry.get('vol48'),
                        message=one_line('SELL %s: floor %dp >= min_sell %dp (%dp over your floor) | %s'
                                         % (entry['name'], floor, entry['min_sell'],
                                            floor - entry['min_sell'], fmt_context(entry)))[:MAX_MSG]))
    return out


def sort_alerts(alerts):
    """Deterministic feed order: buys cheapest floor first, then sells priciest first."""
    buys = sorted([a for a in alerts if a['level'] == 'buy'],
                  key=lambda a: (a['floor'], a['slug']))
    sells = sorted([a for a in alerts if a['level'] == 'sell'],
                   key=lambda a: (-a['floor'], a['slug']))
    return buys + sells


# ---------------------------------------------------------------- network
class Fetcher(object):
    """Live sell-floor lookup for config rows missing from prices.json.

    Hard 0.35s+ spacing, a per-run call cap, and a trip-switch: a connection-level failure
    (DNS/timeout/refused) flips the run to offline instead of probing every remaining slug.
    """

    def __init__(self, offline, ids, sleep=DEFAULT_SLEEP, max_live=MAX_LIVE_FETCHES):
        self.offline = bool(offline)
        self.ids = ids or {}
        self.sleep_s = max(MIN_SLEEP, float(sleep))
        self.max_live = min(int(max_live), MAX_LIVE_FETCHES)
        self.last = 0.0
        self.calls = 0
        self.errors = []
        self.cache = {}
        self.status = {}

    def _sleep(self):
        gap = self.sleep_s - (time.time() - self.last)
        if gap > 0:
            time.sleep(gap)
        self.last = time.time()

    def floor(self, slug):
        if slug in self.cache:
            return self.cache[slug]
        if self.offline:
            self.status[slug] = 'offline'
            return None
        if self.calls >= self.max_live:
            self.status[slug] = 'fetch_cap'
            return None
        ref = self.ids.get(slug) or slug
        res = None
        for attempt in range(3):
            self._sleep()
            self.calls += 1
            try:
                req = urllib.request.Request(TOP_URL % ref,
                                             headers={'User-Agent': UA, 'Accept': 'application/json'})
                with urllib.request.urlopen(req, timeout=25) as resp:
                    data = json.loads(resp.read().decode())['data']
                sell = [o for o in (data.get('sell') or []) if o.get('visible')]
                buys = [o for o in (data.get('buy') or []) if o.get('visible')]
                res = dict(floor=min((o['platinum'] for o in sell), default=None),
                           wtb=max((o['platinum'] for o in buys), default=None),
                           n_sell=len(sell), n_buy=len(buys), live=True)
                self.status[slug] = 'ok' if res['floor'] is not None else 'empty'
                break
            except urllib.error.HTTPError as exc:
                if exc.code in RETRY_CODES and attempt < 2:
                    time.sleep(2.0 + 2.0 * attempt)
                    continue
                self.errors.append('%s: http %s' % (slug, exc.code))
                self.status[slug] = 'http_%d' % exc.code
                break
            except Exception as exc:                      # DNS/timeout/refused -> stop probing
                self.errors.append('%s: %s' % (slug, type(exc).__name__))
                self.status[slug] = 'error'
                self.offline = True
                break
        self.cache[slug] = res
        return res


# ---------------------------------------------------------------- rows
def compute_row(row, prices, stats, names, fetcher, allow_live, allow_alerts=True):
    """One watchlist entry: floor / median / vol48 / status / distance / alerts / provenance.

    ``allow_alerts=False`` (suggested candidates) keeps status/distance for display but never
    publishes alert rows - the feed only pages you about your own watchlist.
    """
    slug = row['slug']
    quote = prices.get(slug) if isinstance(prices.get(slug), dict) else {}
    floor, src = pos_num(quote.get('wts')), 'prices_json'
    n_sell = quote.get('n_sell')
    cache_note = 'cached' if quote and floor is not None else ('cached_floor_null' if quote
                                                              else 'not_cached')
    live_note = None
    if floor is None:
        if not allow_live:                            # suggested candidates never hit the network
            src, cache_note = 'none', cache_note + '_suggested'
        else:
            live = fetcher.floor(slug)
            status = fetcher.status.get(slug)
            if live and live.get('floor') is not None:
                floor, src, n_sell = live['floor'], 'live', live.get('n_sell')
            else:
                src, live_note = 'none', {
                    'offline': 'offline', 'fetch_cap': 'fetch_cap', 'empty': 'no_live_sell_orders',
                    'error': 'network_error',
                }.get(status, status if status and str(status).startswith('http_') else 'fetch_failed')
    stats_row = stats.get(slug) if isinstance(stats.get(slug), dict) else {}
    max_buy, min_sell = row.get('max_buy'), row.get('min_sell')
    status, distance = status_for(floor, max_buy, min_sell)
    entry = {
        'slug': slug,
        'name': one_line(names.get(slug)) or row.get('name') or pretty(slug),
        'floor': (int(floor) if floor is not None else None),
        'median': med_of(stats_row),
        'vol48': vol_of(stats_row),
        'max_buy': max_buy,
        'min_sell': min_sell,
        'status': status,
        'distance_p': distance,
        'alerts': [],
        'note': row.get('note') or '',
        'band': band_text(max_buy, min_sell),
        'source': row.get('source') or 'config',
        'suggested_from': row.get('suggested_from'),
        'basis': row.get('basis'),
        'floor_src': src,
        'floor_note': live_note,
        'cache_note': cache_note,
        'n_sell': n_sell,
        'overridden_by_config': bool(row.get('overridden_by_config')),
    }
    alerts = entry_alerts(entry) if allow_alerts else []
    entry['alerts'] = [a['message'] for a in alerts]
    return entry, alerts


def check_output(doc):
    """Contract checks over the finished document (mirrors wishlist.py's self_check)."""
    entries, alerts, summary = doc['entries'], doc['alerts'], doc['summary']
    by_slug = {e['slug']: e for e in entries}
    entry_slugs = {e['slug'] for e in entries}
    suggested_slugs = {s['slug'] for s in doc['suggested']}
    overridden = {s['slug'] for s in doc['suggested'] if s.get('overridden_by_config')}
    return dict(
        statuses_known=all(e['status'] in STATUSES for e in entries),
        entry_keys_exact=all(list(e)[:len(ENTRY_KEYS)] == list(ENTRY_KEYS) for e in entries),
        unique_entry_slugs=len(entry_slugs) == len(entries),
        summary_matches_entries=(summary['total'] == len(entries)
                                 and summary['hit_buy'] == len([e for e in entries if e['status'] == 'HIT_BUY'])
                                 and summary['hit_sell'] == len([e for e in entries if e['status'] == 'HIT_SELL'])
                                 and summary['wait'] == len([e for e in entries if e['status'] == 'WAIT'])
                                 and summary['hit_buy'] + summary['hit_sell'] + summary['wait'] == len(entries)),
        alert_keys_exact=all(list(a)[:len(ALERT_KEYS)] == list(ALERT_KEYS) for a in alerts),
        alert_levels_known=all(a['level'] in LEVELS for a in alerts),
        alerts_one_line=all('\n' not in a['message'] and '\r' not in a['message']
                            and 0 < len(a['message']) <= MAX_MSG for a in alerts),
        alerts_match_entries=all(a['slug'] in by_slug
                                 and a['target'] == (by_slug[a['slug']]['max_buy'] if a['level'] == 'buy'
                                                     else by_slug[a['slug']]['min_sell'])
                                 and a['floor'] == by_slug[a['slug']]['floor']
                                 and a['message'] in by_slug[a['slug']]['alerts'] for a in alerts),
        alerts_cover_hits=(summary['alerts_total'] == len(alerts)
                           and summary['alerts_total'] >= summary['hit_buy'] + summary['hit_sell']),
        alert_order_deterministic=(sort_alerts(alerts) == alerts),
        no_alerts_for_suggested=all(not s['alerts'] for s in doc['suggested']),
        no_alert_without_floor=all(e['alerts'] == [] for e in entries if e['floor'] is None),
        floor_note_only_without_floor=all(e['floor_note'] is None or e['floor'] is None
                                          for e in entries),
        cache_note_present=all(bool(e['cache_note']) for e in entries),
        distance_typed=all(e['distance_p'] is None or isinstance(e['distance_p'], int) for e in entries),
        floors_typed=all(e['floor'] is None or isinstance(e['floor'], int) for e in entries),
        config_rows_kept=len(entries) == doc['config']['entries'],
        suggested_unique=len(suggested_slugs) == len(doc['suggested']),
        suggested_not_duplicated=not ((suggested_slugs - overridden) & entry_slugs),
        live_calls_within_cap=doc['network']['live_calls'] <= doc['network']['live_cap'],
    )


def run(offline=False, sleep=DEFAULT_SLEEP, max_live=MAX_LIVE_FETCHES, suggested_limit=TOP_SUGGESTED,
        data_dir=None, out_path=None, config_path=None, stamp=None):
    """Full pipeline -> watchlist document (also written to out_path). No argparse here.

    ``data_dir``/``out_path``/``config_path`` default to the repo paths; selftest and tests
    pass a temp dir so no real data is read or written.
    """
    data_dir = data_dir or DATA
    out_path = out_path or OUT_PATH
    config_path = config_path or CONFIG_PATH
    started = time.time()

    prices = jload_input(data_dir, 'prices.json', {}) or {}
    stats = jload_input(data_dir, 'stats.json', {}) or {}
    prices = prices if isinstance(prices, dict) else {}
    stats = stats if isinstance(stats, dict) else {}
    catalog_doc = jload_input(data_dir, 'wfm_items_v2.json', {}) or {}
    catalog = catalog_doc.get('data') if isinstance(catalog_doc, dict) else None
    catalog = catalog if isinstance(catalog, list) else []
    names, ids = {}, {}
    for item in catalog:
        if isinstance(item, dict) and item.get('slug'):
            names[item['slug']] = ((item.get('i18n') or {}).get('en') or {}).get('name') or item['slug']
            if item.get('id'):
                ids[item['slug']] = item['id']

    cfg, cfg_created = ensure_config(config_path)
    cfg_rows, cfg_warns = parse_config(cfg)
    flip_doc = jload_input(data_dir, 'flip_digest.json', {}) or {}
    deals_doc = jload_input(data_dir, 'deals.json', {}) or {}
    suggested = suggested_rows(flip_doc, deals_doc, suggested_limit)
    cfg_slugs = {r['slug'] for r in cfg_rows}
    for row in suggested:
        row['overridden_by_config'] = row['slug'] in cfg_slugs
        row['name'] = names.get(row['slug']) or row['name'] or pretty(row['slug'])

    fetcher = Fetcher(offline, ids, sleep=sleep, max_live=max_live)
    entries, alerts = [], []
    for row in cfg_rows:                              # config rows: cache first, live fallback
        entry, row_alerts = compute_row(row, prices, stats, names, fetcher, True)
        entries.append(entry)
        alerts.extend(row_alerts)
    suggested_entries = []
    for row in suggested:                             # candidates: cache only, never alert
        entry, _ = compute_row(row, prices, stats, names, fetcher, False, allow_alerts=False)
        suggested_entries.append(entry)
    alerts = sort_alerts(alerts)

    counts = {s: len([e for e in entries if e['status'] == s]) for s in STATUSES}
    overrides = len(cfg_slugs & {r['slug'] for r in suggested})
    doc = dict(
        version=VERSION,
        generated=stamp or time.strftime(STAMP),
        generated_iso=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        source=('watchlist_config.json bands vs prices.json floors (+ live v2 top-order fallback '
                'for misses); offline=%s live_calls=%d' % (bool(offline or fetcher.offline),
                                                           fetcher.calls)),
        config_path='data/watchlist_config.json',
        config=dict(created=cfg_created, entries=len(cfg_rows), raw_entries=len(cfg.get('entries') or []),
                    warnings=cfg_warns, suggested=len(suggested), overrides=overrides),
        entries=entries,
        suggested=suggested_entries,
        summary=dict(hit_buy=counts['HIT_BUY'], hit_sell=counts['HIT_SELL'], wait=counts['WAIT'],
                     total=len(entries), alerts_total=len(alerts), suggested_total=len(suggested_entries),
                     unknown_floor=len([e for e in entries if e['floor'] is None]),
                     live_calls=fetcher.calls, offline=bool(offline or fetcher.offline)),
        alerts=alerts,
        network=dict(offline=bool(offline or fetcher.offline), live_calls=fetcher.calls,
                     live_cap=fetcher.max_live, sleep_s=fetcher.sleep_s,
                     fetched=len(fetcher.cache), errors=fetcher.errors[:8]),
        assumptions=[
            'HIT_BUY = floor <= max_buy; HIT_SELL = floor >= min_sell; else WAIT (buy precedence)',
            'a row with no floor this run stays WAIT with floor null plus floor_note '
            '(why the live attempt failed) and cache_note (local snapshot state) - never guessed',
            'distance_p = plat gap to the nearest trigger (0 exactly on it, null without a floor)',
            'alerts[] carry level buy (target max_buy) / sell (target min_sell), one line per message',
            'alerts are ordered buys (cheapest floor first) then sells (priciest first)',
            'suggested rows come from flip_digest flips then deals by score; they never alert',
            'config rows override suggested rows for the same slug',
            'floors missing from prices.json are fetched live (0.35s spacing, cap %d) unless --offline'
            % MAX_LIVE_FETCHES,
            'data/watchlist_config.json is created once and never rewritten'],
        self_check=None)
    doc['self_check'] = check_output(doc)
    atomic_write(out_path, doc)
    doc['_runtime_s'] = round(time.time() - started, 2)
    return doc


def report(doc):
    """Human summary on stdout (UI reads the JSON)."""
    summary, config = doc['summary'], doc['config']
    print('watchlist.py -> data/watchlist.json   %s   (%ss)' % (doc['generated'], doc.get('_runtime_s')))
    print('config: data/watchlist_config.json %s | rows %d (%d raw)%s'
          % ('CREATED (empty entries)' if config['created'] else 'existing, untouched',
             config['entries'], config['raw_entries'],
             ' | warnings: ' + '; '.join(config['warnings'][:3]) if config['warnings'] else ''))
    print('rows: %d watched | %d suggested (overrides %d)'
          % (summary['total'], summary['suggested_total'], config['overrides']))
    print('floors: %d from prices.json | %d live | %d unavailable | %s'
          % (len([e for e in doc['entries'] if e['floor_src'] == 'prices_json']),
             len([e for e in doc['entries'] if e['floor_src'] == 'live']),
             len([e for e in doc['entries'] if e['floor'] is None]),
             'OFFLINE' if doc['network']['offline'] else 'online'))
    print('status: HIT_BUY %d | HIT_SELL %d | WAIT %d | alerts %d'
          % (summary['hit_buy'], summary['hit_sell'], summary['wait'], summary['alerts_total']))
    for entry in doc['entries']:
        print('   %-38s %-9s floor=%-5s cap=%-5s sell=%-5s dist=%-5s %s'
              % (ascii_s(entry['slug']), entry['status'], entry['floor'], entry['max_buy'],
                 entry['min_sell'], entry['distance_p'], ascii_s(entry['band'])[:34]))
    for alert in doc['alerts']:
        print('   [%s] %s' % (alert['level'].upper(), ascii_s(alert['message'])))
    for entry in doc['suggested'][:3]:
        print('   (candidate) %-32s %-9s floor=%-5s buy<=%-5s sell>=%s'
              % (ascii_s(entry['slug']), entry['status'], entry['floor'], entry['max_buy'],
                 entry['min_sell']))
    failed = [k for k, v in doc['self_check'].items() if not v]
    print('self-check: %s' % ('OK (%d checks)' % len(doc['self_check'])
                              if not failed else 'FAILED: ' + ', '.join(failed)))
    if doc['network']['errors']:
        print('network errors: %s' % ', '.join(doc['network']['errors'][:4]))


# ---------------------------------------------------------------- selftest
SELFTEST_PRICES = {
    'cheap_item': {'wts': 30, 'wtb': 20, 'n_sell': 5, 'n_buy': 2},      # <= max_buy 40  -> HIT_BUY
    'rich_item': {'wts': 120, 'wtb': 90, 'n_sell': 4, 'n_buy': 3},      # >= min_sell 90 -> HIT_SELL
    'mid_item': {'wts': 50, 'wtb': 44, 'n_sell': 6, 'n_buy': 1},        # between        -> WAIT 10p
    'both_item': {'wts': 100, 'wtb': 60, 'n_sell': 3, 'n_buy': 2},      # inverted band  -> HIT_BUY
    'overridden_item': {'wts': 77, 'wtb': 70, 'n_sell': 5, 'n_buy': 0},
    'candidate_cached': {'wts': 22, 'wtb': 18, 'n_sell': 5, 'n_buy': 1},
}
SELFTEST_STATS = {
    'cheap_item': {'vol48': 20, 'med48': 33.3333, 'median': 33.3},
    'rich_item': {'vol48': 7, 'median': 118.0},
    'mid_item': {'vol48': 12, 'avg48': 51.0},
    'both_item': {'vol48': 3, 'med48': 99.9},
    'overridden_item': {'vol48': 9, 'med48': 80.0},
    'candidate_cached': {'vol48': 15, 'med48': 24.0},
    'candidate_right': {'vol48': 11, 'med48': 210.0},
}
SELFTEST_CONFIG = {
    '_comment': 'selftest fixtures',
    'entries': [
        {'slug': 'cheap_item', 'max_buy': 40, 'min_sell': 90, 'note': 'buy the dip'},
        {'slug': 'rich_item', 'max_buy': 40, 'min_sell': 90, 'note': ''},
        {'slug': 'mid_item', 'max_buy': 40, 'min_sell': 90},
        {'slug': 'both_item', 'max_buy': 100, 'min_sell': 100, 'note': 'inverted band by design'},
        {'slug': 'no_floor_item', 'max_buy': 40},
        {'slug': 'overridden_item', 'max_buy': 80, 'min_sell': 150, 'note': 'config wins'},
        {'slug': '  ', 'max_buy': 10},                     # bad: no usable slug
        {'max_buy': 10},                                   # bad: no slug key
        {'slug': 'zero_item', 'max_buy': 0, 'min_sell': 0},  # bad: no usable threshold
        {'slug': 'cheap_item', 'max_buy': 999},            # bad: duplicate
        'not-an-object',                                   # bad: wrong type
        {'slug': 'sell_only_item', 'min_sell': 500, 'note': 'sell side only'},
    ],
}
SELFTEST_FLIPS = {
    'flips': [
        {'slug': 'overridden_item', 'name': 'Overridden Item', 'kind': 'undercut',
         'buy_at': 175, 'sell_at': 299, 'score': 100.0},
        {'slug': 'candidate_cached', 'name': 'Candidate Cached', 'kind': 'undercut',
         'buy_at': 40, 'sell_at': 120, 'score': 90.0},
        {'slug': 'candidate_right', 'name': 'Candidate Right', 'kind': 'spread',
         'buy_at': 100, 'sell_at': 260, 'score': 80.0},
        {'slug': 'junk_row', 'buy_at': 0, 'sell_at': 0},   # dropped: no usable band
    ],
}
SELFTEST_DEALS = {
    'deals': [
        {'slug': 'candidate_cached', 'name': 'Candidate Cached', 'kind': 'spread',
         'floor_sell': 20, 'target_price': 100, 'score': 300.0},   # dropped: already suggested
        {'slug': 'deals_candidate', 'name': 'Deals Candidate', 'kind': 'spread',
         'floor_sell': 60, 'target_price': 150, 'score': 500.0},
    ],
}
SELFTEST_CATALOG = {'data': [
    {'slug': slug, 'id': 'id-%s' % slug, 'i18n': {'en': {'name': slug.replace('_', ' ').title()}}}
    for slug in ('cheap_item', 'rich_item', 'mid_item', 'both_item', 'overridden_item',
                 'candidate_cached', 'candidate_right', 'deals_candidate', 'zero_item')
]}


def _sha(path):
    try:
        with open(path, 'rb') as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def selftest():
    """Offline fixtures through the real pipeline. No network, no repo data touched."""
    tmpdir = tempfile.mkdtemp(prefix='watchlist_selftest_')
    real_out, real_cfg = _sha(OUT_PATH), _sha(CONFIG_PATH)
    out_path = os.path.join(tmpdir, 'watchlist.json')
    cfg_path = os.path.join(tmpdir, 'watchlist_config.json')
    results = []

    def check(name, cond):
        results.append((name, bool(cond)))

    def seed(d):
        for name, payload in (('prices.json', SELFTEST_PRICES), ('stats.json', SELFTEST_STATS),
                              ('wfm_items_v2.json', SELFTEST_CATALOG),
                              ('flip_digest.json', SELFTEST_FLIPS), ('deals.json', SELFTEST_DEALS)):
            with open(os.path.join(d, name), 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, indent=1)

    try:
        # --- first run: config absent -> created empty, then re-run with fixtures
        doc = run(offline=True, suggested_limit=0, data_dir=tmpdir, out_path=out_path,
                  config_path=cfg_path)
        check('config created once when absent', doc['config']['created'] is True
              and os.path.exists(cfg_path))
        check('created config has an empty entries list',
              jload(cfg_path) == {'_comment': CONFIG_COMMENT, 'entries': []})
        check('no config entries -> no alerts, doc still written',
              doc['entries'] == [] and doc['alerts'] == [] and doc['summary']['total'] == 0)

        # --- the real fixture run
        with open(cfg_path, 'w', encoding='utf-8') as fh:
            json.dump(SELFTEST_CONFIG, fh, indent=1)
        cfg_hash = _sha(cfg_path)
        seed(tmpdir)
        doc = run(offline=True, data_dir=tmpdir, out_path=out_path, config_path=cfg_path,
                  stamp='2026-01-01 00:00')
        entries = {e['slug']: e for e in doc['entries']}
        summary, alerts = doc['summary'], doc['alerts']

        check('config kept (not overwritten) when it already exists', doc['config']['created'] is False
              and _sha(cfg_path) == cfg_hash)
        check('output file written atomically + parseable', jload(out_path) is not None
              and jload(out_path)['entries'] == doc['entries'])
        check('7 valid config rows survive (junk rows skipped)',
              summary['total'] == 7 and doc['config']['entries'] == 7)
        check('junk config rows are reported as warnings',
              len(doc['config']['warnings']) == 6
              and any('duplicate' in w for w in doc['config']['warnings'])
              and any('inverted band' in w for w in doc['config']['warnings'])
              and any('both missing or <= 0' in w for w in doc['config']['warnings']))
        check('entry keys start with the documented contract',
              all(list(e)[:len(ENTRY_KEYS)] == list(ENTRY_KEYS) for e in doc['entries']))
        check('generated stamps: local + UTC iso',
              doc['generated'] == '2026-01-01 00:00' and doc['generated_iso'].endswith('Z'))

        # --- statuses
        check('cheap floor <= max_buy -> HIT_BUY with distance',
              entries['cheap_item']['status'] == 'HIT_BUY' and entries['cheap_item']['distance_p'] == 10)
        check('rich floor >= min_sell -> HIT_SELL with distance',
              entries['rich_item']['status'] == 'HIT_SELL' and entries['rich_item']['distance_p'] == 30)
        check('floor inside the band -> WAIT, distance to the nearer trigger',
              entries['mid_item']['status'] == 'WAIT' and entries['mid_item']['distance_p'] == 10)
        check('inverted band: HIT_BUY wins, both alerts emitted',
              entries['both_item']['status'] == 'HIT_BUY' and len(entries['both_item']['alerts']) == 2)
        check('no cached floor + offline -> WAIT, floor null, both notes honest',
              entries['no_floor_item']['status'] == 'WAIT' and entries['no_floor_item']['floor'] is None
              and entries['no_floor_item']['floor_note'] == 'offline'
              and entries['no_floor_item']['cache_note'] == 'not_cached')
        check('sell-side-only row still evaluates',
              entries['sell_only_item']['status'] == 'WAIT' and entries['sell_only_item']['max_buy'] is None)
        check('statuses are exactly the documented set',
              {e['status'] for e in doc['entries']} <= set(STATUSES))
        check('median pref falls back med48 -> median -> avg48',
              entries['cheap_item']['median'] == 33.3 and entries['rich_item']['median'] == 118.0
              and entries['mid_item']['median'] == 51.0)
        check('vol48 carried from stats.json', entries['mid_item']['vol48'] == 12)

        # --- alerts feed
        check('summary counts match the entry statuses',
              summary['hit_buy'] == 3 and summary['hit_sell'] == 1 and summary['wait'] == 3
              and summary['total'] == 7 and summary['alerts_total'] == 5)
        check('alert feed = buys first (cheap -> rich), then sells (priciest first)',
              [a['level'] for a in alerts] == ['buy', 'buy', 'buy', 'sell', 'sell']
              and [a['floor'] for a in alerts] == [30, 77, 100, 120, 100]
              and [a['slug'] for a in alerts] == ['cheap_item', 'overridden_item', 'both_item',
                                                  'rich_item', 'both_item'])
        check('every alert carries the machine keys',
              all(list(a)[:len(ALERT_KEYS)] == list(ALERT_KEYS) for a in alerts))
        check('buy alert targets max_buy, sell alert targets min_sell',
              all(a['target'] == entries[a['slug']]['max_buy'] for a in alerts if a['level'] == 'buy')
              and all(a['target'] == entries[a['slug']]['min_sell'] for a in alerts if a['level'] == 'sell'))
        check('messages are one line and name the item + trigger',
              all('\n' not in a['message'] and a['level'].upper() in a['message']
                  and entries[a['slug']]['name'] in a['message'] for a in alerts))
        check('entry.alerts mirror the feed messages',
              all(set(entries[a['slug']]['alerts']) and a['message'] in entries[a['slug']]['alerts']
                  for a in alerts))
        check('rows with no floor never alert',
              all(e['alerts'] == [] for e in doc['entries'] if e['floor'] is None))

        # --- suggestions
        check('suggested rows derived from flip_digest then deals by score',
              summary['suggested_total'] == 4
              and [s['slug'] for s in doc['suggested']] == ['overridden_item', 'candidate_cached',
                                                            'candidate_right', 'deals_candidate']
              and all(s['source'] == 'suggested' for s in doc['suggested']))
        check('unusable suggested rows are dropped (0/0 band, sell_at <= buy_at)',
              'junk_row' not in [s['slug'] for s in doc['suggested']]
              and len(SELFTEST_FLIPS['flips']) == 4)
        check('config row wins over the suggested row for the same slug',
              doc['config']['overrides'] == 1
              and entries['overridden_item']['source'] == 'config'
              and entries['overridden_item']['max_buy'] == 80
              and [s for s in doc['suggested'] if s['slug'] == 'overridden_item'][0]
                  ['overridden_by_config'] is True)
        check('suggested rows never alert',
              all(s['alerts'] == [] for s in doc['suggested']))
        check('a candidate whose band is hit still shows its status, just no alert',
              [s for s in doc['suggested'] if s['slug'] == 'candidate_cached'][0]['status'] == 'HIT_BUY'
              and [s for s in doc['suggested'] if s['slug'] == 'candidate_cached'][0]['alerts'] == [])
        check('candidate without a cached floor stays null + cache-only noted',
              [s for s in doc['suggested'] if s['slug'] == 'deals_candidate'][0]['cache_note']
              == 'not_cached_suggested'
              and [s for s in doc['suggested'] if s['slug'] == 'deals_candidate'][0]['floor_note'] is None)
        check('--suggested-limit 0 drops the candidate rows',
              run(offline=True, suggested_limit=0, data_dir=tmpdir, out_path=out_path,
                  config_path=cfg_path)['suggested'] == [])
        check('offline run makes zero live calls',
              doc['network']['live_calls'] == 0 and doc['network']['offline'] is True
              and all(e['floor_src'] != 'live' for e in doc['entries']))

        # --- no prices.json at all
        bare = os.path.join(tmpdir, 'bare')
        os.makedirs(bare, exist_ok=True)
        with open(os.path.join(bare, 'watchlist_config.json'), 'w', encoding='utf-8') as fh:
            json.dump(SELFTEST_CONFIG, fh)
        doc2 = run(offline=True, suggested_limit=0, data_dir=bare,
                   out_path=os.path.join(bare, 'watchlist.json'),
                   config_path=os.path.join(bare, 'watchlist_config.json'))
        check('missing prices.json degrades to all-WAIT, no crash',
              doc2['summary']['total'] == 7 and doc2['summary']['wait'] == 7
              and doc2['alerts'] == [] and all(e['floor'] is None for e in doc2['entries']))
        check('self_check passes on that degraded doc too',
              all(doc2['self_check'].values()))

        # --- cached-but-null floor vs missing cache entry (two different facts, both told)
        null_dir = os.path.join(tmpdir, 'nullfloor')
        os.makedirs(null_dir, exist_ok=True)
        with open(os.path.join(null_dir, 'watchlist_config.json'), 'w', encoding='utf-8') as fh:
            json.dump({'entries': [{'slug': 'cached_null', 'max_buy': 40},
                                   {'slug': 'never_priced', 'max_buy': 40}]}, fh)
        with open(os.path.join(null_dir, 'prices.json'), 'w', encoding='utf-8') as fh:
            json.dump({'cached_null': {'wts': None, 'n_sell': 0}}, fh)
        doc3 = run(offline=True, suggested_limit=0, data_dir=null_dir,
                   out_path=os.path.join(null_dir, 'watchlist.json'),
                   config_path=os.path.join(null_dir, 'watchlist_config.json'))
        rows = {e['slug']: e for e in doc3['entries']}
        check('cached null floor vs missing cache entry are told apart',
              rows['cached_null']['cache_note'] == 'cached_floor_null'
              and rows['never_priced']['cache_note'] == 'not_cached'
              and rows['cached_null']['floor_note'] == 'offline'
              and rows['never_priced']['floor_note'] == 'offline'
              and all(e['floor'] is None for e in doc3['entries']))

        # --- self-check on the main doc
        check('self_check: every contract check true', all(doc['self_check'].values()))
        check('self_check lists both a price and an alert invariant',
              {'summary_matches_entries', 'alerts_one_line', 'live_calls_within_cap'}
              <= set(doc['self_check']))

        # --- Fetcher contract (no network: offline trips, the cap trips before any call)
        fetcher = Fetcher(True, {'cheap_item': 'id-cheap_item'})
        check('offline fetcher refuses without a call', fetcher.floor('x') is None
              and fetcher.calls == 0 and fetcher.status['x'] == 'offline')
        capped = Fetcher(False, {}, sleep=0.0, max_live=0)
        check('live cap refuses without a call',
              capped.floor('never_cached') is None and capped.calls == 0
              and capped.status['never_cached'] == 'fetch_cap')
        check('sleep floor is respected', Fetcher(True, {}, sleep=0.0).sleep_s == MIN_SLEEP
              and Fetcher(True, {}, sleep=5).sleep_s == 5.0)
        check('live cap can never exceed the hard ceiling',
              Fetcher(True, {}, max_live=9999).max_live == MAX_LIVE_FETCHES)

        # --- pure helpers
        check('status_for is pure and buy-first',
              status_for(40, 40, 90) == ('HIT_BUY', 0)
              and status_for(90, 40, 90) == ('HIT_SELL', 0)
              and status_for(50, 40, 90) == ('WAIT', 10)
              and status_for(None, 40, 90) == ('WAIT', None)
              and status_for(100, 100, 100) == ('HIT_BUY', 0))
        check('parse_config warns on a non-list entries value',
              parse_config({'entries': 'nope'})[1] == ['"entries" is str, expected a list; ignored']
              and parse_config({})[1] == ['no "entries" list in config; treated as empty'])
        check('pos_num / as_plat never trust junk',
              pos_num(0) is None and pos_num(-5) is None and pos_num('12') == 12.0
              and pos_num('x') is None and pos_num(True) is None
              and as_plat(12.6) == 13 and as_plat(None) is None)
        check('one_line flattens newlines for the feed',
              one_line('a\nb  c') == 'a b c' and one_line(None) == '')
        check('pretty() gives a readable fallback name', pretty('arcane_energize') == 'Arcane Energize')
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    check('repo data/watchlist.json untouched by selftest', _sha(OUT_PATH) == real_out)
    check('repo data/watchlist_config.json untouched by selftest', _sha(CONFIG_PATH) == real_cfg)

    passed = sum(1 for _, ok in results if ok)
    for name, ok in results:
        if not ok:
            print('FAIL: %s' % name)
    print('selftest: %d checks, %d passed, %d failed' % (len(results), passed, len(results) - passed))
    return passed == len(results)


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description='Watchlist bands + alert feed -> data/watchlist.json')
    ap.add_argument('--offline', action='store_true', help='skip the live /top fallback (cache only)')
    ap.add_argument('--sleep', type=float, default=DEFAULT_SLEEP,
                    help='seconds between live calls (floor %.2f)' % MIN_SLEEP)
    ap.add_argument('--max-live', type=int, default=MAX_LIVE_FETCHES,
                    help='live fallback budget this run (hard cap %d)' % MAX_LIVE_FETCHES)
    ap.add_argument('--suggested-limit', type=int, default=TOP_SUGGESTED,
                    help='max computed candidate rows (0 = none)')
    ap.add_argument('--selftest', action='store_true',
                    help='offline fixture run of every rule (no repo data, no network)')
    args = ap.parse_args(argv)

    if args.selftest:
        return 0 if selftest() else 1

    doc = run(offline=args.offline, sleep=args.sleep, max_live=args.max_live,
              suggested_limit=args.suggested_limit)
    report(doc)

    if doc['summary']['total'] == 0:
        print('note: no watchlist rows yet - add entries to data/watchlist_config.json '
              '(copy a candidate above)')
    if not jload(os.path.join(DATA, 'prices.json')):
        print('WARN data/prices.json missing or empty: every floor is unavailable '
              '(run scripts/setup.py or scripts/fetch_prices.py)')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
