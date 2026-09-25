#!/usr/bin/env python3
"""Per-item price history logger + 24h movers report (offline, stdlib only).

Appends ONE compact point per priced item to data/price_history.json --
[date, wts, wtb, median, vol48] -- one point per item per calendar day, so a
same-day re-run REPLACES that day's point instead of duplicating it. Prints the
biggest 24h movers (sell-price % change vs the most recent earlier day) and
writes data/price_movers.json.

Inputs (read-only): data/prices.json, data/stats.json, data/wfm_items_v2.json,
data/owned.json.  No network.  Env: PRICE_HISTORY_PATH / PRICE_MOVERS_PATH.
"""
import json
import os
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
HISTP = os.environ.get('PRICE_HISTORY_PATH') or os.path.join(DATA, 'price_history.json')
MOVERP = os.environ.get('PRICE_MOVERS_PATH') or os.path.join(DATA, 'price_movers.json')
SCHEMA = 1
TOP = 15        # movers printed
KEEP = 400      # max points retained per item
MIN_PREV = 3.0  # ignore sub-3p items when ranking % moves (noise)


def load(name, default=None):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return default
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def names_map():
    """slug -> display name (market item list, falling back to owned.json)."""
    out = {}
    v2 = load('wfm_items_v2.json', {}) or {}
    for it in (v2.get('data') or []):
        en = ((it.get('i18n') or {}).get('en') or {})
        if it.get('slug') and en.get('name'):
            out[it['slug']] = en['name']
    for o in (load('owned.json', []) or []):
        if o.get('slug') and o.get('name'):
            out.setdefault(o['slug'], o['name'])
    return out


def make_point(day, slug, prices, stats):
    """One compact snapshot: [date, wts, wtb, median, vol48]."""
    p, s = prices.get(slug) or {}, stats.get(slug) or {}
    med = s.get('med48')
    if med is None:
        med = s.get('median')
    return [day, p.get('wts'), p.get('wtb'), round(med, 2) if med is not None else None,
            s.get('vol48')]


def load_hist():
    if not os.path.exists(HISTP):
        return {}
    try:
        doc = json.load(open(HISTP, encoding='utf-8'))
        hist = doc.get('items') if isinstance(doc, dict) else None
        return hist if isinstance(hist, dict) else {}
    except Exception as e:
        print(f'price_history: store unreadable ({e}); re-baselining from scratch')
        return {}


def save_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, separators=(',', ':'))
    os.replace(tmp, path)


def fmt(v):
    return '-' if v is None else f'{v:g}'


def rel(p):
    """Repo-relative display path; absolute when the store lives on another drive."""
    try:
        return os.path.relpath(p, ROOT).replace('\\', '/')
    except ValueError:
        return p.replace('\\', '/')


def find_movers(hist, nm, day):
    """Sell-price (wts) change vs the most recent snapshot from an earlier day."""
    rows = []
    for slug, pts in hist.items():
        if not pts or pts[-1][0] != day:
            continue
        prev = None
        for pt in reversed(pts[:-1]):
            if pt[0] < day:
                prev = pt
                break
        if not prev:
            continue
        a, b = prev[1], pts[-1][1]
        if a is None or b is None or a < MIN_PREV:
            continue
        d = b - a
        rows.append(dict(slug=slug, name=nm.get(slug, slug), prev=a, now=b,
                         delta=round(d, 2), pct=round(d / a * 100.0, 1),
                         vol48=pts[-1][4], median=pts[-1][3]))
    rows.sort(key=lambda r: (-abs(r['pct']), -abs(r['delta'])))
    return rows


def fallback(hist, nm, day):
    """No earlier day yet: rank by gap between sell offer and 48h median."""
    rows = []
    for slug, pts in hist.items():
        if not pts or pts[-1][0] != day:
            continue
        wts, med = pts[-1][1], pts[-1][3]
        if wts is None or med is None or med < MIN_PREV:
            continue
        rows.append(dict(slug=slug, name=nm.get(slug, slug), wts=wts, median=round(med, 2),
                         gap_pct=round((wts - med) / med * 100.0, 1), vol48=pts[-1][4]))
    rows.sort(key=lambda r: (-abs(r['gap_pct']), -abs(r['wts'] - r['median'])))
    return rows


def main():
    t0 = time.time()
    day = datetime.now().strftime('%Y-%m-%d')
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    prices = load('prices.json', {}) or {}
    stats = load('stats.json', {}) or {}
    if not prices:
        print('price_history: data/prices.json missing or empty - nothing to snapshot')
        return 1
    hist = load_hist()

    born = upd = same = 0
    for slug in sorted(prices):
        pts = hist.setdefault(slug, [])
        pt = make_point(day, slug, prices, stats)
        if pts and pts[-1][0] == day:
            if pts[-1] != pt:
                pts[-1] = pt
                upd += 1
            else:
                same += 1
        else:
            pts.append(pt)
            born += 1
        if len(pts) > KEEP:
            del pts[:-KEEP]

    save_json(HISTP, dict(schema=SCHEMA, updated=now,
                          fields=['date', 'wts', 'wtb', 'median', 'vol48'], items=hist))

    nm = names_map()
    all_rows = find_movers(hist, nm, day)
    prev_days = sorted({pt[0] for pts in hist.values() for pt in pts if pt[0] < day})
    span = sorted({pt[0] for pts in hist.values() for pt in pts})
    size_kb = os.path.getsize(HISTP) / 1024.0

    print('=' * 74)
    print(f' WFM price history  |  {now}  |  {len(hist)} items tracked')
    print('=' * 74)
    print(f' store        : {rel(HISTP)}  ({size_kb:.1f} KB)')
    print(f' points       : {sum(len(p) for p in hist.values())} total'
          f'  |  new day: {born}  |  same-day updated: {upd}  |  unchanged: {same}')
    print(f' history span : {span[0] if span else "-"} .. {span[-1] if span else "-"} ({len(span)} day(s))')
    if not prev_days:
        gap = fallback(hist, nm, day)
        print(' Top movers   : none yet - baseline day, no earlier snapshot to compare')
        print(f' (informational) widest sell-offer vs 48h-median gaps, {min(TOP, len(gap))} of {len(gap)}:')
        print(' ' + '-' * 72)
        for r in gap[:TOP]:
            print(f'   {r["gap_pct"]:+7.1f}%  wts {fmt(r["wts"]):>7}  med {fmt(r["median"]):>7}'
                  f'   {r["name"][:32]:<32} vol48={fmt(r["vol48"])}')
        ranked, rows, mode, prev_day = len(gap), gap, 'baseline-gaps', None
    else:
        print(f' Top 24h movers - sell price (wts) vs {prev_days[-1]}, {min(TOP, len(all_rows))}'
              f' of {len(all_rows)} ranked:')
        print(' ' + '-' * 72)
        for r in all_rows[:TOP]:
            print(f'   {r["pct"]:+7.1f}%  {fmt(r["prev"]):>7} -> {fmt(r["now"]):<7}'
                  f'   {r["name"][:32]:<32} vol48={fmt(r["vol48"])}')
        ranked, rows, mode, prev_day = len(all_rows), all_rows, '24h-movers', prev_days[-1]

    save_json(MOVERP, dict(generated=now, day=day, prev_day=prev_day, mode=mode,
                           ranked=ranked, movers=rows[:TOP]))
    print(f'\n movers json  : {rel(MOVERP)}')
    print(f' runtime      : {time.time() - t0:.2f}s')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
