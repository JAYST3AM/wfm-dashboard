#!/usr/bin/env python3
"""Smart sell advisor - "what should I actually do with this item right now?"

Integration layer. It owns no data of its own: every fact comes from a module the
dashboard already runs, so the numbers can never drift apart.

  scripts/report.py        copy maths (owned / equipped / sellable) + floor, median,
                           vol48, vol/day, est days          -> report.build_rows()
  data/trends.json         demand badge (spike|steady|fade) + 30d price trend %
  data/price_history.json  price direction fallback when trends.json lacks the slug
  data/ducats.json         ducat-vs-plat verdict per prime part (BURN pays more)
  data/craft.json          parts earmarked to craft results he still wants
  data/sets.json           near-complete sets (held parts stay for the set sale)
  data/collection_log.json items still missing from the collection
  data/baro.json           Baro Ki'Teer visit context
  data/relic_ev.json       relic open-vs-sell verdicts (EV vs sell floor)
  data/sell_timing.json    when this account actually sells (hours, per kind)
  data/trade_log.json      sale history (has he sold this exact item before?)
  data/trader_plan.json    rows already queued for listing (never double-sell)
  data/self_orders.json    live WFM orders (an empty book means nothing is listed)

Output: data/sell_advisor.json
  {"generated", "counts", "items": {slug: rec}, "ranked": [slug, ...]}
rec = {item, name, owned, equipped, reserved, sellable, market_price, median,
       trend, price_trend_pct, liquidity, vol48, volday, best_sell_window,
       recommendation, recommended_quantity, recommended_price, reasons[], text,
       score}

Rules (Jay's spec):
  * equipped copies are never sellable (report.build_rows already removes them);
  * one spare copy stays for the collection when the item is a collection card (mods);
  * parts of a near-complete set / a profitable craft are reserved, not sold;
  * a factor without data is OMITTED, never guessed;
  * the text explains WHY, it does not just print a score.

Stdlib only, local files only, no network. Deterministic: same inputs -> same file
(content hash + reused stamp, like nudges.py).
"""
import argparse
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, 'data')
OUT = os.path.join(DATA, 'sell_advisor.json')
if HERE not in sys.path:                      # `python scripts/sell_advisor.py`
    sys.path.insert(0, HERE)

import report                                  # noqa: E402  (copy maths, one source)
import sell_timing                             # noqa: E402  (sale-hour stats)
from nudges import liquidity_conf, units_missing, held_slugs   # noqa: E402

VERSION = 1
STAMP = '%Y-%m-%d %H:%M'
DEMAND_MULT = {'spike': 1.25, 'steady': 1.0, 'fade': 0.8}
MAX_LIST = 200                                 # ranked list cap in the output doc


# ------------------------------------------------------------------ io helpers
def load(name, default=None):
    """Load data/<name>; return default when missing or unreadable."""
    path = os.path.join(DATA, name)
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def ascii_s(value):
    return str(value).encode('ascii', 'replace').decode('ascii')


def fnum(value, default=0.0):
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def optnum(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def pfmt(value):
    """Platinum: whole numbers stay whole, otherwise one decimal."""
    v = optnum(value)
    if v is None:
        return None
    return str(int(v)) if abs(v - round(v)) < 0.05 else '%.1f' % v


def hours_window(best_hours):
    """[{hour,...}] -> '20:00-22:00' when the top hours are contiguous, else '20:00, 22:00'."""
    hours = sorted({int(h.get('hour')) for h in best_hours if h.get('hour') is not None})
    if not hours:
        return None
    if len(hours) == 1:
        return '%02d:00' % hours[0]
    head = hours[:3]
    if head == list(range(head[0], head[0] + len(head))):
        return '%02d:00-%02d:00' % (head[0], head[-1] + 1)
    return ', '.join('%02d:00' % h for h in head)


# ------------------------------------------------------------------ context
def build_context():
    """Everything the advisor reads, loaded once."""
    owned = load('owned.json', []) or []
    prices = load('prices.json', {}) or {}
    stats = load('stats.json', {}) or {}
    dec = load('lastData.dec.json', {}) or {}
    in_use = report.in_use_counts(load('inuse.json', {}))
    lanes = (load('price_lanes.json', {}) or {}).get('items') or {}
    own_ranks = report.own_ranks_of(load('mod_cards.json', {}))
    rows = report.build_rows(owned, prices, stats, dec, in_use, lanes, own_ranks)
    by_slug = {r['slug']: r for r in rows}

    trends = {}
    for r in ((load('trends.json', {}) or {}).get('rows') or []):
        if r.get('slug'):
            trends[r['slug']] = r

    ducats = {}
    for r in ((load('ducats.json', {}) or {}).get('rows') or []):
        if r.get('slug'):
            ducats[r['slug']] = r

    # parts reserved to craft something (verdict CRAFT = the craft is worth doing)
    craft_res = {}
    for r in ((load('craft.json', {}) or {}).get('rows') or []):
        if str(r.get('verdict', '')).upper() != 'CRAFT':
            continue
        for slug in (r.get('owned_parts') or []):
            craft_res[slug] = r.get('result_name') or r.get('result_slug')

    # near-complete sets keep their held parts (same rule nudges.py uses)
    set_nodes = (load('sets.json', {}) or {}).get('sets') or []
    set_res = {}
    for row in set_nodes:
        um = units_missing(row)
        if um > 1:
            continue
        missing = row.get('missing') if isinstance(row.get('missing'), list) else []
        miss0 = missing[0] if missing else {}
        info = {'set': row.get('slug'), 'set_name': str(row.get('name', '')), 'missing': um,
                'set_value': optnum(row.get('set_value')), 'profit': optnum(row.get('profit')),
                'roi': optnum(row.get('roi')),
                'missing_part': str(miss0.get('slug', '')),
                'missing_name': str(miss0.get('name', '')),
                'cost_missing': optnum(row.get('cost_missing')) or optnum(row.get('cost_est'))}
        for part in held_slugs(row):
            set_res[part] = info
    cash_out = {str(c.get('part', '')): c
                for c in ((load('sets.json', {}) or {}).get('cash_out_parts') or [])
                if c.get('part')}

    # collection: items still missing (owned:false) + every collection slug
    coll_all, coll_missing = set(), set()
    for cat in ((load('collection_log.json', {}) or {}).get('categories') or []):
        for it in (cat.get('items') or []):
            slug = it.get('slug')
            if not slug:
                continue
            coll_all.add(slug)
            if not it.get('owned'):
                coll_missing.add(slug)

    mod_slugs = {c.get('slug') for c in ((load('mod_cards.json', {}) or {}).get('cards') or [])
                 if c.get('slug')}

    relics = {}
    for r in ((load('relic_ev.json', {}) or {}).get('rows') or []):
        if r.get('slug'):
            key = (r['slug'], str(r.get('refinement') or ''))
            relics[key] = r

    timing = load('sell_timing.json', {}) or {}
    trade_log = load('trade_log.json', []) or []
    sales_by_name = {}
    for ev in (trade_log if isinstance(trade_log, list) else trade_log.get('events') or []):
        if isinstance(ev, dict) and ev.get('kind') == 'sale' and ev.get('name'):
            sales_by_name[ev['name']] = sales_by_name.get(ev['name'], 0) + 1

    plan = load('trader_plan.json', {}) or {}
    queued = {str(r.get('slug')): r for r in (plan.get('plan') or []) if r.get('slug')}

    orders = load('self_orders.json', [])
    if isinstance(orders, dict):
        orders = orders.get('orders') or []
    live = {str(o.get('item', {}).get('slug') if isinstance(o.get('item'), dict) else o.get('slug')):
            o for o in orders if (o.get('type') == 'sell')}

    baro = load('baro.json', {}) or {}

    return dict(rows=rows, by_slug=by_slug, trends=trends, ducats=ducats,
                craft_res=craft_res, set_res=set_res, cash_out=cash_out,
                coll_all=coll_all, coll_missing=coll_missing, mod_slugs=mod_slugs,
                relics=relics, timing=timing, sales_by_name=sales_by_name,
                queued=queued, live=live, baro=baro)


# ------------------------------------------------------------------ one item
def advise(slug, ctx, now=None):
    """The structured recommendation for one owned slug (plus the human text)."""
    row = ctx['by_slug'].get(slug)
    if row is None:
        return None
    now = now or time.localtime()
    name = row.get('name') or slug
    owned = int(row.get('count') or 0)
    equipped = int(row.get('in_use_count') or 0)
    spares = max(0, owned - equipped)

    reasons, notes = [], []

    # ---- reservations (never sold) ----
    keeper = 0
    if spares >= 1 and slug in ctx['mod_slugs']:
        keeper = 1
        reasons.append('1 stays in the mod collection')
    collection_need = 1 if (spares >= 1 and slug in ctx['coll_missing']) else 0
    if collection_need and not keeper:
        keeper = 1
        reasons.append('still missing from your collection - keep 1')
    craft_for = ctx['craft_res'].get(slug) if spares >= 1 else None
    set_for = ctx['set_res'].get(slug) if spares >= 1 else None
    reserved = min(spares, keeper + (1 if craft_for else 0) + (1 if set_for else 0))
    sellable = max(0, spares - reserved)

    # ---- market facts ----
    price = optnum(row.get('wts'))
    median = optnum(row.get('med'))
    lane_rank = int(row['lane_rank']) if isinstance(row.get('lane_rank'), int) else None
    if price is None and median is not None and lane_rank is None:
        # An all-rank median is a mix (rank-0 sales dominate it). Only fall back to it
        # for unranked items - a ranked copy with no lane price has no honest quote.
        price = median
        notes.append('no seller listed - using the 48h median')
    vol48 = int(row.get('vol48') or 0)
    volday = optnum(row.get('volday')) or 0.0
    trend_row = ctx['trends'].get(slug) or {}
    badge = trend_row.get('badge')
    if badge not in DEMAND_MULT:
        badge = None
    pct = optnum(trend_row.get('price_trend_pct'))
    liquidity = liquidity_conf(vol48) if (vol48 or volday) else None

    # ---- own sale history for this item / category ----
    sold_n = ctx['sales_by_name'].get(name, 0)
    kind = row.get('cat') or 'other'
    kind_row = ((ctx['timing'].get('by_kind') or {}).get(kind)) or {}
    window = hours_window(kind_row.get('best_hours') or [])
    window_src = kind
    if window is None:
        window = hours_window(ctx['timing'].get('hours') or [])
        window_src = 'all items'
    timing_note = kind_row.get('note')

    # ---- relic verdict (own row beats raw EV maths) ----
    relic_call = None
    relic_row = None
    for (rslug, _ref), rrow in ctx['relics'].items():
        if rslug == slug:
            relic_row = rrow
            break
    if relic_row is not None:
        verdict = str(relic_row.get('verdict') or relic_row.get('action') or '').upper()
        ev_u, sell_u = optnum(relic_row.get('ev_unit_wts')), optnum(relic_row.get('relic_wts'))
        if 'OPEN' in verdict:
            relic_call = 'open'
        elif 'SELL' in verdict or 'HOLD' in verdict:
            relic_call = 'sell'
        elif ev_u is not None and sell_u is not None:
            relic_call = 'open' if ev_u > sell_u * 1.1 else 'sell'

    # ---- Baro context ----
    trader = ctx['baro'].get('trader') or {}
    baro_line = None
    if ctx['baro'].get('generated'):
        if trader.get('active'):
            baro_line = 'Baro is live now (his stock adds supply - other sellers may undercut)'
        elif optnum(trader.get('starts_in_days')) is not None and \
                fnum(trader.get('starts_in_days'), 99) <= 3:
            baro_line = 'Baro lands in %s - some sellers wait for his stock' % trader.get('starts_in')
        else:
            baro_line = 'No obvious Baro-related supply pressure'

    # ---- queued / listed already ----
    plan_row = ctx['queued'].get(slug)
    live_row = ctx['live'].get(slug)

    # ---- decide ----
    rec, qty, rec_price = 'hold', 0, price
    if live_row is not None:
        rec, qty = 'already_listed', int(live_row.get('quantity') or 0)
        notes.append('live sell order on the market')
    elif plan_row is not None:
        rec, qty = 'already_listed', int(plan_row.get('qty') or 0)
        rec_price = optnum(plan_row.get('price')) or price
        notes.append('queued in the trader plan (qty %s @ %sp)'
                     % (plan_row.get('qty'), pfmt(plan_row.get('price'))))
    elif sellable == 0:
        if owned == 0:
            return None
        if equipped and equipped >= owned:
            rec = 'keep'
            reasons.append('every copy is slotted in a loadout')
        elif craft_for:
            rec = 'keep'
            reasons.append('earmarked to craft %s' % craft_for)
        elif set_for and set_for.get('missing') == 0:
            rec, qty, rec_price = 'assemble_set', 1, set_for.get('set_value')
        elif set_for and set_for.get('missing') == 1 and fnum(set_for.get('roi'), -1) >= 0.5:
            rec, qty, rec_price = 'finish_set', 1, set_for.get('set_value')
            notes.append('buy %s (~%sp), sell the set (~%sp)'
                         % (set_for.get('missing_name') or set_for.get('missing_part') or 'the last part',
                            pfmt(set_for.get('cost_missing')), pfmt(set_for.get('set_value'))))
        elif set_for:
            rec = 'keep'
            reasons.append('part of the near-complete %s' % (set_for.get('set_name') or 'set'))
        else:
            rec = 'keep'
    elif relic_call == 'open':
        rec, qty = 'open_relic', min(sellable, 3)
        notes.append('opening beats selling (EV %.1fp vs %.1fp per relic)'
                     % (fnum((relic_row or {}).get('ev_unit_wts')), fnum((relic_row or {}).get('relic_wts'))))
    elif ctx['cash_out'].get(slug):
        rec, qty = 'list', sellable
        notes.append('sets.py already marks this part for cashing out')
    elif ctx['ducats'].get(slug) and str(ctx['ducats'][slug].get('verdict')) == 'BURN' \
            and price is not None and price <= 5:
        rec, qty = 'burn_ducats', min(sellable, int(ctx['ducats'][slug].get('count') or sellable))
        notes.append('burning for ducats pays more than the %sp sale (%s)'
                     % (pfmt(price), ctx['ducats'][slug].get('reason') or 'ducat-dense'))
    elif set_for and set_for.get('missing') == 0:
        rec, qty, rec_price = 'assemble_set', 1, set_for.get('set_value')
        notes.append('you hold the whole set%s'
                     % ((' (~%sp set value)' % pfmt(set_for['set_value']))
                        if set_for.get('set_value') else ''))
        if sellable > 1:
            notes.append('%d spare copies stay sellable on their own' % (sellable - 1))
    elif set_for and set_for.get('missing') == 1 and fnum(set_for.get('roi'), -1) >= 0.5:
        rec, qty, rec_price = 'finish_set', 1, set_for.get('set_value')
        notes.append('buy %s (~%sp), sell the set (~%sp)'
                     % (set_for.get('missing_name') or set_for.get('missing_part') or 'the last part',
                        pfmt(set_for.get('cost_missing')), pfmt(set_for.get('set_value'))))
        if sellable > 1:
            notes.append('%d spare copies stay sellable on their own' % (sellable - 1))
    else:
        if price is None:
            rec, qty = 'hold', 0
            if lane_rank is not None:
                notes.append('no sell orders at rank %d - nothing to undercut' % lane_rank)
            else:
                notes.append('no local price data')
        else:
            rec = 'list'
            cap = sellable
            if vol48 and sellable > max(1, vol48 // 4):
                cap = max(1, vol48 // 4)
                notes.append('only ~%d sold in 48h - stagger the listings' % vol48)
            elif vol48 == 0 and volday < 0.2 and sellable > 1:
                cap = 1
                notes.append('thin local demand - list one and watch it')
            qty = cap

    # ---- reasons from market facts (only when data exists) ----
    if price is not None:
        line = 'Current market price: %sp' % pfmt(price)
        if lane_rank is not None:
            line += ' at rank %d (your copy\'s rank)' % lane_rank
        if median is not None:
            line += ' (48h median %sp, all ranks)' % pfmt(median)
        reasons.append(line)
    if badge == 'spike':
        reasons.append('demand is rising (48h volume above the 90d rate)')
    elif badge == 'fade':
        reasons.append('demand is fading (recent volume below the 90d rate)')
    elif badge == 'steady':
        reasons.append('demand is steady')
    if pct is not None:
        if pct >= 5:
            reasons.append('price trend up %s%% over 30d' % pfmt(pct))
        elif pct <= -5:
            reasons.append('price trend down %s%% over 30d' % pfmt(pct))
        else:
            reasons.append('price trend flat over 30d')
    if vol48 or volday:
        reasons.append('liquidity %s (%d sold in 48h, ~%s/day)' % (liquidity or 'unknown', vol48, pfmt(volday)))
    if window:
        reasons.append('you sell %s fastest %s%s'
                       % ('items' if window_src == 'all items' else kind.replace('_', ' ') + 's',
                          window, ' (thin sample - hint only)' if timing_note else ''))
    if sold_n:
        reasons.append('you have sold this exact item %d time%s before'
                       % (sold_n, '' if sold_n == 1 else 's'))
    if baro_line:
        reasons.append(baro_line)

    # ---- text ----
    lines = ['You own %d of this.' % owned]
    if equipped:
        lines.append('%d %s equipped.' % (equipped, 'is' if equipped == 1 else 'are'))
    for extra in reasons:
        if extra.startswith('1 stays') or extra.startswith('still missing'):
            lines.append(extra[0].upper() + extra[1:] + '.')
    lines.append('%d %s genuinely sellable.' % (sellable, 'is' if sellable == 1 else 'are'))
    lines.append('')
    if price is not None:
        block = 'Current market price: %sp' % pfmt(price)
        if lane_rank is not None:
            block += ' at rank %d (your copy\'s rank)' % lane_rank
        if median is not None:
            block += ' (48h median %sp)' % pfmt(median)
        lines.append(block + '.')
    for label, value in (('Demand', badge), ('Price trend', pct)):
        if label == 'Demand' and value:
            lines.append('Demand is %s.' % {'spike': 'rising', 'steady': 'steady', 'fade': 'fading'}[value])
        if label == 'Price trend' and value is not None:
            lines.append('Recent price trend is %s.' %
                         ('stable' if abs(value) < 5 else ('up' if value > 0 else 'down')))
    if window:
        lines.append('You historically sell this fastest %s.' % window)
    if baro_line:
        lines.append(baro_line + '.')
    lines.append('')
    if rec == 'list' and qty:
        when = 'tonight' if (now and 17 <= now.tm_hour <= 23) else 'now'
        lines.append('Recommendation: list %d %s around %sp.'
                     % (qty, when, pfmt(rec_price if rec_price is not None else price)))
    elif rec == 'burn_ducats' and qty:
        lines.append('Recommendation: burn %d for ducats.' % qty)
    elif rec == 'open_relic' and qty:
        lines.append('Recommendation: open %d.' % qty)
    elif rec == 'assemble_set':
        lines.append('Recommendation: assemble and list it as one set sale%s.'
                     % ((' - ' + notes[0]) if notes else ''))
    elif rec == 'finish_set':
        lines.append('Recommendation: finish the set%s.'
                     % ((' - ' + notes[0]) if notes else ' - buy the last part first'))
    elif rec == 'already_listed':
        lines.append('Recommendation: already listed%s.' % ((' - ' + notes[0]) if notes else ''))
    elif rec == 'keep':
        lines.append('Recommendation: hold - nothing sellable left after reservations.')
    else:
        lines.append('Recommendation: hold%s.' % ((': ' + notes[0]) if notes else ''))
    for note in notes[1:]:
        lines.append('  (' + note + ')')

    # ---- score: sellable value x demand ----
    score = round((price or 0) * sellable * DEMAND_MULT.get(badge, 1.0), 1)

    return {
        'item': slug, 'name': name, 'cat': kind,
        'owned': owned, 'equipped': equipped, 'reserved': reserved, 'sellable': sellable,
        'market_price': price, 'median': median,
        'lane_rank': lane_rank,
        'trend': {'spike': 'rising', 'fade': 'falling', 'steady': 'steady'}.get(badge),
        'demand_badge': badge, 'price_trend_pct': pct,
        'liquidity': liquidity, 'vol48': vol48, 'volday': volday,
        'best_sell_window': window,
        'recommendation': rec, 'recommended_quantity': qty, 'recommended_price': rec_price,
        'reasons': reasons, 'notes': notes, 'score': score,
        'text': '\n'.join(lines),
    }


# ------------------------------------------------------------------ output
def atomic_write(path, doc):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, indent=1)
    os.replace(tmp, path)


def payload_hash(doc):
    body = {k: v for k, v in doc.items() if k not in ('generated', 'content_hash')}
    blob = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(blob.encode('ascii')).hexdigest()[:16]


def previous_stamp(path, digest):
    try:
        with open(path, encoding='utf-8') as fh:
            old = json.load(fh)
    except (OSError, ValueError):
        return None
    if isinstance(old, dict) and old.get('content_hash') == digest and old.get('generated'):
        return str(old['generated'])
    return None


def rank_key(rec):
    """Actionable first, then already-listed, then hold/keep; within a group, score desc."""
    order = 0 if rec['recommendation'] not in ('already_listed', 'hold', 'keep') else \
        1 if rec['recommendation'] == 'already_listed' else 2
    return (order, -rec['score'], rec['item'])


def build_doc(ctx=None, now=None):
    """The whole data/sell_advisor.json document."""
    ctx = ctx or build_context()
    items = {}
    for row in ctx['rows']:
        rec = advise(row['slug'], ctx, now=now)
        if rec:
            items[row['slug']] = rec
    ranked = sorted(items.values(), key=rank_key)
    counts = {}
    for rec in items.values():
        counts[rec['recommendation']] = counts.get(rec['recommendation'], 0) + 1
    doc = {'version': VERSION, 'generated': None,
           'counts': counts,
           'items': items,
           'ranked': [r['item'] for r in ranked[:MAX_LIST]],
           'top': ranked[:12],
           'content_hash': None}
    digest = payload_hash(doc)
    doc['content_hash'] = digest
    doc['generated'] = previous_stamp(OUT, digest) or time.strftime(STAMP)
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description='Smart sell advisor for owned tradeables')
    ap.add_argument('slug', nargs='?', default=None, help='one item slug (prints its advice)')
    ap.add_argument('--top', type=int, default=12, help='how many picks to print (default 12)')
    ap.add_argument('--write', action='store_true', help='write data/sell_advisor.json')
    ap.add_argument('--json', action='store_true', help='print JSON instead of text')
    args = ap.parse_args(argv)

    ctx = build_context()
    if args.slug:
        rec = advise(args.slug, ctx)
        if rec is None:
            print('no owned data for %r (owned.json has no such slug)' % args.slug)
            return 1
        print(json.dumps(rec, indent=1) if args.json else rec['text'])
        return 0

    doc = build_doc(ctx)
    if args.write:
        atomic_write(OUT, doc)
    if args.json:
        print(json.dumps(doc, indent=1))
        return 0
    print('sell advisor: %d owned slugs | %s' % (len(doc['items']),
          ', '.join('%s %d' % (k, v) for k, v in sorted(doc['counts'].items()))))
    for rec in doc['top'][:args.top]:
        print('  %-34s %-10s sell %s/%s @%s  score %s'
              % (ascii_s(rec['name'])[:34], rec['recommendation'], rec['sellable'],
                 rec['owned'], pfmt(rec['market_price']), rec['score']))
    if args.write:
        print('wrote %s' % OUT.replace('\\', '/'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
