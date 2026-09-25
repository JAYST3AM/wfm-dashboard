"""Relic EV analyzer: expected platinum if a relic is OPENED vs SOLD as-is.

Sources
  data/owned.json          owned relic stacks (tags include 'relic' + 'refinement' + 'count')
  WFCD Relics.json         per-refinement reward tables (drop chances) -- joined on uniqueName == owned 'path'
  data/prices.json         dashboard price cache (wts/wtb) -- used first when it has a price
  api.warframe.market v2   /orders/item/{slug}/top (slug form; the {id} route 404s for some items)
                           for anything still unpriced

Output
  data/relic_ev.json       per relic+refinement rows + summary
  data/relic_prices.json   resumable price cache (plain slugs and slug|subtype)

RELIC_EV rows sort by expected value; recommendations:
  OPEN  EV >= 1.2x the relic's own sell floor   SELL  EV <= 0.8x   HOLD  in between
  Prices use the cheapest visible sell order (wts) as liquidation value; ev_unit_wtb is the
  same expectation against standing buy orders (instant sale) for a conservative floor.
CLI: python scripts/relic_ev.py [--max-age HOURS | --refresh]   (default re-uses cached
  prices < 6h old; --refresh forces one live pass). stdlib only, ASCII output.
"""
import collections
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'
SLEEP = 0.55                      # api.warframe.market politeness (a 2nd scanner runs in parallel)
RELICS_URLS = [
    'https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/Relics.json',
    'https://cdn.jsdelivr.net/gh/WFCD/warframe-items@master/data/json/Relics.json',
]
OPEN_RATIO = 1.2                  # EV must beat the relic's sell price by this much to say OPEN
SELL_RATIO = 0.8
MAX_AGE = 6.0                     # hours; live price cache entries older than this are re-fetched

REFRESH = '--refresh' in sys.argv[1:]
for _a, _arg in enumerate(sys.argv[1:]):
    if _arg.startswith('--max-age'):
        MAX_AGE = float(_arg.split('=')[1]) if '=' in _arg else float(sys.argv[_a + 2])
    elif _arg == '--refresh':
        MAX_AGE = 0.0


def log(msg):
    print(msg, flush=True)


def http_json(url, tries=4):
    """GET json with UA + backoff on throttling."""
    last = None
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            last = f'http {e.code}'
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(3 + 3 * a)
                continue
            return {'__error': last}
        except Exception as e:  # timeouts, dns, truncated body
            last = str(e)
            time.sleep(2 + 2 * a)
    return {'__error': last}


def top_orders(slug):
    """v2 /top by SLUG (the id route 404s for some items, e.g. lith_p8_relic).
    -> orders dict, 'NOT_FOUND' when the market has no such item, or None on transient failure."""
    d = http_json(f'https://api.warframe.market/v2/orders/item/{slug}/top')
    if '__error' in d:
        return 'NOT_FOUND' if d['__error'] == 'http 404' else None
    return d.get('data') or {}


def top_prices(orders, subtype=None):
    """(cheapest visible sell, highest visible buy) from a /top payload.
    If any order carries a subtype, it must match -- relic orders are per refinement."""
    def side(kind, agg):
        rows = [o for o in (orders.get(kind) or []) if o.get('visible')]
        if subtype and any((o.get('subtype') or '') for o in rows):
            rows = [o for o in rows if (o.get('subtype') or '').lower() == subtype]
        return agg((o['platinum'] for o in rows), default=None)
    return side('sell', min), side('buy', max)


def load_json(path, default=None):
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return default


def save_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f)
    os.replace(tmp, path)


# ---------------------------------------------------------------- load local data
owned = load_json(os.path.join(DATA, 'owned.json'), [])
relics = [o for o in owned if {'relic'} & {t.lower() for t in o.get('tags', [])} and o.get('refinement')]
if not relics:
    sys.exit('no owned relic entries found in data/owned.json')

dashboard_prices = load_json(os.path.join(DATA, 'prices.json'), {})

cache_path = os.path.join(DATA, 'relic_prices.json')
cache = load_json(cache_path, {}) or {}
cache.setdefault('items', {})
if REFRESH or MAX_AGE <= 0:                       # drop tainted live entries once, up front
    cache['items'] = {k: v for k, v in cache['items'].items() if not v.get('ts')}
log(f'owned relic stacks: {len(relics)} | cache entries: {len(cache["items"])}')

# ---------------------------------------------------------------- relic reward tables
relic_tables, source = None, None
for url in RELICS_URLS:
    d = http_json(url)
    if isinstance(d, list) and d and 'rewards' in d[0]:
        relic_tables, source = d, url
        log(f'relic table: {url.split("/data/json/")[-1].split("/")[-1]} ({len(d)} entries)')
        break
if relic_tables is None:
    sys.exit('FAILED to download WFCD Relics.json from any mirror (Drops.json fallback is 404/dead)')
by_unique = {r['uniqueName']: r for r in relic_tables}

# ---------------------------------------------------------------- price resolution
fetched_now = 0


def price_for(slug, key, subtype=None):
    """Price of an item (optionally a relic subtype). Cache -> dashboard prices.json -> live /top.
    Returns None only on transient API failure (uncached, so the next run retries)."""
    global fetched_now
    hit = cache['items'].get(key)
    expired = False
    if hit is not None and hit.get('ts') and MAX_AGE > 0:
        age_h = (time.time() - datetime.datetime.fromisoformat(hit['ts']).timestamp()) / 3600.0
        if age_h > MAX_AGE:
            hit, expired = None, True                    # stale: refresh from the market
    if hit is None:
        # dashboard cache is only usable for plain items (its relic numbers are not subtype-filtered)
        dp = dashboard_prices.get(key) if (subtype is None and not expired) else None
        if dp and (dp.get('wts') is not None or dp.get('wtb') is not None):
            hit = {'wts': dp.get('wts'), 'wtb': dp.get('wtb'), 'src': 'prices.json', 'ts': None}
        else:
            time.sleep(SLEEP)
            orders = top_orders(slug)
            fetched_now += 1
            if orders is None:                      # transient failure: retry next run
                return None
            if orders == 'NOT_FOUND':               # market has no such item: genuinely unpriced
                hit = {'wts': None, 'wtb': None, 'src': 'not-on-market', 'ts': None}
            else:
                wts, wtb = top_prices(orders, subtype)
                hit = {'wts': wts, 'wtb': wtb, 'src': 'live',
                       'ts': datetime.datetime.now().isoformat(timespec='seconds')}
        cache['items'][key] = hit
        if fetched_now % 25 == 0:
            save_json(cache_path, cache)
            log(f'  ...{fetched_now} live lookups done')
    return hit


# ---------------------------------------------------------------- build rows
groups = collections.OrderedDict()
for o in relics:
    groups.setdefault((o['slug'], o['refinement']), 0)
    groups[(o['slug'], o['refinement'])] += o.get('count') or 1

rows, missing_slugs, nontrad_occ, one_sided = [], {}, 0, set()
for (slug, refinement) in groups:
    ent = next(o for o in relics if o['slug'] == slug and o['refinement'] == refinement)
    table = by_unique.get(ent['path'])
    rewards = list(table['rewards']) if table else []
    chance_sum = sum(float(r.get('chance') or 0) for r in rewards)
    # raw drop chances are used as-is: chance_sum deviates from 100 only where the WFCD table
    # carries extra/untradable slots (flagged), so no rescaling that would inflate EV

    ev_wts = ev_wtb = 0.0
    priced = 0
    unpriced, best = [], None
    for r in rewards:
        ch = float(r.get('chance') or 0) / 100.0
        m = (r.get('item') or {}).get('warframeMarket')
        if not m:                        # Forma Blueprint / Kuva / Riven Sliver: not on the market, 0 liquidation value
            nontrad_occ += 1
            continue
        p = price_for(m['urlName'], m['urlName'])
        if p is None:                    # transient API failure: uncached, retried next run
            unpriced.append(m['urlName'])
            continue
        wts, wtb = p.get('wts'), p.get('wtb')
        if wts is None and wtb is None:
            unpriced.append(m['urlName'])
            missing_slugs[m['urlName']] = m['id']
            continue
        priced += 1
        v = wts if wts is not None else wtb
        ev_wts += ch * v
        ev_wtb += ch * (wtb if wtb is not None else wts)
        if wts is None or wtb is None:
            one_sided.add(m['urlName'])
        if best is None or v > best[1]:
            best = (r['item']['name'], v, r.get('rarity'))

    # relic as-is: subtype-filtered floor (a plain min over all subtypes mixes refinements)
    rp = price_for(slug, f'{slug}|{refinement.lower()}', subtype=refinement.lower())
    relic_price = None
    if rp is not None:
        relic_price = rp.get('wts') if rp.get('wts') is not None else rp.get('wtb')

    cnt = groups[(slug, refinement)]
    ratio = (ev_wts / relic_price) if (relic_price and relic_price > 0) else None
    no_price = relic_price is None
    if no_price:
        action = 'OPEN' if ev_wts > 0 else 'HOLD'
    elif ratio >= OPEN_RATIO:
        action = 'OPEN'
    elif ratio <= SELL_RATIO:
        action = 'SELL'
    else:
        action = 'HOLD'

    rows.append({
        'relic': ent['name'], 'slug': slug, 'refinement': refinement, 'count': cnt,
        'chance_sum': round(chance_sum, 2),
        'table_complete': abs(chance_sum - 100) <= 0.5,
        'ev_unit_wts': round(ev_wts, 2), 'ev_total_wts': round(ev_wts * cnt, 2),
        'ev_unit_wtb': round(ev_wtb, 2),
        'relic_wts': relic_price, 'relic_total_value': round(relic_price * cnt, 2) if relic_price else None,
        'relic_price_missing': no_price,
        'gain_if_opened_total': round(ev_wts * cnt - (relic_price * cnt if relic_price else 0), 2),
        'ratio': round(ratio, 2) if ratio is not None else None,
        'action': action,
        'rewards_priced': priced, 'rewards_total': len(rewards),
        'unpriced_rewards': unpriced,
        'best_reward': {'name': best[0], 'platinum': best[1], 'rarity': best[2]} if best else None,
    })

save_json(cache_path, cache)

rows.sort(key=lambda r: -r['ev_total_wts'])
tot_ev = sum(r['ev_total_wts'] for r in rows)
tot_sell = sum(r['relic_total_value'] or 0 for r in rows)
acts = collections.Counter(r['action'] for r in rows)
partial = [r for r in rows if r['unpriced_rewards']]

out = {
    'generated': datetime.datetime.now().isoformat(timespec='seconds'),
    'reward_source': source,
    'relic_snapshot': 'data/owned.json',
    'relics_analyzed': len(rows),
    'relic_copies': sum(r['count'] for r in rows),
    'missing_prices': {
        'distinct_reward_slugs': len(missing_slugs),        # reward items with NO price on either side
        'slugs': sorted(missing_slugs),
        'rows_with_unpriced_rewards': len(partial),
        'one_sided_quotes': len(one_sided),                 # priced, but only a sell or only a buy side
        'relics_without_market_price': sum(1 for r in rows if r['relic_price_missing']),
    },
    'non_tradable_reward_slots': nontrad_occ,
    'unmatched_owned_relics': [o['slug'] for o in relics if o['path'] not in by_unique],
    'totals': {
        'ev_if_all_opened': round(tot_ev, 2),
        'value_if_all_sold_as_is': round(tot_sell, 2),
        'actions': dict(acts),
        'live_lookups_this_run': fetched_now,
    },
    'rows': rows,
}
save_json(os.path.join(DATA, 'relic_ev.json'), out)

# ---------------------------------------------------------------- report
log('')
log(f'RELIC EV REPORT  {out["generated"]}')
log(f'  relic stacks analyzed : {len(rows)} ({out["relic_copies"]} copies)')
log(f'  reward prices missing : {len(missing_slugs)} distinct reward items with no price '
    f'({len(partial)} stacks affected; {len(one_sided)} prices are one-sided)')
log(f'  relics w/o price quote: {out["missing_prices"]["relics_without_market_price"]} stacks')
log(f'  non-tradable rewards  : {nontrad_occ} slots (Forma bp etc, 0 trade value)')
log(f'  EV if all opened      : {tot_ev:,.0f}p   |   sell-as-is value: {tot_sell:,.0f}p')
log(f'  verdicts              : {dict(acts)}')
log('')
hdr = f'{"relic (refined)":34} {"cnt":>3} {"ev/unit":>7} {"sell":>5} {"ratio":>5} {"action":>6} {"rewards":>8}'
log(hdr)
log('-' * len(hdr))
for r in rows[:5]:
    tag = f'{r["relic"]} ({r["refinement"][:4]})'
    sell = f'{r["relic_wts"]}' if r['relic_wts'] is not None else 'n/a'
    log(f'{tag[:34]:34} {r["count"]:>3} {r["ev_unit_wts"]:>7.2f} {sell:>5} '
        f'{r["ratio"] if r["ratio"] is not None else 0:>5.2f} {r["action"]:>6} {r["rewards_priced"]}/{r["rewards_total"]:>6}')
log('')
log(f'best open-instead-of-sell: {rows[0]["relic"]} ({rows[0]["refinement"]}) ratio {rows[0]["ratio"]}')
log('wrote data/relic_ev.json + data/relic_prices.json')
