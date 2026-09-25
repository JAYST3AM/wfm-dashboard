"""Fetch warframe.market item statistics (liquidity + price quality) for owned slugs.

Source: GET https://api.warframe.market/v1/items/{slug}/statistics
Writes: data/stats.json  (resumable, slug -> {vol48, volday90, med48, wa48, min48, max48, avg48})
"""
import json, os, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'
API = 'https://api.warframe.market/v1/items/{}/statistics'


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def agg(buckets):
    """Volume-weighted median/wa price + extremes over a bucket list."""
    vol = sum((b.get('volume') or 0) for b in buckets)
    wmed = wwa = 0.0
    mins, maxs = [], []
    for b in buckets:
        v = b.get('volume') or 0
        if b.get('median') is not None:
            wmed += b['median'] * v
        if b.get('wa_price') is not None:
            wwa += b['wa_price'] * v
        if b.get('min_price') is not None:
            mins.append(b['min_price'])
        if b.get('max_price') is not None:
            maxs.append(b['max_price'])
    return dict(
        vol=vol,
        med=(wmed / vol) if vol else None,
        wa=(wwa / vol) if vol else None,
        mn=min(mins) if mins else None,
        mx=max(maxs) if maxs else None,
    )


def main():
    prices = json.load(open(os.path.join(DATA, 'prices.json'), encoding='utf-8'))
    slugs = sorted(prices.keys())
    outp = os.path.join(DATA, 'stats.json')
    out = {}
    if os.path.exists(outp):
        try:
            out = json.load(open(outp, encoding='utf-8'))
        except Exception:
            out = {}
    todo = [s for s in slugs if s not in out]
    print(f'stats: {len(slugs)} slugs | done: {len(slugs) - len(todo)} | to fetch: {len(todo)}', flush=True)
    t0 = time.time()
    for i, slug in enumerate(todo, 1):
        try:
            j = get(API.format(slug))
            closed = j['payload']['statistics_closed']
            h48 = (closed.get('48hours') or [])[-48:]
            d90 = closed.get('90days') or []
            a48, a90 = agg(h48), agg(d90)
            out[slug] = dict(vol48=a48['vol'], volday90=round(a90['vol'] / 90, 2) if a90['vol'] else 0,
                             med48=a48['med'], avg48=a48['wa'], median=a48['med'],
                             min48=a48['mn'], max48=a48['mx'])
        except Exception as e:
            out[slug] = dict(error=str(e)[:120])
        if i % 40 == 0 or i == len(todo):
            json.dump(out, open(outp, 'w', encoding='utf-8'), indent=0)
            el = time.time() - t0
            eta = (el / i) * (len(todo) - i) if i else 0
            print(f'{i}/{len(todo)} done, elapsed {el:.0f}s, eta {eta:.0f}s', flush=True)
        time.sleep(0.12)
    json.dump(out, open(outp, 'w', encoding='utf-8'), indent=0)
    ok = sum(1 for v in out.values() if 'error' not in v)
    print(f'ALL DONE {len(out)} stats written ({ok} ok)', flush=True)


if __name__ == '__main__':
    main()
