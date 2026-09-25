"""Liquidity + margin research over owned inventory.

Inputs:  data/owned.json, data/prices.json, data/stats.json
Outputs: data/report.json (machine), data/report.md (human)
"""
import json, os, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')


def load(n, d=None):
    p = os.path.join(DATA, n)
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else d


def cat_of(tags):
    tags = set(tags or [])
    if 'relic' in tags: return 'relic'
    if 'mod' in tags: return 'mod'
    if 'arcane_enhancement' in tags: return 'arcane'
    if 'prime' in tags and 'set' in tags: return 'prime_set'
    if 'prime' in tags and 'component' in tags: return 'prime_part'
    if 'prime' in tags and 'blueprint' in tags: return 'prime_bp'
    return 'other'


def main():
    owned = load('owned.json') or []
    prices = load('prices.json') or {}
    stats = load('stats.json') or {}
    dec = load('lastData.dec.json') or {}

    agg = {}
    for o in owned:
        s = o['slug']
        a = agg.setdefault(s, dict(slug=s, name=o['name'], count=0, ducats=o.get('ducats'),
                                   tags=set(), refs={}))
        a['count'] += o.get('count') or 1
        a['tags'].update(o.get('tags') or [])
        if o.get('refinement'):
            a['refs'][o['refinement']] = a['refs'].get(o['refinement'], 0) + (o.get('count') or 1)

    rows = []
    for s, a in agg.items():
        p = prices.get(s) or {}
        t = stats.get(s) or {}
        wts, wtb = p.get('wts'), p.get('wtb')
        count = a['count']
        vol48 = t.get('vol48') or 0
        vold = t.get('volday90') or 0
        med = t.get('med48')
        val = (wts or 0) * count
        rows.append(dict(
            slug=s, name=a['name'], cat=cat_of(a['tags']), count=count,
            dupes=a['refs'] or None, ducats=a['ducats'],
            wts=wts, wtb=wtb, med=round(med, 1) if med else None,
            mn48=t.get('min48'), mx48=t.get('max48'),
            n_sell=p.get('n_sell'), n_buy=p.get('n_buy'),
            vol48=vol48, volday=round(vold, 2),
            est_days=(round(count / vold, 1) if vold > 0 else None),
            value=val, spread=(wts - wtb) if (wts is not None and wtb is not None) else None,
        ))

    sellable = [r for r in rows if r['wts'] is not None]
    tot_val = sum(r['value'] for r in sellable)
    by_cat = {}
    for r in sellable:
        by_cat[r['cat']] = by_cat.get(r['cat'], 0) + r['value']

    # ---- Sell-now: real market activity + worthwhile value ----
    sell_now = [r for r in sellable if r['vol48'] >= 2 and r['value'] >= 6]
    sell_now.sort(key=lambda r: (-(r['value'] * min(1 + r['vol48'] / max(r['count'], 1), 4))))
    sell_now = sell_now[:30]

    # ---- Patient: high value, thin market ----
    patient = [r for r in sellable if r['value'] >= 12 and r['vol48'] < 2]
    patient.sort(key=lambda r: -r['value'])
    patient = patient[:20]

    # ---- Flips: buy orders below sell floor with live demand ----
    flips = [r for r in rows if r['wtb'] is not None and r['wts'] is not None
             and (r['wts'] - r['wtb']) >= 1 and r['vol48'] >= 1]
    flips.sort(key=lambda r: -((r['wts'] - r['wtb']) * max(r['volday'], 0.2)))
    flips = flips[:25]

    # ---- Bulk junk: cheap mods in quantity (endo fodder / bulk trade) ----
    junk = [r for r in sellable if (r['wts'] or 0) <= 2 and r['count'] >= 3]
    junk_val = sum(r['value'] for r in junk)

    report = dict(
        generated=time.strftime('%Y-%m-%d %H:%M'),
        mr=dec.get('PlayerLevel'), trades=dec.get('TradesRemaining'),
        totals=dict(value=tot_val, sellable_slugs=len(sellable), stacks=sum(r['count'] for r in sellable),
                    by_cat=by_cat),
        sell_now=sell_now, patient=patient, flips=flips,
        junk=dict(count=len(junk), value=junk_val, rows=junk[:40]),
    )
    json.dump(report, open(os.path.join(DATA, 'report.json'), 'w', encoding='utf-8'), indent=1)

    def tbl(rs):
        out = ['| Item | Qty | List@ | Med48 | Vol48 | Vol/day | Sellers | Value | Est days |',
               '|---|---|---|---|---|---|---|---|---|']
        for r in rs:
            out.append(f"| {r['name']} | {r['count']} | {r['wts']} | {r['med']} | {r['vol48']} | "
                       f"{r['volday']} | {r['n_sell']} | {r['value']} | {r['est_days']} |")
        return '\n'.join(out)

    md = [f"# WFM research — {report['generated']}",
          f"MR {report['mr']} · {report['trades']} trades left today · total street value **{tot_val}p** "
          f"across {len(sellable)} sellable items",
          '',
          '## Value by category', '']
    for k, v in sorted(by_cat.items(), key=lambda x: -x[1]):
        md.append(f'- **{k}**: {v}p')
    md += ['', '## Sell now (liquid, worthwhile)', '', tbl(sell_now),
           '', '## Patient (high value, thin market)', '', tbl(patient),
           '', '## Flip candidates (buy order margin)', '', tbl(flips),
           '', f"## Bulk junk: {len(junk)} stacks, {junk_val}p total (endo fodder or bulk lot)"]
    open(os.path.join(DATA, 'report.md'), 'w', encoding='utf-8').write('\n'.join(md))

    print('report.json + report.md written')
    print(f"total value {tot_val}p | sellable {len(sellable)} | sell_now {len(sell_now)} | patient {len(patient)} | flips {len(flips)} | junk {len(junk)} ({junk_val}p)")
    for r in sell_now[:12]:
        print(f"SELL {r['name']:38s} x{r['count']:<3} @{r['wts']:<4} vol48={r['vol48']:<5} med={r['med']} val={r['value']}")
    for r in flips[:8]:
        print(f"FLIP {r['name']:38s} buy@{r['wtb']:<4} sell@{r['wts']:<4} spread={r['spread']} vol/day={r['volday']}")


if __name__ == '__main__':
    main()
