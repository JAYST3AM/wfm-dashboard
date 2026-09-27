#!/usr/bin/env python3
r"""Mastery Helper - what to master next, what it costs, and how close the next MR is.

Inputs (read-only)
  %LOCALAPPDATA%/AlecaFrame/lastData.dat   live save (AES-CBC; PlayerLevel + XPInfo).  Preferred -
                                           same order scripts/collection_log.py reads it.
  data/lastData.dec.json                   cached decrypted save, used when the live file is absent
  data/collection_log.json                 the 834 masterable rows: name / slug / unique_name /
                                           category / owned / mastered / mastery_req / obtain
  data/craft.json                          build-vs-buy rows: result_slug / verdict / buy_cost /
                                           missing_parts / built_floor
  data/dropdata/mastery/*.json             cached raw wiki API responses (fetched once, then reused)
  https://wiki.warframe.com/api.php        'Mastery Rank' page + 'Module:MasteryRank' wikitext
Output
  data/mastery.json                        the store this helper is built around
  static/mastery.json                      copy of the same payload, because server.py serves only
                                           static/ (--no-static-copy skips it)

Store shape (schema 1)
  schema, updated, updated_iso, source, mr, summary, categories, next, items - exactly these keys.
  mr         rank (save PlayerLevel), xp_total, xp_into_rank, xp_for_next, pct, next_rank,
             xp_per_rank_source (where the rank XP curve came from).
  summary    tracked, mastered, owned_unmastered, missing, buildable_now, gated_by_mr.
  categories [{key, name, total, mastered, owned_unmastered, missing, pct}] - the collection log's
             own category order and labels.
  next       the ranked 'do this next' queue, each row {name, category, slug, unique_name, state,
             xp_value, build, obtain, mastery_req, gated} - never a mastered row.  unique_name is
             the save path every other store joins on; gated marks a NON-mastered row whose
             mastery_req is above the current rank (a mastered row needs no access).
  items      all 834 rows, same fields, in the collection log's own order.

Rules (nothing here is guessed)
  * rank comes from the save's PlayerLevel; the rank XP curve comes from the wiki:
    'Mastery Rank' §Mastery Ranks Allocation - XP(rank) = 2,500 x rank^2 up to MR 30 (the section's
    rank table is parsed and checked against that formula), +147,500 per Legendary rank
    (Module:MasteryRank getRankXP).  Both raw API responses are cached under data/dropdata/mastery/.
  * xp_value per row is the wiki's own per-category mastery value (Module:MasteryRank
    baseMasteryXp, the table behind 'Mastery Rank' §Mastery Points): weapons / Amp prisms /
    Sentinel & Archwing weapons 3,000, Warframes / Companions / Archwings / K-Drive / Sentinel 6,000,
    Necramechs 8,000.  A category the table does not cover keeps xp_value null and says so -
    never a number from memory.  ('other' = the log's Necramech bucket, matched per row on the save
    path /EntratiMech/.)  Two limits of that table are named in `source` rather than hidden: the
    log's 'amps' rows are Amp parts while the wiki's 3,000 is per ranked Amp prism, and rank-40
    variants (Kuva/Tenet/Coda weapons, Paracesis) are worth 4,000, which the per-category table
    does not split out.
  * xp_total is the account's mastery points ACCOUNTED FROM THE SAVE: every mastered row contributes
    min(save XP, its category value), because the game never awards more mastery than the item's cap
    - the rest of XPInfo is affinity.  The raw XPInfo XP sum is affinity, not mastery, and is named
    in `source` instead of being compared with the rank curve.  The save carries no star chart /
    junction / Intrinsics mastery, so this total sits a little below the current rank's floor; pct is
    therefore a floor, and `source` says so.
  * XP cross-check (honesty check on the value table): every mastered row's save XP must be >= the
    derived xp_value for its category.  Any row that is not is counted and named in `source` - the
    table is never fudged to hide it.
  * queue order: MR-gated rows last (mastery_req above the current rank - the game will not let the
    account equip them yet), then owned-but-not-mastered (no farming needed), then CRAFT-with-cost
    rows cheapest first, then everything else (highest xp_value first).  Mastered rows never appear.
  * build / obtain are straight from data/craft.json and the collection log's own obtain payload
    (short + the first where-to-get line); a row with neither keeps null.

Env overrides (tests / selftest)  WFM_DATA_DIR (data dir), WFM_STATIC_DIR (static dir),
WFM_ALECA_DIR (AlecaFrame dir).  Stdlib only, atomic writes, UTC stamps.

CLI: --once (default) | --out PATH | --json | --dry-run | --no-fetch | --refresh |
     --no-static-copy | --selftest
Exit codes: 0 ok, 1 no save / no collection log, 2 selftest failure.
"""
import argparse
import json
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get('WFM_DATA_DIR') or os.path.join(ROOT, 'data')
STATIC = os.environ.get('WFM_STATIC_DIR') or os.path.join(ROOT, 'static')
AF = os.environ.get('WFM_ALECA_DIR') or os.path.expandvars(r'%LOCALAPPDATA%\AlecaFrame')

SCHEMA = 1
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'
TIMEOUT = 60
WIKI_API = 'https://wiki.warframe.com/api.php'
# (page title, cache file name) - the page carries the rank curve, the module the category values
WIKI_PAGES = (('Mastery Rank', 'mastery_rank.json'), ('Module:MasteryRank', 'module_masteryrank.json'))
RANK_SECTION_RE = re.compile(r'^===Mastery Ranks Allocation===\s*$(.*?)(?=^==[^=]|^===)',
                             re.S | re.M)
CURVE_RE = re.compile(r'return\s+([\d_]+)\s*\*\s*Rank\s*\^\s*2\s*\+\s*legRank\s*\*\s*([\d_]+)')
CATEGORY_BLOCK_RE = re.compile(r'baseMasteryXp\s*=\s*\{(.*?)\}', re.S)
CATEGORY_ROW_RE = re.compile(r"(?:\[['\"]([^'\"]+)['\"]\]|([A-Za-z_][A-Za-z0-9_]*))\s*=\s*(\d+)")

# the collection log's category key -> Module:MasteryRank baseMasteryXp key
CATEGORY_XP_KEY = {
    'warframes': 'warframes', 'primary': 'primaries', 'secondary': 'secondaries', 'melee': 'melee',
    'sentinels': 'sentinels', 'sentinel_weapons': 'sentinelWeapons', 'companions': 'companions',
    'archwing': 'archwings', 'archgun': 'archGuns', 'archmelee': 'archMelees',
    'kdrives': 'k-drives', 'amps': 'amps',
}
# 'other' is the collection log's Necramech bucket (WFCD productCategory MechSuits); the wiki's key
# is necramechs (8,000).  Only rows whose save path proves a Necramech are mapped - never by name.
OTHER_XP_KEY = 'necramechs'
NECRAMECH_PATH = '/EntratiMech/'

SAVE_KEY = bytes([76, 69, 79, 45, 65, 76, 69, 67, 9, 69, 79, 45, 65, 76, 69, 67])
SAVE_IV = bytes([49, 50, 70, 71, 66, 51, 54, 45, 76, 69, 51, 45, 113, 61, 57, 0])
STAMP = '%Y-%m-%dT%H:%M:%SZ'


# --------------------------------------------------------------------- small helpers
def jload(path, default=None):
    """Load JSON; default on any failure (missing/partial/foreign file)."""
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def atomic_write(path, doc):
    """tmp + os.replace, so a reader never sees a half-written file."""
    tmp = path + '.tmp'
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)


def iso_z(epoch):
    return datetime.fromtimestamp(int(epoch), timezone.utc).strftime(STAMP)


def rel(path):
    """Repo-relative display path; absolute when the store lives outside the repo (tests)."""
    try:
        sub = os.path.relpath(path, ROOT)
        if not sub.startswith('..'):
            return sub.replace('\\', '/')
    except ValueError:                                  # another drive: keep it absolute
        pass
    return path.replace('\\', '/')


def ascii_s(value):
    return str(value).encode('ascii', 'replace').decode('ascii')


def num_or_none(value):
    """int/float (bools rejected) else None - a store cell that was never a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def pct_of(part, whole):
    return round(100.0 * part / whole, 1) if whole else 0.0


def fmt_num(value):
    """17,500 -> '17500'; None -> '?' (display only, never fed back into the store)."""
    return '?' if value is None else str(int(value))


def out_path():
    return os.path.join(DATA, 'mastery.json')


def static_copy_path():
    return os.path.join(STATIC, 'mastery.json')


def log_path():
    return os.path.join(DATA, 'collection_log.json')


def craft_path():
    return os.path.join(DATA, 'craft.json')


def save_cached_path():
    return os.path.join(DATA, 'lastData.dec.json')


def save_live_path():
    return os.path.join(AF, 'lastData.dat')


def wiki_cache_dir():
    return os.path.join(DATA, 'dropdata', 'mastery')


# --------------------------------------------------------------------- save / XPInfo
def decrypt_data(path):
    """lastData.dat -> decrypted bytes.  Plaintext JSON (leading '{') passes through; otherwise
    AES-128-CBC with the fixed key/IV the app uses (same recipe as scripts/refresh.py)."""
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


def read_save():
    """({save dict} | None, meta) - live save first, cached decrypted copy as the fallback.

    meta: {source: 'live'|'cached'|None, path, mtime_iso, error}
    """
    live = save_live_path()
    err = None
    if os.path.exists(live):
        try:
            save = json.loads(decrypt_data(live).decode('utf-8', 'replace'))
            return save, {'source': 'live', 'path': live,
                          'mtime_iso': iso_z(os.path.getmtime(live)), 'error': None}
        except Exception as exc:                        # noqa: BLE001 - read/decrypt/parse anything
            err = '%s: %s' % (type(exc).__name__, exc)
    else:
        err = 'no live save at %s' % live
    cached = save_cached_path()
    if os.path.exists(cached):
        save = jload(cached)
        if isinstance(save, dict):
            return save, {'source': 'cached', 'path': cached,
                          'mtime_iso': iso_z(os.path.getmtime(cached)), 'error': err}
        err = '%s; cached save unreadable (%s)' % (err, cached)
    return None, {'source': None, 'path': None, 'mtime_iso': None,
                  'error': '%s; no cached save either (%s)' % (err, cached)}


def xpinfo_map(save):
    """{uniqueName: XP} from the save's XPInfo (one row per item the account earned XP with)."""
    out = {}
    for row in (save or {}).get('XPInfo') or []:
        if not isinstance(row, dict):
            continue
        item = row.get('ItemType')
        xp = row.get('XP')
        if isinstance(item, str) and item and num_or_none(xp) is not None:
            out[item] = xp
    return out


def player_level(save):
    """PlayerLevel (the account's current mastery rank) as an int, else None."""
    value = (save or {}).get('PlayerLevel')
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


# --------------------------------------------------------------------- wiki (cached raw API)
def wiki_cache_path(name):
    return os.path.join(wiki_cache_dir(), name)


def wiki_api_url(title):
    params = urllib.parse.urlencode({'action': 'query', 'prop': 'revisions', 'rvprop': 'content',
                                     'rvslots': 'main', 'redirects': '1', 'titles': title,
                                     'format': 'json', 'formatversion': '2'})
    return WIKI_API + '?' + params


def save_wiki_cache(name, title, text, fetched=None, url=None, response=None):
    """Write one cached wiki response; also used by the tests to seed the cache offline."""
    fetched = int(fetched if fetched is not None else time.time())
    doc = {'title': title, 'resolved': title, 'missing': text is None, 'fetched': fetched,
           'url': url or wiki_api_url(title), 'response': response, 'text': text}
    if response is not None:
        pages = ((response or {}).get('query') or {}).get('pages') or []
        page = pages[0] if pages else {}
        doc['resolved'] = page.get('title') or title
        doc['missing'] = 'revisions' not in page
    atomic_write(wiki_cache_path(name), doc)
    return doc


def wiki_text(doc):
    """The wikitext of a cached wiki doc (raw API response first, stored text as fallback)."""
    if not isinstance(doc, dict):
        return None
    response = doc.get('response')
    pages = ((response or {}).get('query') or {}).get('pages') or []
    if pages and 'revisions' in pages[0]:
        try:
            return pages[0]['revisions'][0]['slots']['main']['content']
        except (KeyError, IndexError, TypeError):
            return None
    return doc.get('text')


def fetch_wiki(name, title, offline=False, refresh=False, write=True):
    """(doc, meta) for one wiki page; cached raw response reused unless refresh/absent.

    doc is the cache wrapper ({title, resolved, missing, fetched, url, response, text}); meta
    names what happened ('cache' | 'fetched' | None) plus the error when it failed.
    """
    path = wiki_cache_path(name)
    cached = jload(path) if os.path.exists(path) else None
    if isinstance(cached, dict) and not refresh:
        return cached, {'source': 'cache', 'path': path, 'fetched': cached.get('fetched'),
                        'error': None}
    if offline:
        return None, {'source': None, 'path': path, 'fetched': None,
                      'error': 'offline and not cached (%s)' % rel(path)}
    try:
        req = urllib.request.Request(wiki_api_url(title),
                                     headers={'User-Agent': UA, 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            response = json.loads(resp.read().decode('utf-8', 'replace'))
    except Exception as exc:                            # noqa: BLE001 - network/parse anything
        return None, {'source': None, 'path': path, 'fetched': None,
                      'error': '%s: %s' % (type(exc).__name__, exc)}
    doc = {'title': title, 'resolved': title, 'missing': False, 'fetched': int(time.time()),
           'url': wiki_api_url(title), 'response': response, 'text': None}
    doc['text'] = wiki_text(doc)
    if write:
        save_wiki_cache(name, doc.get('resolved') or title, doc['text'], fetched=doc['fetched'],
                        url=doc['url'], response=response)
    return doc, {'source': 'fetched', 'path': path, 'fetched': doc['fetched'], 'error': None}


def parse_category_xp(module_text):
    """Module:MasteryRank baseMasteryXp -> {wiki key: mastery value}.  {} when unparseable."""
    if not module_text:
        return {}
    m = CATEGORY_BLOCK_RE.search(module_text)
    if not m:
        return {}
    out = {}
    for key, key2, value in CATEGORY_ROW_RE.findall(m.group(1)):
        name = key or key2
        if name:
            out[name] = int(value)
    return out


def parse_rank_table(page_text):
    """'Mastery Rank' §Mastery Ranks Allocation -> {rank: total XP required}.

    Rank rows are '|| Rank Name || Rank Number || Next Requirement || Total XP || ...'; Legendary
    rows carry the legendary index in the number column and map to rank 30 + n.  Only the section
    between §Mastery Ranks Allocation and the next heading is parsed, so the other tables on the
    page cannot leak in.  Rows whose cells are not numbers are skipped, never repaired.
    """
    if not page_text:
        return {}
    m = RANK_SECTION_RE.search(page_text)
    body = m.group(1) if m else ''
    out = {}
    for line in body.splitlines():
        if not line.lstrip().startswith('|'):
            continue
        cells = [c.strip() for c in line.split('||')]
        if len(cells) < 5:
            continue
        name, rank_cell, total_cell = cells[1], cells[2], cells[4]
        if not re.fullmatch(r'[\d,]+', total_cell):
            continue
        digits = re.search(r'\d+', rank_cell)
        if not digits:
            continue
        rank = int(digits.group(0))
        if name.lower().startswith('legendary'):
            rank += 30
        out[rank] = int(total_cell.replace(',', ''))
    return out


def parse_curve_constants(module_text):
    """(base, legendary step) from Module:MasteryRank getRankXP, else (None, None)."""
    if not module_text:
        return None, None
    m = CURVE_RE.search(module_text)
    if not m:
        return None, None
    return int(m.group(1).replace('_', '')), int(m.group(2).replace('_', ''))


def build_curve(page_text, module_text):
    """(curve, meta) - curve(rank) -> total XP required, from the wiki table + module formula.

    base is derived from the parsed rank table (XP(rank) / rank^2 for the highest rank <= 30
    present) and the Legendary step from the table's Legendary rows; the module's getRankXP
    constants are cross-checked against both.  Every parsed table row is verified against the
    curve - mismatches are reported, never averaged away.  curve is None when neither source
    parsed (the store then carries null MR numbers instead of inventing a progression).
    """
    table = parse_rank_table(page_text)
    mod_base, mod_step = parse_curve_constants(module_text)
    base = step = None
    if table:
        top = max((r for r in table if 0 < r <= 30), default=None)
        if top:
            base = table[top] // (top * top)
        leg = [(r - 30, xp) for r, xp in table.items() if r > 30]
        if leg and base:
            n, xp = max(leg)
            if n > 0:
                step = (xp - base * 900) // n
    if base is None:
        base = mod_base
    if step is None:
        step = mod_step if mod_base is not None else None
    if not base or not step:
        return None, {'table_rows': len(table), 'table': table, 'mismatches': [],
                      'source': None}

    def curve(rank):
        r = max(0, int(rank))
        return base * min(r, 30) ** 2 + max(0, r - 30) * step

    mismatches = [(r, xp, curve(r)) for r, xp in sorted(table.items()) if curve(r) != xp]
    return curve, {'table_rows': len(table), 'table': table,
                   'base': base, 'step': step, 'module_base': mod_base, 'module_step': mod_step,
                   'mismatches': mismatches,
                   'source': ('wiki.warframe.com/api.php Mastery Rank §Mastery Ranks Allocation '
                              '(%d rank rows, XP(rank) = %s x rank^2 up to MR 30) + '
                              'Module:MasteryRank getRankXP (+%s per Legendary rank)'
                              % (len(table), base, step))}


def load_wiki(offline=False, refresh=False, write=True):
    """(category table, curve, curve meta, wiki meta) with every fetch cached under dropdata."""
    docs, meta = {}, {}
    for title, name in WIKI_PAGES:
        doc, m = fetch_wiki(name, title, offline=offline, refresh=refresh, write=write)
        docs[name] = doc
        meta[name] = m
    page_text = wiki_text(docs.get('mastery_rank.json'))
    module_text = wiki_text(docs.get('module_masteryrank.json'))
    table = parse_category_xp(module_text)
    curve, curve_meta = build_curve(page_text, module_text)
    wiki_meta = {'pages': {name: {'source': m.get('source'), 'fetched': m.get('fetched'),
                                  'error': m.get('error'), 'path': rel(m.get('path') or '')}
                           for name, m in meta.items()},
                 'category_keys': len(table), 'curve_rows': curve_meta['table_rows']}
    return table, curve, curve_meta, wiki_meta


# --------------------------------------------------------------------- rows
def xp_value_for(item, category, table):
    """(xp_value, wiki key) for one row: the category's table value, or (None, None).

    'other' is the Necramech bucket: it maps only when the save path proves a Necramech
    (/EntratiMech/), never by name.
    """
    if not table:
        return None, None
    key = CATEGORY_XP_KEY.get(category)
    if key is None and category == 'other' and NECRAMECH_PATH in str(item.get('unique_name') or ''):
        key = OTHER_XP_KEY
    if key is None:
        return None, None
    value = table.get(key)
    return (int(value), key) if isinstance(value, int) else (None, key)


def craft_index(craft_doc):
    """{result_slug: row} from data/craft.json."""
    out = {}
    for row in (craft_doc or {}).get('rows') or []:
        if isinstance(row, dict) and row.get('result_slug'):
            out.setdefault(str(row['result_slug']), row)
    return out


def find_craft(slug, index):
    """The craft row for a collection item: bare slug, then <slug>_set, then <slug>_blueprint.

    (craft.json keys assembled results - a warframe/weapon is quoted as its set or blueprint.)"""
    if not slug:
        return None
    for suffix in ('', '_set', '_blueprint'):
        row = index.get(slug + suffix)
        if row is not None:
            return row
    return None


def craft_payload(row):
    """{verdict, cost, missing_parts} straight from data/craft.json, or None."""
    if not isinstance(row, dict):
        return None
    verdict = row.get('verdict')
    if not isinstance(verdict, str):
        return None
    missing = [str(p) for p in (row.get('missing_parts') or []) if p]
    return {'verdict': verdict, 'cost': num_or_none(row.get('buy_cost')), 'missing_parts': missing}


def first_line_text(line):
    """One readable where-to-get line from a collection-log obtain line (never invented)."""
    if not isinstance(line, dict):
        return None
    bits = [str(b) for b in (line.get('label'), line.get('detail') or line.get('text')) if b]
    return ' \u00b7 '.join(bits) if bits else None


def obtain_payload(obtain):
    """{short, first, text} - the collection log's own obtain payload, or None."""
    if not isinstance(obtain, dict):
        return None
    lines = obtain.get('lines') or []
    first = lines[0] if lines and isinstance(lines[0], dict) else None
    short = obtain.get('short')
    text = first_line_text(first)
    if short is None and text is None:
        return None
    return {'short': short, 'first': first, 'text': text}


def build_rows(categories, xp_map, craft_idx, table, rank, log_flags=None):
    """(rows, stats) - one row per collection-log item, in the log's own order.

    state is mastered (in the save's XPInfo) | owned (in owned.json) | missing; log_flags counts
    how many rows' mastered flag disagrees with the save (reported, never silently resolved).
    """
    flags = log_flags or {'disagree': 0, 'log_mastered_only': [], 'save_mastered_only': []}
    rows, order = [], []
    for cat in categories or []:
        if not isinstance(cat, dict):
            continue
        key = cat.get('key') or 'other'
        for item in cat.get('items') or []:
            if not isinstance(item, dict):
                continue
            uniq = item.get('unique_name')
            mastered = bool(uniq) and uniq in xp_map
            owned = bool(item.get('owned'))
            log_mastered = bool(item.get('mastered'))
            if log_mastered and not mastered:
                flags['disagree'] += 1
                flags['log_mastered_only'].append(item.get('name'))
            elif mastered and not log_mastered:
                flags['disagree'] += 1
                flags['save_mastered_only'].append(item.get('name'))
            value, _key = xp_value_for(item, key, table)
            req = item.get('mastery_req')
            req = int(req) if isinstance(req, int) and not isinstance(req, bool) else None
            rows.append({
                'name': item.get('name'),
                'category': key,
                'slug': item.get('slug'),
                'unique_name': uniq,
                'state': 'mastered' if mastered else ('owned' if owned else 'missing'),
                'xp_value': value,
                'build': craft_payload(find_craft(item.get('slug'), craft_idx)),
                'obtain': obtain_payload(item.get('obtain')),
                'mastery_req': req,
                # 'gated' is about the queue: a mastered row needs no access, so it is never gated
                'gated': bool(not mastered and req is not None and rank is not None and req > rank),
            })
            order.append(key)
    return rows, flags


def queue_key(row):
    """Sort key for the 'next' queue - documented in the module docstring."""
    value = row.get('xp_value')
    vkey = (0, -value) if isinstance(value, int) else (1, 0)
    gated = 1 if row.get('gated') else 0
    build = row.get('build') or {}
    cost = num_or_none(build.get('cost'))
    name = str(row.get('name') or '').lower()
    if row.get('state') == 'owned':
        return (gated, 0) + vkey + (name,)
    if build.get('verdict') == 'CRAFT' and cost is not None:
        return (gated, 1, float(cost)) + vkey + (name,)
    return (gated, 2) + vkey + (name,)


def rank_queue(rows):
    """The ranked 'do this next' queue: never a mastered row (see the docstring for the order)."""
    return sorted((r for r in rows if r.get('state') != 'mastered'), key=queue_key)


# --------------------------------------------------------------------- totals
def mastery_total(rows, xp_map):
    """(xp_total, detail) - mastery points accounted from the save's XPInfo.

    Every mastered row contributes min(save XP, its category value): the game awards mastery up to
    the item's cap and nothing beyond it.  Rows with no table value and XPInfo rows outside the
    collection log are counted and named, never guessed at.
    """
    total = 0
    counted = valued = unvalued = 0
    raw_sum = 0
    for row in rows:
        if row['state'] != 'mastered':
            continue
        counted += 1
        xp = xp_map.get(row['unique_name'])
        if isinstance(xp, (int, float)) and not isinstance(xp, bool):
            raw_sum += xp
        if row['xp_value'] is None:
            unvalued += 1
            continue
        valued += 1
        total += min(xp, row['xp_value']) if isinstance(xp, (int, float)) else 0
    known = set(xp_map)
    outside = sorted(known - {r['unique_name'] for r in rows if r['unique_name']})
    return int(total), {'mastered_rows': counted, 'valued': valued, 'unvalued': unvalued,
                        'raw_xp_sum': int(raw_sum), 'xpinfo_outside_log': outside}


def xp_cross_check(rows, xp_map):
    """Mastered rows whose save XP is NOT >= their category value - the value-table honesty check.

    checked counts every mastered row with a category value AND an XPInfo row; ok_count is how
    many of those pass.  Rows with no XPInfo row are listed as uncheckable.  Nothing here is
    corrected or hidden: the caller reports the counts and the first few names.
    """
    below, uncheckable = [], []
    checked = 0
    for row in rows:
        if row['state'] != 'mastered':
            continue
        if row['xp_value'] is None:
            continue
        xp = xp_map.get(row['unique_name'])
        if not isinstance(xp, (int, float)) or isinstance(xp, bool):
            uncheckable.append({'name': row['name'], 'category': row['category']})
            continue
        checked += 1
        if xp < row['xp_value']:
            below.append({'name': row['name'], 'category': row['category'], 'xp': xp,
                          'xp_value': row['xp_value']})
    return {'checked': checked, 'ok': checked - len(below), 'below_value': below,
            'uncheckable': uncheckable}


def summarize(rows):
    """The store's summary block + per-category counts, from the built rows."""
    summary = {'tracked': len(rows), 'mastered': 0, 'owned_unmastered': 0, 'missing': 0,
               'buildable_now': 0, 'gated_by_mr': 0}
    cats = {}
    for row in rows:
        state = row['state']
        if state == 'mastered':
            summary['mastered'] += 1
        elif state == 'owned':
            summary['owned_unmastered'] += 1
        else:
            summary['missing'] += 1
        if state != 'mastered' and row.get('gated'):
            summary['gated_by_mr'] += 1
        build = row.get('build') or {}
        if (state != 'mastered' and build.get('verdict') == 'CRAFT'
                and not build.get('missing_parts')):
            summary['buildable_now'] += 1
        cat = cats.setdefault(row['category'], {'total': 0, 'mastered': 0, 'owned_unmastered': 0,
                                                'missing': 0})
        cat['total'] += 1
        if state == 'mastered':
            cat['mastered'] += 1
        elif state == 'owned':
            cat['owned_unmastered'] += 1
        else:
            cat['missing'] += 1
    return summary, cats


def category_rows(categories, cats):
    """The categories block, keeping the collection log's own order and labels."""
    out = []
    for cat in categories or []:
        if not isinstance(cat, dict):
            continue
        key = cat.get('key') or 'other'
        counts = cats.get(key) or {'total': 0, 'mastered': 0, 'owned_unmastered': 0, 'missing': 0}
        out.append({'key': key, 'name': cat.get('name') or key, 'total': counts['total'],
                    'mastered': counts['mastered'],
                    'owned_unmastered': counts['owned_unmastered'], 'missing': counts['missing'],
                    'pct': pct_of(counts['mastered'], counts['total'])})
    return out


def mr_block(rank, xp_total, curve):
    """The mr object: rank from the save, progression from the wiki rank curve."""
    if rank is None or curve is None:
        return {'rank': rank, 'xp_total': None if rank is None else xp_total,
                'xp_into_rank': None, 'xp_for_next': None, 'pct': None,
                'next_rank': None if rank is None else rank + 1}
    floor = curve(rank)
    band = curve(rank + 1) - floor
    into = max(0, int(xp_total) - floor)
    return {'rank': rank, 'xp_total': int(xp_total), 'xp_into_rank': into,
            'xp_for_next': band,
            'pct': round(min(100.0, 100.0 * into / band), 1) if band else None,
            'next_rank': rank + 1}


# --------------------------------------------------------------------- the store
def build_doc(log_doc, craft_doc, save, save_meta, table, curve, curve_meta, wiki_meta,
              now=None):
    """(doc, stats) - the data/mastery.json payload plus the CLI numbers behind it."""
    now = int(now if now is not None else time.time())
    rank = player_level(save)
    xp_map = xpinfo_map(save)
    craft_idx = craft_index(craft_doc)
    categories = (log_doc or {}).get('categories') or []
    rows, flags = build_rows(categories, xp_map, craft_idx, table, rank)
    summary, cats = summarize(rows)
    xp_total, total_meta = mastery_total(rows, xp_map)
    check = xp_cross_check(rows, xp_map)
    mr = mr_block(rank, xp_total, curve)
    next_rows = rank_queue(rows)

    # every fact below names its source; nothing is inferred from memory
    floor = curve(rank) if (curve is not None and rank is not None) else None
    progress = ('the save stores no star chart / junction / Intrinsics mastery, so the accounted '
                'total sits %s below the MR %s floor (%s): pct is a floor, not the exact in-game '
                'bar' % ('{:,}'.format(max(0, floor - xp_total)), rank, '{:,}'.format(floor))
                if floor is not None else
                'no wiki rank table was cached, so the MR progression fields are null')
    source = ('save: %s %s (PlayerLevel %s + XPInfo %s rows); rows: data/collection_log.json '
              '(%d masterable rows, owned/mastered/mastery_req/obtain); builds: data/craft.json '
              '(verdict + buy_cost of the missing parts + missing_parts); '
              'rank curve: %s; item values: Module:MasteryRank baseMasteryXp (Mastery Rank '
              '\u00a7Mastery Points: weapons/Amp prisms/Sentinel & Archwing weapons 3,000, '
              'Warframes/Companions/Archwings/K-Drive/Sentinels 6,000, Necramechs 8,000); '
              'xp_total is mastery points accounted from the save (each mastered row = '
              'min(XPInfo XP, its category value); the raw XPInfo XP sum %s is affinity, not '
              'mastery); %s; '
              'xp check: %d of %d compared mastered rows have save XP >= their category value'
              % (save_meta.get('source') or 'none', rel(save_meta.get('path') or ''), rank,
                 len(xp_map), len(rows), curve_meta.get('source') or
                 'unavailable (no wiki table cached - xp_value null, MR progression null)',
                 '{:,}'.format(total_meta['raw_xp_sum']), progress,
                 check['ok'], check['checked']))
    if curve is not None:
        source += ('; the §Mastery Ranks Allocation rank table was checked row by row against the '
                   'curve (%d rows, %d mismatches%s)'
                   % (curve_meta.get('table_rows') or 0, len(curve_meta.get('mismatches') or []),
                      (': ' + ', '.join('rank %s table %s != %s' % (r, f, c) for r, f, c in
                                        (curve_meta.get('mismatches') or [])[:5]))
                      if curve_meta.get('mismatches') else ''))
    source += ('; value-table notes: the collection log\'s "amps" rows are Amp parts '
               '(prism/scaffold/brace) while the wiki\'s 3,000 is per ranked Amp prism, so a part '
               'row can overstate; rank-40 variants (Kuva/Tenet/Coda weapons, Paracesis) are worth '
               '4,000 (Module:MasteryRank RankForties), which the per-category table does not '
               'split out')
    if check['below_value']:
        source += ('; XP BELOW VALUE (%d, the value table is wrong for these): %s'
                   % (len(check['below_value']),
                      ', '.join('%s (%s %s < %s)' % (m['name'], m['category'], fmt_num(m['xp']),
                                                     fmt_num(m['xp_value']))
                                for m in check['below_value'][:5])))
    if check['uncheckable']:
        source += ('; %d mastered rows have no XPInfo row to check: %s'
                   % (len(check['uncheckable']),
                      ', '.join(m['name'] for m in check['uncheckable'][:5])))
    if total_meta['unvalued']:
        source += ('; %d mastered rows have no category value in the wiki table and are not '
                   'counted in xp_total' % total_meta['unvalued'])
    if total_meta['xpinfo_outside_log']:
        source += ('; %d XPInfo rows match no collection row and are not counted: %s'
                   % (len(total_meta['xpinfo_outside_log']),
                      ', '.join(total_meta['xpinfo_outside_log'][:3])))
    if flags['disagree']:
        source += ('; NOTE %d rows: collection_log.json mastered flag != this save XPInfo '
                   '(log: %s | save: %s) - the log was built from a different save copy'
                   % (flags['disagree'], ', '.join(flags['log_mastered_only'][:3]),
                      ', '.join(flags['save_mastered_only'][:3])))

    mr['xp_per_rank_source'] = (
        (curve_meta.get('source') or
         'unavailable: no wiki rank table cached (run without --no-fetch)')
        + ' | per-category xp_value: Module:MasteryRank baseMasteryXp (the table behind the '
          'Mastery Rank page §Mastery Points) at wiki.warframe.com/api.php')
    doc = {'schema': SCHEMA, 'updated': now, 'updated_iso': iso_z(now), 'source': source,
           'mr': mr, 'summary': summary, 'categories': category_rows(categories, cats),
           'next': next_rows, 'items': rows}
    stats = {'summary': summary, 'check': check, 'total': total_meta, 'flags': flags,
             'wiki': wiki_meta, 'queue': len(next_rows), 'floor': floor}
    return doc, stats


def summary_line(doc):
    """'mastery: MR 22 (61.2% to 23) | tracked 834 | mastered N | owned N | missing N | ...'"""
    mr = doc.get('mr') or {}
    rank = mr.get('rank')
    nxt = mr.get('next_rank')
    pct = mr.get('pct')
    head = 'MR %s' % ('?' if rank is None else rank)
    tail = ('%s%% to %s' % ('?' if pct is None else ('%.1f' % pct), nxt)
            if nxt is not None else 'no rank curve')
    s = doc.get('summary') or {}
    return ('mastery: %s (%s) | tracked %d | mastered %d | owned %d | missing %d | '
            'buildable now %d | next queue %d'
            % (head, tail, s.get('tracked') or 0, s.get('mastered') or 0,
               s.get('owned_unmastered') or 0, s.get('missing') or 0, s.get('buildable_now') or 0,
               len(doc.get('next') or [])))


# --------------------------------------------------------------------- selftest
SELFTEST_SAVE = {'PlayerLevel': 2, 'XPInfo': [
    {'ItemType': '/Lotus/Powersuits/Ninja/Ninja', 'XP': 612345},                  # frame, maxed
    {'ItemType': '/Lotus/Weapons/Tenno/Rifle/Braton', 'XP': 450123},              # weapon, maxed
    {'ItemType': '/Lotus/Weapons/Tenno/Rifle/BratonPrime', 'XP': 500},            # below value!
    {'ItemType': '/Lotus/Powersuits/EntratiMech/NechroTech', 'XP': 900000},       # necramech
]}
SELFTEST_LOG = {'categories': [
    {'key': 'warframes', 'name': 'Warframes', 'items': [
        {'name': 'Ash', 'slug': 'ash', 'unique_name': '/Lotus/Powersuits/Ninja/Ninja',
         'owned': False, 'mastered': True, 'mastery_req': 0,
         'obtain': {'short': 'Skirmish A', 'lines': [{'k': 'mission', 'label': 'Venus - X',
                                                      'detail': 'Skirmish \u00b7 13.33%'}]}},
        {'name': 'Nezha', 'slug': 'nezha', 'unique_name': '/Lotus/Powersuits/Odalisk/Odalisk',
         'owned': False, 'mastered': False, 'mastery_req': 3,          # gated (rank 2)
         'obtain': {'short': 'Skirmish B', 'lines': [{'k': 'mission', 'label': 'Venus - Y',
                                                      'detail': 'Skirmish \u00b7 12.5%'}]}},
    ]},
    {'key': 'primary', 'name': 'Primary', 'items': [
        {'name': 'Braton', 'slug': 'braton', 'unique_name': '/Lotus/Weapons/Tenno/Rifle/Braton',
         'owned': False, 'mastered': True, 'mastery_req': 0, 'obtain': None},
        {'name': 'Braton Prime', 'slug': 'braton_prime',
         'unique_name': '/Lotus/Weapons/Tenno/Rifle/BratonPrime', 'owned': False,
         'mastered': True, 'mastery_req': 8, 'obtain': None},
        {'name': 'Braton Vandal', 'slug': 'braton_vandal',
         'unique_name': '/Lotus/Weapons/Tenno/Rifle/BratonVandal', 'owned': False,
         'mastered': False, 'mastery_req': 0, 'obtain': None},
        {'name': 'Latron', 'slug': 'latron', 'unique_name': '/Lotus/Weapons/Tenno/Rifle/Latron',
         'owned': False, 'mastered': False, 'mastery_req': 0, 'obtain': None},
        {'name': 'Boltor', 'slug': 'boltor', 'unique_name': '/Lotus/Weapons/Tenno/Rifle/Boltor',
         'owned': False, 'mastered': False, 'mastery_req': 0, 'obtain': None},
    ]},
    {'key': 'archwing', 'name': 'Archwing', 'items': [
        {'name': 'Itzal', 'slug': 'itzal', 'unique_name': '/Lotus/Powersuits/Archwing/Itzal',
         'owned': True, 'mastered': False, 'mastery_req': 0, 'obtain': None},
    ]},
    {'key': 'other', 'name': 'Other', 'items': [
        {'name': 'Voidrig', 'slug': 'voidrig', 'unique_name': '/Lotus/Powersuits/EntratiMech/NechroTech',
         'owned': True, 'mastered': True, 'mastery_req': 0, 'obtain': None},
        {'name': 'Bonewidow', 'slug': 'bonewidow',
         'unique_name': '/Lotus/Powersuits/EntratiMech/ThanoTech', 'owned': False,
         'mastered': False, 'mastery_req': 0, 'obtain': None},
    ]},
    {'key': 'lab_parts', 'name': 'Lab Parts', 'items':      # a category the wiki table lacks
        [{'name': 'Weird Thing', 'slug': 'weird_thing', 'unique_name': '/Lotus/Types/Lab/Thing',
          'owned': False, 'mastered': False, 'mastery_req': 0, 'obtain': None}]},
]}
SELFTEST_CRAFT = {'rows': [
    {'result_slug': 'braton_vandal_set', 'result_name': 'Braton Vandal Set', 'verdict': 'CRAFT',
     'buy_cost': 0.0, 'missing_parts': [], 'built_floor': 10.0, 'owned_parts': ['p1']},
    {'result_slug': 'latron_set', 'result_name': 'Latron Set', 'verdict': 'CRAFT',
     'buy_cost': 5.0, 'missing_parts': ['latron_barrel'], 'built_floor': 8.0, 'owned_parts': []},
    {'result_slug': 'boltor_blueprint', 'result_name': 'Boltor Blueprint', 'verdict': 'BUY',
     'buy_cost': 12.0, 'missing_parts': ['boltor_stock'], 'built_floor': 4.0, 'owned_parts': []},
    {'result_slug': 'nezha_set', 'result_name': 'Nezha Set', 'verdict': 'CRAFT',
     'buy_cost': 40.0, 'missing_parts': ['nezha_chassis'], 'built_floor': 45.0, 'owned_parts': []},
]}
SELFTEST_WIKI_PAGE = """Intro prose.
===Mastery Ranks Allocation===
*Experience needed for each level, up to MR 30, is calculated by the formula: 2,500 {{mul}} (Rank<sup>2</sup>)
{| class="article-table"
! Rank Image !! Rank Name!! Rank Number !! Next Rank Requirement !! Total XP Required !! Test
|-
| [[File:Unranked.png|64x64px]] || Unranked || 0 || 2,500 || 0 || ''None''
|-
| [[File:IconRank1.png|64x64px]] || Initiate || 1 || 7,500 || 2,500 || ''x''
|-
| [[File:IconRank2.png|64x64px]] || Silver Initiate || 2 || 12,500 || 10,000 || ''x''
|-
| [[File:IconRank3.png|64x64px]] || Gold Initiate || 3 || 17,500 || 22,500 || ''x''
|-
| [[File:IconRank31.png|64x64px]] || Legendary 1 || 1 [[File:LegendaryIcon.png|class=icon]] || 147,500 || 2,397,500 || ''x''
|-
|}
===Total Mastery===
prose that must not leak into the rank table
"""
SELFTEST_WIKI_MODULE = """-- helper module
local baseMasteryXp = {
    warframes = 6000,
    primaries = 3000,
    amps = 3000,
    ['k-drives'] = 6000,
    archwings = 6000,
    necramechs = 8000,
}
local function getRankXP(Rank)
    local legRank = math.max(0, Rank - 30)
    Rank = math.min(Rank, 30)
    return 2500 * Rank ^ 2  +  legRank * 147500
end
"""


def selftest():
    """Offline fixture run in a tmp dir: fixture save + collection rows + craft rows + a fixture
    wiki cache prove the join, the ranking, the MR gating, the curve parse and the XP cross-check.
    No network, no repo writes."""
    checks = []

    def ok(cond, what):
        if not cond:
            raise AssertionError(what)
        checks.append(what)

    try:
        with tempfile.TemporaryDirectory(prefix='mastery_selftest_') as td:
            saved = (DATA, STATIC, AF)
            try:
                globals()['DATA'] = os.path.join(td, 'data')
                globals()['STATIC'] = os.path.join(td, 'static')
                globals()['AF'] = os.path.join(td, 'no-alecaframe')

                # --- the wiki parse: category table + rank curve, offline
                table = parse_category_xp(SELFTEST_WIKI_MODULE)
                ok(table.get('warframes') == 6000 and table.get('primaries') == 3000
                   and table.get('k-drives') == 6000 and table.get('necramechs') == 8000
                   and table.get('archwings') == 6000 and table.get('amps') == 3000,
                   'baseMasteryXp parsed (warframes 6000, primaries 3000, k-drives 6000, '
                   'archwings 6000, amps 3000, necramechs 8000)')
                raw_table = parse_rank_table(SELFTEST_WIKI_PAGE)
                ok(raw_table == {0: 0, 1: 2500, 2: 10000, 3: 22500, 31: 2397500},
                   'rank table parsed from §Mastery Ranks Allocation only (%d rows)' % len(raw_table))
                curve, cmeta = build_curve(SELFTEST_WIKI_PAGE, SELFTEST_WIKI_MODULE)
                ok(curve is not None and cmeta['mismatches'] == [], 'curve matches every table row')
                ok(curve(2) == 10000 and curve(3) == 22500 and curve(31) == 2397500,
                   'curve: XP(2)=10000, XP(3)=22500, XP(31)=2397500')
                ok(cmeta['base'] == 2500 and cmeta['step'] == 147500,
                   'curve constants from the table (2,500/rank^2, +147,500 legendary)')
                ok(cmeta['module_base'] == 2500 and cmeta['module_step'] == 147500,
                   'module getRankXP cross-checks the table')
                ok(build_curve('no table here', None)[0] is None,
                   'no table + no module -> no curve, never an invented progression')

                # --- the join + the derived row fields
                xp_map = xpinfo_map(SELFTEST_SAVE)
                ok(len(xp_map) == 4 and player_level(SELFTEST_SAVE) == 2, 'fixture save read')
                rows, flags = build_rows(SELFTEST_LOG['categories'], xp_map,
                                         craft_index(SELFTEST_CRAFT), table, 2)
                ok(len(rows) == 11 and flags['disagree'] == 0, '11 rows, log flags agree with save')
                by = {r['name']: r for r in rows}
                ok(by['Ash']['state'] == 'mastered' and by['Itzal']['state'] == 'owned'
                   and by['Boltor']['state'] == 'missing', 'states: mastered / owned / missing')
                ok(by['Ash']['xp_value'] == 6000 and by['Braton']['xp_value'] == 3000
                   and by['Voidrig']['xp_value'] == 8000 and by['Itzal']['xp_value'] == 6000,
                   'xp_value per category (frames 6000, weapons 3000, necramech 8000, archwing 6000)')
                ok(by['Weird Thing']['xp_value'] is None,
                   'a category the wiki table lacks keeps xp_value null')
                ok(by['Nezha']['gated'] and not by['Ash']['gated'],
                   'gating: mastery_req 3 > rank 2 is gated, req 0 is not')
                ok(by['Braton Vandal']['build'] == {'verdict': 'CRAFT', 'cost': 0.0,
                                                    'missing_parts': []},
                   'build block straight from craft.json (_set join, cost, missing parts)')
                ok(by['Boltor']['build']['verdict'] == 'BUY' and by['Ash']['build'] is None,
                   'BUY verdict kept as-is; an item with no craft row keeps build null')
                ok(by['Ash']['obtain']['short'] == 'Skirmish A'
                   and by['Ash']['obtain']['text'] == 'Venus - X \u00b7 Skirmish \u00b7 13.33%',
                   'obtain keeps the log short + first line in readable form')

                # --- the queue: gated last, owned first, then CRAFT cheapest, then the rest
                queue = rank_queue(rows)
                names = [r['name'] for r in queue]
                ok('Braton' not in names and 'Ash' not in names and 'Voidrig' not in names,
                   'mastered rows never enter the queue')
                ok(names[0] == 'Itzal', 'owned-but-not-mastered first (Itzal)')
                ok(names[1:3] == ['Braton Vandal', 'Latron'],
                   'then CRAFT with a known cost, cheapest first (0.0 then 5.0)')
                ok(names[-1] == 'Nezha', 'the MR-gated row sorts after every ungated one')
                ok(set(names) == {'Itzal', 'Braton Vandal', 'Latron', 'Boltor', 'Bonewidow',
                                  'Weird Thing', 'Nezha'}, 'queue holds every non-mastered row')

                # --- summary + categories
                summary, cats = summarize(rows)
                ok(summary == {'tracked': 11, 'mastered': 4, 'owned_unmastered': 1, 'missing': 6,
                               'buildable_now': 1, 'gated_by_mr': 1}, 'summary counters')
                crows = category_rows(SELFTEST_LOG['categories'], cats)
                ok([c['key'] for c in crows] == ['warframes', 'primary', 'archwing', 'other',
                                                 'lab_parts'], 'categories keep the log order')
                ok(crows[0]['mastered'] == 1 and crows[0]['total'] == 2 and crows[0]['pct'] == 50.0,
                   'per-category counts + pct')

                # --- MR math + the XP cross-check
                total, tmeta = mastery_total(rows, xp_map)
                ok(total == 17500,
                   'xp_total = min(XP, value) over mastered rows (6000 + 3000 + 500 + 8000 = 17500)')
                ok(tmeta['unvalued'] == 0 and tmeta['xpinfo_outside_log'] == [],
                   'every mastered row valued; no XPInfo row outside the log')
                mr = mr_block(2, total, curve)
                ok(mr == {'rank': 2, 'xp_total': 17500, 'xp_into_rank': 7500, 'xp_for_next': 12500,
                          'pct': 60.0, 'next_rank': 3}, 'MR block (10,000 floor, 12,500 band, 60.0%)')
                ok(mr_block(None, 0, None)['pct'] is None and mr_block(2, 0, None)['xp_for_next'] is None,
                   'no rank curve -> null progression, never an invented one')
                check = xp_cross_check(rows, xp_map)
                ok(check['checked'] == 4 and check['ok'] == 3
                   and [m['name'] for m in check['below_value']] == ['Braton Prime'],
                   'XP cross-check catches the below-value row (3 of 4 pass)')
                ok(xp_cross_check([dict(by['Ash'], unique_name='/Lotus/Gone')], xp_map)['uncheckable']
                   == [{'name': 'Ash', 'category': 'warframes'}],
                   'a mastered row with no XPInfo row is reported as uncheckable')

                # --- the whole store, written into the tmp dir only
                doc, stats = build_doc(SELFTEST_LOG, SELFTEST_CRAFT, SELFTEST_SAVE,
                                       {'source': 'fixture', 'path': '/tmp/fixture-save',
                                        'error': None}, table, curve, cmeta,
                                       {'pages': {}}, now=1700000000)
                ok(list(doc) == ['schema', 'updated', 'updated_iso', 'source', 'mr', 'summary',
                                 'categories', 'next', 'items'], 'store keys exact + ordered')
                ok(list(doc['mr']) == ['rank', 'xp_total', 'xp_into_rank', 'xp_for_next', 'pct',
                                       'next_rank', 'xp_per_rank_source'], 'mr keys exact')
                ok(list(doc['summary']) == ['tracked', 'mastered', 'owned_unmastered', 'missing',
                                            'buildable_now', 'gated_by_mr'], 'summary keys exact')
                ok(list(doc['items'][0]) == ['name', 'category', 'slug', 'unique_name', 'state',
                                             'xp_value', 'build', 'obtain', 'mastery_req',
                                             'gated'],
                   'row keys exact')
                ok(len(doc['items']) == 11 and len(doc['next']) == 7, 'items all rows, next queue')
                ok(doc['updated'] == 1700000000 and doc['updated_iso'].endswith('Z'),
                   'timestamps (epoch + ISO Z)')
                ok('Mastery Ranks Allocation' in doc['mr']['xp_per_rank_source']
                   and 'baseMasteryXp' in doc['mr']['xp_per_rank_source']
                   and 'Mastery Points' in doc['mr']['xp_per_rank_source'],
                   'xp_per_rank_source names the wiki page + section for the curve AND the values')
                ok('XP BELOW VALUE' in doc['source'] and 'Braton Prime' in doc['source']
                   and 'xp check: 3 of 4' in doc['source'],
                   'source names the below-value row + the xp check (3 of 4 pass)')
                path = out_path()
                atomic_write(path, doc)
                ok(os.path.exists(path) and not os.path.exists(path + '.tmp')
                   and jload(path)['summary'] == summary, 'atomic write + round-trip in the tmp dir')
                ok(not os.path.exists(save_live_path()), 'never touched a live save path')
                line = summary_line(doc)
                ok(line.startswith('mastery: MR 2 (60.0% to 3) | tracked 11 | mastered 4 | owned 1 |')
                   and '| missing 6 | buildable now 1 | next queue 7' in line,
                   'summary line format')
            finally:
                globals()['DATA'], globals()['STATIC'], globals()['AF'] = saved
    except AssertionError as exc:
        print('selftest : FAILED - %s' % ascii_s(exc))
        return 2
    print('selftest : ok (%d checks) offline - no network, tmp files only' % len(checks))
    return 0


# --------------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='mastery.py',
        description='Build data/mastery.json (+ the static/ copy): what to master next, what it '
                    'costs, and how close the next Mastery Rank is.',
        epilog='Exit codes: 0 ok, 1 no save / no collection log, 2 selftest failure.')
    ap.add_argument('--once', action='store_true', default=True,
                    help='single pass (default; kept for cron lines)')
    ap.add_argument('--out', metavar='PATH', help='store path (default data/mastery.json)')
    ap.add_argument('--json', action='store_true', help='print the store JSON to stdout')
    ap.add_argument('--dry-run', action='store_true', help='print the plan and write nothing')
    ap.add_argument('--no-fetch', action='store_true',
                    help='use only the cached wiki table (data/dropdata/mastery/)')
    ap.add_argument('--refresh', action='store_true', help='refetch the wiki pages (ignore cache)')
    ap.add_argument('--no-static-copy', action='store_true',
                    help='do not write static/mastery.json')
    ap.add_argument('--selftest', action='store_true',
                    help='offline fixture run in a temp dir (no network, no repo writes)')
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    save, save_meta = read_save()
    if save is None:
        print('mastery : save unreadable (%s) - run scripts/refresh.py first' % ascii_s(save_meta.get('error')))
        return 1
    log_doc = jload(log_path())
    if not isinstance(log_doc, dict) or not log_doc.get('categories'):
        print('mastery : no collection log at %s - run scripts/collection_log.py first'
              % rel(log_path()))
        return 1
    craft_doc = jload(craft_path(), {}) or {}

    write = not args.dry_run
    table, curve, curve_meta, wiki_meta = load_wiki(offline=args.no_fetch, refresh=args.refresh,
                                                    write=write)
    doc, stats = build_doc(log_doc, craft_doc, save, save_meta, table, curve, curve_meta, wiki_meta)
    line = summary_line(doc)
    print(line)                                          # summary line FIRST
    mr = doc['mr']
    print('  mr     : MR %s -> %s | rank band %s mastery (into-rank accounted %s) | '
          'save-accounted item mastery %s | raw XPInfo XP %s (affinity, not mastery)'
          % (fmt_num(mr['rank']), fmt_num(mr['next_rank']), fmt_num(mr['xp_for_next']),
             fmt_num(mr['xp_into_rank']), fmt_num(mr['xp_total']),
             '{:,}'.format(stats['total']['raw_xp_sum'])))
    print('  curve  : %s' % ascii_s(doc['mr']['xp_per_rank_source']))
    if stats.get('floor') is not None:
        print('  bar    : the save accounts %s of the %s mastery needed to hold MR %s; star chart '
              '/ junction / Intrinsics mastery are not in the save, so pct is a floor'
              % (fmt_num(mr['xp_total']), fmt_num(stats['floor']), fmt_num(mr['rank'])))
    if table:
        print('  values : %s' % ', '.join('%s %d' % (k, v) for k, v in sorted(table.items())))
    else:
        print('  values : UNAVAILABLE - no wiki table cached (xp_value null).  run without '
              '--no-fetch to fetch it.')
    check = stats['check']
    print('  xp check: %d of %d compared mastered rows have save XP >= their category value '
          '(%d below, %d without an XPInfo row to check)'
          % (check['ok'], check['checked'], len(check['below_value']), len(check['uncheckable'])))
    for m in check['below_value'][:5]:
        print('    BELOW : %s (%s) save XP %s < value %s - the table is wrong here'
              % (ascii_s(m['name']), m['category'], fmt_num(m['xp']), fmt_num(m['xp_value'])))
    if check['uncheckable']:
        print('    ??    : %s' % ', '.join(ascii_s(m['name']) for m in check['uncheckable'][:5]))
    if not curve:
        note = next((m.get('error') for m in wiki_meta.get('pages', {}).values()
                     if m.get('error')), None)
        if note:
            print('  wiki   : %s' % ascii_s(note))
    top = doc['next'][:3]
    if top:
        print('  queue  : %s' % ' | '.join(
            '%s (%s%s)' % (ascii_s(r['name']), r['state'],
                           (', CRAFT %s' % fmt_num((r['build'] or {}).get('cost')))
                           if r['build'] else '') for r in top))

    if args.dry_run:
        print('plan : write %d rows -> %s (+ the static copy)' % (len(doc['items']),
                                                                  rel(args.out or out_path())))
        print('plan : dry-run - nothing written (the wiki cache included)')
        if args.json:
            print(json.dumps(doc, ensure_ascii=False, separators=(',', ':')))
        return 0

    target = args.out or out_path()
    atomic_write(target, doc)
    static_note = 'static copy skipped (--no-static-copy)'
    if not args.no_static_copy:
        try:
            atomic_write(static_copy_path(), doc)
            static_note = 'static copy -> %s' % rel(static_copy_path())
        except OSError as exc:
            static_note = 'static copy failed: %s' % ascii_s(exc)
    print('store  : %s (%.1f KB) + %s' % (rel(target), os.path.getsize(target) / 1024.0,
                                          static_note))
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
