"""scripts/saveio.py: the one save reader (shape contract + decrypt + load paths).

AlecaFrame moved the inventory - and PlayerLevel / TradesRemaining / RegularCredits /
PremiumCredits / XPInfo - INTO a JSON-encoded 'InventoryJson' string.  normalise() hoists it
so every reader (and data/lastData.dec.json itself) keeps the classic flat shape.  The rules
pinned here are the ones refresh.py used to own:

  * a flat save is returned untouched (the top level wins when the sections are present);
  * a JSON-string or a dict 'InventoryJson' is hoisted; inner keys win on a collision;
  * top-level keys the inner document does not carry survive;
  * no 'InventoryJson' (or a malformed one, or anything that is not a JSON object) leaves
    the document unchanged - normalise() never raises, and it is idempotent;
  * decrypt() passes plaintext JSON through and AES-128-CBC round-trips.

The last test proves the patched store readers (player / materials / collection_log /
mastery) actually see the hoisted document, which is the point of the whole exercise.
"""
import json
import os

import pytest

from conftest import load_script, read_json, write_json

FLAT = {'PlayerLevel': 22, 'TradesRemaining': 22, 'PremiumCredits': 1022,
        'FusionPoints': 5,
        'MiscItems': [{'ItemType': '/Lotus/Types/Items/MiscItems/Ferrite', 'ItemCount': 100}],
        'Upgrades': [{'ItemType': '/Lotus/Upgrades/Galv',
                      'UpgradeFingerprint': '{"lvl": 6}'}],
        'XPInfo': [{'ItemType': '/Lotus/Powersuits/Ninja/Ninja', 'XP': 14116270}]}

INNER = {'PlayerLevel': 22, 'TradesRemaining': 22, 'RegularCredits': 4606665,
         'PremiumCredits': 1022, 'FusionPoints': 9,
         'MiscItems': [{'ItemType': '/Lotus/Types/Items/MiscItems/Ferrite', 'ItemCount': 100}],
         'Upgrades': [{'ItemType': '/Lotus/Upgrades/Galv',
                       'UpgradeFingerprint': '{"lvl": 6}'}],
         'XPInfo': [{'ItemType': '/Lotus/Powersuits/Ninja/Ninja', 'XP': 14116270}]}


@pytest.fixture
def io(monkeypatch):
    """A fresh saveio module per test (repo convention: no leaked monkeypatching)."""
    return load_script('saveio')


# ---------------------------------------------------------------- normalise(): the shape
def test_flat_save_is_left_untouched(io):
    save = dict(FLAT)
    out = io.normalise(save)
    assert out is save                    # refresh.py semantics: flat -> the same document
    assert out == FLAT


def test_hoists_a_json_string_inventory(io):
    save = {'FusionPoints': 5, 'InventoryJson': json.dumps(INNER)}
    out = io.normalise(save)
    assert out['PlayerLevel'] == 22 and out['TradesRemaining'] == 22
    assert out['RegularCredits'] == 4606665 and out['PremiumCredits'] == 1022
    assert out['MiscItems'] == INNER['MiscItems']
    assert out['XPInfo'] == INNER['XPInfo']           # the mastery list hoists too
    assert out['FusionPoints'] == 9                   # inner wins on a collision
    assert out is not save                            # a hoisted copy, original untouched


def test_hoists_a_dict_inventory(io):
    out = io.normalise({'InventoryJson': {'PlayerLevel': 7, 'TradesRemaining': 3,
                                          'MiscItems': [{'ItemType': '/x', 'ItemCount': 1}]}})
    assert out['PlayerLevel'] == 7 and out['TradesRemaining'] == 3
    assert out['MiscItems'] == [{'ItemType': '/x', 'ItemCount': 1}]


def test_no_inventory_json_is_unchanged(io):
    save = {'PlayerLevel': 22, 'MiscItems': []}       # classic flat save
    assert io.normalise(save) is save
    other = {'FusionPoints': 5, 'WeaponSkins': [1]}   # sections but no InventoryJson
    assert io.normalise(other) is other


@pytest.mark.parametrize('junk', ['{not json', '{', 'garbage', 'null', '[1, 2]', '"x"',
                                  '   ', b'{}', 5, None, ['a']])
def test_malformed_inner_string_is_unchanged(io, junk):
    """A malformed/foreign InventoryJson value never raises - the document passes through."""
    save = {'InventoryJson': junk, 'FusionPoints': 1}
    assert io.normalise(save) is save


def test_flat_sections_present_the_top_level_wins(io):
    save = {'PlayerLevel': 22, 'MiscItems': [{'ItemType': '/top'}],
            'InventoryJson': json.dumps({'PlayerLevel': 99,
                                         'MiscItems': [{'ItemType': '/inner'}]})}
    out = io.normalise(save)
    assert out is save
    assert out['PlayerLevel'] == 22 and out['MiscItems'] == [{'ItemType': '/top'}]


def test_extra_top_level_keys_survive(io):
    save = {'FusionPoints': 5, 'MissionCredits': 120, 'TotalCredits': 4606790,
            'InventoryChanges': 'ignored-by-readers', 'InventoryJson': json.dumps(INNER)}
    out = io.normalise(save)
    for key in ('MissionCredits', 'TotalCredits', 'InventoryChanges'):
        assert out[key] == save[key]
    assert out['PlayerLevel'] == 22


def test_normalise_is_idempotent(io):
    save = {'FusionPoints': 5, 'InventoryJson': json.dumps(INNER)}
    once = io.normalise(save)
    twice = io.normalise(once)
    assert twice == once and io.normalise(twice) == once
    assert twice['MiscItems'] == INNER['MiscItems']   # the hoist survives re-runs


@pytest.mark.parametrize('doc', [[], None, 'x', 5, [{'a': 1}]])
def test_non_dict_documents_pass_through(io, doc):
    assert io.normalise(doc) is doc


# ---------------------------------------------------------------- decrypt + load paths
def test_decrypt_plaintext_fallback_and_aes_roundtrip(io, tmp_path):
    plain = tmp_path / 'plain.dat'
    plain.write_bytes(b'{"MiscItems": []}')
    assert io.decrypt(str(plain)) == b'{"MiscItems": []}'   # leading '{': passthrough

    pytest.importorskip('cryptography')
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    payload = json.dumps(FLAT).encode('utf-8')
    pad = padding.PKCS7(128).padder()
    body = pad.update(payload) + pad.finalize()
    enc = Cipher(algorithms.AES(io.KEY), modes.CBC(io.IV)).encryptor()
    dat = tmp_path / 'lastData.dat'
    dat.write_bytes(enc.update(body) + enc.finalize())
    assert io.decrypt(str(dat)) == payload
    # the pinned recipe the whole repo shares
    assert io.KEY == bytes([76, 69, 79, 45, 65, 76, 69, 67, 9, 69, 79, 45, 65, 76, 69, 67])
    assert io.IV == bytes([49, 50, 70, 71, 66, 51, 54, 45, 76, 69, 51, 45, 113, 61, 57, 0])


def test_load_save_reports_its_source(io, tmp_path):
    plain = tmp_path / 'lastData.dec.json'
    write_json(plain, FLAT)
    save, source = io.load_save(str(plain))
    assert source == 'plaintext' and save == FLAT
    assert io.load_save(str(tmp_path / 'nope.json')) == ({}, 'missing')
    assert io.load_save('') == ({}, 'missing')
    not_an_object = tmp_path / 'list.json'
    write_json(not_an_object, [1, 2])
    assert io.load_save(str(not_an_object)) == ({}, 'plaintext')


def test_load_save_decrypts_an_encrypted_save(io, tmp_path):
    pytest.importorskip('cryptography')
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    pad = padding.PKCS7(128).padder()
    body = pad.update(json.dumps(FLAT).encode('utf-8')) + pad.finalize()
    enc = Cipher(algorithms.AES(io.KEY), modes.CBC(io.IV)).encryptor()
    dat = tmp_path / 'lastData.dat'
    dat.write_bytes(enc.update(body) + enc.finalize())
    save, source = io.load_save(str(dat))
    assert source == 'decrypted' and save['PlayerLevel'] == 22


def test_load_normalised_hoists(io, tmp_path):
    p = tmp_path / 'lastData.dec.json'
    write_json(p, {'FusionPoints': 5, 'InventoryJson': json.dumps(INNER)})
    doc = io.load_normalised(str(p))
    assert doc['PlayerLevel'] == 22 and doc['RegularCredits'] == 4606665
    assert doc['FusionPoints'] == 9


# ------------------------------------------- the patched readers actually see it (lock)
def test_store_readers_see_the_hoisted_shape(tmp_path, monkeypatch):
    """player / materials / collection_log / mastery must hoist the new save themselves -
    the fallback paths the bug report is about (no pre-normalised data/lastData.dec.json)."""
    new_shape = {'FusionPoints': 5, 'InventoryJson': json.dumps(
        {'PlayerLevel': 22, 'TradesRemaining': 22, 'RegularCredits': 4606665,
         'PremiumCredits': 1022,
         'XPInfo': [{'ItemType': '/Lotus/Powersuits/Ninja/Ninja', 'XP': 14116270}],
         'MiscItems': [{'ItemType': '/Lotus/Types/Items/MiscItems/Ferrite', 'ItemCount': 100}]})}
    dec = write_json(tmp_path / 'save' / 'lastData.dec.json', new_shape)

    player = load_script('player', monkeypatch=monkeypatch, env={
        'PLAYER_SAVE': dec, 'PLAYER_CATALOG': str(tmp_path / 'nope.json'),
        'PLAYER_ALIAS': str(tmp_path / 'nope.txt'), 'PLAYER_OUT': str(tmp_path / 'player.json')})
    doc, source = player.load_save(dec)
    assert source == 'decrypted' and doc['PlayerLevel'] == 22 and doc['TradesRemaining'] == 22

    materials = load_script('materials', monkeypatch=monkeypatch, env={
        'MATERIALS_SAVE': dec, 'MATERIALS_CATALOG': str(tmp_path / 'nope.json'),
        'MATERIALS_CACHE': str(tmp_path / 'nope.cache'), 'MATERIALS_OUT': str(tmp_path / 'm.json')})
    assert materials.load_save(dec)['MiscItems'][0]['ItemCount'] == 100

    log = load_script('collection_log', monkeypatch=monkeypatch)
    data = tmp_path / 'logdata'
    data.mkdir()
    monkeypatch.setattr(log, 'DATA', str(data))
    monkeypatch.setattr(log, 'AF', str(tmp_path / 'no-alecaframe'))
    write_json(data / 'lastData.dec.json', new_shape)
    read = log.read_save()
    assert read['source'] == 'cached' and read['xp'] == {'/Lotus/Powersuits/Ninja/Ninja'}

    mastery = load_script('mastery', monkeypatch=monkeypatch, env={
        'WFM_DATA_DIR': str(data), 'WFM_STATIC_DIR': str(tmp_path / 'static'),
        'WFM_ALECA_DIR': str(tmp_path / 'no-alecaframe')})
    save, meta = mastery.read_save()
    assert meta['source'] == 'cached' and save['PlayerLevel'] == 22
    assert save['TradesRemaining'] == 22
    # the cached fixture above is shared on purpose: one new-shape document, four readers
    assert read_json(data / 'lastData.dec.json') == new_shape   # nothing mutated on disk
    assert not os.path.exists(str(tmp_path / 'no-alecaframe'))
