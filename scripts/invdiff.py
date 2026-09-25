"""Inventory change tracker: snapshot owned.json and diff against the last snapshot.

Snapshots: data/inventory_snapshots/owned_YYYY-MM-DD.json (refreshed during the day when
           the current owned.json differs; first snapshot of a day is the day's baseline copy).
Reference: newest snapshot from an earlier day -> added / removed / changed lists.
Intraday:  counts since this file was last refreshed (before today's copy is overwritten).
Output:    data/invdiff.json

Usage: python invdiff.py [--root DIR] [--cap N]
"""
import json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPS = 'inventory_snapshots'


def jload(p, d=None):
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else d


def agg(items):
    """slug -> {slug,name,count,tags,ducats}; owned.json may hold several rows per slug."""
    out = {}
    for o in items or []:
        s = o.get('slug')
        if not s:
            continue
        a = out.setdefault(s, dict(slug=s, name=o.get('name') or s, count=0, tags=[], ducats=None))
        a['count'] += o.get('count') or 1
        for t in o.get('tags') or []:
            if t not in a['tags']:
                a['tags'].append(t)
        if a['ducats'] is None:
            a['ducats'] = o.get('ducats')
    return out


def wts_of(prices, slug):
    return (prices.get(slug) or {}).get('wts')


def row(a, now, prev, prices):
    w = wts_of(prices, a['slug'])
    units = now if now else prev
    return dict(slug=a['slug'], name=a['name'], prev=prev, count=now, delta=now - prev,
                wts=w, value=(w * units) if w is not None else None, ducats=a.get('ducats'),
                tags=a['tags'][:4])


def compare(cur, prev, prices, cap):
    """(added, removed, changed, summary) - each list capped, sorted by value desc."""
    added, removed, changed = [], [], []
    for s in set(cur) | set(prev):
        c, p = cur.get(s), prev.get(s)
        if p is None:
            r = row(c, c['count'], 0, prices)
            added.append((r['value'] or 0, r))
        elif c is None:
            r = row(p, 0, p['count'], prices)
            removed.append((r['value'] or 0, r))
        elif c['count'] != p['count']:
            r = row(c, c['count'], p['count'], prices)
            changed.append((abs((wts_of(prices, s) or 0) * r['delta']), r))
    for lst in (added, removed, changed):
        lst.sort(key=lambda x: -x[0])
    return ([r for _, r in added[:cap]], [r for _, r in removed[:cap]],
            [r for _, r in changed[:cap]],
            dict(added=len(added), removed=len(removed), changed=len(changed)))


def totals(a, prices):
    val = sum((wts_of(prices, s) or 0) * x['count'] for s, x in a.items())
    return dict(items=len(a), stacks=sum(x['count'] for x in a.values()), value=val)


def main(argv):
    root, cap = ROOT, 60
    i = 1
    while i < len(argv):
        if argv[i] == '--root' and i + 1 < len(argv):
            root = argv[i + 1]; i += 2
        elif argv[i] == '--cap' and i + 1 < len(argv):
            cap = int(argv[i + 1]); i += 2
        else:
            print(__doc__); return 2
    data, sdir = os.path.join(root, 'data'), os.path.join(root, 'data', SNAPS)
    os.makedirs(sdir, exist_ok=True)
    owned = jload(os.path.join(data, 'owned.json'))
    if not owned:
        print('no owned.json yet - nothing to snapshot')
        return 1
    prices = jload(os.path.join(data, 'prices.json')) or {}
    today = time.strftime('%Y-%m-%d')
    this_name = 'owned_%s.json' % today
    files = sorted(f for f in os.listdir(sdir) if f.startswith('owned_') and f.endswith('.json'))
    prior = [f for f in files if f != this_name]
    ref_name = prior[-1] if prior else None
    day_items = jload(os.path.join(sdir, this_name))

    cur, ref = agg(owned), agg(jload(os.path.join(sdir, ref_name)) if ref_name else None)
    intra = dict(added=0, removed=0, changed=0, added_names=[], removed_names=[])
    if day_items is not None and day_items != owned:
        ia, ir, ic, isum = compare(cur, agg(day_items), prices, 10)
        intra = dict(isum, added_names=[r['name'] for r in ia], removed_names=[r['name'] for r in ir])
    refreshed = day_items is None or day_items != owned
    if refreshed:
        json.dump(owned, open(os.path.join(sdir, this_name), 'w', encoding='utf-8'), indent=1)

    if ref:
        added, removed, changed, summary = compare(cur, ref, prices, cap)
        status = 'ok'
    else:
        added, removed, changed = [], [], []
        summary = dict(added=0, removed=0, changed=0)
        status = 'baseline'
    t_cur, t_ref = totals(cur, prices), totals(ref, prices)
    net_value = t_cur['value'] - t_ref['value'] if ref else 0
    out = dict(
        generated=time.strftime('%Y-%m-%d %H:%M'),
        status=status, snapshot='data/%s/%s' % (SNAPS, this_name),
        reference=('data/%s/%s' % (SNAPS, ref_name)) if ref_name else None,
        refreshed=refreshed, cap=cap,
        summary=dict(summary, net_stacks=(t_cur['stacks'] - t_ref['stacks']) if ref else 0,
                     net_value=net_value, net_items=(t_cur['items'] - t_ref['items']) if ref else 0),
        totals=dict(now=t_cur, previous=t_ref),
        intraday=intra, added=added, removed=removed, changed=changed,
        note=('no earlier snapshot yet - this run is the baseline' if status == 'baseline'
              else 'delta vs %s' % ref_name),
    )
    json.dump(out, open(os.path.join(data, 'invdiff.json'), 'w', encoding='utf-8'), indent=1)

    def sh(v):
        return '-' if v is None else v

    print('snapshot data/%s/%s (%s)' % (SNAPS, this_name, 'written' if refreshed else 'unchanged'))
    print('reference %s' % (ref_name or 'none (baseline)'))
    print('items %d stacks %d value %dp | prev stacks %d value %dp | net %+d stacks %+dp'
          % (t_cur['items'], t_cur['stacks'], t_cur['value'], t_ref['stacks'], t_ref['value'],
             out['summary']['net_stacks'], net_value))
    print('added %d | removed %d | changed %d | intraday +%d/-%d/~%d'
          % (summary['added'], summary['removed'], summary['changed'],
             intra['added'], intra['removed'], intra['changed']))
    for r in added[:10]:
        print('ADD  %-34s x%-3d (%+d) @%-4s value=%sp'
              % (r['name'][:34], r['count'], r['delta'], sh(r['wts']), sh(r['value'])))
    for r in removed[:10]:
        print('REM  %-34s -%-3d (%+d) @%-4s value=%sp'
              % (r['name'][:34], r['prev'], r['delta'], sh(r['wts']), sh(r['value'])))
    for r in changed[:10]:
        print('CHG  %-34s x%d -> x%d (%+d) @%-4s value=%sp'
              % (r['name'][:34], r['prev'], r['count'], r['delta'], sh(r['wts']), sh(r['value'])))
    print('wrote data/invdiff.json')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
