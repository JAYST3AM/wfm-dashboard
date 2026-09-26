#!/usr/bin/env python3
r"""Materials / resources store: AlecaFrame save -> data/materials.json.

Inputs (read-only)
    data/lastData.dec.json                                   decrypted save (from refresh.py)
    %LOCALAPPDATA%\AlecaFrame\lastData.dat                   decrypted here when the above is missing
    %LOCALAPPDATA%\AlecaFrame\cachedData\custom\basic.json   item catalog, dict 'items':
                                                             uniqueName -> {name, pic, wiki}
    data/basic_items_cache.json                              cached catalog copy (AlecaFrame absent)

Outputs
    data/materials.json          materials store for the dashboard inventory panel
    data/basic_items_cache.json  refreshed on every successful run

Only save['MiscItems'] feeds this store.  Prime parts, relics and recipes (ItemType
containing Prime / Projections / Recipes / Relic) and rows with a non-positive ItemCount
are skipped - owned.json already covers those.  A row is kept only when its ItemType
resolves to a catalog name (exact ItemType first, then case-insensitive path leaf);
nothing is invented.  Rows that resolve to the same slug are merged (counts summed,
first path kept) and the store is sorted by count desc, then name.

Offline: stdlib only, no network.  Env overrides for the test-suite: MATERIALS_SAVE,
MATERIALS_CATALOG, MATERIALS_CACHE, MATERIALS_OUT.

CLI: --once (default) | --out PATH | --limit N | --json | --dry-run | --selftest
Exit codes: 0 ok, 1 no save / no catalog, 2 selftest failure.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
AF = os.path.expandvars(r'%LOCALAPPDATA%\AlecaFrame')

KEY = bytes([76, 69, 79, 45, 65, 76, 69, 67, 9, 69, 79, 45, 65, 76, 69, 67])
IV = bytes([49, 50, 70, 71, 66, 51, 54, 45, 76, 69, 51, 45, 113, 61, 57, 0])

SAVE = os.environ.get('MATERIALS_SAVE') or os.path.join(DATA, 'lastData.dec.json')
CATALOG = os.environ.get('MATERIALS_CATALOG') or os.path.join(AF, 'cachedData', 'custom', 'basic.json')
CACHE = os.environ.get('MATERIALS_CACHE') or os.path.join(DATA, 'basic_items_cache.json')
OUT = os.environ.get('MATERIALS_OUT') or os.path.join(DATA, 'materials.json')

SCHEMA = 1
FIELDS = ['slug', 'name', 'count', 'cat', 'path', 'pic', 'dojo_hint']
CATS = ['resource', 'component', 'currency', 'other']

SKIP_RE = re.compile(r'Prime|/Projections/|/Recipes/|Relic')
RESOURCE_RE = re.compile(r'/Items/MiscItems/|/Types/Items/')
# Credits/Platinum/Ducats-like rows (Nora & Intermission creds live under /MiscItems/,
# so the currency test has to run BEFORE the resource path test to ever fire).
CURRENCY_RE = re.compile(r'(?i)cred|platinum|ducat')

# clan dojo rooms + research consume these; drives the dojo_hint flag
DOJO_HINT = frozenset((
    'Ferrite', 'Polymer Bundle', 'Plastids', 'Rubedo', 'Salvage', 'Alloy Plate', 'Circuits',
    'Control Module', 'Nano Spores', 'Oxium', 'Cryotic', 'Tellurium', 'Argon Crystal',
    'Gallium', 'Morphics', 'Neurodes', 'Orokin Cell', 'Neural Sensors', 'Kuva', 'Hexenon',
    'Forma', 'Fieldron Sample', 'Detonite Ampule', 'Mutagen Sample', 'Fieldron',
    'Detonite Injector', 'Mutagen Mass'))


def slugify(name):
    """Dashboard-wide slug rule (other agents join on it): non-alnum runs -> '_'."""
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')


def classify(name, path):
    """cat for the store: currency | resource | component | other."""
    leaf = path.rsplit('/', 1)[-1]
    if CURRENCY_RE.search(name) or CURRENCY_RE.search(leaf):
        return 'currency'
    if RESOURCE_RE.search(path) and not SKIP_RE.search(path):
        return 'resource'
    if name.endswith('Component'):
        return 'component'
    return 'other'


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


def load_save(path):
    """Save dict from the decrypted copy; decrypts lastData.dat when that is missing."""
    if path and os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    dat = os.path.join(AF, 'lastData.dat')
    if not os.path.exists(dat):
        raise FileNotFoundError(f'no decrypted save at {path} and no {dat}')
    return json.loads(decrypt(dat).decode('utf-8'))


def catalog_items(path):
    """The uniqueName -> {name, pic, wiki} dict of a basic.json-shaped catalog."""
    with open(path, encoding='utf-8') as f:
        doc = json.load(f)
    items = doc.get('items') if isinstance(doc, dict) else None
    if not isinstance(items, dict):
        raise ValueError('no "items" dict')
    return items


def load_catalog(catalog_path, cache_path):
    """(items, source): basic.json first, then the local cache, else (None, None)."""
    for path, label in ((catalog_path, 'basic.json'), (cache_path, 'cache')):
        if path and os.path.exists(path):
            try:
                return catalog_items(path), label
            except (OSError, ValueError) as e:
                print(f'materials : catalog unreadable ({path}: {e}) - trying the next source')
    return None, None


def leaf_index(items):
    """path-leaf (lowercased) -> (uniqueName, entry), for the case-insensitive fallback."""
    out = {}
    for un, v in items.items():
        if isinstance(v, dict) and v.get('name'):
            out.setdefault(un.rsplit('/', 1)[-1].lower(), (un, v))
    return out


def resolve(item_type, items, leaves):
    """Catalog entry for an ItemType: exact match first, then case-insensitive leaf."""
    v = items.get(item_type)
    if not (isinstance(v, dict) and v.get('name')):
        hit = leaves.get(item_type.rsplit('/', 1)[-1].lower())
        v = hit[1] if hit else None
    return v if isinstance(v, dict) and v.get('name') else None


def collect(save, items, limit=None):
    """save['MiscItems'] -> (rows, stats); rows are merged and sorted, stats are RAW.

    stats describes the pre-merge rows so the printed summary keeps reporting
    'total 278' even though duplicate slugs collapse the store to fewer rows.
    """
    leaves = leaf_index(items)
    by_slug, order = {}, []
    cats = {c: 0 for c in CATS}
    raw = dojo = skipped = 0
    for e in save.get('MiscItems') or []:
        t = e.get('ItemType') if isinstance(e, dict) else None
        cnt = e.get('ItemCount') if isinstance(e, dict) else None
        if not isinstance(t, str) or SKIP_RE.search(t):
            continue
        if not isinstance(cnt, int) or cnt <= 0:
            continue
        v = resolve(t, items, leaves)
        if v is None:
            skipped += 1
            continue
        raw += 1
        name = v['name']
        cats[classify(name, t)] += 1
        hint = name in DOJO_HINT
        dojo += 1 if hint else 0
        s = slugify(name)
        r = by_slug.get(s)
        if r is None:
            by_slug[s] = dict(slug=s, name=name, count=cnt, cat=classify(name, t), path=t,
                              pic=v.get('pic') or None, dojo_hint=hint)
            order.append(s)
        else:
            r['count'] += cnt                       # merge: sum counts, keep the first path
    rows = [by_slug[s] for s in order]
    rows.sort(key=lambda r: (-r['count'], r['name']))
    merged = raw - len(rows)
    if limit is not None and limit >= 0:
        rows = rows[:limit]
    return rows, dict(raw=raw, cats=cats, dojo=dojo, skipped=skipped, merged=merged)


def build_doc(rows, now=None):
    """data/materials.json document for the given (already merged + sorted) rows."""
    now = int(time.time()) if now is None else int(now)
    cats = {c: 0 for c in CATS}
    for r in rows:
        cats[r['cat']] += 1
    return dict(schema=SCHEMA, updated=now,
                updated_iso=datetime.fromtimestamp(now, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                count=len(rows), fields=list(FIELDS), materials=rows, categories=cats)


def save_json(path, obj):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, separators=(',', ':'))
    os.replace(tmp, path)


def save_cache(items, cache_path):
    """Name/pic-only copy of the catalog so later runs work without AlecaFrame."""
    keep = {un: dict(name=v['name'], pic=v.get('pic') or None)
            for un, v in items.items() if isinstance(v, dict) and v.get('name')}
    save_json(cache_path, dict(schema=SCHEMA, updated=int(time.time()),
                               updated_iso=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                               fields=['name', 'pic'], items=keep))
    return len(keep)


def rel(p):
    """Repo-relative display path; absolute when the store lives on another drive."""
    try:
        return os.path.relpath(p, ROOT).replace('\\', '/')
    except ValueError:
        return p.replace('\\', '/')


def summary_line(stats):
    """'materials : total N | resources N | currency N | other N | dojo-relevant N'."""
    c = stats['cats']
    return (f'materials : total {stats["raw"]} | resources {c["resource"]}'
            f' | currency {c["currency"]} | other {c["other"] + c["component"]}'
            f' | dojo-relevant {stats["dojo"]}')


# ------------------------------------------------------------------ selftest

SELFTEST_SAVE = dict(MiscItems=[
    dict(ItemCount=231709, ItemType='/Lotus/Types/Items/MiscItems/AlloyPlate'),
    dict(ItemCount=172629, ItemType='/Lotus/Types/Items/MiscItems/Ferrite'),
    dict(ItemCount=57010, ItemType='/Lotus/Types/Items/MiscItems/PolymerBundle'),
    dict(ItemCount=1249532, ItemType='/Lotus/Types/Items/MiscItems/Nanospores'),
    dict(ItemCount=23, ItemType='/Lotus/Types/Items/MiscItems/Morphic'),
    dict(ItemCount=336, ItemType='/Lotus/Types/Items/MiscItems/NavCode'),
    dict(ItemCount=125, ItemType='/Lotus/Types/Items/MiscItems/NoraIntermissionThreeCreds'),
    dict(ItemCount=6, ItemType='/Lotus/Types/Items/Fish/Deimos/InfestedCommonEFishItem'),
    dict(ItemCount=9, ItemType='/Lotus/Types/Items/Fish/Deimos/InfestedCommonEFishItemMedium'),
    dict(ItemCount=0, ItemType='/Lotus/Types/Items/MiscItems/Circuits'),                   # zero
    dict(ItemCount=2, ItemType='/Lotus/Types/Recipes/Weapons/WeaponParts/BurstonPrimeStock'),  # prime
    dict(ItemCount=3, ItemType='/Lotus/Types/Projections/Lith/RelicLithAMod'),            # relic
    dict(ItemCount=4, ItemType='/Lotus/Types/Items/MiscItems/NotInCatalog'),              # no name
])
SELFTEST_CATALOG = dict(items={
    '/Lotus/Types/Items/MiscItems/AlloyPlate': dict(name='Alloy Plate', pic='AlloyPlate.png', wiki='Alloy_Plate'),
    '/Lotus/Types/Items/MiscItems/Ferrite': dict(name='Ferrite', pic='ComponentFerrite.png', wiki='Ferrite'),
    '/Lotus/Types/Items/MiscItems/PolymerBundle': dict(name='Polymer Bundle', pic='ComponentPolymerBundle.png', wiki='Polymer_Bundle'),
    '/Lotus/Types/Items/MiscItems/Nanospores': dict(name='Nano Spores', pic='ComponentNanospores.png', wiki='Nano_Spores'),
    '/Lotus/Types/Items/MiscItems/Morphic': dict(name='Morphics', wiki='Morphics'),
    '/Lotus/Types/Items/MiscItems/NavCode': dict(name='Nav Coordinate', pic='NavCodeIcon.png', wiki='Nav_Coordinate'),
    '/Lotus/Types/Items/MiscItems/NoraIntermissionThreeCreds': dict(name='Intermission Iii Cred', pic='CredIcon.png', wiki='Nightwave'),
    '/Lotus/Types/Items/Fish/Deimos/InfestedCommonEFishItem': dict(name='Lobotriscid', pic=None),
    '/Lotus/Types/Items/Fish/Deimos/InfestedCommonEFishItemMedium': dict(name='Lobotriscid', wiki='Lobotriscid'),
})


def selftest():
    """Offline fixture run in a scratch dir: no AlecaFrame, no network, tmp files only."""
    checks = []

    def ok(cond, what):
        if not cond:
            raise AssertionError(what)
        checks.append(what)

    try:
        with tempfile.TemporaryDirectory(prefix='materials_selftest_') as td:
            sp = os.path.join(td, 'lastData.dec.json')
            cp = os.path.join(td, 'basic.json')
            cache = os.path.join(td, 'basic_items_cache.json')
            out = os.path.join(td, 'materials.json')
            save_json(sp, SELFTEST_SAVE)
            save_json(cp, SELFTEST_CATALOG)

            save = load_save(sp)
            ok(len(save['MiscItems']) == 13, 'fixture save loaded (13 MiscItems)')

            # decrypt() plaintext fallback + AES round-trip via the refresh.py KEY/IV
            plain = os.path.join(td, 'plain.dat')
            open(plain, 'wb').write(b'{"MiscItems": []}')
            ok(decrypt(plain) == b'{"MiscItems": []}', 'decrypt() passes plaintext through')
            try:
                from cryptography.hazmat.primitives import padding
                from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
                enc = os.path.join(td, 'lastData.dat')
                pad = padding.PKCS7(128).padder()
                body = pad.update(json.dumps(SELFTEST_SAVE).encode('utf-8')) + pad.finalize()
                e = Cipher(algorithms.AES(KEY), modes.CBC(IV)).encryptor()
                open(enc, 'wb').write(e.update(body) + e.finalize())
                ok(json.loads(decrypt(enc).decode('utf-8')) == SELFTEST_SAVE,
                   'decrypt() AES-128-CBC round-trip with the refresh.py KEY/IV')
            except ImportError:
                pass  # cryptography absent: the plaintext fallback above still ran

            items = catalog_items(cp)
            rows, stats = collect(save, items)
            ok(stats['raw'] == 9, 'skips prime/relic/zero/unresolvable rows (9 raw of 13)')
            ok(len(rows) == 8 and stats['merged'] == 1, 'duplicate slugs merged (8 rows, 1 merge)')
            ok(all(r['path'].find('Prime') < 0 for r in rows), 'no prime rows survived')
            by = {r['slug']: r for r in rows}
            ok(round(by['lobotriscid']['count']) == 15, 'merged duplicate counts sum (6 + 9)')
            ok(by['lobotriscid']['path'].endswith('InfestedCommonEFishItem'), 'first path kept')
            ok(by['alloy_plate']['cat'] == 'resource', 'Alloy Plate classified resource')
            ok(by['intermission_iii_cred']['cat'] == 'currency', 'Intermission cred classified currency')
            ok(by['nav_coordinate']['name'] == 'Nav Coordinate', 'exact ItemType resolution')
            ok(by['morphics']['pic'] is None, 'missing catalog pic stays null')
            ok(by['alloy_plate']['pic'] == 'AlloyPlate.png', 'catalog pic passed through')
            ok(by['ferrite']['dojo_hint'] and by['polymer_bundle']['dojo_hint'], 'dojo hint set')
            ok(not by['nav_coordinate']['dojo_hint'], 'dojo hint off for unlisted names')
            ok([r['slug'] for r in rows][0] == 'nano_spores', 'sorted by count desc first')
            ok(stats['cats']['currency'] == 1 and stats['cats']['resource'] == 8, 'raw category counts')

            doc = build_doc(rows, now=1700000000)
            ok(list(doc) == ['schema', 'updated', 'updated_iso', 'count', 'fields', 'materials',
                             'categories'], 'store keys exact')
            ok(doc['fields'] == FIELDS and doc['count'] == 8, 'fields + count')
            ok(doc['updated'] == 1700000000 and doc['updated_iso'].endswith('Z'), 'timestamps')
            ok(sum(doc['categories'].values()) == len(doc['materials']), 'categories sum to count')
            save_json(out, doc)
            ok(os.path.exists(out) and sum(1 for _ in open(out, encoding='utf-8')) == 1,
               'store written to the tmp dir only')

            save_cache(items, cache)
            got, source = load_catalog(os.path.join(td, 'missing', 'basic.json'), cache)
            ok(source == 'cache' and got['/Lotus/Types/Items/MiscItems/AlloyPlate']['name'] == 'Alloy Plate',
               'catalog falls back to the local cache')
            ok(len(got) == 9, 'cache kept 9 name/pic entries')
    except AssertionError as e:
        print(f'selftest : FAILED - {e}')
        return 2
    print(f'selftest : ok ({len(checks)} checks) offline - no AlecaFrame, no network')
    return 0


# ------------------------------------------------------------------ CLI

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='materials.py', description='Build data/materials.json from the AlecaFrame save.',
        epilog='Exit codes: 0 ok, 1 no save/catalog, 2 selftest failure.')
    ap.add_argument('--once', action='store_true', help='single pass (default; kept for cron lines)')
    ap.add_argument('--out', metavar='PATH', help='store path to write (default data/materials.json)')
    ap.add_argument('--limit', type=int, metavar='N', help='write only the N largest materials')
    ap.add_argument('--json', action='store_true', help='also print the store JSON to stdout')
    ap.add_argument('--dry-run', action='store_true', help='print the plan and write nothing')
    ap.add_argument('--selftest', action='store_true',
                    help='offline fixture run in a temp dir (no AlecaFrame, no network)')
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    t0 = time.time()
    out_path = args.out or OUT
    try:
        save = load_save(SAVE)
    except (OSError, ValueError) as e:
        print(f'materials : save unreadable ({e}) - run scripts/refresh.py first')
        return 1
    items, source = load_catalog(CATALOG, CACHE)
    if items is None:
        print(f'materials : no item catalog ({CATALOG} or {CACHE}) - run scripts/refresh.py first')
        return 1

    rows, stats = collect(save, items, limit=args.limit)
    print(summary_line(stats))                       # summary line FIRST

    if args.dry_run:
        print(f'plan : {stats["skipped"]} row(s) skipped (no catalog name),'
              f' {stats["merged"]} duplicate row(s) merged')
        print(f'plan : write {len(rows)} rows -> {rel(out_path)}  (catalog: {source})')
        print('plan : dry-run - nothing written')
        if args.json:
            print(json.dumps(build_doc(rows), separators=(',', ':')))
        return 0

    doc = build_doc(rows)
    save_json(out_path, doc)
    save_cache(items, CACHE)
    print(f'store : {rel(out_path)} ({os.path.getsize(out_path) / 1024.0:.1f} KB)')
    if args.json:
        print(json.dumps(doc, separators=(',', ':')))
    print(f'runtime : {time.time() - t0:.2f}s')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
