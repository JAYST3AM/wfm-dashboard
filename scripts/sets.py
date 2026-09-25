"""Set-builder / completion analyzer for prime sets.

Inputs : data/wfm_items_v2.json (catalog), data/owned.json, data/prices.json, data/stats.json
Output : data/sets.json  (per prime set: parts owned vs needed + ROI decision)

Parts of a set = catalog items whose slug starts with '<set slug minus _set>_'. Real quotes exist
only for owned items (prices.json 'wts' sell floor, stats.json 48h median/vol48); unowned parts and
sets are estimated from catalog ducats via a tier table calibrated on the player's own priced prime
parts (thin tiers use a log-log fit), flagged price_real=False. Set value =
sum of part prices unless the assembled set itself has a real quote.
"""
import json, math, os, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')

MULTI = {'akbronco_prime_link': 2, 'akjagara_prime_barrel': 2, 'akjagara_prime_receiver': 2}
MIN_TIER_N, ROI_COMPLETE, ROI_MAYBE = 5, 0.25, 0.12  # tier sample floor; profit/spend gates
MIN_PROFIT_COMPLETE, MIN_PROFIT_MAYBE = 10.0, 5.0    # absolute plat floors for COMPLETE*
ACTIONS = ('COMPLETE', 'COMPLETE_MAYBE', 'ASSEMBLE_SELL', 'OWNED_SET', 'SELL_PARTS', 'HOLD', 'WATCH', 'IGNORE')


def load(name, default=None):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return default
    with open(p, encoding='utf-8') as fh:
        return json.load(fh)


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    return None if not n else xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def main():
    cat = (load('wfm_items_v2.json') or {}).get('data') or []
    owned, prices, stats = load('owned.json') or [], load('prices.json') or {}, load('stats.json') or {}
    by = {i['slug']: i for i in cat}

    def nm(slug):
        return ((by.get(slug) or {}).get('i18n') or {}).get('en', {}).get('name') or slug

    def duc(slug):
        return (by.get(slug) or {}).get('ducats') or 0

    have = {}
    for o in owned:                                              # dupes summed per slug
        have[o['slug']] = have.get(o['slug'], 0) + (o.get('count') or 1)

    # ---- ducat -> plat calibration from the player's own priced prime parts ----
    tiers = {}
    for slug, t in stats.items():
        it, m, d = by.get(slug), t.get('median'), duc(slug)
        if it and m and d and 'prime' in it['tags'] and ({'component', 'blueprint'} & set(it['tags'])):
            tiers.setdefault(d, []).append(m)
    tier_med = {d: median(v) for d, v in tiers.items() if len(v) >= MIN_TIER_N}
    xs = [math.log(d) for d in tier_med]
    ys = [math.log(tier_med[d]) for d in tier_med]
    mx, my = sum(xs) / max(len(xs), 1), sum(ys) / max(len(ys), 1)   # log-log fit fallback
    slope = (sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sum((x - mx) ** 2 for x in xs) or 1.0)
             if len(xs) >= 2 else 1.0)
    icept = (my - slope * mx) if len(xs) >= 2 else math.log(5.0)

    def quote(slug):
        """-> (price, source, is_real): observed market data first, else the ducat model."""
        q, s, d = prices.get(slug) or {}, stats.get(slug) or {}, duc(slug)
        if q.get('wts'):
            return float(q['wts']), 'wts_live', True
        if s.get('median'):
            return round(float(s['median']), 1), 'median48', True
        if d in tier_med:
            return round(tier_med[d], 1), 'ducat_tier_%d' % d, False
        return ((round(math.exp(icept + slope * math.log(d)), 1), 'ducat_fit', False) if d
                else (None, 'no_data', False))

    # ---- per-set analysis ----
    sets = sorted((i for i in cat if i['slug'].endswith('_set') and 'prime' in (i.get('tags') or [])),
                  key=lambda i: i['slug'])
    rows = []
    for s in sets:
        slug = s['slug']
        pre = slug[:-4] + '_'
        parts = []
        for p in sorted(i['slug'] for i in cat if i['slug'] != slug and i['slug'].startswith(pre)):
            need, cnt = MULTI.get(p, 1), have.get(p, 0)
            price, src, real = quote(p)
            got = min(cnt, need)
            parts.append(dict(slug=p, name=nm(p), have=cnt, need=need, got=got, missing=max(0, need - cnt),
                              partial=0 < got < need, ducats=duc(p), unit_price=price, price_src=src,
                              price_real=real, vol48=(stats.get(p) or {}).get('vol48') or 0,
                              value=round(price * got, 1) if price else None))
        missing, held_parts = [p for p in parts if p['missing']], [p for p in parts if p['got']]
        cost = round(sum((p['unit_price'] or 0) * p['missing'] for p in missing), 1)
        held = round(sum(p['value'] or 0 for p in held_parts), 1)
        dupes = round(sum((p['unit_price'] or 0) * max(0, p['have'] - p['need'])
                          for p in parts if p['unit_price']), 1)
        part_sum = round(sum((p['unit_price'] or 0) * p['need'] for p in parts if p['unit_price']), 1)
        sp, ssrc, sreal = quote(slug)
        priced = [p for p in parts if p['unit_price']]
        set_value = round(sp, 1) if sreal else part_sum
        value_src = ssrc if sreal else ('parts_sum_real' if priced and all(p['price_real'] for p in priced)
                                        and len(priced) == len(parts) else
                                        'parts_sum_mixed' if any(p['price_real'] for p in priced)
                                        else 'parts_sum_est')
        own_set, near = have.get(slug, 0), len(missing) <= 2
        profit = round(set_value - cost, 1)
        roi = round(profit / cost, 3) if cost > 0 else None
        cost_real = bool(missing) and all(p['price_real'] for p in missing)
        real_backed = (set_value if sreal else sum((p['value'] or 0) for p in held_parts
                                                   if p['price_real']) + sum((p['unit_price'] or 0)
                                                                             for p in missing if p['price_real']))
        exposure = set_value + cost                        # value at stake + capital committed
        real_share = round(real_backed / exposure, 2) if exposure else 0.0
        conf = 'high' if real_share >= 0.9 else 'medium' if real_share >= 0.4 else 'low'

        if own_set and not missing:
            action = 'OWNED_SET'                           # assembled item already in inventory
        elif not missing:
            action = 'ASSEMBLE_SELL' if set_value >= held else 'SELL_PARTS'
        elif not held_parts:
            action = 'WATCH' if (roi or 0) >= 0.5 and profit >= 15 else 'IGNORE'
        elif near and roi is not None and profit >= MIN_PROFIT_MAYBE and roi >= ROI_MAYBE:
            action = ('COMPLETE' if roi >= ROI_COMPLETE and profit >= MIN_PROFIT_COMPLETE
                      else 'COMPLETE_MAYBE')
        elif own_set:
            action = 'OWNED_SET'
        elif any(p['price_real'] and p['vol48'] >= 2 for p in held_parts):
            action = 'SELL_PARTS'
        else:
            action = 'HOLD'

        rows.append(dict(
            slug=slug, name=nm(slug), tags=s['tags'], parts_total=len(parts),
            units_needed=sum(p['need'] for p in parts), units_have=sum(p['got'] for p in parts),
            units_missing=sum(p['missing'] for p in parts), partial_parts=len([p for p in parts if p['partial']]),
            parts_have=len(held_parts), missing_count=len(missing), missing=missing, got=held_parts,
            cost_missing=cost, held_value=held, dupes_value=dupes, parts_sum=part_sum, set_price=sp,
            set_price_src=ssrc, set_price_real=sreal, set_value=set_value, value_src=value_src,
            profit=profit, roi=roi, profit_basis=('gross' if not missing else 'net'),
            cost_basis=('real' if cost_real else 'model' if missing else 'none'), real_share=real_share,
            confidence=conf, own_set=own_set, duplicate_build=bool(own_set and missing), trades_to_complete=len(missing),
            price_coverage=round(len(priced) / max(len(parts), 1), 2),
            score=round(100.0 * len(held_parts) / max(len(parts), 1) + max(0.0, profit) / 10.0, 2),
            action=action))

    complete, near = ([r for r in rows if not r['missing_count']],
                      [r for r in rows if r['missing_count'] == 1])
    two = [r for r in rows if r['missing_count'] == 2]
    targets = [r for r in rows if r['action'] in ('COMPLETE', 'COMPLETE_MAYBE', 'ASSEMBLE_SELL')
               and r['parts_have']]
    targets.sort(key=lambda r: (r['missing_count'], -r['profit'], r['cost_missing']))
    build, ready = ([r for r in targets if r['action'].startswith('COMPLETE')],
                    [r for r in targets if r['action'] == 'ASSEMBLE_SELL'])

    def brief(r, n):
        return dict(slug=r['slug'], name=r['name'], parts='%d/%d' % n, need=[x['slug'] for x in r['missing']],
                    cost_est=r['cost_missing'], cost_basis=r['cost_basis'], set_value=r['set_value'],
                    value_src=r['value_src'], profit=r['profit'], roi=r['roi'], held_value=r['held_value'],
                    action=r['action'], confidence=r['confidence'], score=r['score'])

    is_t = lambda r: r['action'] in ('COMPLETE', 'COMPLETE_MAYBE', 'ASSEMBLE_SELL')
    # parts worth cashing out: real quotes, live demand, in sets we are not assembling
    cash = [dict(part=p['slug'], set=r['slug'], value=p['value'], wts=p['unit_price'], vol48=p['vol48'])
            for r in rows if not is_t(r) for p in r['got']
            if p['price_real'] and p['vol48'] >= 2 and (p['value'] or 0) >= 6]
    cash.sort(key=lambda c: -(c['value'] * min(1 + c['vol48'] / 5.0, 3)))

    checks = dict(
        rows_match_sets=len(rows) == len(sets),
        units_balance=all(r['units_have'] + r['units_missing'] == r['units_needed'] for r in rows),
        cost_matches_parts=all(abs(r['cost_missing'] - round(sum((p['unit_price'] or 0) * p['missing']
                            for p in r['missing']), 1)) < 1e-6 for r in rows),
        actions_known=all(r['action'] in ACTIONS for r in rows), every_set_has_parts=all(r['parts_total'] >= 1 for r in rows),
        target_actions_real=all(r['parts_have'] >= 1 for r in rows if is_t(r)))

    out = dict(
        generated=time.strftime('%Y-%m-%d %H:%M'),
        source='wfm catalog + owned inventory; prices.json/stats.json (real quotes) + ducat model',
        model=dict(tier_medians={str(d): round(v, 1) for d, v in sorted(tier_med.items())},
                   tier_samples={str(d): len(v) for d, v in sorted(tiers.items())},
                   fit=dict(a=round(math.exp(icept), 4), b=round(slope, 3)), multi_parts=MULTI,
                   thresholds=dict(roi_complete=ROI_COMPLETE, roi_maybe=ROI_MAYBE,
                                   min_profit_complete=MIN_PROFIT_COMPLETE, min_profit_maybe=MIN_PROFIT_MAYBE)),
        assumptions=['set value = sum of part prices unless the assembled set itself has a real quote',
                     'missing-part cost = ducat-tier model estimate (no market data for unowned parts)',
                     'one trade per missing part; assembled set sells in one trade',
                     'parts needed twice are listed in model.multi_parts, everything else 1',
                     'confidence = share of value+cost backed by real quotes (high >= 0.9, medium >= 0.4)',
                     'gross profit with cost_basis none is sale proceeds, not margin'],
        summary=dict(sets_total=len(rows), parts_total=sum(r['parts_total'] for r in rows),
                     complete=len(complete), near_1_missing=len(near), two_missing=len(two),
                     owned_assembled_sets=len([r for r in rows if r['own_set']]),
                     complete_or_near=len(complete) + len(near), targets=len(targets),
                     net_profit_build_targets=round(sum(r['profit'] for r in build), 1),
                     gross_value_ready_to_sell=round(sum(r['profit'] for r in ready), 1),
                     held_parts_value_incomplete=round(sum(r['held_value'] for r in rows if r['missing_count']), 1),
                     held_parts_value_near=round(sum(r['held_value'] for r in near), 1),
                     dupes_value=round(sum(r['dupes_value'] for r in rows), 1),
                     real_quoted_sets=len([r for r in rows if r['set_price_real']]),                     actions={a: len([r for r in rows if r['action'] == a])
                              for a in sorted({r['action'] for r in rows})}),
        top_targets=[brief(r, (r['parts_have'], r['parts_total'])) for r in targets[:12]],
        cash_out_parts=cash[:12], self_check=checks, sets=rows)

    with open(os.path.join(DATA, 'sets.json'), 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=1)

    failed = [k for k, v in checks.items() if not v]
    ssum, tw = out['summary'], out['top_targets']
    lines = ['sets.py -> data/sets.json   %s' % out['generated'],
             'prime sets %d | parts tracked %d | complete %d | 1-away %d | 2-away %d | complete_or_near %d'
             % (ssum['sets_total'], ssum['parts_total'], ssum['complete'], ssum['near_1_missing'],
                ssum['two_missing'], ssum['complete_or_near']),
             'actions: ' + '  '.join('%s=%d' % kv for kv in ssum['actions'].items()),
             'held value incomplete %.1fp (1-away %.1fp) | dupes %.1fp | net profit on build targets %.1fp'
             ' | gross on assemble-ready %.1fp' % (ssum['held_parts_value_incomplete'], ssum['held_parts_value_near'],
                                                   ssum['dupes_value'], ssum['net_profit_build_targets'],
                                                   ssum['gross_value_ready_to_sell']),
             'ducat tiers: %s | fit p=%.3f*d^%.3f | thin: %s'
             % (', '.join('%d->%.1f(n=%d)' % (d, v, len(tiers[d])) for d, v in sorted(tier_med.items())),
                math.exp(icept), slope, ', '.join('%d->n=%d' % (d, len(v)) for d, v in
                                                  sorted(tiers.items()) if len(v) < MIN_TIER_N) or 'none'),
             'self-check: ' + ('OK (%d checks)' % len(checks) if not failed
                               else 'FAILED -> ' + ', '.join(failed)),
             '', 'TOP COMPLETION TARGETS']
    lines += ['%-34s %s miss=%d cost=%7.1f(%s) set=%7.1f(%s) profit=%7.1f roi=%s conf=%-6s %s%s'
              % (b['slug'], b['parts'], len(b['need']), b['cost_est'], b['cost_basis'], b['set_value'],
                 b['value_src'], b['profit'], ('%.2f' % b['roi']) if b['roi'] is not None else '-',
                 b['confidence'], b['action'], '\n    need: ' + ', '.join(b['need']) if b['need'] else '')
              for b in tw]
    lines += ['', 'CASH-OUT PARTS (real quote, live demand, set not worth completing)']
    lines += ['%-36s from %-32s wts=%-5s vol48=%-4s value=%s'
              % (c['part'], c['set'], c['wts'], c['vol48'], c['value']) for c in out['cash_out_parts'][:8]]
    lines += ['', 'SAMPLES (first complete, first 1-away, first 2-away, first owned-as-set, one far set)']
    bys = {r['slug']: r for r in rows}
    picks = [bys[s] for s in dict.fromkeys(r['slug'] for r in complete[:1] + near[:1] + two[:1]
                                           + [x for x in rows if x['own_set']][:1] + rows[:1])]
    lines += ['%-34s %d/%d miss=%d held=%7.1f set=%7.1f(%s) action=%s conf=%s\n    have: %s\n    need: %s'
              % (r['slug'], r['parts_have'], r['parts_total'], r['missing_count'], r['held_value'],
                 r['set_value'], r['value_src'], r['action'], r['confidence'],
                 ', '.join('%s x%d' % (p['slug'], p['have']) for p in r['got']) or '-',
                 ', '.join(p['slug'] for p in r['missing']) or '-') for r in picks]
    print('\n'.join(lines))
    return out


if __name__ == '__main__':
    main()
