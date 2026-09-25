"""Trading session analytics from local history.

Inputs:  data/trade_log.json (sale/purchase/listing/unlist/reprice/note), data/plat_history.json
         (plat/credit snapshots - heartbeats included while the game runs).
Sessions: clusters of activity timestamps (trade events + plat points) split wherever the gap
          exceeds --gap minutes (default 45; heartbeats land every ~15-30 min).
Output:  data/session_stats.json

Usage: python session_stats.py [--root DIR] [--gap MIN] [--last N]
"""
import json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAP = 45
TRADE_KINDS = ('sale', 'purchase')
LIST_KINDS = ('listing', 'unlist', 'reprice')


def jload(p, d=None):
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else d


def hhmm(ts):
    return time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))


def sh(v):
    return '-' if v is None else v


def clusters(marks, gap):
    out = []
    for t in sorted(set(marks)):
        if out and t - out[-1][-1] <= gap:
            out[-1].append(t)
        else:
            out.append([t])
    return out


def session(win, events, points, prices):
    a, b = win[0], win[-1]
    evs = [e for e in events if a <= (e.get('ts') or 0) <= b]
    pts = [p for p in points if a <= (p.get('ts') or 0) <= b]
    kinds = {}
    for e in evs:
        k = e.get('kind') or '?'
        kinds[k] = kinds.get(k, 0) + 1
    sales = [e for e in evs if e.get('kind') == 'sale']
    buys = [e for e in evs if e.get('kind') == 'purchase']
    gross = sum(e.get('total') or 0 for e in sales)
    spent = sum(e.get('total') or 0 for e in buys)
    units = sum(int(e.get('qty') or 0) for e in sales)
    bought = sum(int(e.get('qty') or 0) for e in buys)
    p0 = pts[0] if pts else None
    p1 = pts[-1] if pts else None
    dur = (b - a) / 60.0
    net = round(gross - spent, 2)
    def v(p, k):
        return p.get(k) if p else None
    best = max(sales, key=lambda e: e.get('total') or 0) if sales else None
    states = [e.get('slug') for e in evs if e.get('slug')]
    est = sum((prices.get(s) or {}).get('wts') or 0 for s in states) or None
    if sales or buys:
        kind = 'trade'
    elif any((e.get('kind') in LIST_KINDS) for e in evs):
        kind = 'listing'
    else:
        kind = 'idle'
    return dict(
        date=time.strftime('%Y-%m-%d', time.localtime(a)), start=a, end=b,
        start_at=hhmm(a), end_at=hhmm(b), dur_min=round(dur, 1),
        kind=kind, points=len(pts), events=len(evs), kinds=kinds,
        sales=len(sales), units_sold=units, gross=round(gross, 2),
        purchases=len(buys), units_bought=bought, spent=round(spent, 2),
        net=net, plat_per_hour=round(net / max(dur / 60.0, 0.25), 1),
        plat_from=v(p0, 'plat'), plat_to=v(p1, 'plat'),
        plat_delta=((v(p1, 'plat') - v(p0, 'plat')) if (p0 and p1 and v(p0, 'plat') is not None
                    and v(p1, 'plat') is not None) else None),
        credits_delta=((v(p1, 'credits') - v(p0, 'credits')) if (p0 and p1 and v(p0, 'credits') is not None
                       and v(p1, 'credits') is not None) else None),
        items=sorted({e.get('name') or '' for e in evs if e.get('name')})[:10],
        touched_slugs=len(set(states)),
        best_sale=(dict(name=best.get('name'), qty=best.get('qty'), plat=best.get('plat'),
                        total=best.get('total')) if best else None),
    )


def main(argv):
    root, gap, last = ROOT, GAP, 50
    i = 1
    while i < len(argv):
        if argv[i] == '--root' and i + 1 < len(argv):
            root = argv[i + 1]; i += 2
        elif argv[i] == '--gap' and i + 1 < len(argv):
            gap = float(argv[i + 1]); i += 2
        elif argv[i] == '--last' and i + 1 < len(argv):
            last = int(argv[i + 1]); i += 2
        else:
            print(__doc__); return 2
    data = os.path.join(root, 'data')
    events = jload(os.path.join(data, 'trade_log.json')) or []
    points = jload(os.path.join(data, 'plat_history.json')) or []
    prices = jload(os.path.join(data, 'prices.json')) or {}
    marks = [e['ts'] for e in events if e.get('ts')] + [p['ts'] for p in points if p.get('ts')]
    if not marks:
        print('no activity history yet (trade_log / plat_history empty)')
        return 1

    sess = [session(w, events, points, prices) for w in clusters(marks, gap * 60)]
    sess.sort(key=lambda s: -s['start'])
    trade = [s for s in sess if s['kind'] == 'trade']
    gross = sum(s['gross'] for s in sess)
    spent = sum(s['spent'] for s in sess)
    tot = dict(
        sessions=len(sess), trade_sessions=len(trade),
        first_at=hhmm(sess[-1]['start']), last_at=hhmm(sess[0]['end']),
        days=len({s['date'] for s in sess}),
        in_game_hours=round(sum(s['dur_min'] for s in sess) / 60.0, 2),
        gross=round(gross, 2), spent=round(spent, 2), net=round(gross - spent, 2),
        units_sold=sum(s['units_sold'] for s in sess),
        events=sum(s['events'] for s in sess), points=sum(s['points'] for s in sess),
        best_session=(max(sess, key=lambda s: s['net'])['start_at'] if trade else None),
        best_net=(max(round(s['net'], 2) for s in trade) if trade else 0),
        busiest_session=(max(sess, key=lambda s: s['events'])['start_at'] if sess else None),
    )
    out = dict(generated=time.strftime('%Y-%m-%d %H:%M'), gap_min=gap, totals=tot,
               sessions=sess[:last], shown=min(last, len(sess)))
    json.dump(out, open(os.path.join(data, 'session_stats.json'), 'w', encoding='utf-8'), indent=1)

    print('sessions %d (%d with trades) over %d day(s), in-game %.2fh | window %s -> %s'
          % (tot['sessions'], tot['trade_sessions'], tot['days'], tot['in_game_hours'],
             tot['first_at'], tot['last_at']))
    print('events %d | points %d | gross %sp spent %sp net %sp | sold %d units'
          % (tot['events'], tot['points'], tot['gross'], tot['spent'], tot['net'], tot['units_sold']))
    for s in sess[:12]:
        print('%-7s %s -> %s %6.1fmin pts %-3d ev %-3d sales %-2d gross %-6s plat %s->%s (%s) %s'
              % (s['kind'], s['start_at'], s['end_at'][11:], s['dur_min'], s['points'],
                 s['events'], s['sales'], s['gross'], sh(s['plat_from']), sh(s['plat_to']),
                 sh(s['plat_delta']), ','.join(s['items'][:3])))
    print('wrote data/session_stats.json (%d of %d sessions)' % (out['shown'], len(sess)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
