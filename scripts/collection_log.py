#!/usr/bin/env python3
"""Collection log - "what has this account collected vs everything obtainable".

Inputs
  %LOCALAPPDATA%/AlecaFrame/lastData.dat   live save (AES-encrypted; XPInfo = mastery list)
  data/lastData.dec.json                   cached decrypted save (used when the live file
                                           is unreadable - same fallback trader/detector.py uses)
  data/owned.json                          current inventory (slug/name/path/count rows)
  data/prices.json                         local WFM price snapshot (wts = lowest sell order)
  data/wfcd_items_cache.json               cached catalog projection (written by this script)
  WFCD warframe-items data/json/*.json     network catalog (see "catalog sources" below)
Output
  data/collection_log.json                 the log the Collection page renders
  static/collection_log.json               copy of the same payload, because server.py serves
                                           only static/ (so /collection_log.json works today
                                           with no server change; --no-static-copy skips it)

Collected
  = the save's XPInfo uniqueNames (mastery) UNION data/owned.json (currently owned, matched by
    uniqueName "path" or by slug).  Every row keeps both flags (owned / mastered); a row counts
    as collected on either.

Obtainable set
  WFCD rows flagged masterable, plus Amp parts (WFCD never flags Amp components masterable),
  plus any row the save proves is mastery-tracked.  Amp / K-Drive / Kitgun component rows are
  routed by type.

Category mapping (WFCD file -> log category)
  Warframes.json       type Warframe, productCategory != MechSuits -> warframes
  Warframes.json       productCategory MechSuits (Voidrig/Bonewidow) -> other  (necramechs)
  Primary.json -> primary        Secondary.json -> secondary      Melee.json -> melee
  Sentinels.json -> sentinels    SentinelWeapons.json -> sentinel_weapons
  Pets.json -> companions        Archwing.json -> archwing
  Arch-Gun.json -> archgun       Arch-Melee.json -> archmelee
  Misc.json  type 'K-Drive Component' -> kdrives
  Misc.json  type 'Amp'               -> amps          (all parts; WFCD flags them non-masterable)
  Misc.json  type 'Kitgun Component'  -> secondary     (kitgun mastery counts as secondary)
  anything else masterable            -> other
  Categories with total 0 are dropped from the output.

Catalog sources, tried in order
  1. data/wfcd_items_cache.json (TTL 7 days; --refresh forces a refetch)
  2. WFCD warframe-items data/json/*.json on raw.githubusercontent.com -- data/json/All.json is
     404 as of this build, so the per-category files are fetched instead (11 files, ~4MB, one
     per category; sleep between requests).  These carry uniqueName + name + imageName +
     masterable, which is everything the log needs.
  3. calamity-inc warframe-public-export-plus exports (ExportWarframes/ExportWeapons/
     ExportSentinels/ExportAnimals.json + dict.en.json for the language-key names).  Names only:
     that export stores /Lotus/Interface icon paths, so icons stay null.
  4. the local AlecaFrame WFCD mirror (%LOCALAPPDATA%/AlecaFrame/cachedData/json/*.json) - the
     same WFCD data on disk, used when the network is unavailable.
  --catalog-source {auto,cache,wfcd,calamity,local} forces one of them; --offline never fetches.

Icons
  WFCD imageName -> https://cdn.warframestat.us/img/<imageName> (verified: HTTP 200 + PNG bytes
  for Ash.png).  Rows without imageName fall back to the local warframe.market catalog
  (data/wfm_items_v2.json gameRef -> market CDN path, the same CDN static/lookup.js uses).
  When neither matches, icon is null and the page draws a placeholder.

Missing tradeables
  slugify(name) -> data/prices.json floor (wts).  Candidate order is the bare slug, then
  "<slug>_set", then "<slug>_blueprint" (built frames/weapons are only quoted as sets or
  blueprints); floor_kind records which candidate matched.

Stdlib only, no AI, no writes outside data/ + static/collection_log.json.  Atomic writes
(tmp file + os.replace), UTC stamps, idempotent when nothing else changed (content_hash).

Usage
  python scripts/collection_log.py                 # live save + cached/network catalog
  python scripts/collection_log.py --refresh       # refetch the catalog first
  python scripts/collection_log.py --offline       # never touch the network
  python scripts/collection_log.py --verify-icons 3
  python scripts/collection_log.py --selftest      # offline fixture checks
"""
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
STATIC = os.path.join(ROOT, 'static')
AF = os.path.expandvars(r'%LOCALAPPDATA%\AlecaFrame')

UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'
IMG_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
          'Chrome/124.0 Safari/537.36')

VERSION = 1
CACHE_SCHEMA = 1
CACHE_TTL = 7 * 86400                     # catalog rows are good for a week
SLEEP = 0.35                              # between catalog fetches
TIMEOUT = 60

WFCD_BASE = 'https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/'
# WFCD file -> source key used by categorize(); order = fetch order
WFCD_FILES = [('Warframes', 'Warframes.json'), ('Primary', 'Primary.json'),
              ('Secondary', 'Secondary.json'), ('Melee', 'Melee.json'),
              ('Sentinels', 'Sentinels.json'), ('SentinelWeapons', 'SentinelWeapons.json'),
              ('Pets', 'Pets.json'), ('Archwing', 'Archwing.json'),
              ('Arch-Gun', 'Arch-Gun.json'), ('Arch-Melee', 'Arch-Melee.json'),
              ('Misc', 'Misc.json')]
CALAMITY_BASE = ('https://raw.githubusercontent.com/calamity-inc/'
                 'warframe-public-export-plus/master/')
CALAMITY_FILES = [('Warframes', 'ExportWarframes.json'), ('Primary', 'ExportWeapons.json'),
                  ('Sentinels', 'ExportSentinels.json'), ('Pets', 'ExportAnimals.json')]

CDN_IMG = 'https://cdn.warframestat.us/img/'          # WFCD imageName -> PNG (verified 200/png)
CDN_MARKET = 'https://warframe.market/static/assets/'  # same base static/lookup.js verifies

# WFCD file -> log category, for the files that map 1:1
FILE_CATEGORY = {'Primary': 'primary', 'Secondary': 'secondary', 'Melee': 'melee',
                 'Sentinels': 'sentinels', 'SentinelWeapons': 'sentinel_weapons',
                 'Pets': 'companions', 'Archwing': 'archwing', 'Arch-Gun': 'archgun',
                 'Arch-Melee': 'archmelee'}
CATEGORIES = [('warframes', 'Warframes'), ('primary', 'Primary'), ('secondary', 'Secondary'),
              ('melee', 'Melee'), ('sentinels', 'Sentinels'),
              ('sentinel_weapons', 'Sentinel Weapons'), ('companions', 'Companions'),
              ('archwing', 'Archwing'), ('archgun', 'Arch-Gun'), ('archmelee', 'Arch-Melee'),
              ('kdrives', 'K-Drives'), ('amps', 'Amps'), ('other', 'Other')]
CAT_NAME = dict(CATEGORIES)
STAMP = '%Y-%m-%dT%H:%M:%SZ'

# AlecaFrame save decryptor (same recipe as scripts/refresh.py; kept here so this script still
# runs when the trader/refresh helper is unavailable - e.g. the public repo, where the crypto
# import is optional).
SAVE_KEY = bytes([76, 69, 79, 45, 65, 76, 69, 67, 9, 69, 79, 45, 65, 76, 69, 67])
SAVE_IV = bytes([49, 50, 70, 71, 66, 51, 54, 45, 76, 69, 51, 45, 113, 61, 57, 0])

# Bad characters for anything we paste into a URL path.
BAD_URL_CHARS = re.compile(r'[\x00-\x1f\x7f"\'<>\\\s]')


# --------------------------------------------------------------------- helpers
def jload(path, default=None):
    """Load JSON; default on any failure (missing/partial/foreign file)."""
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def atomic_write(path, doc):
    """tmp + os.replace, so a reader never sees a half-written file."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def iso(epoch):
    return time.strftime(STAMP, time.gmtime(epoch))


def ascii_s(value):
    return str(value).encode('ascii', 'replace').decode('ascii')


def slugify(name):
    """'Ash Prime' -> 'ash_prime' (matches warframe.market slugs / prices.json keys)."""
    s = str(name or '').strip().lower().replace('&', ' and ')
    return re.sub(r'[^a-z0-9]+', '_', s).strip('_')


def url_join_path(base, rel):
    """Whitelist + percent-encode each segment; None when the path looks hostile."""
    if not isinstance(rel, str) or not rel or '..' in rel or BAD_URL_CHARS.search(rel):
        return None
    return base + '/'.join(urllib.parse.quote(seg, safe='') for seg in rel.split('/'))


def int_or_none(value):
    """int for numbers (bools rejected), else None - WFCD masteryReq is int or absent."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def pct(part, whole):
    return round(100.0 * part / whole, 1) if whole else 0.0


def out_path():
    return os.path.join(DATA, 'collection_log.json')


def static_copy_path():
    return os.path.join(STATIC, 'collection_log.json')


def cache_path():
    return os.path.join(DATA, 'wfcd_items_cache.json')


def owned_path():
    return os.path.join(DATA, 'owned.json')


def prices_path():
    return os.path.join(DATA, 'prices.json')


def wfm_catalog_path():
    return os.path.join(DATA, 'wfm_items_v2.json')


def save_live_path():
    return os.path.join(AF, 'lastData.dat')


def save_cached_path():
    return os.path.join(DATA, 'lastData.dec.json')


def local_wfcd_dir():
    return os.path.join(AF, 'cachedData', 'json')


# --------------------------------------------------------------------- save / mastery
def _decrypt_with_helper(path):
    """Reuse scripts/refresh.py's decrypt() when it is importable (read-only reuse)."""
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    from refresh import decrypt  # noqa: E402  (repo helper: AES-CBC + plaintext passthrough)
    return decrypt(path)


def _decrypt_local(path):
    """Copy of refresh.decrypt's recipe, used when the helper cannot be imported.

    The app itself writes either plaintext JSON (leading '{') or AES-256-CBC with a fixed
    key/IV; the plaintext branch keeps fixtures and future format changes readable.
    """
    raw = open(path, 'rb').read()
    if raw[:1] == b'{':
        return raw
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    dec = Cipher(algorithms.AES(SAVE_KEY), modes.CBC(SAVE_IV)).decryptor()
    pt = dec.update(raw) + dec.finalize()
    pad = pt[-1] if pt else 0
    if 1 <= pad <= 16 and pt[-pad:] == bytes([pad]) * pad:
        pt = pt[:-pad]
    return pt


def decrypt_save(path):
    """lastData.dat -> decrypted bytes (helper first, local copy as fallback)."""
    try:
        return _decrypt_with_helper(path)
    except Exception:
        return _decrypt_local(path)


def read_save():
    """Mastery list from the live save, else the cached decrypted snapshot.

    Returns {'xp': set(uniqueNames), 'xp_count': int, 'source': 'live'|'cached'|None,
             'path': str|None, 'mtime_iso': str|None, 'error': str|None}
    """
    live = save_live_path()
    if os.path.exists(live):
        try:
            save = json.loads(decrypt_save(live).decode('utf-8', 'replace'))
            xp = xpinfo_names(save)
            if xp:
                return {'xp': xp, 'xp_count': len(xp), 'source': 'live', 'path': live,
                        'mtime_iso': iso(os.path.getmtime(live)), 'error': None}
            err = 'live save has no XPInfo'
        except Exception as exc:                      # noqa: BLE001 - any read/decrypt failure
            err = '%s: %s' % (type(exc).__name__, exc)
    else:
        err = 'no live save at %s' % live
    cached = save_cached_path()
    if os.path.exists(cached):
        save = jload(cached) or {}
        xp = xpinfo_names(save)
        return {'xp': xp, 'xp_count': len(xp), 'source': 'cached', 'path': cached,
                'mtime_iso': iso(os.path.getmtime(cached)), 'error': err}
    return {'xp': set(), 'xp_count': 0, 'source': None, 'path': None, 'mtime_iso': None,
            'error': '%s; no cached save either (%s)' % (err, cached)}


def xpinfo_names(save):
    """uniqueNames from the save's XPInfo array (entries: {ItemType, XP})."""
    out = set()
    for row in (save.get('XPInfo') or []):
        if isinstance(row, dict) and row.get('ItemType'):
            out.add(str(row['ItemType']))
    return out


# --------------------------------------------------------------------- catalog
def normalize_wfcd(rows_by_file):
    """WFCD rows -> flat entries: name/unique_name/type/product_category/masterable/..."""
    entries = []
    for src in sorted(rows_by_file):                    # sorted -> stable, source-agnostic
        rows = rows_by_file.get(src) or []
        if isinstance(rows, dict):                      # keyed export -> values
            rows = list(rows.values())
        for row in rows:
            if not isinstance(row, dict):
                continue
            uniq = row.get('uniqueName') or row.get('unique_name')
            name = row.get('name')
            if not uniq or not name:
                continue
            entries.append({
                'name': str(name),
                'unique_name': str(uniq),
                'type': row.get('type'),
                'product_category': row.get('productCategory'),
                'masterable': row.get('masterable') is True,
                'mastery_req': int_or_none(row.get('masteryReq')),
                'image_name': row.get('imageName'),
                'src': src,
            })
    return entries


def categorize(entry):
    """WFCD entry -> log category key (see the module docstring for the table)."""
    src = entry.get('src')
    typ = entry.get('type')
    pcat = entry.get('product_category')
    if src in FILE_CATEGORY:
        return FILE_CATEGORY[src]
    if src == 'Warframes':
        if pcat == 'MechSuits':                         # Necramechs (Voidrig/Bonewidow)
            return 'other'
        return 'warframes' if typ == 'Warframe' else 'other'
    if src == 'Misc':
        if typ == 'Amp':
            return 'amps'                               # WFCD never flags Amp parts masterable
        if typ == 'K-Drive Component':
            return 'kdrives'
        if typ == 'Kitgun Component':
            return 'secondary'                          # kitgun mastery counts as secondary
    return 'other'


def is_obtainable(entry, xp_names):
    """Masterable rows + Amp parts + anything the save proves mastery-tracked."""
    return bool(entry.get('masterable') or entry.get('type') == 'Amp'
                or entry.get('unique_name') in xp_names)


def build_icon_map():
    """uniqueName -> market CDN path, from the local warframe.market catalog (may be empty)."""
    doc = jload(wfm_catalog_path(), {})
    rows = doc.get('data') if isinstance(doc, dict) else doc
    out = {}
    for row in (rows or []):
        if not isinstance(row, dict) or not row.get('gameRef'):
            continue
        icon = ((row.get('i18n') or {}).get('en') or {}).get('icon')
        if icon:
            out.setdefault(str(row['gameRef']), icon)
    return out


def icon_for(entry, icon_map):
    """WFCD imageName first (cdn.warframestat.us), then the market CDN path, else None."""
    if entry.get('image_name'):
        return url_join_path(CDN_IMG, str(entry['image_name']))
    rel = icon_map.get(entry.get('unique_name'))
    return url_join_path(CDN_MARKET, rel) if rel else None


def fetch_json(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8', 'replace'))


def _fetch_set(files, base, sleep_fn, notes):
    """Fetch one group of catalog files; returns (rows_by_file, urls, errors)."""
    rows, urls, errors = {}, [], []
    for src, filename in files:
        url = base + filename
        urls.append(url)
        try:
            rows[src] = fetch_json(url)
        except Exception as exc:                        # noqa: BLE001 - network/parse anything
            errors.append('%s: %s' % (filename, type(exc).__name__))
        if sleep_fn:
            sleep_fn(SLEEP)
    for err in errors:
        notes.append('catalog fetch failed (%s)' % err)
    return rows, urls, errors


def load_catalog_wfcd(sleep_fn=time.sleep, notes=None):
    """WFCD per-category JSON (All.json is 404). Returns (entries, meta)."""
    notes = notes if notes is not None else []
    rows, urls, errors = _fetch_set(WFCD_FILES, WFCD_BASE, sleep_fn, notes)
    entries = normalize_wfcd(rows)
    ok_files = sorted(rows)
    if not entries:
        raise RuntimeError('WFCD fetch returned no rows (%s)' % (', '.join(errors) or 'no files'))
    notes.append('catalog source wfcd-json: %d of %d files (All.json 404 -> per-category files)'
                 % (len(ok_files), len(WFCD_FILES)))
    return entries, {'source': 'wfcd-json', 'source_url': WFCD_BASE, 'files': ok_files,
                     'urls': urls, 'partial': bool(errors)}


def load_catalog_calamity(sleep_fn=time.sleep, notes=None):
    """calamity-inc export-plus fallback: language-key names, no icons. (entries, meta)."""
    notes = notes if notes is not None else []
    rows, urls, errors = _fetch_set(CALAMITY_FILES, CALAMITY_BASE, sleep_fn, notes)
    try:
        lang = fetch_json(CALAMITY_BASE + 'dict.en.json')
        urls.append(CALAMITY_BASE + 'dict.en.json')
    except Exception as exc:                            # noqa: BLE001
        lang = {}
        notes.append('calamity dict.en.json fetch failed (%s) - raw language keys kept'
                     % type(exc).__name__)
    merged = []
    for src, payload in rows.items():
        if not isinstance(payload, dict):
            continue
        for uniq, row in payload.items():
            if not isinstance(row, dict):
                continue
            row = dict(row)
            row.setdefault('uniqueName', uniq)
            name = str(row.get('name') or '')
            if name.startswith('/Lotus/Language/'):
                entry = lang.get(name) or {}
                row['name'] = (entry.get('name') if isinstance(entry, dict) else None) or name
            # the export has no masterable flag: every exported warframe/weapon/sentinel/pet
            # row is treated as obtainable, and the save's XPInfo still proves mastery.
            row['masterable'] = True
            row['_src'] = src
            merged.append((src, row))
    entries = []
    for src, row in merged:
        entries.append({'name': str(row.get('name')), 'unique_name': str(row['uniqueName']),
                        'type': row.get('type') or row.get('variantType'),
                        'product_category': row.get('productCategory'),
                        'masterable': True,
                        'mastery_req': row.get('masteryReq') if isinstance(row.get('masteryReq'), int) else None,
                        'image_name': None, 'src': src})   # /Lotus/Interface icons are not URLs
    if not entries:
        raise RuntimeError('calamity export returned no rows (%s)' % (', '.join(errors) or 'no files'))
    notes.append('catalog source calamity-export: %d rows from %d files (names only, no icons)'
                 % (len(entries), len(rows)))
    return entries, {'source': 'calamity-export', 'source_url': CALAMITY_BASE,
                     'files': sorted(rows), 'urls': urls, 'partial': bool(errors)}


def load_catalog_local(notes=None):
    """Offline fallback: the AlecaFrame WFCD mirror on this PC. (entries, meta)."""
    notes = notes if notes is not None else []
    base = local_wfcd_dir()
    rows = {}
    for src, filename in WFCD_FILES:
        payload = jload(os.path.join(base, filename))
        if payload:
            rows[src] = payload
    entries = normalize_wfcd(rows)
    if not entries:
        raise RuntimeError('no WFCD mirror under %s' % base)
    notes.append('catalog source local-aleaframe: %d files from the AlecaFrame cache (offline)'
                 % len(rows))
    return entries, {'source': 'local-aleaframe', 'source_url': 'file://' + base.replace('\\', '/'),
                     'files': sorted(rows), 'urls': [], 'partial': False}


def load_cached_catalog():
    doc = jload(cache_path())
    if not isinstance(doc, dict) or doc.get('schema') != CACHE_SCHEMA:
        return None
    entries = doc.get('items')
    if not isinstance(entries, list) or not entries:
        return None
    meta = {'source': doc.get('source'), 'source_url': doc.get('source_url'),
            'files': doc.get('files') or [], 'urls': doc.get('urls') or [],
            'partial': bool(doc.get('partial'))}
    return entries, meta, doc.get('fetched') or 0


def save_catalog_cache(entries, meta, fetched):
    doc = dict(schema=CACHE_SCHEMA, source=meta.get('source'), source_url=meta.get('source_url'),
               files=meta.get('files') or [], urls=meta.get('urls') or [],
               partial=bool(meta.get('partial')), fetched=int(fetched), fetched_iso=iso(fetched),
               count=len(entries), items=entries)
    atomic_write(cache_path(), doc)


def get_catalog(force_source='auto', refresh=False, offline=False, sleep_fn=time.sleep):
    """(entries, meta) from cache -> network (wfcd, then calamity) -> local mirror."""
    notes = []
    cached = None if refresh else load_cached_catalog()
    if cached and force_source in ('auto', 'cache'):
        entries, meta, fetched = cached
        age = max(0, int(time.time() - fetched))
        if age <= CACHE_TTL or offline or force_source == 'cache':
            meta = dict(meta, cached=True, fetched=fetched)
            notes.append('catalog from cache (fetched %s, %dh old)'
                         % (iso(fetched), age // 3600))
            return entries, meta, notes

    attempts = []
    if force_source == 'cache':
        attempts = []
    elif offline:
        attempts = [('local', load_catalog_local)]
    elif force_source == 'wfcd':
        attempts = [('wfcd', load_catalog_wfcd)]
    elif force_source == 'calamity':
        attempts = [('calamity', load_catalog_calamity)]
    elif force_source == 'local':
        attempts = [('local', load_catalog_local)]
    else:
        attempts = [('wfcd', load_catalog_wfcd), ('calamity', load_catalog_calamity),
                    ('local', load_catalog_local)]

    for label, loader in attempts:
        try:
            if label == 'local':
                entries, meta = loader(notes)
            else:
                entries, meta = loader(sleep_fn, notes)
        except Exception as exc:                        # noqa: BLE001 - try the next source
            notes.append('catalog source %s unavailable (%s: %s)'
                         % (label, type(exc).__name__, exc))
            continue
        fetched = int(time.time())
        if label in ('wfcd', 'calamity'):
            save_catalog_cache(entries, meta, fetched)
        meta = dict(meta, cached=False, fetched=fetched)
        return entries, meta, notes

    if cached:                                          # stale cache beats nothing
        entries, meta, fetched = cached
        notes.append('all catalog sources failed - reusing stale cache from %s' % iso(fetched))
        return entries, dict(meta, cached=True, fetched=fetched), notes
    return [], {'source': None, 'source_url': None, 'files': [], 'urls': [], 'partial': True,
                'cached': False, 'fetched': 0}, notes


# --------------------------------------------------------------------- prices / inventory
def load_price_floor_map():
    doc = jload(prices_path(), {})
    return doc if isinstance(doc, dict) else {}


def price_floor(name, prices):
    """(floor, kind) for a slugified name: bare slug, then _set, then _blueprint."""
    slug = slugify(name)
    if not slug:
        return None, None
    for suffix in ('', '_set', '_blueprint'):
        row = prices.get(slug + suffix)
        if isinstance(row, dict):
            try:
                floor = int(row.get('wts'))
            except (TypeError, ValueError):
                floor = None
            if floor and floor > 0:
                return floor, (suffix.lstrip('_') or 'item')
    return None, None


def owned_index():
    """data/owned.json -> (paths, slugs, count)."""
    rows = jload(owned_path(), [])
    if isinstance(rows, dict):
        rows = list(rows.values())
    paths, slugs = set(), set()
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        if row.get('path'):
            paths.add(str(row['path']))
        if row.get('slug'):
            slugs.add(str(row['slug']))
    return paths, slugs, len(rows or [])


# --------------------------------------------------------------------- log build
def build_log(entries, xp_names, owned_paths, owned_slugs, prices, icon_map, catalog_meta,
              save_meta, notes, now=None):
    """The data/collection_log.json payload."""
    now = int(now if now is not None else time.time())
    buckets = {key: [] for key, _ in CATEGORIES}
    seen = set()
    for entry in entries:
        uniq = entry.get('unique_name')
        if not uniq or uniq in seen:                    # one slot per uniqueName
            continue
        if not is_obtainable(entry, xp_names):
            continue
        key = categorize(entry)
        if key not in buckets:
            key = 'other'
        seen.add(uniq)
        slug = slugify(entry.get('name'))
        mastered = uniq in xp_names
        owned = uniq in owned_paths or (bool(slug) and slug in owned_slugs)
        floor, floor_kind = (None, None)
        if not (mastered or owned):
            floor, floor_kind = price_floor(entry.get('name'), prices)
        buckets[key].append({
            'name': entry.get('name'),
            'slug': slug,
            'unique_name': uniq,
            'icon': icon_for(entry, icon_map),
            'owned': owned,
            'mastered': mastered,
            'floor': floor,
            'floor_kind': floor_kind,
            'mastery_req': entry.get('mastery_req'),
        })

    categories, obtained, total = [], 0, 0
    for key, label in CATEGORIES:
        items = buckets[key]
        if not items:
            continue                                    # only categories with total > 0
        items.sort(key=lambda r: (r['name'] or '').lower())
        got = sum(1 for r in items if r['owned'] or r['mastered'])
        obtained += got
        total += len(items)
        categories.append({'key': key, 'name': label, 'obtained': got, 'total': len(items),
                           'pct': pct(got, len(items)), 'items': items})

    tradeable_missing = sum(1 for cat in categories for r in cat['items']
                            if not (r['owned'] or r['mastered']) and r['floor'])
    mastered_only = sum(1 for cat in categories for r in cat['items']
                        if r['mastered'] and not r['owned'])
    owned_only = sum(1 for cat in categories for r in cat['items']
                     if r['owned'] and not r['mastered'])

    doc = {
        'version': VERSION,
        'generated': now,
        'generated_iso': iso(now),
        'overall': {'obtained': obtained, 'total': total, 'pct': pct(obtained, total),
                    'mastered_only': mastered_only, 'owned_only': owned_only,
                    'missing': total - obtained, 'missing_with_price': tradeable_missing},
        'categories': categories,
        'sources': {
            'catalog_source': catalog_meta.get('source'),
            'catalog_url': catalog_meta.get('source_url'),
            'catalog_count': total,
            'catalog_rows_fetched': len(entries),
            'catalog_fetched_iso': iso(catalog_meta['fetched']) if catalog_meta.get('fetched') else None,
            'catalog_from_cache': bool(catalog_meta.get('cached')),
            'catalog_partial': bool(catalog_meta.get('partial')),
            'catalog_files': catalog_meta.get('files') or [],
            'save_xpinfo_count': save_meta.get('xp_count') or 0,
            'save_source': save_meta.get('source'),
            'save_path': save_meta.get('path'),
            'save_mtime_iso': save_meta.get('mtime_iso'),
            'owned_rows': save_meta.get('owned_rows'),
            'prices_quotes': len(prices),
        },
        'notes': list(notes),
        'content_hash': None,
    }
    if save_meta.get('error'):
        doc['notes'].append('save note: %s' % save_meta['error'])
    return doc


def payload_hash(doc):
    body = {k: v for k, v in doc.items() if k not in ('generated', 'generated_iso', 'content_hash')}
    blob = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(blob.encode('ascii')).hexdigest()[:16]


def previous_stamp(doc, digest):
    """Reuse the previous generated/generated_iso when the payload is unchanged."""
    try:
        with open(out_path(), encoding='utf-8') as fh:
            old = json.load(fh)
    except (OSError, ValueError):
        return None
    if (isinstance(old, dict) and old.get('content_hash') == digest
            and old.get('generated') and old.get('generated_iso')):
        return int(old['generated']), str(old['generated_iso'])
    return None


def verify_icons(items, count):
    """HEAD/GET up to <count> icons with a browser-like UA; returns (ok, checked, first)."""
    checked, ok, first = 0, 0, None
    for row in items:
        if checked >= count:
            break
        url = row.get('icon')
        if not url:
            continue
        checked += 1
        try:
            req = urllib.request.Request(url, headers={'User-Agent': IMG_UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                blob = resp.read(512)
                good = resp.status == 200 and (blob[:4] in (b'\x89PNG', b'GIF8')
                                               or blob[:3] == b'\xff\xd8\xff' or b'<svg' in blob[:64])
            printed = ascii_s(url)
        except Exception as exc:                        # noqa: BLE001
            good = False
            printed = '%s (%s)' % (ascii_s(url), type(exc).__name__)
        ok += 1 if good else 0
        if first is None:
            first = (row.get('name'), url, good)
        print('  icon %-6s %s' % ('ok' if good else 'FAIL', printed))
        time.sleep(SLEEP)
    return ok, checked, first


# --------------------------------------------------------------------- selftest
FIXTURE_WFCD = {
    'Warframes': [
        {'uniqueName': '/Lotus/Powersuits/Ninja/Ninja', 'name': 'Ash', 'type': 'Warframe',
         'productCategory': 'Suits', 'masterable': True, 'masteryReq': 0, 'imageName': 'Ash.png'},
        {'uniqueName': '/Lotus/Powersuits/Odalisk/Odalisk', 'name': 'Nezha', 'type': 'Warframe',
         'productCategory': 'Suits', 'masterable': True, 'masteryReq': 0, 'imageName': 'Nezha.png'},
        {'uniqueName': '/Lotus/Powersuits/EntratiMech/NechroTech', 'name': 'Voidrig',
         'type': 'Warframe', 'productCategory': 'MechSuits', 'masterable': True,
         'masteryReq': 0, 'imageName': 'Voidrig.png'},
        {'uniqueName': '/Lotus/Powersuits/MonkeyKing/Helminth', 'name': 'Helminth',
         'type': 'Warframe', 'productCategory': 'Suits', 'masterable': False, 'imageName': None},
    ],
    'Primary': [
        {'uniqueName': '/Lotus/Weapons/Tenno/Rifle/Braton', 'name': 'Braton', 'type': 'Rifle',
         'productCategory': 'LongGuns', 'masterable': True, 'masteryReq': 0,
         'imageName': 'Braton.png'},
        {'uniqueName': '/Lotus/Weapons/Tenno/Rifle/BratonPrime', 'name': 'Braton Prime',
         'type': 'Rifle', 'productCategory': 'LongGuns', 'masterable': True, 'masteryReq': 8,
         'imageName': 'BratonPrime.png'},
    ],
    'Misc': [
        {'uniqueName': '/Lotus/Weapons/Operator/Amps/MotePrism', 'name': 'Mote Prism',
         'type': 'Amp', 'productCategory': 'Pistols', 'masterable': False, 'masteryReq': 0,
         'imageName': 'MotePrism.png'},
        {'uniqueName': '/Lotus/Types/Kaiju/Boards/KDrives/KDriveBadBaby', 'name': 'Bad Baby',
         'type': 'K-Drive Component', 'productCategory': 'Pistols', 'masterable': True,
         'masteryReq': 0, 'imageName': 'BadBaby.png'},
    ],
}
FIXTURE_XP = ['/Lotus/Powersuits/Ninja/Ninja', '/Lotus/Weapons/Tenno/Rifle/Braton',
              '/Lotus/Weapons/Operator/Amps/MotePrism']
FIXTURE_OWNED = [{'slug': 'braton_prime', 'name': 'Braton Prime',
                  'path': '/Lotus/Weapons/Tenno/Rifle/BratonPrime', 'count': 1}]
FIXTURE_PRICES = {'braton_prime_set': {'wts': 12}, 'ash_set': {'wts': 40},
                  'nezha_blueprint': {'wts': 7}}


def selftest():
    """Offline fixture checks: mapping, collected union, floors, missing files."""
    checks = []

    def check(label, cond):
        checks.append((label, bool(cond)))
        print('  %-52s %s' % (label, 'ok' if cond else 'FAIL'))

    tmp = tempfile.mkdtemp(prefix='collection_log_selftest_')
    entries = normalize_wfcd(FIXTURE_WFCD)
    check('normalize_wfcd keeps 8 uniqueNames', len({e['unique_name'] for e in entries}) == 8)

    got = [categorize(e) for e in entries]
    by_name = {e['name']: categorize(e) for e in entries}
    check('Ash -> warframes', by_name['Ash'] == 'warframes')
    check('Nezha -> warframes', by_name['Nezha'] == 'warframes')
    check('Voidrig -> other (necramech)', by_name['Voidrig'] == 'other')
    check('Braton -> primary', by_name['Braton'] == 'primary')
    check('Mote Prism -> amps', by_name['Mote Prism'] == 'amps')
    check('Bad Baby -> kdrives', by_name['Bad Baby'] == 'kdrives')
    check('every row categorised', all(c in CAT_NAME for c in got))

    xp = set(FIXTURE_XP)
    check('Amp part is obtainable without the flag',
          is_obtainable(next(e for e in entries if e['name'] == 'Mote Prism'), xp))
    check('non-masterable Helminth excluded',
          not is_obtainable(next(e for e in entries if e['name'] == 'Helminth'), xp))
    check('masterable Braton Prime included',
          is_obtainable(next(e for e in entries if e['name'] == 'Braton Prime'), xp))

    check('slugs: Braton Prime -> braton_prime', slugify('Braton Prime') == 'braton_prime')
    check('slugs: MK1-Bo -> mk1_bo', slugify('MK1-Bo') == 'mk1_bo')
    check('slugs: Ack & Brunt -> ack_and_brunt', slugify('Ack & Brunt') == 'ack_and_brunt')

    check('floor: no quote -> (None, None)', price_floor('Braton Prime', {}) == (None, None))
    check('floor: exact slug', price_floor('Braton Prime',
                                           {'braton_prime': {'wts': 5}}) == (5, 'item'))
    check('floor: exact slug beats _set', price_floor('Braton Prime',
                                                      {'braton_prime': {'wts': 5},
                                                       'braton_prime_set': {'wts': 12}})
          == (5, 'item'))
    check('floor: _set candidate', price_floor('Ash', FIXTURE_PRICES) == (40, 'set'))
    check('floor: _blueprint candidate', price_floor('Braton Prime',
                                                     {'braton_prime_blueprint': {'wts': 3}})
          == (3, 'blueprint'))
    check('floor: zero / blank wts ignored',
          price_floor('Ash', {'ash': {'wts': 0}, 'ash_set': {'wts': None}, 'ash_blueprint': {}})
          == (None, None))

    icon_map = {'/Lotus/Weapons/Tenno/Rifle/BratonPrime': 'items/images/en/braton_prime.png'}
    primary = next(e for e in entries if e['name'] == 'Braton')
    nobody = next(e for e in entries if e['name'] == 'Braton Prime')
    check('icon from imageName',
          icon_for(primary, icon_map) == CDN_IMG + 'Braton.png')
    fallback = dict(nobody, image_name=None)
    check('icon falls back to the market CDN',
          icon_for(fallback, icon_map) == CDN_MARKET + 'items/images/en/braton_prime.png')
    check('hostile image path refused',
          icon_for(dict(primary, image_name='../../etc/passwd'), icon_map) is None)

    # --- a full build_log over the fixtures -------------------------------------------
    owned_paths = {r['path'] for r in FIXTURE_OWNED}
    owned_slugs = {r['slug'] for r in FIXTURE_OWNED}
    doc = build_log(entries, xp, owned_paths, owned_slugs, dict(FIXTURE_PRICES), icon_map,
                    {'source': 'fixture', 'source_url': 'fixture://wfcd', 'files': ['fixture'],
                     'partial': False, 'cached': False, 'fetched': 1700000000},
                    {'xp_count': len(xp), 'source': 'fixture', 'path': 'fixture',
                     'mtime_iso': None, 'error': None, 'owned_rows': 1}, ['fixture'],
                    now=1700000000)
    cats = {c['key']: c for c in doc['categories']}
    check('categories: no empty ones', all(c['total'] > 0 for c in doc['categories']))
    check('categories: 5 keys present',
          sorted(cats) == ['amps', 'kdrives', 'other', 'primary', 'warframes'])
    check('categories: warframes 2 (Helminth out, Voidrig -> other)',
          cats['warframes']['total'] == 2 and cats['other']['total'] == 1)
    check('categories: amps/kdrives kept', cats['amps']['total'] == 1
          and cats['kdrives']['total'] == 1)
    check('overall total 7 obtainable', doc['overall']['total'] == 7)
    check('overall obtained 4 (3 mastered + 1 owned)', doc['overall']['obtained'] == 4)
    check('overall pct', doc['overall']['pct'] == round(100 * 4 / 7, 1))
    check('overall counters', (doc['overall']['mastered_only'], doc['overall']['owned_only'],
                               doc['overall']['missing'], doc['overall']['missing_with_price'])
          == (3, 1, 3, 1))
    ash = next(r for r in cats['warframes']['items'] if r['name'] == 'Ash')
    nezha = next(r for r in cats['warframes']['items'] if r['name'] == 'Nezha')
    braton_prime = next(r for r in cats['primary']['items'] if r['name'] == 'Braton Prime')
    mote = next(r for r in cats['amps']['items'] if r['name'] == 'Mote Prism')
    check('Ash mastered, not owned', ash['mastered'] and not ash['owned'])
    check('collected rows carry no floor', (ash['floor'], ash['floor_kind']) == (None, None))
    check('missing Nezha -> floor via _blueprint', (nezha['floor'], nezha['floor_kind'])
          == (7, 'blueprint'))
    check('Braton Prime owned (path match) not mastered',
          braton_prime['owned'] and not braton_prime['mastered'])
    check('Braton mastered', next(r for r in cats['primary']['items']
                                 if r['name'] == 'Braton')['mastered'])
    check('Amp part mastered counts as collected (XP proves it)', mote['mastered'])
    check('rows carry icon/slug/unique_name/mastery_req',
          all(r.get('icon') and r.get('unique_name') and 'mastery_req' in r
              for c in doc['categories'] for r in c['items']))
    check('per-category pct matches counts',
          all(c['pct'] == pct(c['obtained'], c['total']) for c in doc['categories']))
    check('items sorted by name',
          all([r['name'].lower() for r in c['items']] ==
              sorted(r['name'].lower() for r in c['items']) for c in doc['categories']))
    check('top-level keys are the documented contract',
          set(doc) == {'version', 'generated', 'generated_iso', 'overall', 'categories',
                       'sources', 'notes', 'content_hash'})
    check('sources contract', set(doc['sources']) >= {'catalog_url', 'catalog_count',
                                                      'save_xpinfo_count'})
    digest = payload_hash(doc)
    doc['generated'], doc['generated_iso'] = 1700000000, iso(1700000000)
    check('payload hash is stable for identical input',
          digest == payload_hash(json.loads(json.dumps(doc))))

    # --- file behaviour: atomic write, cache round-trip, missing files ----------------
    out = os.path.join(tmp, 'collection_log.json')
    doc['content_hash'] = digest
    atomic_write(out, doc)
    check('atomic_write leaves no .tmp', os.path.exists(out) and not os.path.exists(out + '.tmp'))
    check('payload round-trips', jload(out)['overall']['total'] == doc['overall']['total'])

    saved = (DATA, AF)
    try:
        globals()['DATA'] = tmp
        globals()['AF'] = os.path.join(tmp, 'no-alecaframe')
        save_catalog_cache(entries, {'source': 'fixture', 'source_url': 'fixture://wfcd',
                                     'files': ['fixture'], 'urls': [], 'partial': False},
                           1700000000)
        cached = load_cached_catalog()
        check('catalog cache round-trips',
              bool(cached) and cached[0] == entries and cached[2] == 1700000000)
        fresh, meta_fresh, _ = get_catalog(force_source='cache')
        check('get_catalog(cache) reuses the cache',
              meta_fresh.get('cached') and len(fresh) == len(entries))
        stale, meta_stale, notes_stale = get_catalog(offline=True)
        check('offline reuses the cached catalog with a note',
              len(stale) == len(entries) and meta_stale.get('cached')
              and any('catalog from cache' in n for n in notes_stale))
        save_missing = read_save()
        check('missing save -> no mastery, error noted',
              save_missing['xp_count'] == 0 and save_missing['source'] is None
              and 'no live save' in (save_missing['error'] or ''))
        plain = os.path.join(tmp, 'lastData.dec.json')          # plaintext branch of decrypt
        with open(plain, 'w', encoding='utf-8') as fh:
            json.dump({'XPInfo': [{'ItemType': '/Lotus/X', 'XP': 5}]}, fh)
        save_cached = read_save()
        check('cached save read via the plaintext decrypt branch',
              save_cached['xp_count'] == 1 and save_cached['source'] == 'cached')
        check('xpinfo_names ignores junk rows',
              xpinfo_names({'XPInfo': [{'ItemType': '/Lotus/Y'}, None, {'XP': 1}, 'x']})
              == {'/Lotus/Y'})
        globals()['DATA'] = os.path.join(tmp, 'empty')
        entries_empty, meta_empty, notes_empty = get_catalog(offline=True)
        check('offline + no mirror -> empty catalog, notes explain',
              entries_empty == [] and meta_empty['source'] is None and notes_empty)
        check('owned_index tolerates a missing file', owned_index() == (set(), set(), 0))
    finally:
        globals()['DATA'], globals()['AF'] = saved

    failed = [label for label, ok in checks if not ok]
    print('selftest: %d checks, %d failed' % (len(checks), len(failed)))
    for label in failed:
        print('  FAILED: %s' % label)
    return 1 if failed else 0


# --------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description='Build the Warframe collection log')
    ap.add_argument('--refresh', action='store_true', help='refetch the catalog (ignore TTL)')
    ap.add_argument('--offline', action='store_true', help='never touch the network')
    ap.add_argument('--catalog-source', choices=('auto', 'cache', 'wfcd', 'calamity', 'local'),
                    default='auto', help='force one catalog source (default auto)')
    ap.add_argument('--no-static-copy', action='store_true',
                    help='do not write static/collection_log.json')
    ap.add_argument('--verify-icons', type=int, default=0, metavar='N',
                    help='fetch the first N catalog icons to prove the CDN serves images')
    ap.add_argument('--selftest', action='store_true', help='offline fixture checks')
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    save_meta = read_save()
    if save_meta.get('error'):
        print('save: %s' % ascii_s(save_meta['error']))
    print('mastery list: %d uniqueNames (%s %s)'
          % (save_meta['xp_count'], save_meta['source'] or 'none',
             save_meta['mtime_iso'] or ''))

    entries, catalog_meta, notes = get_catalog(force_source=args.catalog_source,
                                              refresh=args.refresh, offline=args.offline)
    if not entries:
        print('ERROR no catalog available - run without --offline, or check '
              'data/wfcd_items_cache.json')
        return 1
    print('catalog: %s (%s) rows=%d%s'
          % (catalog_meta.get('source'), catalog_meta.get('source_url') or '-', len(entries),
             ' [cache]' if catalog_meta.get('cached') else ''))

    prices = load_price_floor_map()
    owned_paths, owned_slugs, owned_n = owned_index()
    icon_map = build_icon_map()
    if not icon_map:
        notes.append('no local warframe.market catalog (data/wfm_items_v2.json): icons come from '
                     'WFCD imageName only')
    notes.insert(0, 'Collected = save XPInfo mastery UNION data/owned.json inventory; each row '
                    'keeps owned/mastered flags and counts as collected on either.')
    notes.insert(1, 'Obtainable = WFCD masterable rows + Amp parts (WFCD never flags them '
                    'masterable) + anything the save proves mastery-tracked; empty categories '
                    'are dropped.')
    notes.append('Category mapping: Warframes(+MechSuits->other) / Primary / Secondary / Melee / '
                 'Sentinels / SentinelWeapons / Pets(companions) / Archwing / Arch-Gun / '
                 'Arch-Melee, Misc: Amp->amps, K-Drive Component->kdrives, Kitgun Component->'
                 'secondary.')
    notes.append('Floor price = data/prices.json wts; candidates slug, slug_set, slug_blueprint '
                 '(floor_kind says which one matched).')
    notes.append('Icons: WFCD imageName -> cdn.warframestat.us/img (verified 200 + PNG bytes), '
                 'else the warframe.market CDN path from data/wfm_items_v2.json, else null.')
    save_meta = dict(save_meta, owned_rows=owned_n)
    doc = build_log(entries, save_meta['xp'], owned_paths, owned_slugs, prices, icon_map,
                    catalog_meta, save_meta, notes)
    digest = payload_hash(doc)
    doc['content_hash'] = digest
    prev = previous_stamp(doc, digest)
    if prev:
        doc['generated'], doc['generated_iso'] = prev
    atomic_write(out_path(), doc)

    static_note = 'static copy skipped (--no-static-copy)'
    if not args.no_static_copy:
        try:
            atomic_write(static_copy_path(), doc)
            static_note = 'static/collection_log.json written (server.py serves static/ only)'
        except OSError as exc:
            static_note = 'static copy failed: %s' % exc
    print('collection log -> %s' % ascii_s(out_path().replace('\\', '/')))
    print('  %s  hash %s' % (doc['generated_iso'], digest))
    print('  overall %d/%d (%.1f%%) | mastered-only %d | owned-only %d | missing with price %d'
          % (doc['overall']['obtained'], doc['overall']['total'], doc['overall']['pct'],
             doc['overall']['mastered_only'], doc['overall']['owned_only'],
             doc['overall']['missing_with_price']))
    for cat in doc['categories']:
        print('  %-16s %4d/%-4d %5.1f%%' % (cat['name'], cat['obtained'], cat['total'],
                                            cat['pct']))
    print('  %s' % static_note)

    if args.verify_icons:
        ok, checked, _ = verify_icons([r for c in doc['categories'] for r in c['items']],
                                     args.verify_icons)
        print('  icon check: %d/%d ok' % (ok, checked))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
