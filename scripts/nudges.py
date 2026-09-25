#!/usr/bin/env python3
"""Near-complete nudges - "what is nearly done: finish it or cash it?"

Inputs : data/sets.json (required), data/trader_plan.json, data/prices.json, data/owned.json
Output : data/nudges.json

Categories
  READY     units_missing == 0  -> assemble + sell, 1 trade
  ONE_AWAY  units_missing == 1  -> buy the missing part then sell as set (roi >= 0.5)
                                   else sell your held parts
  TWO_AWAY  units_missing == 2  -> lighter info; two purchases before the set pays
  PART_CASH parts held while their set is far from complete -> sell these parts

Ranking  profit desc, then confidence (high > medium > low), then slug (stable).
Urgency  profit x confidence weight (high 1.0 / medium 0.6 / low 0.3).

Cross-check: sets.json (completion state) against trader_plan.json (listing queue).
A READY set whose parts sit in the plan's listing rows is a conflict - the parts are
queued for listing instead of a set sale. Near-complete sets (1-2 away) whose held
parts are queued are flagged too, with their own kind.

Stdlib only, local data only, no network. Idempotent: while the inputs are unchanged
the file is byte-identical (the previous 'generated' stamp is reused when the payload
hash matches). Atomic write: tmp file + os.replace.
"""
import hashlib
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
OUT = os.path.join(DATA, 'nudges.json')

VERSION = 1
CONF_W = {'high': 1.0, 'medium': 0.6, 'low': 0.3}   # urgency weight
CONF_R = {'high': 3, 'medium': 2, 'low': 1}         # ranking tie-break
ROI_BUY = 0.5                                       # roi at which buying a part pays
TOP_ONE, TOP_TWO, TOP_CASH = 12, 8, 8               # list caps
CASH_VOL_MIN = 10                                   # fallback liquidity floor (vol48)
STAMP = '%Y-%m-%d %H:%M'


# ---------------------------------------------------------------- helpers
def load(name, default):
    """Load data/<name>; return default when missing or unreadable."""
    path = os.path.join(DATA, name)
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        print('WARN cannot read %s: %s' % (name, exc))
        return default


def ascii_s(value):
    """ASCII-only text for stdout."""
    return str(value).encode('ascii', 'replace').decode('ascii')


def fnum(value, default=0.0):
    """Float or default; bools and junk never raise."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def optnum(value):
    """Float or None (keeps 'unknown roi' distinct from roi 0)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def conf_of(row):
    conf = str(row.get('confidence', '')).strip().lower()
    return conf if conf in CONF_W else 'low'


def weight(conf):
    return CONF_W.get(conf, CONF_W['low'])


def rank(conf):
    return CONF_R.get(conf, 0)


def r1(value):
    return round(fnum(value), 1)


def units_missing(row):
    """units_missing, falling back to units_needed - units_have."""
    if 'units_missing' in row:
        return int(fnum(row.get('units_missing')))
    return max(0, int(fnum(row.get('units_needed'))) - int(fnum(row.get('units_have'))))


def held_slugs(row):
    """Slugs the player actually holds for this set (got list, else missing list)."""
    got = row.get('got')
    if not isinstance(got, list):
        got = row.get('parts')
    out = []
    if isinstance(got, list):
        for part in got:
            if isinstance(part, dict) and part.get('slug') and int(fnum(part.get('got'), 1)) >= 1:
                out.append(str(part['slug']))
    return out


def part_rows(row, key='missing'):
    rows = row.get(key)
    return [p for p in rows if isinstance(p, dict)] if isinstance(rows, list) else []


def sort_key(entry):
    """profit desc, confidence desc, slug asc - fully deterministic."""
    return (-fnum(entry.get('profit')), -rank(entry.get('confidence', '')), entry.get('slug', ''))


def tag(entry):
    entry['urgency'] = round(fnum(entry.get('profit')) * weight(entry.get('confidence', '')), 1)
    return entry


# ---------------------------------------------------------------- categories
def build_ready(rows):
    out = []
    for row in rows:
        if units_missing(row) != 0:
            continue
        parts = []
        for part in part_rows(row, 'got'):
            parts.append({
                'slug': str(part.get('slug', '')),
                'unit_price': r1(part.get('unit_price')),
                'vol48': int(fnum(part.get('vol48'))) if part.get('vol48') is not None else None,
                'price_real': bool(part.get('price_real')),
            })
        conf = conf_of(row)
        entry = {
            'slug': str(row.get('slug', '')),
            'name': str(row.get('name', '')),
            'category': 'READY',
            'action': 'assemble + sell, 1 trade',
            'set_value': r1(row.get('set_value')),
            'profit': r1(row.get('profit')),
            'roi': optnum(row.get('roi')),
            'confidence': conf,
            'trades_to_complete': 0,
            'own_set': int(fnum(row.get('own_set'))) if row.get('own_set') is not None else 0,
            'duplicate_build': bool(row.get('duplicate_build')),
            'value_src': str(row.get('value_src', '')),
            'parts': parts or [{'slug': s} for s in held_slugs(row)],
            'note': 'complete (4/4 parts held); assemble and list as one set sale',
        }
        if int(fnum(row.get('own_set'))) == 1:
            entry['note'] = 'complete and already assembled (own_set) - list as one set sale'
        out.append(tag(entry))
    out.sort(key=sort_key)
    return out


def build_one_away(rows):
    out = []
    for row in rows:
        if units_missing(row) != 1:
            continue
        missing = part_rows(row, 'missing')
        miss = missing[0] if missing else {}
        miss_slug = str(miss.get('slug', ''))
        if not miss_slug:
            need = row.get('need')
            miss_slug = str(need[0]) if isinstance(need, list) and need else ''
        cost = optnum(row.get('cost_missing'))
        if cost is None:
            cost = optnum(row.get('cost_est')) or 0.0
        roi = optnum(row.get('roi'))
        conf = conf_of(row)
        buy = roi is not None and roi >= ROI_BUY
        entry = {
            'slug': str(row.get('slug', '')),
            'name': str(row.get('name', '')),
            'category': 'ONE_AWAY',
            'action': 'buy the missing part then sell as set' if buy else 'sell your held parts',
            'missing': miss_slug,
            'missing_name': str(miss.get('name', '')),
            'cost_est': r1(cost),
            'set_value': r1(row.get('set_value')),
            'profit': r1(row.get('profit')),
            'roi': roi,
            'held_value': r1(row.get('held_value')),
            'confidence': conf,
            'trades_to_complete': 1,
            'cost_basis': str(row.get('cost_basis', '')),
            'value_src': str(row.get('value_src', '')),
            'missing_detail': {
                'ducats': int(fnum(miss.get('ducats'))) if miss.get('ducats') is not None else None,
                'unit_price': r1(miss.get('unit_price')),
                'price_src': str(miss.get('price_src', '')),
                'price_real': bool(miss.get('price_real')),
                'vol48': int(fnum(miss.get('vol48'))) if miss.get('vol48') is not None else None,
            },
            'note': ('spend %sp on 1 part, then 1 set sale (roi %s)'
                     % (r1(cost), roi)) if buy else
                    ('roi %s below %s - listing held parts beats finishing the set'
                     % (roi, ROI_BUY)),
        }
        out.append(tag(entry))
    out.sort(key=sort_key)
    return out


def build_two_away(rows):
    out = []
    for row in rows:
        if units_missing(row) != 2:
            continue
        missing = part_rows(row, 'missing')
        cost = optnum(row.get('cost_missing'))
        if cost is None:
            cost = optnum(row.get('cost_est')) or 0.0
        roi = optnum(row.get('roi'))
        conf = conf_of(row)
        buy = roi is not None and roi >= ROI_BUY
        entry = {
            'slug': str(row.get('slug', '')),
            'name': str(row.get('name', '')),
            'category': 'TWO_AWAY',
            'action': 'buy 2 missing parts then sell as set' if buy else 'sell your held parts',
            'missing': [str(p.get('slug', '')) for p in missing],
            'cost_est': r1(cost),
            'set_value': r1(row.get('set_value')),
            'profit': r1(row.get('profit')),
            'roi': roi,
            'held_value': r1(row.get('held_value')),
            'confidence': conf,
            'trades_to_complete': 2,
            'value_src': str(row.get('value_src', '')),
            'note': 'two purchases before the set pays (%sp to finish)' % r1(cost),
        }
        out.append(tag(entry))
    out.sort(key=sort_key)
    return out


def liquidity_conf(vol):
    """Confidence proxy when no analyst confidence is available for a part."""
    if vol is None:
        return 'low'
    if vol >= 50:
        return 'high'
    if vol >= 20:
        return 'medium'
    return 'low'


def build_part_cash(doc, rows, prices):
    """cash_out_parts when sets.json provides them, else derive from held far-off parts."""
    index = {str(r.get('slug', '')): r for r in rows}
    out = []
    declared = doc.get('cash_out_parts')
    if isinstance(declared, list) and declared:
        for item in declared:
            if not isinstance(item, dict):
                continue
            part = str(item.get('part', ''))
            set_slug = str(item.get('set', ''))
            value = optnum(item.get('value'))
            if value is None:
                value = fnum(item.get('wts'))
            vol = item.get('vol48')
            vol = int(fnum(vol)) if vol is not None else None
            conf = liquidity_conf(vol)
            src = index.get(set_slug) or {}
            out.append(tag({
                'part': part,
                'set': set_slug,
                'set_name': str(item.get('set_name') or src.get('name', '')),
                'category': 'PART_CASH',
                'action': 'sell these parts',
                'profit': r1(value),
                'value': r1(value),
                'wts': r1(item.get('wts')) if item.get('wts') is not None else None,
                'vol48': vol,
                'confidence': conf,
                'confidence_basis': 'vol48',
                'set_units_missing': units_missing(src) if src else None,
                'set_confidence': conf_of(src) if src else None,
                'source': 'sets.json:cash_out_parts',
                'note': 'held part of a far-off set - cash it instead of chasing the set',
            }))
    else:
        for row in rows:
            if units_missing(row) < 3:
                continue
            for part in part_rows(row, 'got'):
                slug = str(part.get('slug', ''))
                vol = part.get('vol48')
                liq = 'vol48'
                if vol is None:
                    quote = prices.get(slug) or {}
                    vol = quote.get('n_sell') if quote.get('n_sell') is not None else quote.get('wts')
                    liq = 'prices.n_sell'
                vol = int(fnum(vol)) if vol is not None else None
                if vol is None or vol < CASH_VOL_MIN:
                    continue
                value = optnum(part.get('unit_price'))
                if value is None:
                    value = optnum((prices.get(slug) or {}).get('wts')) or 0.0
                if value <= 0:
                    continue
                conf = liquidity_conf(vol)
                out.append(tag({
                    'part': slug,
                    'set': str(row.get('slug', '')),
                    'set_name': str(row.get('name', '')),
                    'category': 'PART_CASH',
                    'action': 'sell these parts',
                    'profit': r1(value),
                    'value': r1(value),
                    'wts': r1(value),
                    'vol48': vol,
                    'confidence': conf,
                    'confidence_basis': liq,
                    'set_units_missing': units_missing(row),
                    'set_confidence': conf_of(row),
                    'source': 'derived:held_parts',
                    'note': 'held part of a far-off set - cash it instead of chasing the set',
                }))
    # a part appears once: keep the best-paying copy
    best = {}
    for entry in out:
        key = entry['part']
        if key not in best or fnum(entry['profit']) > fnum(best[key]['profit']):
            best[key] = entry
    out = list(best.values())
    out.sort(key=sort_key)
    return out


def find_conflicts(rows, ready, one_away, two_away, plan_rows):
    """sets.json completion state vs trader_plan.json listing queue."""
    queue = {}
    for row in plan_rows:
        if not isinstance(row, dict):
            continue
        slug = str(row.get('slug', ''))
        if not slug:
            continue
        queue.setdefault(slug, []).append({
            'qty': int(fnum(row.get('qty'))) if row.get('qty') is not None else None,
            'price': r1(row.get('price')) if row.get('price') is not None else None,
            'subtype': row.get('subtype'),
            'lane': str(row.get('lane', '')),
        })
    if not queue:
        return []

    near = {}
    for entry in one_away + two_away:
        near[entry['slug']] = entry

    out = []
    for row in rows:
        slug = str(row.get('slug', ''))
        um = units_missing(row)
        parts = held_slugs(row)

        if um == 0:
            queued = [p for p in parts if p in queue]
            if queued:
                out.append(tag({
                    'kind': 'ready_parts_queued',
                    'set': slug,
                    'set_name': str(row.get('name', '')),
                    'parts': queued,
                    'queued_rows': [{'slug': p, 'rows': queue[p]} for p in queued],
                    'set_profit': r1(row.get('profit')),
                    'profit': r1(row.get('profit')),
                    'confidence': conf_of(row),
                    'units_missing': um,
                    'note': 'parts are queued for listing instead of a set sale',
                }))
            if slug in queue:
                out.append(tag({
                    'kind': 'ready_set_queued',
                    'set': slug,
                    'set_name': str(row.get('name', '')),
                    'parts': [],
                    'queued_rows': [{'slug': slug, 'rows': queue[slug]}],
                    'set_profit': r1(row.get('profit')),
                    'profit': r1(row.get('profit')),
                    'confidence': conf_of(row),
                    'units_missing': um,
                    'note': 'set already queued as a set sale in the trader plan',
                }))
        elif um <= 2:
            queued = [p for p in parts if p in queue]
            if queued:
                entry = near.get(slug) or {}
                out.append(tag({
                    'kind': 'near_parts_queued',
                    'set': slug,
                    'set_name': str(row.get('name', '')),
                    'parts': queued,
                    'queued_rows': [{'slug': p, 'rows': queue[p]} for p in queued],
                    'set_profit': r1(row.get('profit')),
                    'profit': r1(row.get('profit')),
                    'confidence': conf_of(row),
                    'units_missing': um,
                    'set_action': entry.get('action', ''),
                    'note': ('%s queued for listing while the set is %d part(s) from complete'
                             % (', '.join(queued), um)),
                }))
    out.sort(key=lambda e: (-fnum(e.get('profit')), -rank(e.get('confidence', '')), e.get('set', '')))
    return out


# ---------------------------------------------------------------- output
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
    """Reuse the previous 'generated' when nothing else changed (idempotent writes)."""
    try:
        with open(path, encoding='utf-8') as fh:
            old = json.load(fh)
    except (OSError, ValueError):
        return None
    if isinstance(old, dict) and old.get('content_hash') == digest and old.get('generated'):
        return str(old['generated'])
    return None


def main():
    sets_doc = load('sets.json', None)
    if sets_doc is None:
        print('ERROR data/sets.json missing or unreadable - run scripts/sets.py first')
        return 1
    rows = sets_doc.get('sets') if isinstance(sets_doc, dict) else sets_doc
    if not isinstance(rows, list):
        rows = []
    plan_doc = load('trader_plan.json', {})
    plan_rows = []
    if isinstance(plan_doc, dict):
        for key in ('plan', 'rows'):
            if isinstance(plan_doc.get(key), list):
                plan_rows = plan_doc[key]
                break
    elif isinstance(plan_doc, list):
        plan_rows = plan_doc
    prices_doc = load('prices.json', {})
    prices = prices_doc if isinstance(prices_doc, dict) else {}
    owned = load('owned.json', [])
    owned_n = len(owned) if isinstance(owned, list) else len(owned or {})

    ready = build_ready(rows)
    one_away = build_one_away(rows)
    two_away = build_two_away(rows)
    part_cash = build_part_cash(sets_doc, rows, prices)
    conflicts = find_conflicts(rows, ready, one_away, two_away, plan_rows)

    doc = {
        'version': VERSION,
        'generated': None,
        'counts': {
            'ready': len(ready),
            'one_away': len(one_away),
            'two_away': len(two_away),
            'part_cash': len(part_cash),
            'conflicts': len(conflicts),
        },
        'ready': ready,
        'one_away': one_away[:TOP_ONE],
        'two_away': two_away[:TOP_TWO],
        'part_cash': part_cash[:TOP_CASH],
        'conflicts': conflicts,
        'limits': {'one_away': TOP_ONE, 'two_away': TOP_TWO, 'part_cash': TOP_CASH},
        'inputs': {
            'sets.json': {'sets': len(rows), 'generated': sets_doc.get('generated')
                          if isinstance(sets_doc, dict) else None},
            'trader_plan.json': {'plan_rows': len(plan_rows)},
            'prices.json': {'quotes': len(prices)},
            'owned.json': {'items': owned_n},
        },
        'content_hash': None,
    }
    digest = payload_hash(doc)
    doc['content_hash'] = digest
    doc['generated'] = previous_stamp(OUT, digest)
    if doc['generated'] is None:
        doc['generated'] = time.strftime(STAMP)
    atomic_write(OUT, doc)

    counts = doc['counts']
    print('nudges -> %s' % ascii_s(OUT.replace('\\', '/')))
    print('  generated %s  hash %s' % (doc['generated'], digest))
    print('  counts: ready %d | one_away %d (shown %d) | two_away %d (shown %d) | part_cash %d (shown %d) | conflicts %d'
          % (counts['ready'], counts['one_away'], len(doc['one_away']),
             counts['two_away'], len(doc['two_away']),
             counts['part_cash'], len(doc['part_cash']), counts['conflicts']))
    for label, entries in (('READY', doc['ready']), ('ONE_AWAY', doc['one_away'][:3]),
                           ('TWO_AWAY', doc['two_away'][:2]), ('PART_CASH', doc['part_cash'][:2])):
        for entry in entries:
            head = entry.get('slug') or entry.get('part')
            print('  %-9s %-42s profit %-7s conf %-6s urgency %-7s %s'
                  % (label, ascii_s(head)[:42], ascii_s(entry.get('profit')),
                     ascii_s(entry.get('confidence')), ascii_s(entry.get('urgency')),
                     ascii_s(entry.get('action'))))
    for entry in doc['conflicts']:
        print('  CONFLICT  %-24s %-34s %s'
              % (ascii_s(entry.get('kind')), ascii_s(entry.get('set'))[:34],
                 ascii_s(entry.get('note'))[:64]))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
