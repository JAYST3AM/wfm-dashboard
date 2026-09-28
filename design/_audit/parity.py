#!/usr/bin/env python3
"""Audit-1 check 1: CONTENT PARITY.

For every Tools workspace list, compute the row count the renderer in static/app.js would
produce, from (a) the raw data/*.json file and (b) the served /api/feature/<name> payload,
then compare against the DOM (the DOM side is filled in by qa_parity.js which appends to
design/_audit/parity.json). This script only reads data files + the local API.

Run:  python3 design/_audit/parity.py
"""
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, 'data')
API = 'http://127.0.0.1:8787/api/feature/'


def jload(p):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:                                   # noqa: BLE001
        return {'__err__': repr(e)}


def api(name):
    try:
        with urllib.request.urlopen(API + name, timeout=20) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:                                   # noqa: BLE001
        return {'__err__': repr(e)}


def cfg():
    return jload(os.path.join(DATA, 'config.json'))


CFG = cfg() if '__err__' not in cfg() else {}
DEALS_SHOWN = CFG.get('deals_shown') or 60


def n(v):
    return len(v) if isinstance(v, (list, dict)) else 0


def expected_from(payload, name):
    """Mirror of the render function in static/app.js -> how many data rows it emits."""
    if name == 'deals':
        return min(14, n(payload.get('deals')))
    if name == 'ducats':
        rows = payload.get('rows') or []
        return min(8, sum(1 for r in rows if r.get('verdict') == 'BURN')) + \
               min(8, sum(1 for r in rows if r.get('verdict') == 'SELL'))
    if name == 'sets':
        return min(12, n(payload.get('top_targets')))
    if name == 'relicev' or name == 'relics':
        return min(12, n(payload.get('rows')))
    if name == 'craft':
        rows = [r for r in (payload.get('rows') or []) if r.get('verdict') != 'SKIP']
        return min(12, len(rows))
    if name == 'movers':
        return min(8, n(payload.get('movers')))
    if name == 'trends':
        return min(6, n(payload.get('top_spikes'))) + min(6, n(payload.get('top_fades')))
    if name == 'rivens':
        return n(payload.get('veiled_bands')) + n(payload.get('owned_rivens'))
    if name == 'watchlist':
        return n(payload.get('entries')) + min(4, n(payload.get('suggested')))
    if name == 'nudges':
        return min(10, n(payload.get('ready')) + min(5, n(payload.get('one_away'))))
    if name == 'baro':
        rows = payload.get('rows') or []
        t = payload.get('trader') or {}
        if not t.get('activation_iso'):
            return 0
        return min(10, len(rows))          # 0 rows -> the note line (counted separately)
    if name == 'meta':
        return min(6, n(payload.get('spike'))) + min(6, n(payload.get('sink')))
    return None


SLUGS = [
    ('deals', 'deals', ['dealsList'], 'dealsList'),
    ('trends', 'movers', ['moversList'], 'moversList'),
    ('trends', 'trends', ['trendsList'], 'trendsList'),
    ('rivens', 'rivens', ['rivensList'], 'rivensList'),
    ('wl', 'watchlist', ['wlList'], 'wlList'),
    ('ducats', 'ducats', ['ducatsList'], 'ducatsList'),
    ('craft', 'craft', ['craftList'], 'craftList'),
    ('relicev', 'relics', ['relicsList'], 'relicsList'),
    ('sets', 'sets', ['setsList'], 'setsList'),
    ('sets', 'nudges', ['nudgesList'], 'nudgesList'),
    ('baro', 'baro', ['baroList'], 'baroList'),
    ('meta', 'meta', ['metaList'], 'metaList'),
]

FEATURE_FILE = {
    'deals': 'deals.json', 'movers': 'price_movers.json', 'trends': 'trends.json',
    'rivens': 'rivens.json', 'watchlist': 'watchlist.json', 'ducats': 'ducats.json',
    'craft': 'craft.json', 'relics': 'relic_ev.json', 'sets': 'sets.json',
    'nudges': 'nudges.json', 'baro': 'baro.json', 'meta': 'meta_watch.json',
    'player': 'player.json',
}


def main():
    out = {'deals_shown_cfg': DEALS_SHOWN, 'lists': [], 'raw_files': {}}
    for slug, feat, ids, dom_id in SLUGS:
        pay = api(feat)
        raw = jload(os.path.join(DATA, FEATURE_FILE[feat]))
        exp_api = expected_from(pay, feat)
        exp_raw = expected_from(raw, feat)
        out['lists'].append({
            'slug': slug, 'feature': feat, 'dom_id': dom_id,
            'api_error': pay.get('__err__'), 'raw_error': raw.get('__err__'),
            'expected_rows_api': exp_api, 'expected_rows_raw_direct': exp_raw,
            'api_matches_raw': exp_api == exp_raw,
        })
        out['raw_files'][feat] = FEATURE_FILE[feat]
    # raw-file row inventory the API transform hides (for the audit table)
    pay = api('deals')
    out['detail'] = {
        'deals_payload_len': n(pay.get('deals')),
        'deals_raw_len': n(jload(os.path.join(DATA, 'deals.json')).get('deals')),
        'ducats_raw_rows': n(jload(os.path.join(DATA, 'ducats.json')).get('rows')),
        'sets_raw_sets': n(jload(os.path.join(DATA, 'sets.json')).get('sets')),
        'sets_top_targets': n(jload(os.path.join(DATA, 'sets.json')).get('top_targets')),
        'craft_raw_rows': n(jload(os.path.join(DATA, 'craft.json')).get('rows')),
        'meta_rows': n(jload(os.path.join(DATA, 'meta_watch.json')).get('rows')),
        'meta_spike': n(jload(os.path.join(DATA, 'meta_watch.json')).get('spike')),
        'meta_sink': n(jload(os.path.join(DATA, 'meta_watch.json')).get('sink')),
        'watchlist_entries': n(jload(os.path.join(DATA, 'watchlist.json')).get('entries')),
        'rivens_bands': n(jload(os.path.join(DATA, 'rivens.json')).get('veiled_bands')),
        'rivens_owned': n(jload(os.path.join(DATA, 'rivens.json')).get('owned_rivens')),
        'nudges_ready': n(jload(os.path.join(DATA, 'nudges.json')).get('ready')),
        'nudges_one_away': n(jload(os.path.join(DATA, 'nudges.json')).get('one_away')),
        'baro_rows': n(jload(os.path.join(DATA, 'baro.json')).get('rows')),
        'player_keys': sorted(list(jload(os.path.join(DATA, 'player.json')).keys()))[:20],
    }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'parity.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=1)
    for row in out['lists']:
        print(f"{row['slug']:8} {row['feature']:10} {row['dom_id']:12} "
              f"api={row['expected_rows_api']} raw={row['expected_rows_raw_direct']} "
              f"same={row['api_matches_raw']} err={row['api_error'] or row['raw_error'] or '-'}")
    print(json.dumps(out['detail'], indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
