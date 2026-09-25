"""Fetch live top prices for every owned sellable slug. Resumable -> data/prices.json."""
import json, os, time, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'

owned = json.load(open(os.path.join(DATA, 'owned.json'), encoding='utf-8'))
wfm = json.load(open(os.path.join(DATA, 'wfm_items_v2.json'), encoding='utf-8'))['data']
byslug = {it['slug']: it for it in wfm}

PF = os.path.join(DATA, 'prices.json')
prices = json.load(open(PF, encoding='utf-8')) if os.path.exists(PF) else {}

# unique sellable slugs (skip built gear matched to a whole set/weapon entry)
slugs, seen = [], set()
for o in owned:
    t = set(o['tags'])
    if 'set' in t and 'prime' not in t and o['section'] in ('Suits', 'LongGuns', 'Pistols', 'Melee', 'Sentinels', 'SentinelWeapons'):
        continue
    if o['slug'] in seen:
        continue
    seen.add(o['slug'])
    slugs.append(o['slug'])

todo = [s for s in slugs if s not in prices]
print(f'prices: {len(slugs)} slugs | done {len(slugs) - len(todo)} | to fetch {len(todo)}', flush=True)


def fetch(slug, tries=4):
    it = byslug[slug]
    url = f"https://api.warframe.market/v2/orders/item/{it['id']}/top"
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode())['data']
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503):
                time.sleep(4 + 3 * a)
                continue
            return {'error': f'http {e.code}'}
        except Exception:
            time.sleep(2 + 2 * a)
    return {'error': 'failed'}


done = 0
t0 = time.time()
for slug in todo:
    d = fetch(slug)
    sells = [o for o in (d.get('sell') or []) if o.get('visible')]
    buys = [o for o in (d.get('buy') or []) if o.get('visible')]
    wts = min((o['platinum'] for o in sells), default=None)
    wtb = max((o['platinum'] for o in buys), default=None)
    prices[slug] = {'wts': wts, 'wtb': wtb, 'n_sell': len(sells), 'n_buy': len(buys)}
    done += 1
    if done % 40 == 0 or done == len(todo):
        json.dump(prices, open(PF, 'w', encoding='utf-8'))
        el = time.time() - t0
        eta = el / done * (len(todo) - done)
        print(f'{done}/{len(todo)} done, elapsed {el:.0f}s, eta {eta:.0f}s', flush=True)
    time.sleep(0.32)

json.dump(prices, open(PF, 'w', encoding='utf-8'))
print('prices done', len(prices), flush=True)
