"""Liquidity + margin research over owned inventory.

Inputs:  data/owned.json, data/prices.json, data/stats.json, data/inuse.json
Outputs: data/report.json (machine), data/report.md (human)

Copies slotted in any loadout config are never sellable, so every qty/value here is the
sellable side of the stack: `count` is still everything owned (the dashboard shows it),
`sellable_count` is count minus the equipped copies, and `value` prices sellable copies
only. A row with nothing left to sell stays in the report with `in_use_only: true` and a
zero value, so it never inflates a total. Missing/torn data/inuse.json degrades to plain
ownership (the hard gate that refuses to list an equipped copy lives in trader/lister.py).
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


def in_use_counts(doc):
    """{slug: equipped copies} from data/inuse.json (scripts/trader/inuse.py output).

    One physical copy counts once even when the same item_id is slotted in several loadout
    configs (mirrors trader/riven_lister.in_use_counts), and rows without a slug cannot be
    attributed to a stack, so they are skipped. A missing or torn document returns {}
    (no in-use data -> the report falls back to plain ownership).
    """
    if not isinstance(doc, dict) or not isinstance(doc.get('items'), list):
        return {}
    seen, out = set(), {}
    for it in doc['items']:
        if not isinstance(it, dict):
            continue
        slug = it.get('slug')
        if not slug:
            continue
        iid = it.get('item_id')
        if iid:
            if iid in seen:
                continue
            seen.add(iid)
        out[slug] = out.get(slug, 0) + 1
    return out


def pick_score(r, base=None):
    """Sell-now ranking key: earnings x how fast the stack moves (higher = sell sooner)."""
    return (r['value'] if base is None else base) * min(1 + r['vol48'] / max(r['count'], 1), 4)


def lane_price(lane_doc, rank):
    """(ask, bid) at the owned rank from a price_lanes.json entry, or None.

    None means "no order book to read" - the slug has no lane snapshot at all
    (unranked tradeable, untradeable, or never fetched), so the item-level quote
    stands. A slug WITH lanes but no orders at that rank resolves to (None, None)
    on purpose: the item-level wts/wtb belong to other ranks (usually rank 0) and
    would misprice this copy.
    """
    if not isinstance(lane_doc, dict) or not isinstance(rank, int):
        return None
    cells = lane_doc.get('lanes') or {}
    if not isinstance(cells, dict) or not cells:
        return None
    cell = cells.get(str(rank))
    cell = cell if isinstance(cell, dict) else {}

    def side(key):
        v = cell.get(key)
        return v if isinstance(v, (int, float)) and v > 0 else None
    return side('ask'), side('bid')


def own_ranks_of(cards_doc):
    """{slug: owned_rank} from mod_cards.json - the rank the save proves is owned."""
    cards = (cards_doc or {}).get('cards') or []
    return {c['slug']: c['owned_rank'] for c in cards
            if c.get('slug') and isinstance(c.get('owned_rank'), int)}


def build_rows(owned, prices, stats, dec, in_use, lanes=None, own_ranks=None):
    """Aggregate owned rows + price/stat snapshots into report rows.

    One source of truth for copy maths: `scripts/report.py` writes these rows to
    report.json and `scripts/sell_advisor.py` consumes them for "what should I do
    with this item" advice — never re-derive counts anywhere else.
    """
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
        # A ranked copy is priced from its own rank lane, never from the any-rank quote:
        # the item-level wts is usually a rank-0 listing while wtb can be a rank-10 bid.
        lane_rank = None
        lane_ask = lane_bid = None
        l_doc = (lanes or {}).get(s)
        o_rank = (own_ranks or {}).get(s)
        if isinstance(o_rank, int) and isinstance(l_doc, dict):
            resolved = lane_price(l_doc, o_rank)
            if resolved is not None:
                lane_rank, (lane_ask, lane_bid) = o_rank, resolved
                wts, wtb = lane_ask, lane_bid
        count = a['count']
        vol48 = t.get('vol48') or 0
        vold = t.get('volday90') or 0
        med = t.get('med48')
        # equipped copies come off the quantity this report prices (never sell a slotted copy)
        in_use_count = min(in_use.get(s, 0), count)
        sellable_count = count - in_use_count
        val = (wts or 0) * sellable_count
        rows.append(dict(
            slug=s, name=a['name'], cat=cat_of(a['tags']), count=count,
            dupes=a['refs'] or None, ducats=a['ducats'],
            wts=wts, wtb=wtb, med=round(med, 1) if med else None,
            lane_rank=lane_rank, lane_ask=lane_ask, lane_bid=lane_bid,
            mn48=t.get('min48'), mx48=t.get('max48'),
            n_sell=p.get('n_sell'), n_buy=p.get('n_buy'),
            vol48=vol48, volday=round(vold, 2),
            est_days=(round(sellable_count / vold, 1) if (vold > 0 and sellable_count) else None),
            value=val, spread=(wts - wtb) if (wts is not None and wtb is not None) else None,
            sellable_count=sellable_count, in_use_count=in_use_count,
            in_use_only=(sellable_count == 0 and in_use_count > 0),
        ))
    return rows


def main():
    owned = load('owned.json') or []
    prices = load('prices.json') or {}
    stats = load('stats.json') or {}
    dec = load('lastData.dec.json') or {}
    in_use = in_use_counts(load('inuse.json'))
    lanes = (load('price_lanes.json') or {}).get('items') or {}
    own_ranks = own_ranks_of(load('mod_cards.json'))

    rows = build_rows(owned, prices, stats, dec, in_use, lanes, own_ranks)

    sellable = [r for r in rows if r['wts'] is not None]
    tot_val = sum(r['value'] for r in sellable)                        # sellable copies only
    tot_owned = sum((r['wts'] or 0) * r['count'] for r in sellable)    # every owned copy
    in_use_copies = sum(r['in_use_count'] for r in sellable)
    by_cat = {}
    for r in sellable:
        by_cat[r['cat']] = by_cat.get(r['cat'], 0) + r['value']

    # ---- Sell-now: real market activity + worthwhile value ----
    # Worthwhileness still judges the whole stack (so a mostly-equipped stack stays visible),
    # but the ranking prices sellable copies only: a row with none left sinks behind every
    # pick, kept and flagged rather than dropped.
    cands = [r for r in sellable if r['vol48'] >= 2 and (r['wts'] or 0) * r['count'] >= 6]
    picks = [r for r in cands if r['sellable_count']]
    picks.sort(key=lambda r: -pick_score(r))
    blocked = [r for r in cands if not r['sellable_count']]
    blocked.sort(key=lambda r: -pick_score(r, (r['wts'] or 0) * r['count']))
    sell_now = picks[:30] + blocked

    # ---- Patient: high value, thin market (value is sellable-only, so a fully equipped
    #      stack drops out on its own) ----
    patient = [r for r in sellable if r['value'] >= 12 and r['vol48'] < 2]
    patient.sort(key=lambda r: -r['value'])
    patient = patient[:20]

    # ---- Flips: buy orders below sell floor with live demand ----
    flips = [r for r in rows if r['wtb'] is not None and r['wts'] is not None
             and (r['wts'] - r['wtb']) >= 1 and r['vol48'] >= 1]
    flips.sort(key=lambda r: -((r['wts'] - r['wtb']) * max(r['volday'], 0.2)))
    flips = flips[:25]

    # ---- Bulk junk: cheap mods in quantity (endo fodder / bulk trade) ----
    junk = [r for r in sellable if (r['wts'] or 0) <= 2 and r['sellable_count'] >= 3]
    junk_val = sum(r['value'] for r in junk)

    report = dict(
        generated=time.strftime('%Y-%m-%d %H:%M'),
        mr=dec.get('PlayerLevel'), trades=dec.get('TradesRemaining'),
        in_use=dict(available=bool(in_use), copies=in_use_copies, value=tot_owned - tot_val),
        totals=dict(value=tot_val, value_owned=tot_owned,
                    sellable_slugs=sum(1 for r in sellable if r['sellable_count']),
                    stacks=sum(r['sellable_count'] for r in sellable),
                    by_cat=by_cat),
        sell_now=sell_now, patient=patient, flips=flips,
        junk=dict(count=len(junk), value=junk_val, rows=junk[:40]),
    )
    json.dump(report, open(os.path.join(DATA, 'report.json'), 'w', encoding='utf-8'), indent=1)

    def tbl(rs):
        out = ['| Item | Qty | Sellable | List@ | Med48 | Vol48 | Vol/day | Sellers | Value | Est days |',
               '|---|---|---|---|---|---|---|---|---|---|']
        for r in rs:
            out.append(f"| {r['name']} | {r['count']} | {r['sellable_count']} | {r['wts']} | {r['med']} | "
                       f"{r['vol48']} | {r['volday']} | {r['n_sell']} | {r['value']} | {r['est_days']} |")
        return '\n'.join(out)

    note = ('' if not blocked else
            f"\n\nSellable 0 = every owned copy is slotted in a build ({len(blocked)} such rows kept here).")
    md = [f"# WFM research — {report['generated']}",
          f"MR {report['mr']} · {report['trades']} trades left today · sellable street value **{tot_val}p** "
          f"across {report['totals']['sellable_slugs']} priced items ({tot_owned}p if every owned copy sold; "
          f"{in_use_copies} copies worth {tot_owned - tot_val}p are slotted in builds and never sellable)",
          '',
          '## Value by category', '']
    for k, v in sorted(by_cat.items(), key=lambda x: -x[1]):
        md.append(f'- **{k}**: {v}p')
    md += ['', '## Sell now (liquid, worthwhile)', '', tbl(sell_now) + note,
           '', '## Patient (high value, thin market)', '', tbl(patient),
           '', '## Flip candidates (buy order margin)', '', tbl(flips),
           '', f"## Bulk junk: {len(junk)} stacks, {junk_val}p total (endo fodder or bulk lot)"]
    open(os.path.join(DATA, 'report.md'), 'w', encoding='utf-8').write('\n'.join(md))

    print('report.json + report.md written')
    print(f"total value {tot_val}p sellable | {tot_owned}p owned incl. equipped copies "
          f"({in_use_copies} copies / {tot_owned - tot_val}p in builds, in-use data "
          f"{'ok' if in_use else 'missing -> plain ownership'})")
    print(f"sellable {len(sellable)} priced rows | sell_now {len(sell_now)} ({len(picks[:30])} picks + "
          f"{len(blocked)} in-use-only) | patient {len(patient)} | flips {len(flips)} | junk {len(junk)} ({junk_val}p)")
    for r in sell_now[:12]:
        print(f"SELL {r['name']:38s} x{r['count']:<3} sellable={r['sellable_count']:<3} "
              f"in_use={r['in_use_count']:<3} @{r['wts']:<4} vol48={r['vol48']:<5} med={r['med']} val={r['value']}")
    for r in flips[:8]:
        print(f"FLIP {r['name']:38s} buy@{r['wtb']:<4} sell@{r['wts']:<4} spread={r['spread']} vol/day={r['volday']}")


if __name__ == '__main__':
    main()
