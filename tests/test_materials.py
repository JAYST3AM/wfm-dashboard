"""scripts/materials.py: slug rule, filters, merge, cache fallback, CLI contract.

materials.py reads MATERIALS_SAVE / MATERIALS_CATALOG / MATERIALS_CACHE / MATERIALS_OUT from
the environment at import time, so the fixture loads it through those overrides (proving the
documented env hook works) and every path lands under tmp_path - the repo's real data/
directory is never read or written, and no network or AlecaFrame file is ever touched.
"""
import json
import os
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

from conftest import load_script, read_json, write_json

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), 'scripts', 'materials.py')

SAVE_KEYS = {'schema', 'updated', 'updated_iso', 'count', 'fields', 'materials', 'categories'}
FIELDS = ['slug', 'name', 'count', 'cat', 'path', 'pic', 'dojo_hint']
SUMMARY_RE = re.compile(
    r'^materials : total \d+ \| resources \d+ \| currency \d+ \| other \d+ \| dojo-relevant \d+$')
STORE_RE = re.compile(r'^store : .+ \(\d+\.\d KB\)$')

BASE_CATALOG = {
    '/Lotus/Types/Items/MiscItems/Nanospores': {'name': 'Nano Spores', 'pic': 'ComponentNanospores.png', 'wiki': 'Nano_Spores'},
    '/Lotus/Types/Items/MiscItems/AlloyPlate': {'name': 'Alloy Plate', 'pic': 'AlloyPlate.png', 'wiki': 'Alloy_Plate'},
    '/Lotus/Types/Items/MiscItems/Ferrite': {'name': 'Ferrite', 'pic': 'ComponentFerrite.png', 'wiki': 'Ferrite'},
    '/Lotus/Types/Items/MiscItems/PolymerBundle': {'name': 'Polymer Bundle', 'pic': 'ComponentPolymerBundle.png', 'wiki': 'Polymer_Bundle'},
    '/Lotus/Types/Items/MiscItems/VoidTearDrop': {'name': 'Void Traces', 'pic': 'VoidTearDrop.png', 'wiki': 'Void_Traces'},
    '/Lotus/Types/Items/MiscItems/NavCode': {'name': 'Nav Coordinate', 'pic': 'NavCodeIcon.png', 'wiki': 'Nav_Coordinate'},
    '/Lotus/Types/Items/MiscItems/NoraIntermissionThreeCreds': {'name': 'Intermission Iii Cred', 'pic': 'CredIcon.png'},
    '/Lotus/Types/Items/MiscItems/Morphic': {'name': 'Morphics'},                    # pic missing
    '/Lotus/Types/Items/Fish/Deimos/InfestedCommonEFishItem': {'name': 'Lobotriscid', 'pic': None},
    '/Lotus/Types/Items/Fish/Deimos/InfestedCommonEFishItemMedium': {'name': 'Lobotriscid'},
}


@pytest.fixture
def mp(tmp_path, monkeypatch):
    """materials.py loaded with every path redirected into tmp_path."""
    catalog_dir = tmp_path / 'af' / 'cachedData' / 'custom'
    save = tmp_path / 'data' / 'lastData.dec.json'
    out = tmp_path / 'data' / 'materials.json'
    cache = tmp_path / 'data' / 'basic_items_cache.json'
    mod = load_script('materials', monkeypatch=monkeypatch, env={
        'MATERIALS_SAVE': str(save), 'MATERIALS_CATALOG': str(catalog_dir / 'basic.json'),
        'MATERIALS_CACHE': str(cache), 'MATERIALS_OUT': str(out)})
    return SimpleNamespace(mod=mod, tmp=tmp_path, save=save, out=out, cache=cache,
                           catalog=catalog_dir / 'basic.json')


def item(path, count):
    return {'ItemCount': count, 'ItemType': path}


def seed(mp, items, catalog=None):
    """Fixture save + catalog; returns the item list for convenience."""
    write_json(mp.save, {'MiscItems': items})
    write_json(mp.catalog, {'items': BASE_CATALOG if catalog is None else catalog})
    return items


def base_save():
    """10 resolvable rows: 9 resources + 1 currency, one merged pair, plus decoys."""
    return [
        item('/Lotus/Types/Items/MiscItems/Nanospores', 1249532),
        item('/Lotus/Types/Items/MiscItems/AlloyPlate', 231709),
        item('/Lotus/Types/Items/MiscItems/Ferrite', 172629),
        item('/Lotus/Types/Items/MiscItems/PolymerBundle', 57010),
        item('/Lotus/Types/Items/MiscItems/VoidTearDrop', 390),
        item('/Lotus/Types/Items/MiscItems/NavCode', 336),
        item('/Lotus/Types/Items/MiscItems/NoraIntermissionThreeCreds', 125),
        item('/Lotus/Types/Items/MiscItems/Morphic', 23),
        item('/Lotus/Types/Items/Fish/Deimos/InfestedCommonEFishItem', 6),
        item('/Lotus/Types/Items/Fish/Deimos/InfestedCommonEFishItemMedium', 9),
        item('/Lotus/Types/Items/MiscItems/Circuits', 0),                                  # zero count
        item('/Lotus/Types/Items/MiscItems/Neurode', -3),                                  # negative
        item('/Lotus/Types/Items/MiscItems/CircuitsPrimeBlueprint', 4),                    # prime part
        item('/Lotus/Types/Recipes/Weapons/WeaponParts/BurstonPrimeStock', 2),             # recipe
        item('/Lotus/Types/Projections/Lith/RelicLithAMod', 5),                            # relic
        item('/Lotus/Types/Items/MiscItems/NotInCatalogAtAll', 7),                         # no name
    ]


def run(mp, argv=None):
    return mp.mod.main(argv or [])


# ------------------------------------------------------------------ env override / loading

def test_env_paths_override_repo_data(mp):
    assert mp.mod.SAVE == str(mp.save)
    assert mp.mod.CATALOG == str(mp.catalog)
    assert mp.mod.CACHE == str(mp.cache)
    assert mp.mod.OUT == str(mp.out)
    for p in (mp.mod.SAVE, mp.mod.CATALOG, mp.mod.CACHE, mp.mod.OUT):
        assert p.startswith(str(mp.tmp))          # nothing points at the repo's real data/


def test_missing_save_returns_1_and_writes_nothing(mp, capsys):
    assert run(mp) == 1
    assert 'refresh.py' in capsys.readouterr().out
    assert not mp.out.exists() and not mp.cache.exists()


def test_missing_catalog_returns_1(mp, capsys):
    write_json(mp.save, {'MiscItems': []})        # save present, catalog + cache absent
    assert run(mp) == 1
    assert 'no item catalog' in capsys.readouterr().out
    assert not mp.out.exists()


# ------------------------------------------------------------------ pure rules

@pytest.mark.parametrize('name,slug', [
    ('Alloy Plate', 'alloy_plate'),
    ('Nano Spores', 'nano_spores'),
    ('Orokin Cell', 'orokin_cell'),
    ('Nav Coordinate', 'nav_coordinate'),
    ("Nora's Mix Vol. 6 Cred", 'nora_s_mix_vol_6_cred'),
])
def test_slug_rule_cases(mp, name, slug):
    assert mp.mod.slugify(name) == slug


def test_classify_rule_cases(mp):
    c = mp.mod.classify
    assert c('Alloy Plate', '/Lotus/Types/Items/MiscItems/AlloyPlate') == 'resource'
    assert c('Kuva', '/Lotus/Types/Items/MiscItems/Kuva') == 'resource'
    assert c('Salvage', '/Lotus/Types/Gameplay/InfestedMicroplanet/Resources/SalvageItem') == 'other'
    assert c('Duroid', '/Lotus/Types/Gameplay/Zariman/Resources/ZarimanMiscItemB') == 'other'
    assert c('Ducats', '/Lotus/Types/Items/MiscItems/Ducats') == 'currency'
    assert c('Intermission Iii Cred', '/Lotus/Types/Items/MiscItems/NoraIntermissionThreeCreds') == 'currency'
    assert c('Foo Component', '/Lotus/Types/Gameplay/KubrowPet/FooComponent') == 'component'


def test_decrypt_plaintext_fallback_and_aes_roundtrip(mp):
    plain = mp.tmp / 'plain.dat'
    plain.write_bytes(b'{"MiscItems": []}')
    assert mp.mod.decrypt(str(plain)) == b'{"MiscItems": []}'
    pytest.importorskip('cryptography')
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    payload = json.dumps({'MiscItems': [item('/Lotus/Types/Items/MiscItems/AlloyPlate', 7)]}).encode()
    pad = padding.PKCS7(128).padder()
    body = pad.update(payload) + pad.finalize()
    enc = Cipher(algorithms.AES(mp.mod.KEY), modes.CBC(mp.mod.IV)).encryptor()
    (mp.tmp / 'lastData.dat').write_bytes(enc.update(body) + enc.finalize())
    assert mp.mod.decrypt(str(mp.tmp / 'lastData.dat')) == payload
    assert mp.mod.KEY == bytes([76, 69, 79, 45, 65, 76, 69, 67, 9, 69, 79, 45, 65, 76, 69, 67])
    assert mp.mod.IV == bytes([49, 50, 70, 71, 66, 51, 54, 45, 76, 69, 51, 45, 113, 61, 57, 0])


def test_save_is_decrypted_from_lastdata_dat_when_absent(mp, monkeypatch):
    pytest.importorskip('cryptography')
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    af = mp.tmp / 'fake_af'
    af.mkdir()
    payload = json.dumps({'MiscItems': [item('/Lotus/Types/Items/MiscItems/AlloyPlate', 11)]}).encode()
    pad = padding.PKCS7(128).padder()
    body = pad.update(payload) + pad.finalize()
    enc = Cipher(algorithms.AES(mp.mod.KEY), modes.CBC(mp.mod.IV)).encryptor()
    (af / 'lastData.dat').write_bytes(enc.update(body) + enc.finalize())
    monkeypatch.setattr(mp.mod, 'AF', str(af))
    write_json(mp.catalog, {'items': BASE_CATALOG})

    assert run(mp) == 0                                       # no lastData.dec.json exists
    doc = read_json(mp.out)
    assert doc['materials'][0]['slug'] == 'alloy_plate' and doc['materials'][0]['count'] == 11


# ------------------------------------------------------------------ store contract

def test_store_schema_keys_exact_and_row_types(mp):
    seed(mp, base_save())
    assert run(mp) == 0
    doc = read_json(mp.out)
    assert set(doc) == SAVE_KEYS
    assert list(doc) == ['schema', 'updated', 'updated_iso', 'count', 'fields', 'materials', 'categories']
    assert doc['schema'] == 1
    assert isinstance(doc['updated'], int) and doc['updated'] > 1_600_000_000
    assert doc['updated_iso'].endswith('Z') and 'T' in doc['updated_iso']
    assert doc['fields'] == FIELDS
    assert doc['count'] == len(doc['materials']) == 9
    for r in doc['materials']:
        assert list(r) == FIELDS
        assert isinstance(r['slug'], str) and isinstance(r['name'], str)
        assert isinstance(r['count'], int) and r['count'] > 0
        assert r['cat'] in ('resource', 'component', 'currency', 'other')
        assert isinstance(r['path'], str) and r['path'].startswith('/Lotus/')
        assert r['pic'] is None or isinstance(r['pic'], str)
        assert isinstance(r['dojo_hint'], bool)


def test_categories_totals_equal_len_materials(mp):
    seed(mp, base_save())
    assert run(mp) == 0
    doc = read_json(mp.out)
    assert doc['categories'] == {'resource': 8, 'component': 0, 'currency': 1, 'other': 0}
    assert sum(doc['categories'].values()) == len(doc['materials']) == doc['count']


def test_prime_relic_and_recipe_rows_excluded(mp):
    seed(mp, base_save())
    assert run(mp) == 0
    doc = read_json(mp.out)
    assert all(not re.search(r'Prime|/Projections/|/Recipes/|Relic', r['path']) for r in doc['materials'])
    slugs = {r['slug'] for r in doc['materials']}
    assert 'circuits_prime_blueprint' not in slugs and 'burston_prime_stock' not in slugs
    assert 'relic_lith_a_mod' not in slugs and 'lith_a_mod' not in slugs


def test_nonpositive_counts_dropped(mp):
    seed(mp, base_save())
    assert run(mp) == 0
    slugs = {r['slug'] for r in read_json(mp.out)['materials']}
    assert 'circuits' not in slugs          # ItemCount 0
    assert 'neurodes' not in slugs          # ItemCount -3
    assert all(r['count'] > 0 for r in read_json(mp.out)['materials'])


def test_unresolvable_rows_are_skipped_not_invented(mp):
    seed(mp, base_save())
    assert run(mp) == 0
    doc = read_json(mp.out)
    assert 'not_in_catalog_at_all' not in {r['slug'] for r in doc['materials']}
    names = {r['name'] for r in doc['materials']}
    assert 'NotInCatalogAtAll' not in names                  # never invents a name
    assert names == {v['name'] for v in BASE_CATALOG.values()}


def test_duplicate_slugs_merge_summing_counts(mp):
    seed(mp, base_save())
    assert run(mp) == 0
    doc = read_json(mp.out)
    rows = [r for r in doc['materials'] if r['slug'] == 'lobotriscid']
    assert len(rows) == 1 and rows[0]['count'] == 15        # 6 + 9, merged not multiplied
    assert rows[0]['path'].endswith('InfestedCommonEFishItem')   # first path kept
    assert doc['count'] == 9                                # 10 raw rows -> 9 unique slugs


def test_name_resolution_falls_back_to_leaf_case_insensitive(mp):
    seed(mp, [item('/Lotus/Types/Items/MiscItems/ALLOYPLATE', 42)])
    assert run(mp) == 0
    doc = read_json(mp.out)
    assert doc['materials'][0]['name'] == 'Alloy Plate'
    assert doc['materials'][0]['slug'] == 'alloy_plate'
    assert doc['materials'][0]['path'] == '/Lotus/Types/Items/MiscItems/ALLOYPLATE'   # save path kept


def test_sorted_by_count_desc_then_name(mp):
    seed(mp, [
        item('/Lotus/Types/Items/MiscItems/NavCode', 5),
        item('/Lotus/Types/Items/MiscItems/Morphic', 5),
        item('/Lotus/Types/Items/MiscItems/AlloyPlate', 100),
    ], catalog={
        '/Lotus/Types/Items/MiscItems/NavCode': {'name': 'Zeta Bloom'},
        '/Lotus/Types/Items/MiscItems/Morphic': {'name': 'Alpha Bloom'},
        '/Lotus/Types/Items/MiscItems/AlloyPlate': {'name': 'Alloy Plate'},
    })
    assert run(mp) == 0
    names = [r['name'] for r in read_json(mp.out)['materials']]
    assert names == ['Alloy Plate', 'Alpha Bloom', 'Zeta Bloom']


def test_dojo_hint_true_for_listed_and_false_for_unlisted(mp):
    seed(mp, base_save())
    assert run(mp) == 0
    rows = {r['slug']: r for r in read_json(mp.out)['materials']}
    assert rows['ferrite']['dojo_hint'] is True
    assert rows['polymer_bundle']['dojo_hint'] is True
    assert rows['void_traces']['dojo_hint'] is False


def test_pic_passed_through_or_null(mp):
    seed(mp, base_save())
    assert run(mp) == 0
    rows = {r['slug']: r for r in read_json(mp.out)['materials']}
    assert rows['alloy_plate']['pic'] == 'AlloyPlate.png'
    assert rows['morphics']['pic'] is None                 # catalog entry has no pic key
    assert rows['lobotriscid']['pic'] is None              # catalog pic is null


# ------------------------------------------------------------------ cache + CLI

def test_cache_written_then_used_when_alecaframe_absent(mp, capsys):
    seed(mp, base_save())
    assert run(mp) == 0
    cache = read_json(mp.cache)
    assert cache['items']['/Lotus/Types/Items/MiscItems/AlloyPlate'] == {
        'name': 'Alloy Plate', 'pic': 'AlloyPlate.png'}
    assert len(cache['items']) == len(BASE_CATALOG)

    os.remove(str(mp.catalog))                             # simulate AlecaFrame going away
    capsys.readouterr()
    assert run(mp) == 0                                    # resolves from the cache instead
    doc = read_json(mp.out)
    names = {r['slug']: r['name'] for r in doc['materials']}
    assert names['nav_coordinate'] == 'Nav Coordinate' and names['alloy_plate'] == 'Alloy Plate'
    assert mp.mod.load_catalog(str(mp.catalog), str(mp.cache))[1] == 'cache'


def test_dry_run_prints_the_plan_and_writes_nothing(mp, capsys):
    seed(mp, base_save())
    assert run(mp, ['--dry-run']) == 0
    out = capsys.readouterr().out
    assert SUMMARY_RE.match(out.splitlines()[0])
    assert 'dry-run' in out and 'plan :' in out
    assert not mp.out.exists() and not mp.cache.exists()   # nothing written, cache included


def test_summary_line_first_then_store_line(mp, capsys):
    seed(mp, base_save())
    assert run(mp) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == 'materials : total 10 | resources 9 | currency 1 | other 0 | dojo-relevant 5'
    assert STORE_RE.match(lines[1]) and lines[1].startswith('store : ')


def test_out_and_limit_flags(mp, capsys):
    seed(mp, base_save())
    custom = mp.tmp / 'elsewhere' / 'top3.json'
    assert run(mp, ['--out', str(custom), '--limit', '3']) == 0
    doc = read_json(custom)
    assert doc['count'] == 3 and sum(doc['categories'].values()) == 3
    assert [r['slug'] for r in doc['materials']] == ['nano_spores', 'alloy_plate', 'ferrite']
    assert not mp.out.exists()                             # default store untouched
    assert f'store : {mp.mod.rel(str(custom))}' in capsys.readouterr().out


def test_json_flag_prints_the_store(mp, capsys):
    seed(mp, base_save())
    assert run(mp, ['--json']) == 0
    payload = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith('{')]
    assert len(payload) == 1
    assert json.loads(payload[0]) == read_json(mp.out)


def test_selftest_is_offline_and_exits_zero(tmp_path, monkeypatch, capsys):
    mod = load_script('materials', monkeypatch=monkeypatch, env={
        'MATERIALS_SAVE': str(tmp_path / 'nope' / 'lastData.dec.json'),
        'MATERIALS_CATALOG': str(tmp_path / 'nope' / 'basic.json'),
        'MATERIALS_CACHE': str(tmp_path / 'nope' / 'cache.json'),
        'MATERIALS_OUT': str(tmp_path / 'nope' / 'materials.json')})
    assert mod.main(['--selftest']) == 0                   # no save, no catalog, still fine
    out = capsys.readouterr().out
    assert 'selftest : ok' in out and 'no network' in out
    assert os.listdir(str(tmp_path)) == []                 # everything lived in its own tmp dir


def test_selftest_subprocess_without_alecaframe(tmp_path):
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path / 'empty_af'))
    r = subprocess.run([sys.executable, SCRIPT, '--selftest'], cwd=str(tmp_path), env=env,
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'selftest : ok' in r.stdout
