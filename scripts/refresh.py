"""Refresh pipeline for the dashboard: decrypt AlecaFrame save -> build owned.json.

Reads:  %LOCALAPPDATA%\\AlecaFrame\\lastData.dat (+ cached catalogs)
Writes: data/lastData.dec.json, data/owned.json  (project-local)
"""
import json, os, sys, collections, re, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
AF = os.path.expandvars(r'%LOCALAPPDATA%\AlecaFrame')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # sibling helper: saveio
from saveio import decrypt, normalise, SECTIONS  # noqa: E402  (the one save reader)
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'


def ensure_wfm_items():
    p = os.path.join(DATA, 'wfm_items_v2.json')
    if os.path.exists(p):
        return json.load(open(p, encoding='utf-8'))['data']
    req = urllib.request.Request('https://api.warframe.market/v2/items', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    open(p, 'wb').write(raw)
    return json.loads(raw.decode())['data']


REFINE = re.compile(r'\s+(Intact|Exceptional|Flawless|Radiant)$', re.I)


def main():
    os.makedirs(DATA, exist_ok=True)
    pt = decrypt(os.path.join(AF, 'lastData.dat'))
    save = json.loads(pt.decode('utf-8'))
    save = normalise(save)
    if 'LastInventorySync' not in ''.join(k for k in save.keys()):
        pass  # key presence not guaranteed top-level; the app checks the raw text
    open(os.path.join(DATA, 'lastData.dec.json'), 'wb').write(json.dumps(save).encode('utf-8'))

    basic = json.load(open(os.path.join(AF, 'cachedData', 'custom', 'basic.json'), encoding='utf-8'))['items']
    relics_json = json.load(open(os.path.join(AF, 'cachedData', 'json', 'Relics.json'), encoding='utf-8'))
    path_name = {p: v['name'] for p, v in basic.items()}
    relic_names = {r['uniqueName']: r['name'] for r in relics_json}

    wfm = ensure_wfm_items()
    by_ref = collections.defaultdict(list)
    for it in wfm:
        if it.get('gameRef'):
            by_ref[it['gameRef']].append(it)
    byname = collections.defaultdict(list)
    for it in wfm:
        byname[it['i18n']['en']['name'].lower()].append(it)

    def find_wfm(path, name):
        if path in by_ref:
            return by_ref[path][0], 'ref'
        if '/Projections/' in path:
            rn = relic_names.get(path)
            if rn:
                base = REFINE.sub('', rn)
                hit = byname.get((base + ' Relic').lower()) or byname.get(base.lower())
                if hit:
                    return hit[0], 'relic-name'
        hit = byname.get(name.lower())
        return (hit[0], 'name') if hit else (None, None)

    owned = []
    for sec in SECTIONS:
        for e in save.get(sec) or []:
            if not isinstance(e, dict) or not e.get('ItemType'):
                continue
            t = e['ItemType']
            cnt = e.get('ItemCount') or 1
            nm = path_name.get(t, t.split('/')[-1])
            it, how = find_wfm(t, nm)
            if not it:
                continue
            ref = None
            if '/Projections/' in t:
                m = REFINE.search(relic_names.get(t, ''))
                ref = m.group(1) if m else 'Intact'
            owned.append(dict(slug=it['slug'], name=it['i18n']['en']['name'], count=cnt,
                              ducats=it.get('ducats'), tags=it.get('tags', []), section=sec,
                              path=t, match=how, refinement=ref))
    out_path = os.path.join(DATA, 'owned.json')
    prev = []
    try:
        prev = json.load(open(out_path, encoding='utf-8')) or []
    except Exception:
        prev = []
    if not owned and prev:
        # Never trade a good inventory for an empty decode: the dashboard auto-syncs on a
        # cadence (auto_refresh_seconds, default 900), so one blank or unreadable save must not
        # cost the live rollup - keep the previous file and say so loudly (rc=3 shows in the UI).
        print(json.dumps({'skipped': 'decode produced 0 items', 'kept': len(prev)}))
        raise SystemExit(3)
    tmp = out_path + '.tmp'
    json.dump(owned, open(tmp, 'w', encoding='utf-8'), indent=1)
    os.replace(tmp, out_path)
    summ = dict(mr=save.get('PlayerLevel'), trades=save.get('TradesRemaining'),
                credits=save.get('RegularCredits'), owned=len(owned))
    print(json.dumps(summ))


if __name__ == '__main__':
    main()
