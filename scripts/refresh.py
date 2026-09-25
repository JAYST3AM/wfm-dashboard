"""Refresh pipeline for the dashboard: decrypt AlecaFrame save -> build owned.json.

Reads:  %LOCALAPPDATA%\\AlecaFrame\\lastData.dat (+ cached catalogs)
Writes: data/lastData.dec.json, data/owned.json  (project-local)
"""
import json, os, sys, collections, re, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
AF = os.path.expandvars(r'%LOCALAPPDATA%\AlecaFrame')

KEY = bytes([76, 69, 79, 45, 65, 76, 69, 67, 9, 69, 79, 45, 65, 76, 69, 67])
IV = bytes([49, 50, 70, 71, 66, 51, 54, 45, 76, 69, 51, 45, 113, 61, 57, 0])
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'


def decrypt(p):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    raw = open(p, 'rb').read()
    if raw[:1] == b'{':
        return raw  # plaintext fallback path the app itself supports
    d = Cipher(algorithms.AES(KEY), modes.CBC(IV)).decryptor()
    pt = d.update(raw) + d.finalize()
    pad = pt[-1]
    if 1 <= pad <= 16 and pt[-pad:] == bytes([pad]) * pad:
        pt = pt[:-pad]
    return pt


def ensure_wfm_items():
    p = os.path.join(DATA, 'wfm_items_v2.json')
    if os.path.exists(p):
        return json.load(open(p, encoding='utf-8'))['data']
    req = urllib.request.Request('https://api.warframe.market/v2/items', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    open(p, 'wb').write(raw)
    return json.loads(raw.decode())['data']


SECTIONS = ['MiscItems', 'Recipes', 'RawUpgrades', 'Upgrades', 'WeaponSkins', 'Sentinels',
            'SentinelWeapons', 'SpaceGuns', 'SpaceMelee', 'SpaceSuits', 'MechSuits', 'KubrowPets',
            'Scoops', 'DataKnives', 'OperatorAmps', 'CrewShipWeapons', 'CrewShipWeaponSkins',
            'CrewShipRawSalvage', 'CrewShipAmmo', 'SpecialItems', 'FlavourItems', 'LevelKeys', 'QuestKeys']
REFINE = re.compile(r'\s+(Intact|Exceptional|Flawless|Radiant)$', re.I)


def main():
    os.makedirs(DATA, exist_ok=True)
    pt = decrypt(os.path.join(AF, 'lastData.dat'))
    save = json.loads(pt.decode('utf-8'))
    if 'LastInventorySync' not in ''.join(k for k in save.keys()):
        pass  # key presence not guaranteed top-level; the app checks the raw text
    open(os.path.join(DATA, 'lastData.dec.json'), 'wb').write(pt)

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
    json.dump(owned, open(os.path.join(DATA, 'owned.json'), 'w', encoding='utf-8'), indent=1)
    summ = dict(mr=save.get('PlayerLevel'), trades=save.get('TradesRemaining'),
                credits=save.get('RegularCredits'), owned=len(owned))
    print(json.dumps(summ))


if __name__ == '__main__':
    main()
