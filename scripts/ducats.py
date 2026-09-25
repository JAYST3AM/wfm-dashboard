"""Ducat optimizer -- sell a prime part for platinum, or burn it into ducats?

For every owned prime part that carries a ducat value, compare what it fetches
on warframe.market (wts = lowest sell listing = realistic quick-sale price)
against the ducats the Void Trader gives for it, and rank by DUCATS PER PLATINUM:

    ducats_per_plat = ducats / wts        (per unit, count-independent rank key)

High value (>= BURN_RATIO) = ducat-dense: the part is a cheap source of ducats,
so burning beats selling. Low value = plat-dense: sell it; only if you then need
ducats, rebuy prime junk at the same reference rate.

Reference rate: prime junk moves in trade chat at ~2p per 15-ducat part, i.e.
2p = 15 ducats -> 7.5 ducats per platinum. A part yielding MORE ducats per plat
than junk costs is worth burning; edge_plat is the per-stack profit of selling
instead (positive -> sell, negative -> burn).

Inputs:  data/owned.json, data/prices.json, data/stats.json, data/lastData.dec.json
Output:  data/ducats.json
Run:     python scripts/ducats.py [--ratio 7.5] [--min-sell 4]
"""
import json, os, time, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
BURN_RATIO = 7.5      # ducats per plat: junk rate (2p per 15-ducat part)
MIN_SELL_PLAT = 4.0   # a stack worth less than this is not worth a trade slot


def load(name, default=None):
    p = os.path.join(DATA, name)
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else default


def aggregate(owned):
    """One row per slug: ducat parts only, counts summed across owned entries."""
    agg = {}
    for o in owned:
        if not o.get('ducats'):
            continue
        a = agg.setdefault(o['slug'], dict(slug=o['slug'], name=o['name'], count=0,
                                           ducats=0, conflict=False, tags=set()))
        a['count'] += o.get('count') or 1
        d = o['ducats']
        if a['ducats'] and d != a['ducats']:
            a['conflict'] = True
        a['ducats'] = max(a['ducats'], d)
        a['tags'].update(o.get('tags') or [])
    return agg


def classify(a, price, stat, ratio, min_sell):
    """SELL / BURN / HOLD for one aggregated part."""
    count, duc = a['count'], a['ducats']
    wts = (price or {}).get('wts')
    duc_total = duc * count
    row = dict(slug=a['slug'], name=a['name'], count=count, ducats=duc,
               ducats_total=duc_total, tags=sorted(a['tags']), conflict=a['conflict'],
               wts=wts, wtb=(price or {}).get('wtb'), n_sell=(price or {}).get('n_sell'),
               median=(stat or {}).get('median'), vol48=(stat or {}).get('vol48') or 0,
               volday=(stat or {}).get('volday90') or 0)
    if wts is None:                                   # no market price at all
        row.update(sell_total=None, ducats_per_plat=None, edge_plat=None,
                   verdict='HOLD', reason='no sell listing - cannot price it')
        return row
    sell_total = wts * count
    q = duc / wts                                     # ducats per platinum
    junk_cost = duc_total / ratio                     # plat to buy those ducats as junk
    row.update(sell_total=sell_total, ducats_per_plat=round(q, 2),
               plat_per_ducat=round(wts / duc, 3), junk_cost=round(junk_cost, 1),
               edge_plat=round(sell_total - junk_cost, 1))
    if q >= ratio:
        row.update(verdict='BURN',
                   reason='ducat-dense %.1f d/p >= junk rate %.1f' % (q, ratio))
    elif sell_total >= min_sell:
        row.update(verdict='SELL',
                   reason='plat-dense %.1f d/p < junk rate %.1f' % (q, ratio))
    else:
        row.update(verdict='HOLD',
                   reason='stack worth only %.1fp (< %.0fp) - trade slot not worth it'
                          % (sell_total, min_sell))
    return row


def main():
    ap = argparse.ArgumentParser(description='Ducat optimizer: sell vs burn prime parts')
    ap.add_argument('--ratio', type=float, default=BURN_RATIO,
                    help='ducats per platinum junk reference rate (default %.1f)' % BURN_RATIO)
    ap.add_argument('--min-sell', type=float, default=MIN_SELL_PLAT,
                    help='min stack plat worth a trade slot (default %.0f)' % MIN_SELL_PLAT)
    args = ap.parse_args()

    owned = load('owned.json', []) or []
    prices = load('prices.json', {}) or {}
    stats = load('stats.json', {}) or {}
    dec = load('lastData.dec.json', {}) or {}

    rows = [classify(a, prices.get(s), stats.get(s), args.ratio, args.min_sell)
            for s, a in aggregate(owned).items()]
    rows.sort(key=lambda r: (-(r['ducats_per_plat'] or 0), -(r['ducats_total'] or 0)))

    sell = [r for r in rows if r['verdict'] == 'SELL']
    burn = [r for r in rows if r['verdict'] == 'BURN']
    hold = [r for r in rows if r['verdict'] == 'HOLD']
    sell.sort(key=lambda r: -r['sell_total'])
    tot_burn_d = sum(r['ducats_total'] for r in burn)
    tot_sell_p = sum(r['sell_total'] for r in sell)
    forgone_p = sum(r['sell_total'] for r in burn)          # plat given up by burning
    junk_match = round(tot_burn_d / args.ratio, 1)          # cost of those ducats as junk

    out = dict(
        generated=time.strftime('%Y-%m-%d %H:%M'),
        params=dict(burn_ratio=args.ratio, min_sell_plat=args.min_sell,
                    junk_rate='2p per 15-ducat part = %.1f ducats/plat' % args.ratio,
                    rank_key='ducats_per_plat = ducats / wts (desc)'),
        account=dict(mr=dec.get('PlayerLevel'), trades_available=dec.get('TradesRemaining')),
        summary=dict(slugs=len(rows), sell_count=len(sell), burn_count=len(burn),
                     hold_count=len(hold), total_burn_ducats=tot_burn_d,
                     total_sell_plat=tot_sell_p,
                     burn_plat_forgone=forgone_p, junk_cost_to_match=round(junk_match, 1),
                     burn_is_cheaper_by=round(junk_match - forgone_p, 1),
                     ducats_owned=sum(r['ducats_total'] for r in rows),
                     plat_if_all_sold=sum(r['sell_total'] or 0 for r in rows)),
        buckets=dict(sell=[r['slug'] for r in sell], burn=[r['slug'] for r in burn],
                     hold=[r['slug'] for r in hold]),
        rows=rows)
    json.dump(out, open(os.path.join(DATA, 'ducats.json'), 'w', encoding='utf-8'), indent=1)

    def line(r):
        return ('%-38s x%-3d %4dd %4dd %6s %4sp %6s  %s'
                % (r['name'][:38], r['count'], r['ducats'], r['ducats_total'],
                   r['ducats_per_plat'], r['wts'], r['sell_total'], r['verdict']))
    print('DUCAT OPTIMIZER  ratio %.1f d/p (junk rate)  min sell %.0fp  MR %s / %s trades'
          % (args.ratio, args.min_sell, dec.get('PlayerLevel'), dec.get('TradesRemaining')))
    print('name                                   qty duc  tot   d/plat  wts  sell   verdict')
    print('--- BURN: %d parts, %d ducats (plat forgone %dp; same ducats as junk = %sp)'
          % (len(burn), tot_burn_d, forgone_p, junk_match))
    for r in burn[:10]:
        print(line(r))
    print('--- SELL: %d parts, %sp' % (len(sell), tot_sell_p))
    for r in sell[:6]:
        print(line(r))
    print('--- HOLD: %d parts' % len(hold))
    for r in hold[:3]:
        print(line(r) + '   (' + r['reason'] + ')')
    conf = [r['slug'] for r in rows if r['conflict']]
    print('buckets: SELL=%d BURN=%d HOLD=%d | ducats owned=%d | burn %d d vs %sp junk'
          % (len(sell), len(burn), len(hold), out['summary']['ducats_owned'],
             tot_burn_d, junk_match))
    if conf:
        print('note: conflicting ducat values for %d slug(s): %s' % (len(conf), conf[:5]))
    print('wrote ' + os.path.join('data', 'ducats.json'))


if __name__ == '__main__':
    main()
