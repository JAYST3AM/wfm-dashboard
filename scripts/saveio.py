"""Single source of truth for reading the AlecaFrame save.

The save (%LOCALAPPDATA%\\AlecaFrame\\lastData.dat) is plaintext JSON (leading '{' - the
fallback the app itself supports) or AES-128-CBC with the fixed key/IV below.  AlecaFrame
moved the inventory - and PlayerLevel / TradesRemaining / RegularCredits / PremiumCredits /
XPInfo - INTO a JSON-encoded 'InventoryJson' string; older saves carry the sections at the
top level.  Every reader must normalise() the document first or it sees an empty inventory
and writes empty stores.

    decrypt(path)           file -> plaintext bytes (AES-CBC, or a plaintext JSON passthrough)
    load_save(path)         file -> (dict, source); source 'plaintext' | 'decrypted' | 'missing'
    normalise(save)         hoist the inner InventoryJson document (idempotent, never raises)
    load_normalised(path)   file -> the normalised document

Read-only: no writes, no network.  stdlib plus 'cryptography' (only for an encrypted save).
"""
import json
import os

KEY = bytes([76, 69, 79, 45, 65, 76, 69, 67, 9, 69, 79, 45, 65, 76, 69, 67])
IV = bytes([49, 50, 70, 71, 66, 51, 54, 45, 76, 69, 51, 45, 113, 61, 57, 0])

# The inventory sections AlecaFrame moved inside 'InventoryJson' (refresh.py's classic set).
SECTIONS = ['MiscItems', 'Recipes', 'RawUpgrades', 'Upgrades', 'WeaponSkins', 'Sentinels',
            'SentinelWeapons', 'SpaceGuns', 'SpaceMelee', 'SpaceSuits', 'MechSuits', 'KubrowPets',
            'Scoops', 'DataKnives', 'OperatorAmps', 'CrewShipWeapons', 'CrewShipWeaponSkins',
            'CrewShipRawSalvage', 'CrewShipAmmo', 'SpecialItems', 'FlavourItems', 'LevelKeys',
            'QuestKeys']


def decrypt(p):
    """A file's bytes: plaintext JSON passes through, anything else gets AES-128-CBC."""
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
    """(save, source) for a save file path.

    source: 'plaintext' when the bytes were JSON, 'decrypted' when they were AES-CBC, and
    'missing' when no file exists at `path` (the document is then {}).  A JSON document
    that is not an object normalises to {}.
    """
    if not path or not os.path.exists(path):
        return {}, 'missing'
    with open(path, 'rb') as fh:
        raw = fh.read()
    try:
        doc, source = json.loads(raw.decode('utf-8')), 'plaintext'
    except (UnicodeDecodeError, ValueError):
        doc, source = json.loads(decrypt(path).decode('utf-8')), 'decrypted'
    return (doc if isinstance(doc, dict) else {}), source


def normalise(save):
    """AlecaFrame's save moved the inventory (and PlayerLevel / TradesRemaining / RegularCredits)
    into a JSON-encoded 'InventoryJson' string; older saves carry the sections at the top level.
    Hoist the inner document so every reader of data/lastData.dec.json sees the classic shape.

    Idempotent; never raises - a malformed inner string (or anything that is not a JSON
    object) leaves the document unchanged.
    """
    if not isinstance(save, dict):
        return save
    ij = save.get('InventoryJson')
    inner = None
    if isinstance(ij, str) and ij.strip().startswith('{'):
        try:
            inner = json.loads(ij)
        except Exception:
            inner = None
    elif isinstance(ij, dict):
        inner = ij
    if not isinstance(inner, dict):
        return save
    if any(isinstance(save.get(s), list) for s in SECTIONS):
        return save                       # already flat - the top level wins
    out = dict(save)
    out.update(inner)                     # inner wins; extra top-level keys survive
    return out


def load_normalised(path):
    """load_save() with normalise() applied - the classic flat document every reader wants."""
    return normalise(load_save(path)[0])
