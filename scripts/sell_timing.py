"""Sell-timing score: which local hours this account actually sells in.

Input:  data/trade_log.json  (sale events written by scripts/log_trade.py and
        scripts/import_aleca_stats.py - the imported AlecaFrame history)
Output: data/sell_timing.json

Every sale is bucketed by local hour-of-day and weekday in Australia/Melbourne (a fixed
UTC+10 fallback covers Windows boxes without a tz database). Hour rows and (weekday, hour)
cells are ranked by sales then platinum, so the dashboard can show a SELL_NOW / HOLD
verdict plus the next window that historically moves. Item kinds reuse the dashboard's own
category chain (server.py items_payload): tags come from a local-only index built off
data/owned.json and the data/wfm_items_v2.json catalog, and items with no local tags fall
back to name rules. The imported history is one account's small sample, so thin buckets
are labelled in sample.note / by_kind notes instead of being dressed up.

Usage: python scripts/sell_timing.py [--root DIR] [--now EPOCH|ISO] [--top N]
                                     [--min-sales N] [--selftest]
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:                     # pragma: no cover - Python without zoneinfo
    ZoneInfo = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_NAME = 'sell_timing.json'
TZ_NAME = 'Australia/Melbourne'
TZ_FALLBACK_HOURS = 10                  # UTC+10 (AEST) when no tz database is installed
TOP_HOURS = 3                           # hours that can trigger SELL_NOW
MIN_HOUR_SALES = 5                      # ... but only with this much sample behind them
TOP_WINDOWS = 5                         # (weekday, hour) cells reported
KIND_TOP_HOURS = 3
MIN_KIND_SALES = 5                      # kinds below this are flagged thin
THIN_SAMPLE = 30                        # sample below this is called a hint in the note
DOW = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
KIND_ORDER = ('prime_part', 'prime_bp', 'prime_set', 'relic', 'arcane', 'mod', 'other')
WATCH_KINDS = ('relic', 'arcane', 'prime_set')      # kinds worth calling out when absent
RELIC_TIERS = ('lith', 'meso', 'neo', 'axi', 'requiem', 'vanguard')
PRIME_PARTS = ('chassis', 'neuroptics', 'systems', 'barrel', 'receiver', 'stock', 'blade',
               'handle', 'link', 'upper limb', 'lower limb', 'ornament', 'carapace',
               'cerebrum', 'boot', 'gauntlet', 'star', 'grip', 'string', 'guard', 'disc',
               'head', 'pouch', 'hilt')


# ------------------------------------------------------------------ io / time

def jload(path, default=None):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return default


def jdump(path, obj):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path + '.tmp', 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, indent=1)
    os.replace(path + '.tmp', path)


def local_tz():
    """Australia/Melbourne when the tz database is available, else a fixed UTC+10."""
    if ZoneInfo is not None:
        try:
            return ZoneInfo(TZ_NAME)
        except Exception:
            pass
    return timezone(timedelta(hours=TZ_FALLBACK_HOURS))


def parse_now(raw, tz):
    """--now takes epoch seconds or an ISO timestamp; None means time.time()."""
    if not raw:
        return int(time.time())
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        pass
    when = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
    if when.tzinfo is None:
        when = when.replace(tzinfo=tz)
    return int(when.timestamp())


# ------------------------------------------------------------------ item kinds

def cat_of(tags):
    """The same tag chain server.py items_payload uses, so kinds match the UI tabs."""
    t = set(tags or ())
    if 'relic' in t:
        return 'relic'
    if 'mod' in t:
        return 'mod'
    if 'arcane_enhancement' in t:
        return 'arcane'
    if 'prime' in t and 'component' in t:
        return 'prime_part'
    if 'prime' in t and 'blueprint' in t:
        return 'prime_bp'
    if 'prime' in t and 'set' in t:
        return 'prime_set'
    return 'other'


def name_kind(name):
    """Fallback kind for items with no local tags - name patterns only, no network."""
    low = (name or '').strip().lower()
    if not low:
        return 'other'
    if 'relic' in low or low.split(' ', 1)[0] in RELIC_TIERS:
        return 'relic'
    if low.startswith('arcane ') or ' arcane ' in low:
        return 'arcane'
    if ' prime ' in ' %s ' % low:
        tail = low.split(' prime ', 1)[1].lstrip()
        if tail.startswith('set'):
            return 'prime_set'
        if any(tail.startswith(part) for part in PRIME_PARTS):
            return 'prime_part'
        return 'prime_bp' if 'blueprint' in tail else 'prime_part'
    return 'other'


def tags_index(data_dir):
    """name -> tags from local files only: owned.json first (current inventory), then the
    wfm_items_v2.json catalog fills in items no longer held. Missing files are fine."""
    idx = {}

    def add(name, tags):
        if name and tags and name not in idx:
            idx[name] = set(tags)

    for row in jload(os.path.join(data_dir, 'owned.json'), []) or []:
        if isinstance(row, dict):
            add(row.get('name'), row.get('tags'))
    catalog = jload(os.path.join(data_dir, 'wfm_items_v2.json'), {}) or {}
    rows = catalog.get('data') if isinstance(catalog, dict) else catalog
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        i18n = (row.get('i18n') or {}).get('en') or {}
        add(i18n.get('name') or row.get('name'), row.get('tags'))
    return idx


def kind_of(name, index=None):
    tags = (index or {}).get(name)
    return cat_of(tags) if tags else name_kind(name)


# ------------------------------------------------------------------ bucketing

def plat_of(event):
    total = event.get('total')
    return total if total is not None else (event.get('plat') or 0)


def trade_events(log):
    """Sale events from trade_log.json (a list, or a dict wrapper with 'events')."""
    rows = log.get('events') if isinstance(log, dict) else log
    return [e for e in (rows or [])
            if isinstance(e, dict) and e.get('kind') == 'sale' and e.get('ts')]


def bucket(events, tz, index=None):
    """[sales, plat] tallies per hour, per weekday, per (dow, hour) cell, per kind hour."""
    out = {'hours': [[0, 0] for _ in range(24)], 'weekdays': [[0, 0] for _ in range(7)],
           'cells': {}, 'kind_hours': {}}
    for event in events:
        when = datetime.fromtimestamp(event['ts'], tz)
        plat = plat_of(event)
        out['hours'][when.hour][0] += 1
        out['hours'][when.hour][1] += plat
        out['weekdays'][when.weekday()][0] += 1
        out['weekdays'][when.weekday()][1] += plat
        cell = out['cells'].setdefault((when.weekday(), when.hour), [0, 0])
        cell[0] += 1
        cell[1] += plat
        kind = kind_of(event.get('name') or '', index)
        hours = out['kind_hours'].setdefault(kind, [[0, 0] for _ in range(24)])
        hours[when.hour][0] += 1
        hours[when.hour][1] += plat
    return out


def local_dates(events, tz):
    return sorted({datetime.fromtimestamp(e['ts'], tz).date() for e in events})


def hour_rows(hours):
    return [{'hour': h, 'sales': v[0], 'plat': round(v[1], 2)} for h, v in enumerate(hours)]


def weekday_rows(weekdays):
    return [{'dow': d, 'sales': v[0], 'plat': round(v[1], 2)} for d, v in enumerate(weekdays)]


def rank_hours(rows):
    """Most sales first, then most platinum, then the earliest hour."""
    return sorted(rows, key=lambda r: (-r['sales'], -r['plat'], r['hour']))


def best_windows(cells, limit=TOP_WINDOWS):
    rows = [{'dow': d, 'hour': h, 'sales': v[0], 'plat': round(v[1], 2)}
            for (d, h), v in cells.items()]
    rows.sort(key=lambda r: (-r['sales'], -r['plat'], r['dow'], r['hour']))
    return rows[:limit]


def next_slot(windows, now):
    """Soonest strictly-future (weekday, hour) cell from `windows`, as dow/hour/label."""
    best = None
    for w in windows:
        days = (w['dow'] - now.weekday()) % 7
        cand = (now + timedelta(days=days)).replace(hour=w['hour'], minute=0,
                                                    second=0, microsecond=0)
        if cand <= now:
            cand += timedelta(days=7)
        if best is None or cand < best[0]:
            best = (cand, w)
    if best is None:
        return None
    cand, w = best
    mins = (cand - now).total_seconds() / 60.0
    return {'dow': w['dow'], 'hour': w['hour'],
            'label': '%s %02d:00 (%s)' % (DOW[w['dow']], w['hour'], fmt_delta(mins))}


def fmt_delta(mins):
    if mins < 60:
        return 'in %dm' % max(1, int(round(mins)))
    if mins < 2880:
        return 'in %dh' % int(round(mins / 60.0))
    return 'in %.1fd' % (mins / 1440.0)


def plural(n, word='sale'):
    return '%d %s' % (n, word if n == 1 else word + 's')


def decide(now, hours, windows, top_n=TOP_HOURS, min_sales=MIN_HOUR_SALES):
    """SELL_NOW only when the current local hour is a top-`top_n` hour WITH sample behind
    it; otherwise HOLD plus the next top window. (verdict, reason, next_window)."""
    ranked = rank_hours(hours)
    top = [r for r in ranked if r['sales'] > 0][:top_n]
    current = hours[now.hour]
    tzab = now.tzname() or ''
    slot = next_slot(windows, now)
    now_txt = '%02d:00 %s' % (now.hour, tzab)
    top_txt = ', '.join('%02d:00' % r['hour'] for r in top) or 'none'
    if any(r['hour'] == now.hour for r in top) and current['sales'] >= min_sales:
        verdict = 'SELL_NOW'
        reason = ('%s is a top-%d sale hour (%s, %sp in sample) - list everything now'
                  % (now_txt, top_n, plural(current['sales']), current['plat']))
    else:
        verdict = 'HOLD'
        reason = ('%s has %s in sample; top hours %s; next window %s'
                  % (now_txt, plural(current['sales']), top_txt,
                     slot['label'] if slot else 'unknown'))
    return verdict, reason, slot


def kind_rows(kind_hours, min_sales=MIN_KIND_SALES):
    """Per-kind totals + best hours. Kinds below `min_sales` carry a thin-sample note."""
    rows = []
    for kind, hours in kind_hours.items():
        hour_list = hour_rows(hours)
        total = sum(r['sales'] for r in hour_list)
        row = {'sales': total, 'plat': round(sum(r['plat'] for r in hour_list), 2),
               'best_hours': [r for r in rank_hours(hour_list) if r['sales'] > 0][:KIND_TOP_HOURS]}
        if total < min_sales:
            row['note'] = 'thin sample (%s) - hours are a hint only' % plural(total)
        rows.append((kind, row))
    rows.sort(key=lambda kv: (-kv[1]['sales'], kv[0]))
    return dict(rows)


def sample_block(events, hours, weekdays, span_days, dates, kind_hours):
    live_hours = sum(1 for r in hours if r['sales'])
    live_dows = sum(1 for r in weekdays if r['sales'])
    missing = [k for k in WATCH_KINDS if k not in kind_hours]
    parts = ['%d sales over %d active day(s) in a %sd window' % (len(events), len(dates), span_days),
             '%d/24 hours and %d/7 weekdays have sample, so 1-2 sale cells are noise'
             % (live_hours, live_dows)]
    if len(events) < THIN_SAMPLE:
        parts.append('thin sample - treat windows as hints, not rules')
    if missing:
        parts.append('no sample for ' + '/'.join(missing))
    return {'sales_total': len(events), 'span_days': span_days, 'active_days': len(dates),
            'first_sale': dates[0].isoformat(), 'last_sale': dates[-1].isoformat(),
            'note': '; '.join(parts) + '.'}


def build(events, tz, now_ts, index=None, top=TOP_HOURS, min_sales=MIN_HOUR_SALES):
    """The full data/sell_timing.json document."""
    now = datetime.fromtimestamp(now_ts, tz)
    b = bucket(events, tz, index)
    hours, weekdays = hour_rows(b['hours']), weekday_rows(b['weekdays'])
    windows = best_windows(b['cells'])
    verdict, reason, slot = decide(now, hours, windows, top, min_sales)
    dates = local_dates(events, tz)
    span = round((max(e['ts'] for e in events) - min(e['ts'] for e in events)) / 86400.0, 1)
    return {
        'generated': now_ts,
        'generated_local': now.strftime('%Y-%m-%d %H:%M'),
        'tz': TZ_NAME,
        'hours': hours,
        'weekdays': weekdays,
        'best_windows': windows,
        'verdict': verdict,
        'verdict_reason': reason,
        'next_window': slot,
        'by_kind': kind_rows(b['kind_hours']),
        'sample': sample_block(events, hours, weekdays, span, dates, b['kind_hours']),
    }


# ------------------------------------------------------------------ cli

def selftest():
    """Offline fixture checks: fixed UTC+10 clock, synthetic sales, no file or network IO."""
    tz = timezone(timedelta(hours=TZ_FALLBACK_HOURS))
    checks = []

    def check(name, got, want):
        if got != want:
            raise AssertionError('%s: got %r want %r' % (name, got, want))
        checks.append(name)

    def ts(y, mo, d, h, mi=0):
        return int(datetime(y, mo, d, h, mi, tzinfo=tz).timestamp())

    events = ([{'ts': ts(2026, 9, 21, 2, i), 'kind': 'sale', 'name': 'Octavia Prime Chassis Blueprint',
                'total': 10} for i in range(5)]                       # Mon 02:00 x5
              + [{'ts': ts(2026, 9, 21, 9), 'kind': 'sale', 'name': 'Galvanized Chamber', 'total': 40},
                 {'ts': ts(2026, 9, 21, 9), 'kind': 'sale', 'name': 'Arcane Energize', 'total': 120},
                 {'ts': ts(2026, 9, 22, 20), 'kind': 'sale', 'name': 'Axi A1 Relic', 'total': 8},
                 {'ts': ts(2026, 9, 23, 5), 'kind': 'purchase', 'name': 'X', 'total': 99},
                 {'ts': ts(2026, 9, 23, 5), 'kind': 'note', 'name': 'Y'}])

    check('trade_events filters to sales with ts', len(trade_events(events)), 8)
    b = bucket(trade_events(events), tz)
    check('hour 2 tally', b['hours'][2], [5, 50])
    check('hour 9 tally', b['hours'][9], [2, 160])
    check('hour 20 tally', b['hours'][20], [1, 8])
    check('weekday Mon tally', b['weekdays'][0], [7, 210])
    check('cell (Mon, 2)', b['cells'][(0, 2)], [5, 50])

    rows = hour_rows(b['hours'])
    check('rank_hours top 3', [r['hour'] for r in rank_hours(rows)[:3]], [2, 9, 20])
    windows = best_windows(b['cells'])
    check('best_windows top 3', [(w['dow'], w['hour']) for w in windows[:3]], [(0, 2), (0, 9), (1, 20)])

    verdict, reason, slot = decide(datetime(2026, 9, 21, 2, 15, tzinfo=tz), rows, windows)
    check('verdict in a fat top hour', verdict, 'SELL_NOW')
    if 'top-3 sale hour (5 sales, 50p in sample)' not in reason:
        raise AssertionError('SELL_NOW reason missing the numbers: %s' % reason)
    verdict, reason, slot = decide(datetime(2026, 9, 22, 20, 30, tzinfo=tz), rows, windows)
    check('verdict in a thin top hour', verdict, 'HOLD')
    if 'top hours 02:00, 09:00, 20:00' not in reason:
        raise AssertionError('HOLD reason missing top hours: %s' % reason)
    check('HOLD next window rolls past the current slot', (slot['dow'], slot['hour']), (0, 2))
    check('next window label', slot['label'], 'Mon 02:00 (in 5.2d)')
    check('zero-sample hours stay out of the top list',
          decide(datetime(2026, 9, 23, 5, 0, tzinfo=tz), rows, windows)[1].split('top hours ')[1]
          .startswith('02:00, 09:00, 20:00'), True)
    check('next window from a fresh day', next_slot(windows, datetime(2026, 9, 22, 10, 0, tzinfo=tz))['label'],
          'Tue 20:00 (in 10h)')

    kinds = kind_rows(b['kind_hours'])
    check('name-rule kinds', sorted(kinds), ['arcane', 'other', 'prime_part', 'relic'])
    check('prime_part row', (kinds['prime_part']['sales'], kinds['prime_part']['plat']), (5, 50))
    check('thin kind note', kinds['relic']['note'].startswith('thin sample (1 sale)'), True)
    check('cat_of chain', [cat_of(t) for t in (['relic'], ['mod'], ['arcane_enhancement'],
                                               ['prime', 'component'], ['prime', 'blueprint'],
                                               ['prime', 'set'], [])],
          ['relic', 'mod', 'arcane', 'prime_part', 'prime_bp', 'prime_set', 'other'])
    check('name_kind fallback', [name_kind(n) for n in ('Axi A1 Relic', 'Arcane Energize',
                                                        'Octavia Prime Chassis Blueprint',
                                                        'Wukong Prime Blueprint', 'Pathocyst Blade')],
          ['relic', 'arcane', 'prime_part', 'prime_bp', 'other'])

    doc = build(trade_events(events), tz, ts(2026, 9, 22, 20, 30))
    check('build verdict', doc['verdict'], 'HOLD')
    check('build hour rows', len(doc['hours']), 24)
    check('build weekday rows', len(doc['weekdays']), 7)
    check('build sample', (doc['sample']['sales_total'], doc['sample']['active_days']), (8, 2))
    check('build tags override name rules',
          build(trade_events(events), tz, ts(2026, 9, 22, 20, 30),
                index={'Galvanized Chamber': {'mod'}})['by_kind']['mod']['sales'], 1)
    check('tz name in doc', doc['tz'], 'Australia/Melbourne')

    print('selftest OK - %d checks (fixed UTC+10 fixture, no files, no network)' % len(checks))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='Sell-timing score: when this account actually sells')
    ap.add_argument('--root', default=ROOT, help='repo root holding data/ (default: repo)')
    ap.add_argument('--now', default=None, help='override now: epoch seconds or ISO timestamp')
    ap.add_argument('--top', type=int, default=TOP_HOURS, help='hours that can trigger SELL_NOW')
    ap.add_argument('--min-sales', type=int, default=MIN_HOUR_SALES,
                    help='sample a top hour needs before it fires SELL_NOW')
    ap.add_argument('--selftest', action='store_true', help='run the offline fixture checks and exit')
    args = ap.parse_args(argv[1:] if argv else None)
    if args.selftest:
        return selftest()

    data = os.path.join(os.path.abspath(args.root), 'data')
    tz = local_tz()
    now_ts = parse_now(args.now, tz)
    events = trade_events(jload(os.path.join(data, 'trade_log.json'), []))
    if not events:
        print('no sale history yet (trade_log.json has no sale events)')
        return 1

    doc = build(events, tz, now_ts, tags_index(data), args.top, args.min_sales)
    jdump(os.path.join(data, OUT_NAME), doc)

    s = doc['sample']
    hot = [h for h in rank_hours(doc['hours']) if h['sales'] > 0][:args.top]
    print('sell timing: %d sales / %sp over %s -> %s (%d active days in %sd) | tz %s'
          % (s['sales_total'], sum(h['plat'] for h in doc['hours']), s['first_sale'],
             s['last_sale'], s['active_days'], s['span_days'], doc['tz']))
    print('top hours: ' + ' | '.join('%02d:00 %s %sp' % (h['hour'], plural(h['sales']), h['plat'])
                                     for h in hot))
    print('best windows: ' + ' | '.join('%s %02d:00 %s' % (DOW[w['dow']], w['hour'], plural(w['sales']))
                                        for w in doc['best_windows']))
    print('kinds: ' + ' | '.join('%s %s' % (k, plural(v['sales'])) for k, v in doc['by_kind'].items()))
    print('verdict: %s - %s' % (doc['verdict'], doc['verdict_reason']))
    print('wrote data/%s' % OUT_NAME)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
