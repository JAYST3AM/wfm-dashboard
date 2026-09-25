"""Flip digest v1: rank deal rows by MARGIN x LIQUIDITY for a repeatable trade plan.

Takes the rotated orderbook scan (data/deals.json: floor_sell = buy-at price, target_price =
sell-at price) and re-ranks it for throughput instead of one-off jackpots, because thin items
must not top the list:

  sales_day  = vol48 / 2                      (proxy: last-48h units sold, halved to per-day)
  margin_pct = profit * 100 / floor_sell
  queue_ahead = n_sell_online                 (online sellers you stand behind in the lane)
  score      = profit * min(sales_day, 10) / max(1, queue_ahead), capped at score_cap so one
               whale deal cannot dwarf/hide liquid moderate deals (min(sales_day, 10) caps the
               liquidity multiplier, score_cap caps the final value; whale_capped count reported)
  safe_score = profit * min(sales_day, 10) * safe_discount when queue_ahead > safe_queue
               (safe ranking = margin x liquidity with a queue-length haircut instead of a divide)

stale == true rows are excluded from both rankings. Rows are sanity-checked and cross-checked
against data/{prices,stats}.json (vol48 agreement, sales_day proxy vs the 90-day daily average,
margin vs the scanner's profit_pct, spread targets far above the lane median).

Reads data/{deals,prices,stats,wfm_items_v2}.json; writes data/flip_digest.json (atomic).
Stdlib only. Idempotent for unchanged inputs (only generated/generated_iso may move).
"""

import argparse
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
DEALS_P = os.path.join(DATA, 'deals.json')
PRICES_P = os.path.join(DATA, 'prices.json')
STATS_P = os.path.join(DATA, 'stats.json')
ITEMS_P = os.path.join(DATA, 'wfm_items_v2.json')
OUT_P = os.path.join(DATA, 'flip_digest.json')


def jload(path, default):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return default


def jdump(path, obj):
    with open(path + '.tmp', 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, indent=1)
    os.replace(path + '.tmp', path)


def iso(epoch):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(epoch))


def as_num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def name_of(slug, name, catalog):
    """Row name, falling back to the catalogue for blank/empty names."""
    if name and str(name).strip():
        return str(name).strip()
    ent = catalog.get(slug) or {}
    return ((ent.get('i18n') or {}).get('en') or {}).get('name') or slug


def ranking_key(row, metric):
    """Deterministic order: metric desc, then uncapped score, the other score, liquidity, profit, slug.

    Ties at the cap (score == score_cap) are resolved by the uncapped value, so the displayed
    ranking follows the raw margin x liquidity formula while the cap keeps the scale bounded.
    """
    other = row['safe_score'] if metric == 'score' else row['score']
    return (-row[metric], -row['score_raw'], -other, -row['sales_day'], -row['profit'], row['slug'])


def build(args):
    deals_doc = jload(DEALS_P, None)
    if not deals_doc or not deals_doc.get('deals'):
        raise SystemExit('no deals: %s (run scripts/deal_scanner.py first)' % DEALS_P)
    prices = jload(PRICES_P, {}) or {}
    stats = jload(STATS_P, {}) or {}
    catalog = {it.get('slug'): it for it in ((jload(ITEMS_P, {}) or {}).get('data') or [])
               if it.get('slug')}

    deals = deals_doc['deals']
    fresh = [d for d in deals if not d.get('stale')]
    stale_n = len(deals) - len(fresh)

    rows, skipped_bad = [], 0
    checks = {'vol48_vs_stats_mismatch': 0, 'missing_in_stats': 0, 'missing_in_prices': 0,
              'sales_day_proxy_outliers': 0, 'margin_vs_source_mismatch': 0,
              'target_gt_2x_lane_median': 0}
    wts_up = wts_dn = 0
    wts_ratios = []
    for d in fresh:
        buy, sell = as_num(d.get('floor_sell')), as_num(d.get('target_price'))
        profit, vol48 = as_num(d.get('profit')), as_num(d.get('vol48'))
        if not buy or buy < 1 or sell is None or profit is None or profit <= 0 or vol48 is None:
            skipped_bad += 1
            continue
        slug = d.get('slug') or ''
        queue = int(d.get('n_sell_online') or 0)
        sales_day = round(vol48 / 2.0, 2)                       # proxy: 48h volume -> per day
        margin_pct = round(profit * 100.0 / buy, 1)
        score_raw = profit * min(sales_day, args.sales_cap) / max(1, queue)
        score = round(min(score_raw, args.score_cap), 2)
        safe_score = round(profit * min(sales_day, args.sales_cap) *
                           (args.safe_discount if queue > args.safe_queue else 1.0), 2)
        rows.append({'slug': slug, 'name': name_of(slug, d.get('name'), catalog),
                     'kind': d.get('kind'), 'buy_at': buy, 'sell_at': sell,
                     'margin_pct': margin_pct, 'profit': round(profit, 2), 'vol48': int(vol48),
                     'sales_day': sales_day, 'queue_ahead': queue, 'score': score,
                     'safe_score': safe_score, 'owned': int(bool(d.get('owned'))),
                     'score_raw': round(score_raw, 2), '_lane_median': as_num(d.get('lane_median')),
                     '_profit_pct': as_num(d.get('profit_pct'))})

    # cross-checks against the snapshot files (informational, never fail the run)
    for r in rows:
        st = stats.get(r['slug'])
        pr = prices.get(r['slug'])
        if st is None:
            checks['missing_in_stats'] += 1
        else:
            if int(st.get('vol48') or 0) != r['vol48']:
                checks['vol48_vs_stats_mismatch'] += 1
            v90 = as_num(st.get('volday90')) or 0
            if v90 > 0 and (r['sales_day'] / v90 > 3.0 or r['sales_day'] / v90 < 1 / 3.0):
                checks['sales_day_proxy_outliers'] += 1
        if pr is None:
            checks['missing_in_prices'] += 1
        else:
            wts = as_num(pr.get('wts'))
            if wts:
                wts_ratios.append(r['buy_at'] / wts)
                if r['buy_at'] > wts:
                    wts_up += 1
                else:
                    wts_dn += 1
        if r['_profit_pct'] is not None and abs(r['_profit_pct'] - r['margin_pct']) > 0.15:
            checks['margin_vs_source_mismatch'] += 1
        if r['kind'] == 'spread' and r['_lane_median'] and r['sell_at'] > 2.0 * r['_lane_median']:
            checks['target_gt_2x_lane_median'] += 1
    checks['floor_vs_snapshot_wts'] = {
        'above_snapshot_best_sell': wts_up, 'at_or_below': wts_dn,
        'median_ratio': round(wts_ratios[len(wts_ratios) // 2], 2) if wts_ratios else None,
        'note': 'prices.json is an older /top snapshot and is lane-agnostic; informational only'}

    flips = sorted(rows, key=lambda r: ranking_key(r, 'score'))[:args.top_n]
    safe_flips = sorted(rows, key=lambda r: ranking_key(r, 'safe_score'))[:args.top_n]
    whale_capped = sum(1 for r in rows if r['score_raw'] > args.score_cap)
    for r in rows:
        r.pop('_lane_median', None)
        r.pop('_profit_pct', None)

    def kind_counts(items):
        out = {}
        for it in items:
            out[it['kind']] = out.get(it['kind'], 0) + 1
        return out

    now = int(time.time())
    digest_lines = []
    for i, r in enumerate(flips[:5], 1):
        sc = '%.2f' % r['score']
        if r['score'] >= args.score_cap - 1e-9:
            sc += ' (capped; raw %.2f)' % r['score_raw']
        digest_lines.append('%d. %s [%s] %sp -> %sp | margin %sp (+%.1f%%) | %.1f sales/day proxy | '
                            'queue %d | score %s' % (i, r['name'], r['kind'], r['buy_at'],
                                                     r['sell_at'], r['profit'], r['margin_pct'],
                                                     r['sales_day'], r['queue_ahead'], sc))
    header = ('WFM flip digest %s | %d fresh deals (%d stale hidden) | top5 by margin x sales/day'
              % (iso(now), len(rows), stale_n))
    doc = {
        'version': 1,
        'generated': now,
        'generated_iso': iso(now),
        'source': {'deals_generated_iso': deals_doc.get('generated_iso'),
                   'deals_total': len(deals)},
        'params': {
            'sales_day': 'vol48 / 2 (proxy: 48h units sold, halved to per-day)',
            'margin_pct': 'profit * 100 / buy_at (buy_at = deals.floor_sell)',
            'queue_ahead': 'n_sell_online (online sellers ahead of you in the lane)',
            'score': 'profit * min(sales_day, %g) / max(1, queue_ahead), capped at %.1f'
                     % (args.sales_cap, args.score_cap),
            'score_raw': 'uncapped score (same formula, no cap) - kept per row so the cap is auditable',
            'score_cap': args.score_cap,
            'score_cap_note': 'caps the whale tail so one huge deal cannot dwarf/hide liquid '
                              'moderate deals; capped rows tie at the cap and are ordered by the '
                              'uncapped score (score_raw) kept on every row',
            'safe_score': 'profit * min(sales_day, %g) * %.2f when queue_ahead > %d, else undiscounted'
                          % (args.sales_cap, args.safe_discount, args.safe_queue),
            'safe_queue': args.safe_queue,
            'safe_discount': args.safe_discount,
            'sales_cap': args.sales_cap,
            'top_n': args.top_n,
            'stale_policy': 'stale == true excluded from all rankings',
            'tiebreak': 'score/safe_score desc, then uncapped score_raw, other score, sales_day, profit, slug',
        },
        'counts': {
            'deals_in': len(deals), 'fresh': len(fresh), 'stale_excluded': stale_n,
            'scored': len(rows), 'skipped_bad_rows': skipped_bad,
            'whale_capped': whale_capped, 'zero_queue': sum(1 for r in rows if r['queue_ahead'] == 0),
            'flips': len(flips), 'safe_flips': len(safe_flips),
            'by_kind_all': kind_counts(deals), 'by_kind_fresh': kind_counts(fresh),
        },
        'checks': checks,
        'flips': flips,
        'safe_flips': safe_flips,
        'digest_header': header,
        'digest_text': '\n'.join(digest_lines),
        'digest': flips[:5],
    }
    jdump(OUT_P, doc)
    return doc, flips, stale_n


def main():
    ap = argparse.ArgumentParser(description='Rank wfm deal rows by margin x liquidity -> data/flip_digest.json')
    ap.add_argument('--top-n', type=int, default=25, help='rows per ranking (default 25)')
    ap.add_argument('--score-cap', type=float, default=100.0, help='upper bound on score (default 100)')
    ap.add_argument('--sales-cap', type=float, default=10.0, help='cap on the sales/day multiplier (default 10)')
    ap.add_argument('--safe-queue', type=int, default=30, help='queue_ahead above which safe_score is discounted (default 30)')
    ap.add_argument('--safe-discount', type=float, default=0.5, help='safe_score multiplier past safe_queue (default 0.5)')
    args = ap.parse_args()

    doc, flips, stale_n = build(args)
    c, ch = doc['counts'], doc['checks']
    print('[digest] deals %d | fresh %d | stale hidden %d | scored %d | skipped %d' %
          (c['deals_in'], c['fresh'], c['stale_excluded'], c['scored'], c['skipped_bad_rows']), flush=True)
    print('[digest] capped whales %d | zero-queue %d | top %d by score, %d by safe_score' %
          (c['whale_capped'], c['zero_queue'], c['flips'], c['safe_flips']), flush=True)
    print('[checks] vol48 mismatch %d | missing stats %d | missing prices %d | proxy outliers %d | margin mismatch %d | spread target >2x lane median %d | floor>snapshot wts %d of %d' %
          (ch['vol48_vs_stats_mismatch'], ch['missing_in_stats'], ch['missing_in_prices'],
           ch['sales_day_proxy_outliers'], ch['margin_vs_source_mismatch'],
           ch['target_gt_2x_lane_median'], ch['floor_vs_snapshot_wts']['above_snapshot_best_sell'],
           ch['floor_vs_snapshot_wts']['above_snapshot_best_sell'] + ch['floor_vs_snapshot_wts']['at_or_below']), flush=True)
    for i, r in enumerate(flips[:5], 1):
        print('  #%d %-32s %-8s %sp -> %sp  margin %sp (+%.1f%%)  %.1f/day  queue %d  score %.2f  safe %.2f' %
              (i, r['slug'][:32], r['kind'], r['buy_at'], r['sell_at'], r['profit'],
               r['margin_pct'], r['sales_day'], r['queue_ahead'], r['score'], r['safe_score']), flush=True)
    print('[digest_text]', flush=True)
    print(doc['digest_text'], flush=True)
    print('[out] %s' % OUT_P, flush=True)


if __name__ == '__main__':
    main()
