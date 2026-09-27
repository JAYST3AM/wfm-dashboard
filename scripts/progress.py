#!/usr/bin/env python3
r"""Progress / session tracker: what have I done today + a short history.

Inputs (read-only; all optional - every absence becomes a short note)
  data/plat_history.json                          plat/credit/MR curve.  It is a STEP curve
                                                  (heartbeats every ~30 min while the game
                                                  runs), not per-day samples.
  data/trade_log.json                             trade events (sale / purchase / listing /
                                                  unlist / reprice / note).
  data/session_stats.json                         read ONLY for its gap_min: the session
                                                  split threshold scripts/session_stats.py
                                                  uses.  Session boundaries here are
                                                  re-derived from the same marks (trade ts +
                                                  plat ts) with that exact gap, so both
                                                  files always split identically.
  data/invdiff.json                               inventory delta vs the newest earlier
                                                  snapshot (added / removed ids).
  data/inventory_snapshots/owned_YYYY-MM-DD.json  one owned snapshot per day.
  data/item_history.json                          per-item count points -> items_gained.
  data/materials.json                             owned material counts.
  data/materials_prev.json                        OPTIONAL earlier material sample (same
                                                  shape as materials.json).  The materials
                                                  delta is only reported when this exists and
                                                  is at most one day old.

Outputs
  data/progress.json                              the store the dashboard reads
  static/progress.json                            copy of the same payload, because server.py
                                                  serves only static/ (--no-static-copy skips)

Rules (never invent)
  * 'current' session = the newest activity timestamp is within the gap window read from
    data/session_stats.json (fallback: session_stats.py's own 45 min default when that file
    is unreadable - never a different number).
  * plat / credit deltas walk plat_history and attribute a step to the LOCAL day of the point
    that first shows it (a 23:50 -> 00:05 change belongs to the next day).
  * day buckets are local midnight-to-midnight; 'week' starts Monday 00:00 local.
  * items_added / items_removed come from invdiff.json, or from consecutive daily snapshots
    when the invdiff reference day differs.  A day with neither is unknown -> null + note.
  * session items_gained = number of distinct items whose tracked count rose inside the
    session window (data/item_history.json).
  * trades count sale + purchase events; listing activity is 'events', not trades.
  * materials_gained needs data/materials_prev.json; without it the delta is 0 and noted.  The
    script writes that baseline itself the first time it runs with none present (stamped with the
    sample date) - an existing baseline is never overwritten, so a stale one keeps reporting as
    stale.
  * a missing input makes its fields null (or 0 where noted) and gets a note - nothing is
    guessed and no number is derived from a file that is not there.
  * days rows: the last --days local calendar days that have activity, today always
    included, newest first (up to --days rows).  sessions: the sessions intersecting that
    same window, newest first, capped at --days rows.

Env overrides (tests): WFM_DATA_DIR (data dir), WFM_STATIC_DIR (static dir).
CLI: --once (default) | --out PATH | --json | --dry-run | --days N (default 30) |
     --no-static-copy | --selftest
Exit codes: 0 ok, 1 nothing to read, 2 selftest failure.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import date as _date
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get('WFM_DATA_DIR') or os.path.join(ROOT, 'data')
STATIC = os.environ.get('WFM_STATIC_DIR') or os.path.join(ROOT, 'static')

SCHEMA = 1
SNAP_DIR = 'inventory_snapshots'
GAP_FALLBACK_MIN = 45          # session_stats.py's own default, used only when its file is gone
DATE_RE = re.compile(r'(\d{4}-\d{2}-\d{2})')
SALE, BUY = 'sale', 'purchase'


# ---------------------------------------------------------------- small helpers

def jload(path, default=None):
    """JSON file -> object; missing / unreadable -> default (never raises)."""
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def atomic_write(path, doc):
    """tmp + os.replace, so a reader never sees a half-written file."""
    tmp = path + '.tmp'
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)


def iso_local(ts):
    """unix seconds -> local ISO-8601 with offset, e.g. 2026-09-27T14:57:00+10:00."""
    return datetime.fromtimestamp(int(ts)).astimezone().isoformat(timespec='seconds')


def now_ts():
    return int(time.time())


def date_of(ts):
    """unix seconds -> local date string YYYY-MM-DD."""
    return time.strftime('%Y-%m-%d', time.localtime(int(ts)))


def start_of(d):
    """local midnight of a datetime.date as unix seconds."""
    return int(datetime(d.year, d.month, d.day).timestamp())


def prev_day(d):
    return d + timedelta(days=1)


def rel(path):
    """Repo-relative display path; absolute when the store lives outside the repo (tests)."""
    try:
        sub = os.path.relpath(path, ROOT)
        if not sub.startswith('..'):
            return sub.replace('\\', '/')
    except ValueError:                                  # another drive: keep it absolute
        pass
    return path.replace('\\', '/')


def num(v):
    """int/float (bools rejected) else None - a value that really was a number."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v


# ---------------------------------------------------------------- input readers

def read_points(data_dir):
    """(points, note): plat_history entries with a usable ts, sorted by ts."""
    raw = jload(os.path.join(data_dir, 'plat_history.json'))
    if not isinstance(raw, list):
        return [], 'plat_history.json missing or unusable - plat/credits/mr are null'
    points = sorted((p for p in raw
                     if isinstance(p, dict) and isinstance(p.get('ts'), (int, float))
                     and not isinstance(p.get('ts'), bool)),
                    key=lambda p: p['ts'])
    if not points:
        return [], 'plat_history.json has no usable points - plat/credits/mr are null'
    return points, None


def read_events(data_dir):
    """(events, note): trade_log entries with a usable ts, sorted by ts."""
    raw = jload(os.path.join(data_dir, 'trade_log.json'))
    if not isinstance(raw, list):
        return [], 'trade_log.json missing or unusable - trades reported as 0'
    events = sorted((e for e in raw
                     if isinstance(e, dict) and isinstance(e.get('ts'), (int, float))
                     and not isinstance(e.get('ts'), bool)),
                    key=lambda e: e['ts'])
    if not events:
        return [], 'trade_log.json is empty - trades reported as 0'
    return events, None


def read_gap(data_dir):
    """(gap_min, note): the session split threshold from session_stats.json.

    Falls back to session_stats.py's own default when that file is unreadable, and says so.
    """
    doc = jload(os.path.join(data_dir, 'session_stats.json'))
    if isinstance(doc, dict):
        g = num(doc.get('gap_min'))
        if g is not None and g > 0:
            return float(g), None
    return float(GAP_FALLBACK_MIN), ('session_stats.json missing or has no gap_min - using the '
                                     'session_stats.py default gap of %d min' % GAP_FALLBACK_MIN)


def read_item_history(data_dir):
    """data/item_history.json doc, or None when missing/unusable."""
    doc = jload(os.path.join(data_dir, 'item_history.json'))
    return doc if isinstance(doc, dict) else None


def read_materials(data_dir):
    """(current counts, previous counts, previous date, notes).

    counts = {slug: {name, count}}; None means the file was not readable at all.
    """
    cur = jload(os.path.join(data_dir, 'materials.json'))
    prev = jload(os.path.join(data_dir, 'materials_prev.json'))
    prev_date = None
    if prev is not None:
        prev_path = os.path.join(data_dir, 'materials_prev.json')
        if isinstance(prev, dict):
            for key in ('updated', 'date', 'generated'):
                v = prev.get(key)
                if num(v) is not None:
                    prev_date = _date.fromtimestamp(v)
                    break
                if isinstance(v, str) and DATE_RE.match(v):
                    try:
                        prev_date = _date.fromisoformat(v[:10])
                        break
                    except ValueError:
                        pass
        if prev_date is None:
            try:
                prev_date = _date.fromtimestamp(os.path.getmtime(prev_path))
            except OSError:
                prev_date = None
    return cur, prev, prev_date, []


def material_counts(doc):
    """-> {slug: {name, count}} from a materials.json-shaped doc, a plain {slug: count} map
    or a row list; {} when the doc holds nothing usable."""
    out = {}

    def put(slug, name, count):
        if slug and num(count) is not None:
            out[str(slug)] = dict(name=str(name or slug), count=count)

    if isinstance(doc, list):
        for row in doc:
            if isinstance(row, dict):
                put(row.get('slug'), row.get('name'), row.get('count'))
    elif isinstance(doc, dict):
        rows = doc.get('materials')
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    put(row.get('slug'), row.get('name'), row.get('count'))
        else:
            for slug, v in doc.items():
                if isinstance(v, dict):
                    put(slug, v.get('name'), v.get('count'))
                else:
                    put(slug, slug, v)
    return out


def stamp_materials_baseline(data_dir, now):
    """Write data/materials_prev.json from today's sample ONLY when no baseline exists.

    materials_delta needs a baseline, and on a fresh install there never is one - so the first
    run stamps today's sample (the note then names it) and every later run reports gains against
    it.  An existing baseline is never touched: a stale one must keep saying so.
    """
    cur_p = os.path.join(data_dir, 'materials.json')
    prev_p = os.path.join(data_dir, 'materials_prev.json')
    if os.path.exists(prev_p):
        return None
    cur = jload(cur_p) or {}
    if not cur.get('materials'):
        return None
    out = dict(cur)
    out['stamped'] = date_of(now)
    atomic_write(prev_p, out)
    return prev_p


def materials_delta(cur_doc, prev_doc, prev_date, now, notes):
    """(materials_gained[:5], material_delta_total) - gains only, largest first.

    The total sums EVERY positive delta, not just the five shown.  No previous sample (or a
    stale one) -> ([], 0) and the reason lands in notes.
    """
    if cur_doc is None:
        notes.append('materials.json missing or unusable - materials_gained is empty')
        return [], 0
    if prev_doc is None:
        notes.append('no previous materials sample (data/materials_prev.json) - '
                     'materials delta is 0')
        return [], 0
    today = _date.fromtimestamp(now)
    if prev_date is not None and (today - prev_date).days > 1:
        notes.append('materials baseline is from %s (older than yesterday) - delta not reported'
                     % prev_date.isoformat())
        return [], 0
    cur, prev = material_counts(cur_doc), material_counts(prev_doc)
    gains, total = [], 0
    for slug, row in cur.items():
        p = prev.get(slug)
        if p is None:
            continue
        d = row['count'] - p['count']
        if d > 0:
            gains.append((d, row['name']))
            total += d
    gains.sort(key=lambda pair: (-pair[0], pair[1]))
    notes.append('materials delta vs the %s sample in data/materials_prev.json'
                 % (prev_date.isoformat() if prev_date else 'previous'))
    return [dict(name=name, delta=d) for d, name in gains[:5]], total


# ---------------------------------------------------------------- inventory data

def snapshot_files(data_dir):
    """[(date, path)] for data/inventory_snapshots/owned_YYYY-MM-DD.json, oldest first."""
    sdir = os.path.join(data_dir, SNAP_DIR)
    out = []
    if not os.path.isdir(sdir):
        return out
    for name in sorted(os.listdir(sdir)):
        if not (name.startswith('owned_') and name.endswith('.json')):
            continue
        try:
            d = _date.fromisoformat(name[len('owned_'):-len('.json')])
        except ValueError:
            continue
        out.append((d, os.path.join(sdir, name)))
    return sorted(out)


def snapshot_slugs(path):
    """-> {slug: summed count} like invdiff.agg(), or None when the file is unusable."""
    rows = jload(path)
    if not isinstance(rows, list):
        return None
    out = {}
    for r in rows:
        if isinstance(r, dict) and r.get('slug'):
            out[r['slug']] = out.get(r['slug'], 0) + (r.get('count') or 1)
    return out


def date_from_path(path):
    """'data/inventory_snapshots/owned_2026-09-26.json' -> date(2026, 9, 26)."""
    if not isinstance(path, str):
        return None
    m = DATE_RE.search(os.path.basename(path))
    if not m:
        return None
    try:
        return _date.fromisoformat(m.group(1))
    except ValueError:
        return None


def inventory_days(data_dir, invdiff):
    """(per_day, items_total, latest_snapshot_date, notes).

    per_day[date] = (added, removed) counting distinct slugs: invdiff.json first, consecutive
    daily snapshots for pairs invdiff does not cover (e.g. its reference day differs), and
    when neither exists the day simply stays out of the map.
    """
    notes = []
    per_day = {}
    counts = {}
    for d, path in snapshot_files(data_dir):
        s = snapshot_slugs(path)
        if s is not None:
            counts[d] = s
    dates = sorted(counts)
    for i in range(1, len(dates)):
        prev, cur = counts[dates[i - 1]], counts[dates[i]]
        per_day[dates[i]] = (sum(1 for s in cur if s not in prev),
                             sum(1 for s in prev if s not in cur))
    items_total = len(counts[dates[-1]]) if dates else None

    if isinstance(invdiff, dict):
        snap_date = date_from_path(invdiff.get('snapshot'))
        ref_date = date_from_path(invdiff.get('reference'))
        summary = invdiff.get('summary') if isinstance(invdiff.get('summary'), dict) else {}
        a, r = num(summary.get('added')), num(summary.get('removed'))
        if snap_date is not None and a is not None and r is not None:
            before = max((d for d in dates if d < snap_date), default=None)
            if before == ref_date or before is None:
                per_day[snap_date] = (int(a), int(r))      # invdiff's own pair
            elif snap_date in counts:
                notes.append('invdiff reference day %s is not the previous snapshot (%s) - '
                             'recomputed from the snapshot pair'
                             % (ref_date.isoformat() if ref_date else 'none',
                                before.isoformat()))
        now_block = (invdiff.get('totals') or {}).get('now') or {}
        if num(now_block.get('items')) is not None:
            items_total = int(now_block['items'])
    if not counts and not isinstance(invdiff, dict):
        notes.append('no inventory snapshots and no invdiff.json - '
                     'items_added/items_removed unavailable')
    return per_day, items_total, (dates[-1] if dates else None), notes


# ---------------------------------------------------------------- session maths

def clusters(marks, gap_s):
    """Activity timestamps -> clusters, split wherever the gap exceeds gap_s.

    Same rule as scripts/session_stats.py clusters(): sorted + de-duplicated, a new cluster
    starts when the next mark is more than the gap after the last one.
    """
    out = []
    for t in sorted(set(marks)):
        if out and t - out[-1][-1] <= gap_s:
            out[-1].append(t)
        else:
            out.append([t])
    return out


def step_walk(points, field):
    """(by_day, timeline) for one numeric field of the plat step curve.

    by_day[local-date] = summed change attributed to that day; a change belongs to the day of
    the point that FIRST shows it.  timeline = [(ts, value)] for every point carrying the
    field, in ts order (carry-forward values).
    """
    by_day, timeline = {}, []
    prev = None
    for p in points:
        v = num(p.get(field))
        if v is None:
            continue
        if prev is not None and v != prev:
            day = date_of(p['ts'])
            by_day[day] = by_day.get(day, 0) + (v - prev)
        timeline.append((p['ts'], v))
        prev = v
    return by_day, timeline


def value_before(timeline, ts):
    """Last timeline value strictly before ts (carry-forward) or None."""
    out = None
    for t, v in timeline:
        if t < ts:
            out = v
        else:
            break
    return out


def events_by_day(events):
    """local date -> {count, sales, purchases, plat_in, plat_out} for sale/purchase events."""
    out = {}
    for e in events:
        kind = e.get('kind')
        if kind not in (SALE, BUY):
            continue
        row = out.setdefault(date_of(e['ts']),
                             dict(count=0, sales=0, purchases=0, plat_in=0, plat_out=0))
        total = e.get('total') or 0
        row['count'] += 1
        if kind == SALE:
            row['sales'] += 1
            row['plat_in'] += total
        else:
            row['purchases'] += 1
            row['plat_out'] += total
    return out


def zero_trades():
    return dict(count=0, sales=0, purchases=0, plat_in=0, plat_out=0)


def count_items_gained(items_doc, a, b):
    """Distinct items whose tracked count rose inside [a, b], per data/item_history.json.

    None when item_history.json is not readable; 0 when it carries no such point.
    """
    if items_doc is None:
        return None
    items = items_doc.get('items')
    if not isinstance(items, dict):
        return None
    n = 0
    for rec in items.values():
        pts = rec.get('points') if isinstance(rec, dict) else None
        if not isinstance(pts, list):
            continue
        prev, up = None, False
        for pt in pts:
            if not (isinstance(pt, (list, tuple)) and len(pt) >= 2):
                continue
            ts, cnt = pt[0], pt[1]
            if num(ts) is None or num(cnt) is None:
                continue
            if prev is not None and a <= ts <= b and cnt > prev:
                up = True
                break
            prev = cnt
        if up:
            n += 1
    return n


def headline(trades, events, plat_delta, items_gained):
    """Short one-liner for the session list, e.g. '6 trades . +42p'."""
    if trades:
        what = '%d trade%s' % (trades, '' if trades == 1 else 's')
    elif events:
        what = '%d event%s' % (events, '' if events == 1 else 's')
    else:
        what = 'idle'
    parts = [what]
    if plat_delta is not None:
        parts.append('%+dp' % plat_delta)
    if items_gained:
        parts.append('+%d items' % items_gained)
    return ' \u00b7 '.join(parts)


def build_sessions(wins, events, points, items_doc, now, gap_s):
    """Session records, newest first (see the module docstring for the field rules)."""
    out = []
    newest = max((w[-1] for w in wins), default=None)
    for w in reversed(wins):
        a, b = w[0], w[-1]
        evs = [e for e in events if a <= e['ts'] <= b]
        pts = [p for p in points if a <= p['ts'] <= b]
        sales = sum(1 for e in evs if e.get('kind') == SALE)
        buys = sum(1 for e in evs if e.get('kind') == BUY)
        ps = num(pts[0].get('plat')) if pts else None
        pe = num(pts[-1].get('plat')) if pts else None
        pd = (pe - ps) if (ps is not None and pe is not None) else None
        ig = count_items_gained(items_doc, a, b)
        out.append(dict(
            start_ts=a, start_iso=iso_local(a), end_ts=b, end_iso=iso_local(b),
            minutes=round((b - a) / 60.0, 1),
            current=bool(b == newest and (now - b) <= gap_s),
            events=len(evs), trades=sales + buys, sales=sales,
            plat_start=ps, plat_end=pe, plat_delta=pd, items_gained=ig,
            headline=headline(sales + buys, len(evs), pd, ig)))
    return out


# ---------------------------------------------------------------- the store

def collect(data_dir, now, days=30):
    """Build the progress store for data_dir as of unix seconds `now`."""
    notes = []
    # --- inputs
    points, note = read_points(data_dir)
    if note:
        notes.append(note)
    events, note = read_events(data_dir)
    if note:
        notes.append(note)
    gap_min, note = read_gap(data_dir)
    if note:
        notes.append(note)
    gap_s = gap_min * 60.0
    invdiff = jload(os.path.join(data_dir, 'invdiff.json'))
    inv_days, items_total, latest_snap, inv_notes = inventory_days(data_dir, invdiff)
    notes += inv_notes
    items_doc = read_item_history(data_dir)
    if items_doc is None:
        notes.append('item_history.json missing - session items_gained is null')
    materials_doc, prev_materials, prev_date, _ = read_materials(data_dir)
    if materials_doc is None:
        materials_cur = None
    else:
        materials_cur = material_counts(materials_doc)
    materials_gained, material_total = materials_delta(
        materials_cur, prev_materials, prev_date, now, notes)

    # --- the walks
    plat_by_day, plat_tl = step_walk(points, 'plat')
    cred_by_day, cred_tl = step_walk(points, 'credits')
    mr_by_day, mr_tl = step_walk(points, 'mr')
    if points and not cred_tl:
        notes.append("plat_history points carry no 'credits' - credits_delta is null")
    if points and not mr_tl:
        notes.append("plat_history points carry no 'mr' - mr is null")
    ev_day = events_by_day(events)
    all_dates = {date_of(p['ts']) for p in points} | {date_of(e['ts']) for e in events}

    # --- today
    today = _date.fromtimestamp(now)
    t0, t1 = start_of(today), start_of(prev_day(today))
    today_s = today.isoformat()
    marks = sorted({p['ts'] for p in points} | {e['ts'] for e in events})
    wins = clusters(marks, gap_s) if marks else []
    sessions_all = build_sessions(wins, events, points, items_doc, now, gap_s)
    t_marks = [t for t in marks if t0 <= t < t1]
    if points and not t_marks:
        notes.append('no plat point today - plat_delta is 0 so far (latest point %s)'
                     % iso_local(points[-1]['ts']))
    plat_start = value_before(plat_tl, t0)
    plat_now = plat_tl[-1][1] if plat_tl else None
    inv_today = inv_days.get(today)
    if inv_today is None and (latest_snap is not None or isinstance(invdiff, dict)):
        where = ('owned_%s.json' % latest_snap.isoformat()) if latest_snap else 'invdiff.json'
        notes.append('no inventory snapshot for today (latest %s) - '
                     "today's items_added/items_removed are null" % where)

    t_wins = [w for w in wins if min(w[-1], t1) > max(w[0], t0)]
    today_block = dict(
        date=today_s,
        first_ts=min(t_marks) if t_marks else None,
        last_ts=max(t_marks) if t_marks else None,
        plat_start=plat_start,
        plat_now=plat_now,
        plat_delta=(plat_by_day.get(today_s, 0) if plat_tl else None),
        credits_delta=(cred_by_day.get(today_s, 0) if cred_tl else None),
        mr=(mr_tl[-1][1] if mr_tl else None),
        items_added=(inv_today[0] if inv_today else None),
        items_removed=(inv_today[1] if inv_today else None),
        items_total=items_total,
        trades=dict(ev_day.get(today_s) or zero_trades()),
        sessions=dict(
            count=len(t_wins),
            minutes=round(sum(min(w[-1], t1) - max(w[0], t0) for w in t_wins) / 60.0, 1),
            current=bool(marks and (now - marks[-1]) <= gap_s)),
        materials_gained=materials_gained,
        material_delta_total=material_total)

    # --- short history: days + sessions inside the last `days` calendar days
    window_start = start_of(today - timedelta(days=days - 1))
    day_rows = []
    for i in range(days):
        d = today - timedelta(days=i)
        ds = d.isoformat()
        if ds not in all_dates and ds not in inv_days and d != today:
            continue
        ev = ev_day.get(ds) or zero_trades()
        day_rows.append(dict(
            date=ds,
            plat_delta=(plat_by_day.get(ds, 0) if plat_tl else None),
            credits_delta=(cred_by_day.get(ds, 0) if cred_tl else None),
            mr=value_before(mr_tl, start_of(prev_day(d))),
            trades=ev['count'], plat_in=ev['plat_in'], plat_out=ev['plat_out'],
            items_added=(inv_days[d][0] if d in inv_days else None),
            sessions=sum(1 for w in wins if min(w[-1], start_of(prev_day(d))) > max(w[0], start_of(d)))))
    sessions_out = [s for s in sessions_all if s['end_ts'] >= window_start][:days]

    # --- streaks (this week starts Monday 00:00 local)
    week_start = today - timedelta(days=today.weekday())
    ws_ts = start_of(week_start)
    streaks = dict(
        days_active=len(all_dates),
        last_active_date=(max(all_dates) if all_dates else None),
        hours_this_week=round(sum(min(w[-1], now) - max(w[0], ws_ts)
                                  for w in wins if min(w[-1], now) > max(w[0], ws_ts)) / 3600.0, 2),
        trades_this_week=sum(1 for e in events
                             if e['ts'] >= ws_ts and e.get('kind') in (SALE, BUY)),
        plat_this_week=(sum(v for ds, v in plat_by_day.items() if ds >= week_start.isoformat())
                        if plat_tl else None))

    # --- provenance
    loaded = []
    if points:
        loaded.append('plat_history.json')
    if isinstance(jload(os.path.join(data_dir, 'trade_log.json')), list):
        loaded.append('trade_log.json')
    if isinstance(jload(os.path.join(data_dir, 'session_stats.json')), dict):
        loaded.append('session_stats.json')
    if isinstance(invdiff, dict):
        loaded.append('invdiff.json')
    if latest_snap is not None:
        loaded.append(SNAP_DIR)
    if items_doc is not None:
        loaded.append('item_history.json')
    if materials_doc is not None:
        loaded.append('materials.json')
    if prev_materials is not None:
        loaded.append('materials_prev.json')

    return dict(schema=SCHEMA, updated=int(now), updated_iso=iso_local(now),
                source='+'.join(loaded) if loaded else 'none', notes=notes,
                today=today_block, sessions=sessions_out, days=day_rows, streaks=streaks)


def summary_line(doc):
    """One-line gist, e.g. 'progress: today +3 items, +42p, 6 trades, 2 sessions (current)
    | 14 active days | week +180p'."""
    t, s = doc['today'], doc['streaks']
    items = '%+d items' % t['items_added'] if t['items_added'] is not None else 'items n/a'
    plat = '%+dp' % t['plat_delta'] if t['plat_delta'] is not None else 'plat n/a'
    trades = '%d trade%s' % (t['trades']['count'], '' if t['trades']['count'] == 1 else 's')
    sessions = '%d session%s%s' % (t['sessions']['count'],
                                   '' if t['sessions']['count'] == 1 else 's',
                                   ' (current)' if t['sessions']['current'] else '')
    week = '%+dp' % s['plat_this_week'] if s['plat_this_week'] is not None else 'n/a'
    return ('progress: today %s, %s, %s, %s | %d active days | week %s'
            % (items, plat, trades, sessions, s['days_active'], week))


# ---------------------------------------------------------------- selftest

def selftest():
    """Offline fixture run: a current vs a closed session, a day-boundary crossing, a plat
    step landing on the next day, a missing trade_log.json and the streak maths."""
    checks = []

    def ok(cond, what):
        if not cond:
            raise AssertionError(what)
        checks.append(what)

    def eq(got, want, what):
        if got != want:
            raise AssertionError('%s (got %r, want %r)' % (what, got, want))
        checks.append(what)

    def write(path, obj):
        atomic_write(os.path.join(td, 'data', path), obj)

    try:
        with tempfile.TemporaryDirectory(prefix='progress_selftest_') as td:
            data = os.path.join(td, 'data')
            static = os.path.join(td, 'static')
            os.makedirs(os.path.join(data, SNAP_DIR))
            # fixed clock: Wednesday 2026-06-17 20:00 local -> the week starts Mon 2026-06-15
            d13, d15, d16, d17 = (_date(2026, 6, 13), _date(2026, 6, 15),
                                  _date(2026, 6, 16), _date(2026, 6, 17))
            now = int(datetime(2026, 6, 17, 20, 0, 0).timestamp())

            def at(d, hh, mm):
                return int(datetime(d.year, d.month, d.day, hh, mm).timestamp())

            write('plat_history.json', [
                dict(ts=at(d13, 10, 0), plat=100, credits=1000, mr=10),   # closed session
                dict(ts=at(d13, 10, 10), plat=130, credits=900),          # +30 that day
                dict(ts=at(d15, 9, 0), plat=130, credits=900),            # Monday, this week
                dict(ts=at(d16, 23, 50), plat=130, credits=900),          # crosses midnight
                dict(ts=at(d17, 0, 5), plat=230, credits=850),            # step lands TODAY
                dict(ts=at(d17, 19, 50), plat=230, credits=850),          # current session
                dict(ts=at(d17, 19, 58), plat=230, credits=850)])
            write('session_stats.json', dict(gap_min=45, sessions=[], shown=0))

            old_data, old_static = globals()['DATA'], globals()['STATIC']
            old_now = globals()['now_ts']
            globals()['DATA'], globals()['STATIC'] = data, static
            globals()['now_ts'] = lambda: now               # pin the clock to the fixture
            try:
                # --- run 1: trade_log.json missing entirely
                rc = main(['--once'])
                ok(rc == 0, 'missing trade_log.json still builds a store (exit 0)')
                doc1 = jload(os.path.join(data, 'progress.json'))
                ok(isinstance(doc1, dict), 'store written to the tmp data dir')
                ok(any('trade_log.json' in n for n in doc1['notes']), 'missing trade_log noted')
                eq(doc1['today']['trades'], zero_trades(), 'missing trade_log -> trades 0')
                ok(os.path.exists(os.path.join(static, 'progress.json')), 'static copy written')
                ok(not os.path.exists(os.path.join(data, 'progress.json.tmp')), 'no .tmp left')

                # --- run 2: the full fixture
                write('trade_log.json', [
                    dict(ts=at(d13, 10, 5), kind='sale', name='Old Mod', qty=1, total=7),
                    dict(ts=at(d15, 9, 30), kind='sale', name='Week Mod', qty=2, total=20),
                    dict(ts=at(d17, 0, 5), kind='purchase', name='Today Part', qty=1, total=5)])
                write(os.path.join(SNAP_DIR, 'owned_2026-06-16.json'), [
                    dict(slug='a', name='A', count=1), dict(slug='b', name='B', count=1),
                    dict(slug='c', name='C', count=1)])
                write(os.path.join(SNAP_DIR, 'owned_2026-06-17.json'), [
                    dict(slug='a', name='A', count=1), dict(slug='c', name='C', count=2),
                    dict(slug='d', name='D', count=1)])
                write('invdiff.json', dict(
                    generated='2026-06-17 20:00', status='ok',
                    snapshot='data/%s/owned_2026-06-17.json' % SNAP_DIR,
                    reference='data/%s/owned_2026-06-16.json' % SNAP_DIR,
                    summary=dict(added=1, removed=1, changed=1),
                    totals=dict(now=dict(items=3, stacks=4, value=0),
                                previous=dict(items=3, stacks=3, value=0))))
                write('item_history.json', dict(schema=1, items={
                    'ferrite_mod': dict(name='Ferrite Mod',
                                        points=[[at(d17, 19, 45), 1], [at(d17, 19, 55), 3]]),
                    'shrinking': dict(name='Shrinking',
                                      points=[[at(d17, 19, 45), 5], [at(d17, 19, 55), 4]]),
                    'monday_gain': dict(name='Monday Gain',
                                        points=[[at(d15, 9, 10), 1], [at(d15, 9, 20), 2]])}))
                write('materials.json', dict(schema=1, updated=now, materials=[
                    dict(slug='ferrite', name='Ferrite', count=1300),
                    dict(slug='nano_spores', name='Nano Spores', count=100)]))
                write('materials_prev.json', dict(updated=now - 3600, materials=[
                    dict(slug='ferrite', name='Ferrite', count=1000),
                    dict(slug='nano_spores', name='Nano Spores', count=150)]))
                rc = main(['--once'])
                ok(rc == 0, 'full fixture run exits 0')
                doc = jload(os.path.join(data, 'progress.json'))

                # store contract
                eq(list(doc), ['schema', 'updated', 'updated_iso', 'source', 'notes',
                               'today', 'sessions', 'days', 'streaks'], 'top-level keys')
                eq(doc['schema'], 1, 'schema 1')
                eq(doc['updated'], now, 'updated = the run clock')
                ok(re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$',
                            doc['updated_iso']) is not None, 'updated_iso has a UTC offset')
                eq(list(doc['today']), ['date', 'first_ts', 'last_ts', 'plat_start', 'plat_now',
                                        'plat_delta', 'credits_delta', 'mr', 'items_added',
                                        'items_removed', 'items_total', 'trades', 'sessions',
                                        'materials_gained', 'material_delta_total'],
                   'today keys')
                eq(list(doc['today']['trades']), ['count', 'sales', 'purchases', 'plat_in',
                                                  'plat_out'], 'today.trades keys')
                eq(list(doc['today']['sessions']), ['count', 'minutes', 'current'],
                   'today.sessions keys')
                eq(list(doc['sessions'][0]), ['start_ts', 'start_iso', 'end_ts', 'end_iso',
                                              'minutes', 'current', 'events', 'trades', 'sales',
                                              'plat_start', 'plat_end', 'plat_delta',
                                              'items_gained', 'headline'], 'session keys')
                eq(list(doc['days'][0]), ['date', 'plat_delta', 'credits_delta', 'mr', 'trades',
                                          'plat_in', 'plat_out', 'items_added', 'sessions'],
                   'day keys')
                eq(list(doc['streaks']), ['days_active', 'last_active_date', 'hours_this_week',
                                          'trades_this_week', 'plat_this_week'], 'streaks keys')
                ok(not any('trade_log.json' in n for n in doc['notes']),
                   'a present trade_log leaves no missing note')

                # today: the day-boundary crossing, the plat step and the item/material deltas
                t = doc['today']
                eq(t['date'], '2026-06-17', 'today date')
                eq(t['first_ts'], at(d17, 0, 5), 'first activity is 00:05 (the 23:50 mark is'
                                                 ' yesterday)')
                eq(t['last_ts'], at(d17, 19, 58), 'last activity today')
                eq((t['plat_start'], t['plat_now'], t['plat_delta']), (130, 230, 100),
                   'plat_start carries forward, the +100 step landed on the next day')
                eq(t['credits_delta'], -50, 'credits step attributed to today')
                eq(t['mr'], 10, 'mr from the last point that carried it')
                eq((t['items_added'], t['items_removed'], t['items_total']), (1, 1, 3),
                   "today's inventory delta and total")
                eq(t['trades'], dict(count=1, sales=0, purchases=1, plat_in=0, plat_out=5),
                   "today's trades")
                eq(t['sessions'], dict(count=2, minutes=13.0, current=True),
                   'two sessions today (5 + 8 min), the newest one live')
                eq(t['materials_gained'], [dict(name='Ferrite', delta=300)], 'materials gains')
                eq(t['material_delta_total'], 300, 'materials total (gains only)')

                # sessions: newest first, current vs closed
                eq([s['start_ts'] for s in doc['sessions']],
                   [at(d17, 19, 50), at(d16, 23, 50), at(d15, 9, 0), at(d13, 10, 0)],
                   'sessions newest first')
                eq([s['current'] for s in doc['sessions']], [True, False, False, False],
                   'only the newest session is current')
                s0 = doc['sessions'][0]
                eq((s0['minutes'], s0['events'], s0['trades'], s0['plat_delta'],
                    s0['items_gained']), (8.0, 0, 0, 0, 1), 'current session numbers')
                ok(s0['headline'].startswith('idle'), 'headline starts with the activity kind')
                s1 = doc['sessions'][1]
                eq((s1['start_ts'], s1['end_ts'], s1['plat_delta'], s1['trades']),
                   (at(d16, 23, 50), at(d17, 0, 5), 100, 1), 'the crossing session')
                eq((s1['plat_start'], s1['plat_end']), (130, 230), 'session plat endpoints')
                eq(doc['sessions'][2]['items_gained'], 1, 'items_gained inside the Monday run')
                eq(doc['sessions'][3]['headline'], '1 trade \u00b7 +30p', 'closed headline')

                # days: attribution + the skipped empty day
                eq([r['date'] for r in doc['days']],
                   ['2026-06-17', '2026-06-16', '2026-06-15', '2026-06-13'],
                   'active days, newest first, gap day left out')
                r17, r16, r15, r13 = doc['days']
                eq((r17['plat_delta'], r17['credits_delta'], r17['items_added'],
                    r17['trades'], r17['sessions']), (100, -50, 1, 1, 2), 'today row')
                eq((r16['plat_delta'], r16['items_added']), (0, None),
                   'the step did not land on the 16th; no reference snapshot before it')
                eq((r15['trades'], r15['plat_in']), (1, 20), 'Monday sale row')
                eq((r13['plat_delta'], r13['plat_in']), (30, 7), 'Saturday row is last week')

                # streaks: 4 active days, this week = Mon 2026-06-15
                eq(doc['streaks'], dict(days_active=4, last_active_date='2026-06-17',
                                        hours_this_week=0.88, trades_this_week=2,
                                        plat_this_week=100), 'streak maths')

                line = summary_line(doc)
                ok(line.startswith('progress: today +1 items, +100p, 1 trade, 2 sessions'
                                   ' (current) | 4 active days | week +100p'),
                   'summary line: %s' % line)

                # determinism: the same inputs and clock rebuild the same store
                doc2 = collect(data, now)
                eq(doc2, doc, 'collect() is deterministic')
            finally:
                globals()['DATA'], globals()['STATIC'] = old_data, old_static
                globals()['now_ts'] = old_now
    except AssertionError as exc:
        print('selftest : FAILED - %s' % exc)
        return 2
    print('selftest : ok (%d checks) offline - no network, tmp files only' % len(checks))
    return 0


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='progress.py',
        description='Build data/progress.json (+ the static/ copy): what have I done today, '
                    'plus a short history of sessions and days.',
        epilog='Exit codes: 0 ok, 1 nothing to read, 2 selftest failure.')
    ap.add_argument('--once', action='store_true', default=True,
                    help='single pass (default; kept for cron lines)')
    ap.add_argument('--out', metavar='PATH', help='store path (default data/progress.json)')
    ap.add_argument('--json', action='store_true', help='print the store JSON to stdout')
    ap.add_argument('--dry-run', action='store_true', help='print the plan and write nothing')
    ap.add_argument('--days', type=int, default=30, metavar='N',
                    help='history depth in local calendar days (default 30)')
    ap.add_argument('--no-static-copy', action='store_true',
                    help='do not write static/progress.json')
    ap.add_argument('--selftest', action='store_true',
                    help='offline fixture checks (no network, tmp files only)')
    args = ap.parse_args(argv)
    if args.days < 1:
        ap.error('--days must be >= 1')

    if args.selftest:
        return selftest()

    now = now_ts()
    doc = collect(DATA, now, days=args.days)
    print(summary_line(doc))                      # summary line FIRST
    for note in doc['notes']:
        print('  note: %s' % note)

    if args.dry_run:
        print('plan : write %s + the static copy (%d note(s), %d sessions, %d day row(s))'
              % (rel(args.out or os.path.join(DATA, 'progress.json')), len(doc['notes']),
                 len(doc['sessions']), len(doc['days'])))
        print('plan : dry-run - nothing written')
        if args.json:
            print(json.dumps(doc, separators=(',', ':')))
        return 0

    if doc['source'] == 'none':
        print('progress: no readable inputs yet (plat_history / trade_log / inventory / '
              'materials all missing) - nothing written')
        return 1

    try:                                              # never fail the run over a baseline
        stamped = stamp_materials_baseline(DATA, now)
        if stamped:
            print('  baseline: wrote %s from today\'s materials sample' % rel(stamped))
    except Exception as _e:
        print('  baseline: stamp failed (%s)' % _e)

    target = args.out or os.path.join(DATA, 'progress.json')
    atomic_write(target, doc)
    static_note = 'static copy skipped (--no-static-copy)'
    if not args.no_static_copy:
        try:
            static_path = os.path.join(STATIC, 'progress.json')
            atomic_write(static_path, doc)
            static_note = 'static copy -> %s' % rel(static_path)
        except OSError as exc:
            static_note = 'static copy failed: %s' % exc
    print('store: %s (%.1f KB)' % (rel(target), os.path.getsize(target) / 1024.0))
    print('  %s' % static_note)
    if args.json:
        print(json.dumps(doc, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
