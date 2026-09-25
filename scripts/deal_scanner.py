"""Market-wide deal scanner v1 for warframe.market.

Rotate-scans LIVE orderbooks (GET /v2/orders/item/{id}) over the whole catalogue and
surfaces deals per (rank, subtype) lane -- lanes stay separate because rank 0 and rank 5 of
the same arcane differ 10x:
  spread   - highest visible buy (wtb) pays more than the cheapest visible sell (wts) in the
             same lane -> instant flip.  undercut - floor sits well below the reference price
             (48h median when the item has one sell rank, else the lane's own median).
Floors prefer online/ingame sellers (floor_sell_any = raw min) and order age discounts the
score, since an old wtb is unlikely to still be honoured. Resumable: a cursor into a
priority-sorted rotation ring (owned first, then 48h liquidity) persists in
data/market_scan_state.json, so each run continues where the last one stopped.
Reads data/{owned,prices,stats}.json + data/wfm_items_v2.json; writes data/deals.json +
data/market_scan_state.json. Stdlib only. Example: --max-items 60
"""
import argparse, hashlib, json, os, statistics, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
DEALS_P = os.path.join(DATA, 'deals.json')
STATE_P = os.path.join(DATA, 'market_scan_state.json')
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'
API = 'https://api.warframe.market/v2/orders/item/{}'
ONLINE, SELL, BUY = ('ingame', 'online'), 'sell', 'buy'
STALE_DAYS, MAX_KEEP = 45, 400


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


def age_days(order, now):
    """Days since the order was last touched by its owner (None if unknown)."""
    try:
        raw = str((order or {}).get('updatedAt'))
        return round((now - time.mktime(time.strptime(raw, '%Y-%m-%dT%H:%M:%SZ'))) / 86400.0, 1)
    except Exception:
        return None


def fetch(item_id, tries=3):
    """Flat orderbook list for one item; backs off on 429/5xx."""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(API.format(item_id), headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=25) as resp:
                return (json.loads(resp.read().decode()) or {}).get('data') or [], None
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 502, 503, 504):
                return None, 'http %s' % exc.code
            time.sleep(3 + 2 * attempt)
        except Exception:
            time.sleep(2 + 2 * attempt)
    return None, 'fetch failed'


def is_online(order):
    return str((order.get('user') or {}).get('status') or '') in ONLINE


def pick(orders, cheapest):
    """Best order on a side: online sellers first, then price order."""
    if not orders:
        return None
    return sorted(orders, key=lambda o: (not is_online(o), o['platinum'] if cheapest else -o['platinum']))[0]


def lanes_of(orders):
    """Group visible, quantity>0 orders into (rank, subtype) lanes."""
    lanes = {}
    for o in orders:
        if o.get('visible') is not True or int(o.get('quantity') or 0) < 1:
            continue
        if o.get('type') not in (SELL, BUY) or not o.get('platinum'):
            continue
        lanes.setdefault((o.get('rank'), o.get('subtype')), {SELL: [], BUY: []})[o['type']].append(o)
    return lanes


def lane_metrics(key, bucket, now):
    """Floor / best buy / median for one lane, plus how stale each side is."""
    sells, buys = bucket[SELL], bucket[BUY]
    plats = sorted(o['platinum'] for o in sells)
    bs, bb = pick(sells, True), pick(buys, False)
    su, bu = (bs.get('user') or {}) if bs else {}, (bb.get('user') or {}) if bb else {}
    return {
        'rank': key[0], 'subtype': key[1], 'n_sell': len(sells), 'n_buy': len(buys),
        'n_sell_online': sum(1 for o in sells if is_online(o)), 'n_buy_online': sum(1 for o in buys if is_online(o)),
        'floor_sell': bs['platinum'] if bs else None, 'floor_sell_any': min(plats) if plats else None,
        'floor_seller': su.get('ingameName'), 'floor_status': su.get('status'),
        'floor_qty': int(bs.get('quantity') or 0) if bs else None, 'floor_age': age_days(bs, now),
        'top_buy': bb['platinum'] if bb else None, 'top_buy_any': max((o['platinum'] for o in buys), default=None),
        'top_buyer': bu.get('ingameName'), 'top_buy_status': bu.get('status'), 'buy_age': age_days(bb, now),
        'buy_qty': int(bb.get('quantity') or 0) if bb else None, 'lane_max_sell': plats[-1] if plats else None,
        'lane_median': statistics.median(plats) if plats else None}


def evaluate(item, metrics_list, ref, ref_src, prev_wts, args, now):
    """Turn lane metrics into deal rows (spread outranks undercut on a lane)."""
    deals = []
    for m in metrics_list:
        floor = m['floor_sell']
        if not floor or floor < 1:
            continue
        r, rs = (ref, ref_src) if args.single_rank else (m['lane_median'], 'lane_median')
        if not r:
            r, rs = m['lane_median'], 'lane_median'
        tb, gain, kind = m['top_buy'], None, None
        if tb and tb - floor >= args.min_profit and (tb - floor) * 100.0 / floor >= args.min_spread_pct:
            gain, kind = tb - floor, 'spread'
        elif r and r - floor >= args.min_profit and floor <= r * (1 - args.undercut_pct / 100.0) \
                and m['n_sell'] >= args.min_lane:
            gain, kind = r - floor, 'undercut'
        if kind is None:
            continue
        ages = [a for a in (m['floor_age'], m['buy_age'] if kind == 'spread' else None) if a is not None]
        worst = max(ages) if ages else 0.0
        deals.append({
            'slug': item['slug'], 'name': item['name'], 'item_id': item['id'], 'kind': kind,
            'url': 'https://warframe.market/items/' + item['slug'], 'lane': {'rank': m['rank'], 'subtype': m['subtype']},
            'floor_sell': floor, 'floor_sell_any': m['floor_sell_any'], 'floor_qty': m['floor_qty'],
            'floor_seller': m['floor_seller'], 'floor_status': m['floor_status'], 'floor_age_days': m['floor_age'],
            'top_buy': tb, 'top_buy_any': m['top_buy_any'], 'buy_qty': m['buy_qty'], 'top_buyer': m['top_buyer'],
            'top_buy_status': m['top_buy_status'], 'buy_age_days': m['buy_age'], 'ref': r, 'ref_src': rs,
            'lane_median': m['lane_median'], 'lane_max_sell': m['lane_max_sell'], 'prev_wts': prev_wts,
            'n_sell': m['n_sell'], 'n_buy': m['n_buy'], 'n_sell_online': m['n_sell_online'], 'n_buy_online': m['n_buy_online'],
            'target_price': tb if kind == 'spread' else r, 'profit': round(gain, 2),
            'profit_pct': round(gain * 100.0 / floor, 1),
            'flip_qty': min(m['floor_qty'] or 0, m['buy_qty'] or 0) if kind == 'spread' else m['floor_qty'],
            'vol48': item['vol48'], 'owned': item['own'], 'stale': worst > STALE_DAYS,
            'score': round(gain * (1 + min(item['vol48'], 60) / 200.0) / (1 + worst / 30.0), 2),
            'first_seen': now, 'last_seen': now})
    return deals
def main():
    ap = argparse.ArgumentParser(description='Market-wide wfm deal scanner (rotating, resumable)')
    ap.add_argument('--max-items', type=int, default=60, help='scan budget this run (0 = rest of rotation)')
    ap.add_argument('--sleep', type=float, default=0.5, help='seconds between API calls (floor 0.5)')
    ap.add_argument('--min-profit', type=float, default=3.0, help='min plat gain to call it a deal')
    ap.add_argument('--min-spread-pct', type=float, default=5.0, help='min spread as %% of the sell floor')
    ap.add_argument('--undercut-pct', type=float, default=25.0, help='%% below ref to call it an undercut')
    ap.add_argument('--min-lane', type=int, default=3, help='min visible sellers in a lane for undercut deals')
    ap.add_argument('--window-hours', type=float, default=12.0, help='keep stale deals this long in deals.json')
    args = ap.parse_args()
    args.sleep, now = max(0.5, args.sleep), int(time.time())

    owned = jload(os.path.join(DATA, 'owned.json'), [])
    prices = jload(os.path.join(DATA, 'prices.json'), {})
    stats = jload(os.path.join(DATA, 'stats.json'), {})
    catalog = (jload(os.path.join(DATA, 'wfm_items_v2.json'), {}) or {}).get('data') or []
    if not catalog:
        raise SystemExit('no catalogue: data/wfm_items_v2.json')
    owned_slugs = {o.get('slug') for o in owned if o.get('slug')}
    pool = []
    for it in catalog:
        if not it.get('slug') or not it.get('id'):
            continue
        st = stats.get(it['slug']) or {}
        pool.append({'slug': it['slug'], 'id': it['id'],
                     'name': ((it.get('i18n') or {}).get('en') or {}).get('name', it['slug']),
                     'vol48': int(st.get('vol48') or 0), 'own': 1 if it['slug'] in owned_slugs else 0})
    pool.sort(key=lambda r: (0 if r['own'] else 1, -r['vol48'], r['slug']))
    n_pool = len(pool)
    pool_hash = hashlib.sha1('|'.join(r['slug'] + ':' + r['id'] for r in pool).encode()).hexdigest()[:12]

    state = jload(STATE_P, {}) or {}
    cursor = int(state.get('cursor') or 0)
    if state.get('pool_hash') and state['pool_hash'] != pool_hash:
        print('[scan] pool changed (%s -> %s): rotation restarted' % (state['pool_hash'], pool_hash), flush=True)
        cursor = 0
    cursor %= n_pool
    budget = n_pool if args.max_items <= 0 else min(args.max_items, n_pool)
    print('[scan] pool %d items (%d owned) | cursor %d | budget %d | sleep %.1fs' % (n_pool, len(owned_slugs), cursor, budget, args.sleep), flush=True)

    found, errors, seen = [], 0, {}
    t0 = time.time()
    for i in range(budget):
        item = pool[(cursor + i) % n_pool]
        data, err = fetch(item['id'])
        if err:
            errors += 1
        else:
            st = stats.get(item['slug']) or {}
            ref = st.get('median') or st.get('avg48') or 0
            ref_src = 'stats48' if st.get('median') else ('stats48_avg' if st.get('avg48') else 'lane_median')
            lanes = lanes_of(data)
            args.single_rank = len({k[0] for k, b in lanes.items() if b[SELL]}) <= 1
            found.extend(evaluate(item, [lane_metrics(k, b, now) for k, b in lanes.items()], ref, ref_src,
                                  (prices.get(item['slug']) or {}).get('wts'), args, now))
        seen[item['slug']] = now
        if (i + 1) % 20 == 0 or i + 1 == budget:
            print('[scan] %d/%d in %.0fs, deals %d, errors %d' % (i + 1, budget, time.time() - t0, len(found), errors), flush=True)
        if i + 1 < budget:
            time.sleep(args.sleep)
    scanned, secs = budget, time.time() - t0
    cursor_end = (cursor + scanned) % n_pool

    window, merged, fresh = args.window_hours * 3600, {}, 0
    for d in (jload(DEALS_P, {}) or {}).get('deals') or []:
        if now - int(d.get('last_seen') or 0) <= window:
            merged[(d.get('slug'), d.get('kind'), json.dumps(d.get('lane'), sort_keys=True))] = d
    for d in found:
        key = (d['slug'], d['kind'], json.dumps(d['lane'], sort_keys=True))
        old = merged.get(key)
        if old:
            d['first_seen'] = old.get('first_seen', now)
        else:
            fresh += 1
        merged[key] = d
    rows = sorted(merged.values(), key=lambda d: -float(d.get('score') or 0))[:MAX_KEEP]
    kinds = {}
    for d in rows:
        kinds[d['kind']] = kinds.get(d['kind'], 0) + 1
    stale_n = sum(1 for d in rows if d['stale'])
    jdump(DEALS_P, {
        'version': 1, 'generated': now, 'generated_iso': iso(now), 'window_hours': args.window_hours,
        'params': {'min_profit': args.min_profit, 'min_spread_pct': args.min_spread_pct, 'stale_days': STALE_DAYS,
                   'undercut_pct': args.undercut_pct, 'min_lane': args.min_lane},
        'scan': {'pool_size': n_pool, 'cursor_start': cursor, 'cursor_end': cursor_end, 'items_scanned': scanned,
                 'errors': errors, 'seconds': round(secs, 1), 'sleep': args.sleep, 'priority': 'owned-first then 48h liquidity'},
        'counts': {'run_deals': len(found), 'stale_marked': stale_n, 'total': len(rows), 'by_kind': kinds},
        'deals': rows})
    jdump(STATE_P, {
        'version': 1, 'updated': now, 'updated_iso': iso(now), 'pool_size': n_pool, 'pool_hash': pool_hash,
        'cursor': cursor_end, 'runs': int(state.get('runs') or 0) + 1, 'errors_total': int(state.get('errors_total') or 0) + errors,
        'scanned_total': int(state.get('scanned_total') or 0) + scanned, 'seen': dict(list((state.get('seen') or {}).items()) + list(seen.items())),
        'last_run': {'ts': now, 'iso': iso(now), 'items': scanned, 'deals': len(found), 'errors': errors,
                     'seconds': round(secs, 1), 'cursor_start': cursor, 'cursor_end': cursor_end}})

    print('[deals] run: spread %d | undercut %d | window total %d (fresh %d, stale %d)' % (kinds.get('spread', 0), kinds.get('undercut', 0), len(rows), fresh, stale_n), flush=True)
    for i, d in enumerate(rows[:5], 1):
        print('  #%d %-8s %-30s %sp  floor %s -> target %s  q%s  score %s%s' % (i, d['kind'], d['slug'][:30], d['profit'], d['floor_sell'], d['target_price'], d['flip_qty'], d['score'], ' STALE' if d['stale'] else ''), flush=True)
    print('[state] cursor %d -> %d | scanned_total %d | %.0fs | %s' % (cursor, cursor_end, int(state.get('scanned_total') or 0) + scanned, secs, iso(now)), flush=True)
    print('[out] %s | %s' % (DEALS_P, STATE_P), flush=True)
if __name__ == '__main__':
    main()
