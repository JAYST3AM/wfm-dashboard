"""Import an AlecaFrame stats export into the dashboard's own history.

- trades            -> data/trade_log.json  (kind sale|purchase|note; idempotent by trade ts+item)
- generalDataPoints -> data/plat_history.json (daily plat/credits/mr points; idempotent by ts)

Multi-item trades expand to one event per item name; the trade's platinum is
prorated exactly (largest-remainder) so the History totals match AlecaFrame.

Usage:  python scripts/import_aleca_stats.py <path-to-alecaframeStatsExport.json>
"""
import json, os, sys, time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
PLAT = '/AF_Special/Platinum'


def jload(name, default=None):
    try:
        return json.load(open(os.path.join(DATA, name), encoding='utf-8'))
    except Exception:
        return default


def iso(ts):
    return int(datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp())


def main(path):
    exp = json.load(open(path, encoding='utf-8'))
    log = jload('trade_log.json') or []
    hist = jload('plat_history.json') or []
    have_src = {e.get('src') for e in log if e.get('src')}
    have_ts = {p.get('ts') for p in hist}

    added, sales, buys, notes, earned, spent = 0, 0, 0, 0, 0, 0
    for ti, t in enumerate(exp.get('trades') or []):
        ts = iso(t['ts'])
        tx = t.get('tx') or []
        rx = t.get('rx') or []
        rx_plat = sum(i.get('cnt') or 0 for i in rx if i.get('name') == PLAT)
        tx_plat = sum(i.get('cnt') or 0 for i in tx if i.get('name') == PLAT)
        out_items = [i for i in tx if i.get('name') != PLAT]
        in_items = [i for i in rx if i.get('name') != PLAT]
        user = (t.get('user') or '?').strip()

        if rx_plat and out_items:
            kind, side, plat_total, extra = 'sale', out_items, rx_plat, ''
        elif tx_plat and in_items:
            kind, side, plat_total, extra = 'purchase', in_items, tx_plat, ''
        elif out_items and in_items:
            kind, side, plat_total = 'note', out_items, 0
            extra = 'swap for ' + ' + '.join(i.get('displayName') or '?' for i in in_items)
        elif out_items:
            kind, side, plat_total, extra = 'note', out_items, 0, 'no plat side'
        else:
            continue

        # expand to per-copy list, then group by item name
        copies = []
        for it in side:
            copies += [it] * int(it.get('cnt') or 1)
        n = len(copies)
        base, rem = divmod(plat_total, n) if n else (0, 0)
        per_copy = [base + (1 if j < rem else 0) for j in range(n)]
        groups = {}
        for it, p in zip(copies, per_copy):
            g = groups.setdefault(it.get('displayName') or '?', [0, 0])  # qty, total
            g[0] += 1
            g[1] += p

        for name, (qty, total) in groups.items():
            src = f"af:{t['ts']}:{name}"
            if src in have_src:
                continue
            note = f'with {user} · imported (AlecaFrame)'
            if extra:
                note += f' · {extra}'
            if len(groups) > 1 or (plat_total and qty and total != qty * (total // qty)):
                note += f' · bundle {n} items, {plat_total}p total' if plat_total else ''
            log.append(dict(ts=ts, kind=kind, name=name, qty=qty,
                            plat=(total // qty if qty else total), total=total,
                            note=note, src=src))
            added += 1
            if kind == 'sale':
                sales += 1; earned += total
            elif kind == 'purchase':
                buys += 1; spent += total
            else:
                notes += 1

    added_ph = 0
    for g in exp.get('generalDataPoints') or []:
        ts = iso(g['ts'])
        if ts in have_ts:
            continue
        hist.append(dict(ts=ts, plat=g.get('plat'), credits=g.get('credits'),
                         mr=g.get('mr'), src='alecaframe'))
        added_ph += 1

    log.sort(key=lambda e: e.get('ts') or 0)
    hist.sort(key=lambda p: p.get('ts') or 0)
    json.dump(log, open(os.path.join(DATA, 'trade_log.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    json.dump(hist, open(os.path.join(DATA, 'plat_history.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)

    ts_all = [iso(t['ts']) for t in (exp.get('trades') or [])]
    if ts_all:
        print('export range:', time.strftime('%Y-%m-%d', time.localtime(min(ts_all))), '->',
              time.strftime('%Y-%m-%d', time.localtime(max(ts_all))))
    print(f'trades: +{added} events ({sales} sale, {buys} purchase, {notes} notes) | earned +{earned}p | spent {spent}p')
    print(f'plat history: +{added_ph} daily points (total now {len(hist)})')
    print(f'trade log total now {len(log)} events')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('usage: python scripts/import_aleca_stats.py <alecaframeStatsExport.json>')
        sys.exit(1)
    main(sys.argv[1])
