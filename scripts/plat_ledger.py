"""Platinum ledger: what the trade log explains, and what the game itself took out.

Inputs:  data/plat_history.json  (platinum balance readings: AlecaFrame daily points plus
                                  tracker heartbeats from scripts/snapshot_plat.py)
         data/trade_log.json     (sale/purchase/note events = player-to-player trades,
                                  imported from the AlecaFrame export)
Optional probes - reported, never invented around:
  --export PATH   AlecaFrame stats export: inventory of every top-level array/object plus
                  its daily plat/credits points merged in as extra balance readings
  --ee-log PATH   Warframe EE.log: probe for market/rush purchase lines. Nothing is parsed
                  unless a stable item+platinum line format exists (see sources.ee_log);
                  EE.log never contributes to the totals.
Output:  data/plat_ledger.json

Method (every number is either exact or explicitly labelled inferred):
  * one balance anchor per Australia/Melbourne day = that day's most recent reading
  * delta      = anchor plat - previous anchor plat                     (exact: readings)
  * trades_net = sale totals - purchase totals of trade_log events with
                 previous_anchor_ts < ts <= anchor_ts                    (exact: trade_log;
                 'note' events carry no platinum side and are counted in sources only)
  * other_net  = delta - trades_net  -> gifts, refunds, in-game market spend, real-money
                 platinum purchases: a RESIDUAL, not a measurement
  * inferred_spend = max(0, -other_net) -> platinum that looks like it left the account
                 outside player trades: INFERRED, never an exact figure
A row is a balance window, not a day of play: the imported readings are sparse (gaps run
for weeks), so rows carry window_from/window_to/window_days and days without a reading are
counted in totals.gap_days rather than listed. Newest day first. Rows with no movement at
all (delta, trades_net and other_net all zero) are dropped unless --all is given.

Usage: python scripts/plat_ledger.py [--root DIR] [--last N] [--tolerance P]
                                     [--export PATH] [--ee-log PATH] [--all] [--selftest]
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:                     # pragma: no cover - Python without zoneinfo
    ZoneInfo = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_NAME = 'plat_ledger.json'
TZ_NAME = 'Australia/Melbourne'
TZ_FALLBACK_HOURS = 10                  # UTC+10 (AEST) when no tz database is installed
TRADE_KINDS = ('sale', 'purchase')      # kinds that move platinum
DEFAULT_LAST = 400
DEFAULT_TOLERANCE = 0.0                 # platinum are integers: exact unless asked otherwise
EE_DEFAULT_PATH = os.path.expandvars(r'%LOCALAPPDATA%\Warframe\EE.log')
EE_TAIL_BYTES = 2 * 1024 * 1024         # probe the newest ~2 MB
EE_KEYWORDS = ('purchase', 'storeitems', 'platinum', 'rush', 'market')
EE_SAMPLE_LINES = 3
EE_STABLE_MIN = 3                       # same-shape item+plat lines needed before parsing
# A stable purchase line would need BOTH a purchase verb AND a platinum amount on one line.
# These two shapes are the gate; today's EE.log matches neither (0 lines), so nothing parses.
EE_PURCHASE_RE = re.compile(r'(?i)\b(?:purchased?|bought)\b[^\n]{0,120}?\bplat(?:inum)?\b'
                            r'[^\n]{0,80}?\b(\d[\d,]{0,9})\b')
EE_SPEND_RE = re.compile(r'(?i)\bplat(?:inum)?\b[^\n]{0,80}?\b(\d[\d,]{0,9})\b'
                         r'[^\n]{0,120}?\b(?:purchased?|bought|rush(?:ed)?)\b')
# Reporting-only buckets for the keyword hits (heuristics, used for the format note).
EE_BUCKETS = (
    ('ui_dialog', re.compile(r'(?i)DetailedPurchaseDialog|PurchaseInProgress|PurchaseCelebration'
                             r'|Dialog::CreateOkCancel|\.swf')),
    ('entity_noise', re.compile(r'(?i)Reusing id=|previously had ')),
    ('asset_load', re.compile(r'(?i)Spot-building|Spot-loading|ResourceLoader|Resloader'
                              r'|BuildLoadOut|\bPlatform\b|platform')),
)


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
        json.dump(obj, fh, indent=1, ensure_ascii=False)
    os.replace(path + '.tmp', path)


def local_tz():
    """Australia/Melbourne when the tz database is available, else a fixed UTC+10."""
    if ZoneInfo is not None:
        try:
            return ZoneInfo(TZ_NAME)
        except Exception:
            pass
    return timezone(timedelta(hours=TZ_FALLBACK_HOURS))


def local_date(ts, tz):
    return datetime.fromtimestamp(int(ts), tz).strftime('%Y-%m-%d')


def local_stamp(ts, tz):
    return datetime.fromtimestamp(int(ts), tz).strftime('%Y-%m-%d %H:%M')


def day_gap(date_a, date_b):
    """Whole days from date_a to date_b (ISO dates), 0 when equal."""
    fmt = '%Y-%m-%d'
    return (datetime.strptime(date_b, fmt) - datetime.strptime(date_a, fmt)).days


# ------------------------------------------------------------------ inputs

def norm_points(points, tz, default_src='tracker'):
    """Normalise plat_history readings into [{ts, plat, credits, src}] sorted by ts."""
    out = []
    for p in points or []:
        if not isinstance(p, dict):
            continue
        try:
            ts = int(p['ts'])
        except (KeyError, TypeError, ValueError):
            continue
        if p.get('plat') is None:
            continue
        out.append(dict(ts=ts, plat=int(p['plat']), credits=p.get('credits'),
                        src=p.get('src') or default_src))
    out.sort(key=lambda p: p['ts'])
    return out


def reading_conflicts(readings):
    """Timestamps carrying two different balances = a data glitch worth flagging."""
    seen, bad = {}, []
    for r in readings:
        if r['ts'] in seen and seen[r['ts']] != r['plat']:
            bad.append(dict(ts=r['ts'], plat=seen[r['ts']], other=r['plat']))
        seen[r['ts']] = r['plat']
    return bad


def trade_totals(events):
    """Exact totals over the whole trade log (all events, every kind)."""
    earned = sum(int(e.get('total') or 0) for e in events if e.get('kind') == 'sale')
    spent = sum(int(e.get('total') or 0) for e in events if e.get('kind') == 'purchase')
    kinds = {}
    for e in events:
        k = e.get('kind') or '?'
        kinds[k] = kinds.get(k, 0) + 1
    return dict(events=len(events), kinds=kinds, earned=earned, spent=spent, net=earned - spent)


def balance_anchors(readings, tz):
    """One anchor per local day (its most recent reading). Sorted by ts."""
    by_day = {}
    for r in readings:
        by_day.setdefault(local_date(r['ts'], tz), []).append(r)
    anchors = []
    for date in sorted(by_day):
        rows = sorted(by_day[date], key=lambda r: r['ts'])
        last = rows[-1]
        plats = sorted({r['plat'] for r in rows})
        anchors.append(dict(
            date=date, ts=last['ts'], plat=last['plat'], credits=last.get('credits'),
            readings=len(rows), sources=sorted({r['src'] for r in rows}),
            first_ts=rows[0]['ts'], first_plat=rows[0]['plat'],
            intraday_swing=(max(plats) - min(plats)),
        ))
    return anchors


def window_trades(events, lo, hi):
    """(count, earned, spent) for sale/purchase events with lo < ts <= hi."""
    count = earned = spent = 0
    for e in events:
        ts = e.get('ts')
        if ts is None or not (lo < ts <= hi):
            continue
        if e.get('kind') == 'sale':
            earned += int(e.get('total') or 0)
            count += 1
        elif e.get('kind') == 'purchase':
            spent += int(e.get('total') or 0)
            count += 1
    return count, earned, spent


def window_rows(anchors, events, tz, include_zero=False):
    """Balance window per reading day: delta, trades_net, other_net, inferred_spend."""
    rows = []
    for i in range(1, len(anchors)):
        prev, cur = anchors[i - 1], anchors[i]
        count, earned, spent = window_trades(events, prev['ts'], cur['ts'])
        trades_net = earned - spent
        delta = cur['plat'] - prev['plat']
        other = delta - trades_net
        rows.append(dict(
            date=cur['date'], balance=cur['plat'], delta=delta,
            trades_net=trades_net, other_net=other,
            inferred_spend=max(0, -other),
            window_from=prev['date'], window_to=cur['date'],
            window_days=day_gap(prev['date'], cur['date']),
            plat_from=prev['plat'], trades=count, earned=earned, spent=spent,
            readings=cur['readings'], intraday_swing=cur['intraday_swing'],
            sources=cur['sources'],
        ))
    rows.sort(key=lambda r: r['date'], reverse=True)
    shown = rows if include_zero else [r for r in rows
                                      if r['delta'] or r['trades_net'] or r['other_net']]
    return shown, rows


# ------------------------------------------------------------------ reconciliation

def check_reconciliation(all_rows, anchors, events, tolerance, readings=None):
    """Independent checks over the whole window set: every failure is reported, not hidden.

    * window_identity  - delta == trades_net + other_net, recomputed from the rows
    * balance_chain    - first anchor + sum(delta) == last anchor
    * trade_coverage   - every trade event inside the anchor span lands in exactly one
                         window, and the windowed net equals the independently summed net
    * day_uniqueness   - window days unique and newest first
    * reading_integrity- no raw reading timestamp carrying two different balances
    """
    checks, failures = {}, []

    def add(name, ok, detail):
        checks[name] = dict(ok=bool(ok), detail=detail)
        if not ok:
            failures.append(name)

    worst = 0.0
    for r in all_rows:
        worst = max(worst, abs(r['delta'] - (r['trades_net'] + r['other_net'])))
    add('window_identity', worst <= tolerance,
        'max |delta - (trades_net + other_net)| = %gp' % worst)

    if anchors:
        chain = sum(r['delta'] for r in all_rows)
        drift = abs((anchors[-1]['plat'] - anchors[0]['plat']) - chain)
        add('balance_chain', drift <= tolerance,
            'first balance %sp -> last %sp, window deltas sum to %sp (drift %sp)'
            % (anchors[0]['plat'], anchors[-1]['plat'], chain, drift))
    else:
        add('balance_chain', False, 'no balance anchors')

    spans = [(anchors[i - 1]['ts'], anchors[i]['ts']) for i in range(1, len(anchors))]
    covered_net, covered_events, extra = 0, 0, 0
    for e in events:
        ts, kind = e.get('ts'), e.get('kind')
        if ts is None or kind not in TRADE_KINDS:
            continue
        hits = sum(1 for lo, hi in spans if lo < ts <= hi)
        extra += 1 if hits > 1 else 0
        if hits:
            covered_events += 1
            covered_net += int(e.get('total') or 0) * (1 if kind == 'sale' else -1)
    rowed_net = sum(r['trades_net'] for r in all_rows)
    rowed_events = sum(r['trades'] for r in all_rows)
    add('trade_coverage',
        extra == 0 and covered_events == rowed_events and abs(covered_net - rowed_net) <= tolerance,
        '%d trade events inside the covered span, %d rows tallied them (%d counted twice), '
        'net %sp vs %sp' % (covered_events, rowed_events, extra, covered_net, rowed_net))

    dates = [r['date'] for r in all_rows]
    add('day_uniqueness', len(dates) == len(set(dates)) and dates == sorted(dates, reverse=True),
        '%d window days, %d unique, newest first: %s'
        % (len(dates), len(set(dates)), dates == sorted(dates, reverse=True)))

    conflicts = reading_conflicts(readings if readings is not None
                                 else [dict(ts=a['ts'], plat=a['plat']) for a in anchors])
    add('reading_integrity', not conflicts,
        'no duplicate timestamps' if not conflicts
        else '%d timestamp(s) carry two balances: %s' % (len(conflicts), conflicts[:3]))

    if not failures:
        note = ('reconciles: %d/%d checks pass at tolerance %gp - every balance delta is '
                'fully explained by trade_log plus the inferred non-trade residual'
                % (len(checks), len(checks), tolerance))
    else:
        note = ('NOT RECONCILED: %d of %d checks failed (%s) - %s'
                % (len(failures), len(checks), ', '.join(failures),
                   '; '.join('%s: %s' % (n, checks[n]['detail']) for n in failures)))
    return dict(reconciles=not failures, tolerance=tolerance, note=note,
                checks=checks, failures=failures)


# ------------------------------------------------------------------ probes

def ee_bucket(line):
    """Reporting-only classifier for a keyword-hit line (heuristic, no meaning for totals)."""
    for bucket, rx in EE_BUCKETS:
        if rx.search(line):
            return bucket
    return 'other'


def probe_ee_log(path, tail_bytes=EE_TAIL_BYTES):
    """Probe a Warframe EE.log for purchase-like lines. Read-only; never invents numbers.

    Counts every keyword hit in the whole file and separates the newest ``tail_bytes``
    (where live activity lives), classifies the hits into UI-dialog / entity-noise /
    asset-load buckets, and only reports parsed records when a STABLE item+platinum line
    shape repeats at least EE_STABLE_MIN times. EE.log never feeds the ledger totals.
    """
    out = dict(found=False, path=str(path or ''), size=None, tail_bytes=tail_bytes,
               parsed=False, keywords={k: 0 for k in EE_KEYWORDS},
               tail_keywords={k: 0 for k in EE_KEYWORDS},
               buckets={}, tail_buckets={}, samples={}, candidates=0, records=[],
               format_note='not probed (pass --ee-log PATH)', coverage='none')
    if not path:
        out['format_note'] = 'not probed (pass --ee-log PATH)'
        return out
    if not os.path.exists(path):
        out['format_note'] = 'no EE.log at %s - nothing to parse' % path
        return out
    out['found'] = True
    size = os.path.getsize(path)
    out['size'] = size
    tail_start = max(0, size - tail_bytes)

    records, shapes = [], {}
    pos = 0
    with open(path, 'rb') as fh:
        for raw in fh:
            line = raw.decode('utf-8', 'replace').rstrip('\r\n')
            end = pos + len(raw)
            in_tail = end > tail_start            # the line reaches into the tail window
            pos = end
            low = line.lower()
            hit = False
            for kw in EE_KEYWORDS:
                if kw in low:
                    out['keywords'][kw] += 1
                    hit = True
                    if in_tail:
                        out['tail_keywords'][kw] += 1
                    got = out['samples'].setdefault(kw, [])
                    got.append(line[:200])
                    del got[:-EE_SAMPLE_LINES]          # keep the newest samples
            if hit:
                bucket = ee_bucket(line)
                out['buckets'][bucket] = out['buckets'].get(bucket, 0) + 1
                if in_tail:
                    out['tail_buckets'][bucket] = out['tail_buckets'].get(bucket, 0) + 1
            for rx in (EE_PURCHASE_RE, EE_SPEND_RE):
                m = rx.search(line)
                if not m:
                    continue
                shape = re.sub(r'\d+', '#', line)[:120]
                shapes[shape] = shapes.get(shape, 0) + 1
                records.append(dict(plat=int(m.group(1).replace(',', '')), line=line[:200],
                                    shape=shape, at=pos))
                break
    out['candidates'] = len(records)
    hits_total = max(out['buckets'].values()) if out['buckets'] else 0
    stable = bool(shapes) and max(shapes.values()) >= EE_STABLE_MIN
    if stable:
        out['parsed'] = True
        out['records'] = [r for r in records if shapes[r['shape']] >= EE_STABLE_MIN]
        out['format_note'] = ('stable item+platinum line shape found (%d lines, e.g. %r) - '
                              'parsed %d record(s), kept separate as source "ee_log"; totals '
                              'still come from plat_history'
                              % (max(shapes.values()), out['records'][0]['line'][:120],
                                 len(out['records'])))
    else:
        out['format_note'] = (
            'no stable purchase format: %s keyword hit line(s) file-wide (%s in the newest '
            '%.1f MB), %d line(s) carry a purchase verb + platinum amount (parsing needs %d '
            'same-shape lines). Hit mix file-wide: %s | tail: %s'
            % (sum(out['keywords'].values()),
               sum(out['tail_keywords'].values()), tail_bytes / 1048576.0,
               out['candidates'], EE_STABLE_MIN,
               ', '.join('%s=%d' % (b, out['buckets'].get(b, 0)) for b in
                         [n for n, _ in EE_BUCKETS] + ['other']),
               ', '.join('%s=%d' % (b, out['tail_buckets'].get(b, 0)) for b in
                         [n for n, _ in EE_BUCKETS] + ['other'])))
        if hits_total:
            out['format_note'] += ' (keyword counts: %s)' % ', '.join(
                '%s=%d' % (k, out['keywords'][k]) for k in EE_KEYWORDS)
    out['coverage'] = ('0 of the ledger totals come from EE.log; in-game spend stays the '
                       'plat_history residual (inferred)' if not out['parsed'] else
                       '%d parsed line(s) reported separately; totals still use the '
                       'plat_history residual (inferred)' % len(out['records']))
    return out


def export_inventory(path, trade_tot):
    """Inventory of the AlecaFrame export: every top-level array/object + usable daily points."""
    exp = jload(path)
    if not isinstance(exp, dict):
        return [], [], [], 'export not readable: %s' % (path or '(none given)')
    arrays, scalars, points = [], [], []
    for key, val in exp.items():
        if isinstance(val, list):
            fields = sorted({k for row in val[:200] if isinstance(row, dict) for k in row})
            entry = dict(name=key, type='list', rows=len(val), fields=fields,
                         beyond_known=key not in ('trades', 'generalDataPoints'))
            if key == 'generalDataPoints':
                points = val
                entry['note'] = ('daily plat/credits(+endo/ducats/aya/relics/mr) points; '
                                 'used as extra balance readings')
            elif key == 'trades':
                plat_sum = sum(int(t.get('totalPlat') or 0) for t in val)
                both = trade_tot['earned'] + trade_tot['spent']
                entry['note'] = ('player trades, totalPlat %sp vs trade_log earned+spent %sp%s'
                                 % (plat_sum, both,
                                    ' (match)' if plat_sum == both
                                    else ' (DIFFERS - trade_log may be stale)'))
            else:
                entry['note'] = 'unrecognised array - reported, not imported'
            arrays.append(entry)
        elif isinstance(val, dict):
            arrays.append(dict(name=key, type='object', rows=len(val),
                               fields=sorted(val)[:20], beyond_known=True,
                               note='unrecognised object - reported, not imported'))
        else:
            scalars.append(dict(name=key, value=val))
    note = ('arrays beyond trades[]/generalDataPoints[]: %s'
            % (', '.join(a['name'] for a in arrays if a['beyond_known']) or 'none')
            if arrays else 'export has no arrays')
    return arrays, scalars, points, note


# ------------------------------------------------------------------ build

def build(readings, events, tz, tolerance=DEFAULT_TOLERANCE, include_zero=False,
          last=DEFAULT_LAST, export=None, export_points=(), export_note='', ee=None):
    conflicts = reading_conflicts(readings)
    anchors = balance_anchors(readings, tz)
    shown, all_rows = window_rows(anchors, events, tz, include_zero=include_zero)
    tot_log = trade_totals(events)

    covered_lo = anchors[0]['ts'] if anchors else 0
    covered_hi = anchors[-1]['ts'] if anchors else 0
    outside = [e for e in events
               if e.get('kind') in TRADE_KINDS and e.get('ts') is not None
               and not (covered_lo < e['ts'] <= covered_hi)]
    outside_net = sum(int(e.get('total') or 0) * (1 if e.get('kind') == 'sale' else -1)
                      for e in outside)
    covered_net = tot_log['net'] - outside_net

    self_check = check_reconciliation(all_rows, anchors, events, tolerance, readings)
    last_balance = anchors[-1]['plat'] if anchors else None

    totals = dict(
        trades_earned_plat=tot_log['earned'], trades_spent_plat=tot_log['spent'],
        trades_net_plat=tot_log['net'],
        in_game_spent_inferred_plat=sum(r['inferred_spend'] for r in all_rows),
        other_net_plat=sum(r['other_net'] for r in all_rows),
        current_balance=last_balance,
        first_balance=anchors[0]['plat'] if anchors else None,
        balance_change_plat=(anchors[-1]['plat'] - anchors[0]['plat']) if anchors else None,
        readings=len(readings), reading_days=len(anchors), windows=len(all_rows),
        windows_shown=min(last, len(shown)), windows_without_movement=sum(
            1 for r in all_rows if not (r['delta'] or r['trades_net'] or r['other_net'])),
        covered_from=anchors[0]['date'] if anchors else None,
        covered_to=anchors[-1]['date'] if anchors else None,
        covered_days=(day_gap(anchors[0]['date'], anchors[-1]['date']) + 1) if anchors else 0,
        gap_days=max(0, (day_gap(anchors[0]['date'], anchors[-1]['date']) + 1 - len(anchors)))
        if anchors else 0,
        trades_net_covered_plat=covered_net,
        trades_net_outside_windows_plat=outside_net,
        trades_outside_windows=len(outside),
        inferred_windows=sum(1 for r in all_rows if r['inferred_spend'] > 0),
    )

    notes = [
        'other_net / inferred_spend are a RESIDUAL (balance delta minus player-trade flow): '
        'they mix in-game market spend, rushing, gifts, refunds, real-money platinum and any '
        'trade the log missed. Treat them as a lead, never as an exact figure.',
        'Balance readings are sparse imported snapshots, so a row is a window between two '
        'readings (window_from/window_to/window_days), not a calendar day of play.',
        'Day bucketing uses %s (fixed UTC+%d fallback); day boundaries can shift by an hour '
        'across DST in the real tz database.'
        % (TZ_NAME, TZ_FALLBACK_HOURS),
        'trades_net counts sale/purchase events only; "note" events (swaps, no platinum side) '
        'are ignored here but counted in sources.trade_log.',
        'self_check.tolerance is %gp: platinum are integers, so any mismatch is a real one.'
        % tolerance,
        'covered windows run %s -> %s; %d trade event(s) netting %sp fall outside them and are '
        'reported in totals, not in rows.'
        % (totals['covered_from'], totals['covered_to'], len(outside), outside_net),
        'trades_earned/spent_plat cover the WHOLE trade log (all %d events, %d outside the '
        'covered windows).' % (tot_log['events'], len(outside)),
    ]
    if conflicts:
        notes.insert(0, 'DATA GLITCH: %d timestamp(s) carry two different balances (%s) - the '
                        'newer value wins, self_check flags it.'
                    % (len(conflicts), conflicts[0]))
    if not self_check['reconciles']:
        notes.insert(0, 'RECONCILIATION FAILED: %s' % self_check['note'])
    if export:
        notes.append('AlecaFrame export: %s' % (export_note or 'array inventory only'))
        if export_points:
            notes.append('AlecaFrame export supplied %d extra balance reading(s) tagged '
                         'source "export".' % len(export_points))
    if ee:
        if ee.get('parsed'):
            notes.append('EE.log: %d purchase line(s) matched a stable item+platinum shape and '
                         'are reported in sources.ee_log.records; they are NOT added to the '
                         'totals.' % len(ee.get('records') or []))
        elif ee.get('found'):
            notes.append('EE.log: %s' % ee['format_note'])
        else:
            notes.append('EE.log: %s' % ee.get('format_note', 'not probed'))

    doc = dict(
        generated=local_stamp(time.time(), tz),
        sources=dict(
            plat_history=dict(
                path='data/plat_history.json', readings=len(readings),
                by_source={s: sum(1 for r in readings if r['src'] == s)
                           for s in sorted({r['src'] for r in readings})},
                first_at=local_stamp(readings[0]['ts'], tz) if readings else None,
                last_at=local_stamp(readings[-1]['ts'], tz) if readings else None,
                duplicate_ts_conflicts=conflicts,
            ),
            trade_log=dict(
                path='data/trade_log.json', events=tot_log['events'], kinds=tot_log['kinds'],
                earned_plat=tot_log['earned'], spent_plat=tot_log['spent'],
                net_plat=tot_log['net'],
                first_at=local_stamp(min(e['ts'] for e in events), tz) if events else None,
                last_at=local_stamp(max(e['ts'] for e in events), tz) if events else None,
            ),
            export_arrays=export or [],
            export_note=(export_note or 'export probed, no arrays') if export
            else 'export not probed (pass --export PATH)',
            ee_log=ee or probe_ee_log(''),
        ),
        totals=totals, days=shown[:last], shown=min(last, len(shown)), all_days=include_zero,
        self_check=self_check, notes=notes,
    )
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Platinum ledger: balance deltas reconciled against player trades')
    ap.add_argument('--root', default=ROOT, help='repo root holding data/ (default: repo)')
    ap.add_argument('--last', type=int, default=DEFAULT_LAST, help='cap the listed days')
    ap.add_argument('--tolerance', type=float, default=DEFAULT_TOLERANCE,
                    help='platinum the reconciliation may drift before it fails (default 0)')
    ap.add_argument('--export', default=None, help='AlecaFrame stats export to inventory/merge')
    ap.add_argument('--ee-log', default=None, help='Warframe EE.log to probe (default: off)')
    ap.add_argument('--all', action='store_true',
                    help='also list windows with no movement at all')
    ap.add_argument('--selftest', action='store_true', help='run the offline fixture checks')
    args = ap.parse_args(argv[1:] if argv else None)
    if args.selftest:
        return selftest()

    data = os.path.join(os.path.abspath(args.root), 'data')
    tz = local_tz()
    readings = norm_points(jload(os.path.join(data, 'plat_history.json'), []), tz)
    events = [e for e in (jload(os.path.join(data, 'trade_log.json'), []) or [])
              if isinstance(e, dict)]
    if not readings:
        print('no platinum history yet (data/plat_history.json has no readings)')
        return 1
    if not events:
        print('note: data/trade_log.json is empty - every delta lands in other_net')

    export_arrays, _, export_points, export_note = [], [], [], 'export not probed'
    if args.export:
        export_arrays, scalars, export_points, export_note = export_inventory(
            args.export, trade_totals(events))
        if export_points:
            have = {r['ts'] for r in readings}
            merged = norm_points([dict(ts=int(datetime.fromisoformat(
                str(g['ts']).replace('Z', '+00:00')).timestamp()), plat=g.get('plat'),
                credits=g.get('credits'), src='export') for g in export_points
                if g.get('ts') and g.get('plat') is not None], tz)
            merged = [m for m in merged if m['ts'] not in have]
            readings = sorted(readings + merged, key=lambda r: r['ts'])
            export_note += '; merged %d new reading(s)' % len(merged)
            export_points = merged
    ee = probe_ee_log(args.ee_log) if args.ee_log else probe_ee_log('')

    doc = build(readings, events, tz, args.tolerance, args.all, args.last,
                export=export_arrays, export_points=export_points, export_note=export_note,
                ee=ee)
    jdump(os.path.join(data, OUT_NAME), doc)

    t = doc['totals']
    print('plat ledger: %d readings over %d day(s) %s -> %s | balance %sp -> %sp (%+dp)'
          % (t['readings'], t['reading_days'], t['covered_from'], t['covered_to'],
             t['first_balance'], t['current_balance'], t['balance_change_plat']))
    print('trades (whole log): earned %sp spent %sp net %+sp | in covered windows net %+sp, '
          '%d event(s) outside'
          % (t['trades_earned_plat'], t['trades_spent_plat'], t['trades_net_plat'],
             t['trades_net_covered_plat'], t['trades_outside_windows']))
    print('inferred in-game spend %sp across %d window(s) | other_net %+sp | gaps %d day(s) '
          'without a reading'
          % (t['in_game_spent_inferred_plat'], t['inferred_windows'], t['other_net_plat'],
             t['gap_days']))
    print('self_check: %s' % doc['self_check']['note'])
    if export_arrays:
        print('export: %s' % export_note)
    if ee['found']:
        print('ee_log: %s' % ee['format_note'])
    for r in doc['days'][:12]:
        print('%-10s bal %-6s delta %+6d trades_net %+6d other_net %+6d inferred %-5d '
              '(%d trades, %dd window)'
              % (r['date'], r['balance'], r['delta'], r['trades_net'], r['other_net'],
                 r['inferred_spend'], r['trades'], r['window_days']))
    print('wrote data/%s (%d of %d windows)' % (OUT_NAME, doc['shown'], t['windows']))
    return 0


# ------------------------------------------------------------------ selftest

def selftest():
    """Offline fixture checks - fixed UTC+10 clock, synthetic readings, no repo files."""
    tz = timezone(timedelta(hours=TZ_FALLBACK_HOURS))
    checks = []

    def check(name, got, want):
        if got != want:
            raise AssertionError('%s: got %r want %r' % (name, got, want))
        checks.append(name)

    def day(d, h=12, mi=0):
        return int(datetime(2026, 9, d, h, mi, tzinfo=tz).timestamp())

    def ev(ts, kind, total, name='X'):
        return dict(ts=ts, kind=kind, total=total, name=name)

    # --- window math: delta - trades_net = other_net, half-open window at both edges
    readings = norm_points([
        dict(ts=day(10), plat=1000),                                  # day 10 anchor
        dict(ts=day(11), plat=1200),                                  # +200, trades +200
        dict(ts=day(12, h=3), plat=1200),                             # heartbeat, no move
        dict(ts=day(12, h=20), plat=900),                             # day-12 anchor
        dict(ts=day(20), plat=800),                                   # -100, no trades at all
    ], tz)
    events = [ev(day(10), 'sale', 999),        # exactly at the previous anchor -> excluded
              ev(day(11, h=9), 'sale', 250),   # inside window 10 -> 11
              ev(day(11, h=10), 'purchase', 50),
              ev(day(11), 'sale', 999),        # exactly at the closing anchor -> included
              ev(day(12, h=10), 'purchase', 300),   # inside window 11 -> 12 (no sale side)
              ev(day(20, h=10), 'note', 0, 'swap')]  # notes never move platinum

    anchors = balance_anchors(readings, tz)
    check('anchors: one per local day, heartbeat collapses', [a['date'] for a in anchors],
          ['2026-09-10', '2026-09-11', '2026-09-12', '2026-09-20'])
    check('anchors: last reading of the day wins', [a['plat'] for a in anchors],
          [1000, 1200, 900, 800])
    check('anchors: readings counted per day', [a['readings'] for a in anchors], [1, 1, 2, 1])

    shown, all_rows = window_rows(anchors, events, tz)
    check('rows: one per window, newest first', [r['date'] for r in shown],
          ['2026-09-20', '2026-09-12', '2026-09-11'])
    row = {r['date']: r for r in all_rows}
    check('window 10->11: trade flow (boundary sale at the closing anchor counts)',
          (row['2026-09-11']['trades_net'], row['2026-09-11']['trades']), (1199, 3))
    check('window 10->11: identity holds', row['2026-09-11']['other_net'], 200 - 1199)
    check('window 11->12: trade spend fully explains the delta',
          (row['2026-09-12']['trades_net'], row['2026-09-12']['delta'],
           row['2026-09-12']['other_net'], row['2026-09-12']['inferred_spend']),
          (-300, -300, 0, 0))
    check('window 11->12: balance + delta', (row['2026-09-12']['balance'], row['2026-09-12']['delta']),
          (900, -300))
    check('intraday heartbeat move is anchored on the day, not double counted',
          (row['2026-09-12']['readings'], row['2026-09-12']['intraday_swing']), (2, 300))
    check('window 19->20: zero-trade window still listed with its movement',
          (row['2026-09-20']['trades'], row['2026-09-20']['other_net'],
           row['2026-09-20']['inferred_spend']), (0, -100, 100))
    check('window_days spans the reading gap', row['2026-09-20']['window_days'], 8)

    zero_rows = [dict(ts=day(1), plat=500), dict(ts=day(2), plat=500)]
    zsh, zall = window_rows(balance_anchors(norm_points(zero_rows, tz), tz), [], tz)
    check('no-movement window dropped by default', (len(zsh), len(zall)), (0, 1))
    zsh, _ = window_rows(balance_anchors(norm_points(zero_rows, tz), tz), [], tz, include_zero=True)
    check('--all keeps the no-movement window', len(zsh), 1)

    # --- reconciliation passes on clean fixtures
    ok = check_reconciliation(all_rows, anchors, events, 0.0)
    check('clean fixture reconciles', (ok['reconciles'], ok['failures']), (True, []))
    check('clean fixture runs every check', len(ok['checks']), 5)
    check('reading_integrity passes on clean readings', ok['checks']['reading_integrity']['ok'], True)

    # --- tolerance: a tampered row must FAIL and be named, not hidden
    tampered = [dict(all_rows[0], other_net=all_rows[0]['other_net'] + 10)] + list(all_rows[1:])
    bad = check_reconciliation(tampered, anchors, events, 0.0)
    check('tampered window fails reconciliation', (bad['reconciles'], bad['failures']),
          (False, ['window_identity']))
    check('failure note names the numbers', 'delta - (trades_net + other_net)' in bad['note'], True)
    loosened = check_reconciliation(tampered, anchors, events, 10.0)
    check('loose tolerance lets the same fixture pass', loosened['reconciles'], True)
    check('tolerance recorded in the verdict', loosened['tolerance'], 10.0)

    # --- duplicate timestamp glitch: end-to-end build must flag it
    glitch = norm_points([dict(ts=day(1), plat=500), dict(ts=day(2), plat=700),
                          dict(ts=day(2), plat=650), dict(ts=day(3), plat=650)], tz)
    doc = build(glitch, [ev(day(2, h=5), 'sale', 0)], tz)
    check('duplicate ts glitch does not reconcile', doc['self_check']['reconciles'], False)
    check('duplicate ts glitch is named', doc['self_check']['failures'], ['reading_integrity'])
    check('glitch is surfaced in notes', doc['notes'][0].startswith('RECONCILIATION FAILED'), True)
    check('later reading of the day wins on a glitch',
          [(r['date'], r['balance'], r['delta']) for r in doc['days']],
          [('2026-09-02', 650, 150)])
    check('glitch conflict reported in sources',
          len(doc['sources']['plat_history']['duplicate_ts_conflicts']), 1)

    # --- coverage: trades outside the covered span are reported, not silently dropped
    span_doc = build(norm_points([dict(ts=day(10), plat=100), dict(ts=day(11), plat=150)], tz),
                     [ev(day(11, h=1), 'sale', 50), ev(day(1), 'sale', 7)], tz)
    check('outside-span trade counted in totals',
          (span_doc['totals']['trades_net_covered_plat'],
           span_doc['totals']['trades_net_outside_windows_plat'],
           span_doc['totals']['trades_outside_windows']), (50, 7, 1))
    check('outside-span trade keeps its own note',
          any('fall outside them' in n for n in span_doc['notes']), True)
    check('whole-log totals stay whole-log',
          span_doc['totals']['trades_earned_plat'], 57)

    # --- doc contract
    check('doc keys', sorted(doc), ['all_days', 'days', 'generated', 'notes', 'self_check',
                                    'shown', 'sources', 'totals'])
    check('sources keys', sorted(doc['sources']), ['ee_log', 'export_arrays', 'export_note',
                                                   'plat_history', 'trade_log'])
    check('totals keys present', [k for k in ('trades_earned_plat', 'trades_spent_plat',
                                              'in_game_spent_inferred_plat', 'other_net_plat',
                                              'current_balance') if k in doc['totals']],
          ['trades_earned_plat', 'trades_spent_plat', 'in_game_spent_inferred_plat',
           'other_net_plat', 'current_balance'])
    check('day row keys', sorted(doc['days'][0]),
          ['balance', 'date', 'delta', 'earned', 'inferred_spend', 'intraday_swing',
           'other_net', 'plat_from', 'readings', 'sources', 'spent', 'trades', 'trades_net',
           'window_days', 'window_from', 'window_to'])

    # --- ee.log probe: real-format lines (dialog only, no price) must not be parsed
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, 'EE.log')
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write('1234.567 Script [Info]: ThemedDetailedPurchaseDialog.lua: DBG: HudVis 1\n'
                     '1234.568 Script [Info]: ThemedDetailedPurchaseDialog.lua: '
                     'PopulateInfo->/Lotus/Types/StoreItems/Packages/HeirloomPackVauban\n'
                     '12584.090 Net [Info]: Reusing id=15898, previously had RusherSuit\n'
                     '2345.678 Script [Info]: Trade.lua: DBG: HudVis 1\n')
        ee = probe_ee_log(p, tail_bytes=65536)
        check('ee probe finds the log', ee['found'], True)
        check('ee probe counts keyword hits', ee['keywords']['purchase'], 2)
        check('ee probe reports tail counts separately', ee['tail_keywords']['purchase'], 2)
        check('ee probe covers every keyword', sorted(ee['keywords']), sorted(EE_KEYWORDS))
        check('ee probe counts rush noise', ee['keywords']['rush'], 1)
        check('ee probe classifies dialog lines', ee['buckets']['ui_dialog'], 2)
        check('ee probe keeps the newest samples', len(ee['samples']['purchase']), 2)
        check('ee probe parses nothing without a price', (ee['parsed'], ee['records']),
              (False, []))
        check('ee probe explains why', 'no stable purchase format' in ee['format_note'], True)
        check('ee coverage stays out of the totals', ee['coverage'].startswith('0 of the ledger'),
              True)

        stable = os.path.join(tmp, 'EE2.log')
        with open(stable, 'w', encoding='utf-8') as fh:
            for n in (1, 2, 3, 4):
                fh.write('999.001 Script [Info]: Shop: purchased item %d for platinum %d\n'
                         % (n, 100 + n))
        ee2 = probe_ee_log(stable, tail_bytes=65536)
        check('stable shape is parsed', (ee2['parsed'], len(ee2['records'])), (True, 4))
        check('stable shape keeps amounts', sorted(r['plat'] for r in ee2['records']),
              [101, 102, 103, 104])

    ee_off = probe_ee_log('')
    check('ee probe off by default', (ee_off['found'], ee_off['parsed']), (False, False))

    # --- export inventory: unknown arrays reported, daily points mergeable
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, 'alecaframeStatsExport.json')
        with open(p, 'w', encoding='utf-8') as fh:
            json.dump(dict(
                trades=[dict(ts='2026-09-01T00:00:00.000Z', tx=[], rx=[], totalPlat=57)],
                generalDataPoints=[dict(ts='2026-09-01T00:00:00.000Z', plat=100, credits=5,
                                        endo=1)],
                relicLog=[dict(ts='x', tier='Axi')], lastUpdate='now', publicParts=0), fh)
        arrays, scalars, points, note = export_inventory(p, dict(earned=50, spent=7))
        check('export arrays inventoried', sorted(a['name'] for a in arrays),
              ['generalDataPoints', 'relicLog', 'trades'])
        check('unknown array flagged beyond the known two',
              [a['name'] for a in arrays if a['beyond_known']], ['relicLog'])
        check('unknown array is not imported', [a for a in arrays
                                                if a['name'] == 'relicLog'][0]['rows'], 1)
        check('export scalars reported (no arrays beyond the known two)',
              sorted(s['name'] for s in scalars), ['lastUpdate', 'publicParts'])
        check('export note lists what is beyond the known two', 'relicLog' in note, True)
        check('generalDataPoints flagged as daily points', bool(
            [a for a in arrays if a['name'] == 'generalDataPoints'][0]['fields']), True)
        check('trade totals cross-checked against trade_log',
              'match' in [a for a in arrays if a['name'] == 'trades'][0]['note'], True)
        check('points handed back for merging', len(points), 1)

    print('selftest OK - %d checks (fixed UTC+10 fixtures, temp files only, no network)'
          % len(checks))
    return 0


if __name__ == '__main__':
    sys.exit(main())
