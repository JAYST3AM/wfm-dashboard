#!/usr/bin/env python3
"""Mod cards - every Warframe mod as a trading card (collection view).

WHAT IT BUILDS
  data/mod_cards.json: one row per mod in the WFCD Mods list, joined to owned copies,
  per-copy mod ranks, and this PC's local price snapshot, so static/cards.html can
  render the collection as trading cards (rarity border, polarity glyph, rank pips,
  xN duplicate badge, price footer, owned vs missing/dimmed states).

INPUTS (only the catalog is fetched; everything else is local and read-only)
  data/wfcd_mods_cache.json  WFCD warframe-items Mods.json, trimmed. --refresh-catalog
                             does ONE GET and rewrites it; otherwise the cache is used.
  data/wfm_items_v2.json     WFM item list -> gameRef -> slug. This is the ONLY
                             reliable uniqueName join: 62 of 1399 mod names do not
                             slugify to their WFM slug ("Hell's Chamber" -> hells_chamber).
  data/owned.json            copies per slug (mod rows = tag 'mod'; arcane rows skipped)
  data/lastData.dec.json     per-copy mod ranks (Upgrades[].UpgradeFingerprint "lvl")
  data/prices.json           sell floor  -> row['wts']   (lowest visible sell listing)
  data/stats.json            48h median  -> row['med48'] (falls back to row['median'])

OUTPUT data/mod_cards.json
  {generated, generated_iso,
   cards:[{slug,name,rarity,type,polarity,base_drain,max_rank,is_prime,owned_copies,
           owned_rank,floor,median,stats_text}],
   summary:{cards,owned,missing,dupes,rarities:{<Rarity>:{total,owned}}},
   sources:{...}, notes:[...]}

RULES
  * owned_rank = the BEST (highest) rank seen in the save fingerprints for any copy of
    the slug; a slug that only has raw (unfused) stack copies is rank 0; when no
    fingerprint can be matched -> null (unknown, never guessed).
  * floor/median are null when the local snapshot has no quote for the slug. Most
    un-owned mods have no quote, so the card shows no price instead of a fake one.
  * stats_text = the mod's in-game card text: EVERY max-rank line (stat modifiers AND
    the effect prose, one per line), cleaned of WFCD markup; falls back to the catalog
    description, then to ''. Clipped to STATS_MAX chars in total.
  * max_rank is the catalog fusionLimit when it is a sane 0..10 rank cap, else the WFM
    maxRank when sane, else null (riven/veiled rows carry nonsense fusionLimits).
  * Deterministic: cards sort owned-first, then rarity desc, then name, then slug, and
    the stamps are reused (payload hash) while the inputs are unchanged -> byte-identical
    output. Atomic write (tmp + os.replace). UTC stamps. Stdlib only, no AI.
  * --selftest runs the whole pipeline on embedded fixtures, offline, and writes nothing.
RUN
  python scripts/mod_cards.py                 # cache-only after the first build
  python scripts/mod_cards.py --refresh-catalog   # ONE GET of the WFCD list
  python scripts/mod_cards.py --no-fetch --top 12  # never touch the network
  python scripts/mod_cards.py --selftest      # offline fixtures, writes nothing

  static/cards.html + static/cards.js render the file as TCG cards. The dashboard server
  serves static/ only, so the page tries /api/feature/cards (route name "cards"), then
  /mod_cards.json, then /data/mod_cards.json, and ?src=<url> pins a source; a build that
  cannot be reached shows the exact URL it tried per route plus a file picker.
"""
import argparse
import collections
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
OUT = os.path.join(DATA, 'mod_cards.json')
CACHE = os.path.join(DATA, 'wfcd_mods_cache.json')
CATALOG_URL = 'https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/Mods.json'
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'
VERSION = 1
STAMP_ISO = '%Y-%m-%dT%H:%M:%SZ'
STATS_MAX = 320          # chars in stats_text (multi-line card text)
MAX_MOD_RANK = 10        # highest legal mod rank in-game (rank pips / sanity cap)
SLEEP = 0.35             # polite pause between market calls (we only ever make one)

# Trimmed catalog fields - everything the card builder needs, nothing else.
CACHE_FIELDS = ('name', 'uniqueName', 'type', 'compatName', 'rarity', 'polarity',
                'baseDrain', 'fusionLimit', 'tradable', 'isPrime', 'isAugment',
                'isExilus', 'isUtility', 'description', 'levelStats')

RARITY_RANK = {'Legendary': 4, 'Rare': 3, 'Uncommon': 2, 'Common': 1, 'Unknown': 0}
RARITY_TAG = {'legendary': 'Legendary', 'rare': 'Rare', 'uncommon': 'Uncommon',
              'common': 'Common'}
NULL_RARITY = 'Unknown'
POLARITIES = ('madurai', 'vazarin', 'naramon', 'zenurik', 'unairu', 'penjaga', 'umbra',
              'universal', 'aura')


# ---------------------------------------------------------------- helpers
def load(name, default):
    """Load data/<name>; return default when missing or unreadable."""
    path = os.path.join(DATA, name)
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        print('WARN cannot read %s: %s' % (name, exc))
        return default


def ascii_s(value):
    """ASCII-only text for stdout."""
    return str(value).encode('ascii', 'replace').decode('ascii')


def atomic_write(path, doc):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, indent=1)
    os.replace(tmp, path)


def iso_utc(epoch=None):
    return time.strftime(STAMP_ISO, time.gmtime(epoch if epoch else time.time()))


def clip(text, limit=STATS_MAX):
    """Strip + collapse whitespace and cut to <= limit chars (never mid-word-ish)."""
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]
    if ' ' in cut[max(0, limit - 24):]:
        cut = cut[:cut.rfind(' ')]
    return cut.rstrip(' ,;:') + '…'


MARKUP_RE = re.compile(r'<[^>]{0,48}>')
NAMED_TOKEN_RE = re.compile(r'<[A-Z_]+(?:_COLOR)?>')


def clean_stat(text):
    """WFCD stat strings carry markup (<DT_..._COLOR>, <LINE_SEPARATOR>) and literal \\n.

    A leading "-" is a REAL negative stat ("-55% Ability Efficiency") and is kept.
    """
    out = str(text or '').replace('\\n', ' ')
    out = NAMED_TOKEN_RE.sub(' ', out)
    out = MARKUP_RE.sub(' ', out)
    out = out.replace('\n', ' ').replace('\r', ' ')
    out = re.sub(r'\s+', ' ', out).strip(' \u00b7,;:')
    return out[:-1].strip() if out.endswith('-') else out


def clean_num(value):
    """int when integral, else 1 decimal (platinum quotes are ints; medians are not)."""
    if value is None:
        return None
    return int(value) if float(value).is_integer() else round(float(value), 1)


def slugify(name):
    """Last-resort slug: lower, non-alphanumerics -> '_' (62 mod names differ from WFM)."""
    return re.sub(r'[^a-z0-9]+', '_', str(name or '').lower()).strip('_')


def norm_polarity(value):
    pol = str(value or '').strip().lower()
    return pol if pol in POLARITIES else (pol or None)


AURA_RE = re.compile(r'^aura\b', re.I)


def norm_type(mod):
    """Catalog type -> card label. 'Warframe Mod' -> 'Warframe'; compat AURA -> 'Aura'."""
    compat = str(mod.get('compatName') or '').strip()
    kind = str(mod.get('type') or '').strip()
    if AURA_RE.match(compat) or kind.lower().startswith('aura'):
        return 'Aura'
    if kind.lower().endswith(' mod'):
        kind = kind[:-4].strip()
    return kind or (compat.title() if compat else 'Mod')


def sane_rank(value):
    """int rank cap in 0..MAX_MOD_RANK, else None (riven rows say 592, parazon say 0)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    ivalue = int(value)
    return ivalue if 0 <= ivalue <= MAX_MOD_RANK and ivalue == value else None


def posnum(value):
    """Positive number or None (a 0p floor / junk never reaches a card)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    try:
        num = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None


def stats_text(mod, limit=STATS_MAX):
    """The mod's in-game card text: EVERY max-rank line, one per line.

    Stat modifiers and the effect prose both belong on the card (e.g. Archon Flow shows
    "+185% Energy Max" AND "Enemies killed by Cold Abilities have 10% chance ..."), so
    nothing after the first line is dropped anymore. Falls back to the catalog
    description, then ''. The whole string stays within `limit` chars.
    """
    levels = mod.get('levelStats')
    if isinstance(levels, list):
        for entry in reversed(levels):
            rows = entry.get('stats') if isinstance(entry, dict) else None
            lines = [line for line in (clean_stat(s) for s in (rows or [])) if line]
            if lines:
                out = []
                budget = limit
                for line in lines:
                    if budget <= 0:
                        break
                    piece = clip(line, budget)
                    out.append(piece)
                    budget -= len(piece) + 1            # +1 for the joining newline
                return '\n'.join(out)
    return clip(clean_stat(mod.get('description')), limit)


# ---------------------------------------------------------------- catalog
def trim_mod(mod):
    """Keep only CACHE_FIELDS (drops ~4MB of drops/wikia/transmute noise)."""
    out = {}
    for key in CACHE_FIELDS:
        value = mod.get(key)
        if key == 'levelStats' and isinstance(value, list):
            rows = []
            for entry in value:
                stats = [str(s) for s in (entry.get('stats') or [])] if isinstance(entry, dict) else []
                if stats:
                    rows.append({'stats': stats})
            value = rows
        if key == 'description':
            value = clip(value, 300)
        if value not in (None, '', [], {}):
            out[key] = value
    return out


def fetch_catalog(url=CATALOG_URL, timeout=90):
    """ONE GET of the WFCD Mods.json list. -> list of raw mod dicts."""
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = json.loads(resp.read().decode('utf-8'))
    mods = raw.get('data') if isinstance(raw, dict) else raw
    if not isinstance(mods, list) or not mods:
        raise RuntimeError('catalog payload was not a non-empty list')
    return mods


def load_catalog(refresh=False, offline=False, log=print):
    """-> (mods, source dict). Cache-first; one fetch on --refresh-catalog or cold start."""
    source = {'source_url': CATALOG_URL, 'cache': CACHE.replace('\\', '/')}
    cached = None
    try:
        with open(CACHE, encoding='utf-8') as fh:
            cached = json.load(fh)
    except (OSError, ValueError):
        cached = None

    def from_cache(doc):
        mods = doc.get('mods') if isinstance(doc, dict) else None
        source.update({'fetched': doc.get('fetched'), 'fetched_iso': doc.get('fetched_iso'),
                       'count': len(mods or []), 'from_cache': True,
                       'cache_fields': doc.get('fields')})
        return mods or []

    if offline:
        if cached is None:
            raise RuntimeError('offline and %s is missing' % os.path.basename(CACHE))
        log('catalog: offline, using %s' % os.path.basename(CACHE))
        return from_cache(cached), source

    if cached is not None and not refresh:
        log('catalog: %s (%s rows)' % (os.path.basename(CACHE), len(cached.get('mods') or [])))
        return from_cache(cached), source

    try:
        log('catalog: fetching %s' % CATALOG_URL)
        raw = fetch_catalog()
    except (urllib.error.URLError, OSError, ValueError, RuntimeError) as exc:
        if cached is None:
            raise RuntimeError('catalog fetch failed and no cache: %s' % exc)
        log('catalog: fetch failed (%s) - using the cache' % exc)
        source['fetch_error'] = str(exc)[:160]
        return from_cache(cached), source

    mods = [m for m in (trim_mod(m) for m in raw) if m.get('name') and m.get('uniqueName')]
    doc = {'source_url': CATALOG_URL, 'fetched': int(time.time()), 'fetched_iso': iso_utc(),
           'count': len(mods), 'fields': list(CACHE_FIELDS), 'raw_count': len(raw), 'mods': mods}
    atomic_write(CACHE, doc)
    log('catalog: %d rows fetched -> %s' % (len(mods), os.path.basename(CACHE)))
    source.update({'fetched': doc['fetched'], 'fetched_iso': doc['fetched_iso'],
                   'count': len(mods), 'from_cache': False, 'cache_fields': list(CACHE_FIELDS)})
    return mods, source


# ---------------------------------------------------------------- joins
def wfm_index(wfm_items):
    """WFM item list -> (gameRef -> slug, name(lower) -> slug, slug -> maxRank).

    Mod-tagged items win; non-mod items only fill gaps. This is the join that keeps
    "Hell's Chamber" on hells_chamber instead of a slugified miss.
    """
    by_ref, by_name, max_rank = {}, {}, {}
    for item in wfm_items or []:
        if not isinstance(item, dict):
            continue
        slug = str(item.get('slug') or '').strip()
        ref = str(item.get('gameRef') or '').strip()
        name = str(((item.get('i18n') or {}).get('en') or {}).get('name') or '').strip()
        if not slug:
            continue
        is_mod = 'mod' in (item.get('tags') or [])
        if ref and (is_mod or ref not in by_ref):
            by_ref[ref] = slug
        if name and (is_mod or name.lower() not in by_name):
            by_name[name.lower()] = slug
        if is_mod and isinstance(item.get('maxRank'), int):
            max_rank[slug] = item['maxRank']
    return by_ref, by_name, max_rank


def wfm_icons(wfm_items):
    """WFM item list -> {slug: icon path} (i18n.en.icon, thumb fallback)."""
    out = {}
    for item in wfm_items or []:
        if not isinstance(item, dict):
            continue
        slug = str(item.get('slug') or '').strip()
        if not slug:
            continue
        en = (item.get('i18n') or {}).get('en') or {}
        icon = en.get('icon') or en.get('thumb')
        if icon:
            out[slug] = str(icon)
    return out


def owned_mods(owned_rows):
    """owned.json mod rows -> {slug: {copies, raw, ranked, name, tags, paths}}.

    Arcane-enhancement rows are skipped: they live in a different catalog (Arcanes.json)
    and this page is mod cards.
    """
    out = {}
    for row in owned_rows or []:
        if not isinstance(row, dict):
            continue
        tags = [str(t) for t in (row.get('tags') or [])]
        if 'mod' not in tags:
            continue
        slug = str(row.get('slug') or '').strip()
        if not slug:
            continue
        entry = out.setdefault(slug, {'copies': 0, 'raw': 0, 'ranked': 0, 'name': '',
                                      'tags': set(), 'paths': []})
        count = int(row.get('count') or 1)
        entry['copies'] += count
        section = str(row.get('section') or '')
        if section == 'RawUpgrades':
            entry['raw'] += count
        elif section == 'Upgrades':
            entry['ranked'] += count
        entry['name'] = entry['name'] or str(row.get('name') or '')
        entry['tags'].update(tags)
        path = str(row.get('path') or '').strip()
        if path and path not in entry['paths']:
            entry['paths'].append(path)
    return out


def ranks_by_path(save):
    """lastData.dec.json -> {upgrade path: Counter(rank -> copies)} from the fingerprints."""
    out = collections.defaultdict(collections.Counter)
    ups = save.get('Upgrades') if isinstance(save, dict) else None
    for row in (ups or []):
        if not isinstance(row, dict):
            continue
        match = re.search(r'"lvl"\s*:\s*(\d+)', str(row.get('UpgradeFingerprint') or ''))
        path = str(row.get('ItemType') or '')
        if match and path:
            out[path][int(match.group(1))] += 1
    return out


def resolve_rank(entry, ranks):
    """Best owned rank for a slug: max fingerprint rank, else 0 for raw-only, else None."""
    found = []
    for path in entry.get('paths') or []:
        counts = ranks.get(path)
        if counts:
            found.extend(counts.keys())
    if found:
        return max(found)
    if entry.get('raw'):
        return 0        # raw (unfused) stack copies are rank 0 by definition
    return None


def rarity_of(mod, owned_entry):
    """Catalog rarity, else the owned row's rarity tag, else None (card shows neutral)."""
    rarity = str(mod.get('rarity') or '').strip()
    if rarity:
        return rarity
    if owned_entry:
        for tag in sorted(owned_entry.get('tags') or []):
            if tag in RARITY_TAG:
                return RARITY_TAG[tag]
    return None


def type_of(mod, owned_entry):
    """Catalog type, else the owned row's weapon-class tag."""
    kind = norm_type(mod) if mod else ''
    if kind:
        return kind
    for tag in ('warframe', 'primary', 'rifle', 'shotgun', 'secondary', 'pistol', 'melee',
                'stance', 'aura', 'sentinel', 'companion', 'archwing', 'necramech',
                'k-drive', 'parazon', 'plexus', 'focus'):
        if owned_entry and tag in (owned_entry.get('tags') or set()):
            return tag.title()
    return ''


def price_of(slug, prices, stats):
    """(floor, median) for a slug: wts floor + 48h median, each None when unquoted."""
    prow = prices.get(slug) if isinstance(prices, dict) else None
    floor = posnum(prow.get('wts')) if isinstance(prow, dict) else None
    srow = stats.get(slug) if isinstance(stats, dict) else None
    median = None
    if isinstance(srow, dict):
        median = posnum(srow.get('med48'))
        if median is None:
            median = posnum(srow.get('median'))
    return clean_num(floor), clean_num(median)


VARIANT_RE = re.compile(r'/(Beginner|Expert|Intermediate)/|(Beginner|Expert|Intermediate)$')


def variant_score(mod, ref):
    """Rank catalog rows that share a mod: prefer complete data, then the canonical path.

    The WFCD list holds Beginner/Expert/Intermediate duplicates of the same mod (the same
    in-game card), so a slug merge must not let '/Rifle/Beginner/...' (rank cap 3) win over
    the plain '/Rifle/...' row (rank cap 5).
    """
    return (1 if mod.get('rarity') else 0,
            1 if mod.get('polarity') else 0,
            0 if VARIANT_RE.search(str(ref or '')) else 1,
            sane_rank(mod.get('fusionLimit')) or 0)


# ---------------------------------------------------------------- build
def build_cards(catalog, wfm_items, owned_rows, save, prices, stats):
    """Pure card build (no I/O). -> (cards, diagnostics)."""
    by_ref, by_name, wfm_rank = wfm_index(wfm_items)
    icons = wfm_icons(wfm_items)
    owned = owned_mods(owned_rows)
    ranks = ranks_by_path(save)

    def icon_url(slug):
        p = icons.get(slug)
        return ('https://warframe.market/static/assets/' + p) if p else None

    # catalog: dedupe by uniqueName (richest/most canonical row wins)
    catalog_by_ref = {}
    duplicates = 0
    for mod in catalog or []:
        ref = str(mod.get('uniqueName') or '').strip()
        if not ref:
            continue
        best = catalog_by_ref.get(ref)
        if best is None:
            catalog_by_ref[ref] = mod
        else:
            duplicates += 1
            if variant_score(mod, ref) > variant_score(best, ref):
                catalog_by_ref[ref] = mod

    cards, by_slug = [], {}
    by_slug_variant = {}
    slug_collisions = 0

    def richness(card):
        """How much a card actually knows - breaks ties when two rows share a WFM slug."""
        known = sum(1 for key in ('rarity', 'polarity', 'base_drain', 'max_rank',
                                  'floor', 'median', 'stats_text') if card.get(key) not in (None, ''))
        return (1 if card['owned_copies'] else 0, known)

    for ref, mod in catalog_by_ref.items():
        name = str(mod.get('name') or '')
        slug = by_ref.get(ref) or by_name.get(name.lower()) or slugify(name)
        entry = owned.get(slug)
        ranks_found = resolve_rank(entry, ranks) if entry else None
        floor, median = price_of(slug, prices, stats)
        cap = sane_rank(mod.get('fusionLimit'))
        if cap is None or VARIANT_RE.search(ref):
            # Junk fusionLimits (rivens) fall back to WFM. Beginner/Intermediate/Expert
            # rows are rank-capped variants of the real card (Quick Thinking ships ONLY
            # as a Beginner row, cap 3, while the real card caps at 5) - take the higher
            # credible cap.
            wfm_cap = sane_rank(wfm_rank.get(slug))
            if wfm_cap is not None:
                cap = wfm_cap if cap is None else max(cap, wfm_cap)
        if isinstance(ranks_found, int):
            if cap is None and ranks_found > 0:
                cap = ranks_found              # the save proves a real cap above 0
            elif cap is not None and ranks_found > cap:
                cap = ranks_found              # a rank above the cap is impossible
        card = {
            'slug': slug,
            'name': name,
            'rarity': rarity_of(mod, entry),
            'type': type_of(mod, entry),
            'polarity': norm_polarity(mod.get('polarity')),
            'base_drain': mod.get('baseDrain') if isinstance(mod.get('baseDrain'), int) else None,
            'max_rank': cap,
            'is_prime': bool(mod.get('isPrime')) or name.startswith('Primed '),
            'owned_copies': int(entry['copies']) if entry else 0,
            'owned_rank': ranks_found,
            'floor': floor,
            'median': median,
            'stats_text': stats_text(mod),
            'icon': icon_url(slug),
        }
        existing = by_slug.get(slug)
        if existing is not None:
            slug_collisions += 1
            if (richness(card), variant_score(mod, ref)) <= (richness(existing), by_slug_variant[slug]):
                continue
        by_slug[slug] = card
        by_slug_variant[slug] = variant_score(mod, ref)

    # owned mods the catalog does not know about (they still must not vanish from the page)
    extras = 0
    for slug, entry in owned.items():
        if slug in by_slug:
            continue
        floor, median = price_of(slug, prices, stats)
        by_slug[slug] = {
            'slug': slug,
            'name': entry['name'] or slug,
            'rarity': rarity_of({}, entry),
            'type': type_of({}, entry),
            'polarity': None,
            'base_drain': None,
            'max_rank': sane_rank(wfm_rank.get(slug)),
            'is_prime': 'prime' in (entry.get('tags') or set()),
            'owned_copies': int(entry['copies']),
            'owned_rank': resolve_rank(entry, ranks),
            'floor': floor,
            'median': median,
            'stats_text': '',
            'icon': icon_url(slug),
        }
        extras += 1

    cards = list(by_slug.values())
    cards.sort(key=lambda c: (0 if c['owned_copies'] else 1,
                              -RARITY_RANK.get(c['rarity'] or NULL_RARITY, 0),
                              c['name'].lower(), c['slug'], str(c['max_rank'])))
    diagnostics = {
        'catalog_rows': len(catalog_by_ref), 'catalog_duplicates': duplicates,
        'slug_collisions': slug_collisions, 'owned_slugs': len(owned),
        'owned_slugs_not_in_catalog': extras,
        'rank_paths_matched': sum(1 for s, e in owned.items() if resolve_rank(e, ranks) is not None),
        'rank_caps_known': sum(1 for c in cards if c['max_rank'] is not None),
        'prime_cards': sum(1 for c in cards if c['is_prime']),
        'quoted': sum(1 for c in cards if c['floor'] is not None),
        'medianised': sum(1 for c in cards if c['median'] is not None),
        'copies_owned': sum(c['owned_copies'] for c in cards),
    }
    return cards, diagnostics


def summarize(cards):
    """{cards, owned, missing, dupes, rarities:{<Rarity>:{total,owned}}}."""
    rarities = {}
    owned = missing = dupes = 0
    for card in cards:
        key = card['rarity'] or NULL_RARITY
        bucket = rarities.setdefault(key, {'total': 0, 'owned': 0})
        bucket['total'] += 1
        if card['owned_copies']:
            owned += 1
            bucket['owned'] += 1
            if card['owned_copies'] > 1:
                dupes += 1
        else:
            missing += 1
    return {'cards': len(cards), 'owned': owned, 'missing': missing, 'dupes': dupes,
            'rarities': {k: rarities[k] for k in sorted(
                rarities, key=lambda r: (-RARITY_RANK.get(r, 0), r))}}


def payload_hash(doc):
    """Stable digest of everything except the stamps (idempotent writes)."""
    body = {k: v for k, v in doc.items() if k not in ('generated', 'generated_iso')}
    blob = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(blob.encode('ascii', 'replace')).hexdigest()


def build_doc(catalog, wfm_items, owned_rows, save, prices, stats, sources, prev=None):
    """Assemble the output document; reuses prev stamps when nothing else changed."""
    cards, diagnostics = build_cards(catalog, wfm_items, owned_rows, save, prices, stats)
    summary = summarize(cards)
    notes = []
    if diagnostics['catalog_duplicates']:
        notes.append('%d duplicate catalog rows collapsed by uniqueName'
                     % diagnostics['catalog_duplicates'])
    if diagnostics['slug_collisions']:
        notes.append('%d catalog rows shared a WFM slug and were merged'
                     % diagnostics['slug_collisions'])
    if diagnostics['owned_slugs_not_in_catalog']:
        notes.append('%d owned mods are absent from the WFCD catalog and carry catalog fields'
                     % diagnostics['owned_slugs_not_in_catalog'])
    no_rarity = sum(1 for c in cards if not c['rarity'])
    if no_rarity:
        notes.append('%d cards have no rarity in the catalog (neutral border)' % no_rarity)
    if summary['missing']:
        notes.append('%d of %d mods are not owned - no local quote for most of them'
                     % (summary['missing'], summary['cards']))
    notes.append('owned_rank = best ranked copy from lastData.dec.json fingerprints; '
                 'raw stack copies count as rank 0; unknown stays null')
    notes.append('stats_text = the mod card text - all max-rank stat + effect lines, '
                 'one per line (catalog levelStats), clipped to %d chars total' % STATS_MAX)

    doc = {
        'generated': int(time.time()),
        'generated_iso': iso_utc(),
        'cards': cards,
        'summary': summary,
        'sources': dict(sources, diagnostics=diagnostics,
                        prices={'file': 'data/prices.json', 'field': 'wts', 'quoted': diagnostics['quoted']},
                        stats={'file': 'data/stats.json', 'field': 'med48'},
                        rank_source='data/lastData.dec.json (Upgrades[].UpgradeFingerprint "lvl")'),
        'notes': notes,
    }
    if isinstance(prev, dict) and prev.get('generated') and payload_hash(prev) == payload_hash(doc):
        doc['generated'], doc['generated_iso'] = prev['generated'], prev.get('generated_iso') or iso_utc()
    return doc


# ---------------------------------------------------------------- selftest
FIXTURE_CATALOG = [
    {'uniqueName': '/Lotus/Upgrades/Mods/Warframe/AvatarHealthMaxMod', 'name': 'Vitality',
     'type': 'Warframe Mod', 'compatName': 'WARFRAME', 'rarity': 'Common', 'polarity': 'vazarin',
     'baseDrain': 2, 'fusionLimit': 10, 'tradable': True,
     'levelStats': [{'stats': ['+9% Health']}, {'stats': ['+100% Health']}]},
    {'uniqueName': '/Lotus/Upgrades/Mods/Melee/WeaponMeleeDamageMod', 'name': 'Pressure Point',
     'type': 'Melee Mod', 'compatName': 'Melee', 'rarity': 'Common', 'polarity': 'madurai',
     'baseDrain': 4, 'fusionLimit': 5, 'tradable': True,
     'levelStats': [{'stats': ['+20% Melee Damage']}, {'stats': ['+120% Melee Damage']}]},
    {'uniqueName': '/Lotus/Upgrades/Mods/Pistol/Expert/WeaponPistolDamageModExpert',
     'name': 'Hornet Strike', 'type': 'Secondary Mod', 'compatName': 'Pistol', 'rarity': 'Rare',
     'polarity': 'madurai', 'baseDrain': 4, 'fusionLimit': 10, 'isPrime': False, 'tradable': True,
     'levelStats': [{'stats': ['+20% Damage']}, {'stats': ['+220% Damage']}]},
    {'uniqueName': '/Lotus/Upgrades/Mods/Shotgun/WeaponFireIterationsMod', 'name': "Hell's Chamber",
     'type': 'Shotgun Mod', 'compatName': 'Shotgun', 'rarity': 'Rare', 'polarity': 'madurai',
     'baseDrain': 4, 'fusionLimit': 5, 'tradable': True, 'levelStats': [{'stats': ['+120% Multishot']}]},
    {'uniqueName': '/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityDurationModExpert',
     'name': 'Primed Continuity', 'type': 'Warframe Mod', 'compatName': 'WARFRAME',
     'rarity': 'Legendary', 'polarity': 'madurai', 'baseDrain': 4, 'fusionLimit': 10,
     'isPrime': True, 'tradable': True,
     'levelStats': [{'stats': ['+30% Ability Duration']}, {'stats': ['+55% Ability Duration']}]},
    {'uniqueName': '/Lotus/Upgrades/Mods/Parazon/WeaponStunChanceMod', 'name': 'Live Wire',
     'type': 'Parazon Mod', 'compatName': 'Parazon', 'rarity': 'Rare', 'polarity': 'naramon',
     'baseDrain': 4, 'fusionLimit': 0, 'tradable': False,
     'description': 'Fatal strikes against an enemy also perform a Codex Scan. ' * 4},
    {'uniqueName': '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponAmmoMaxModExpert',
     'name': 'Mod With No Rarity', 'type': 'Primary Mod', 'compatName': 'Rifle',
     'polarity': None, 'baseDrain': None, 'fusionLimit': 3, 'tradable': True},
    # Beginner duplicate of Vitality: the same in-game card with a lower rank cap. The
    # slug merge must keep the canonical row (rank cap 10), not this one.
    {'uniqueName': '/Lotus/Upgrades/Mods/Warframe/Beginner/AvatarHealthMaxModBeginner',
     'name': 'Vitality', 'type': 'Warframe Mod', 'compatName': 'WARFRAME', 'rarity': 'Common',
     'polarity': 'vazarin', 'baseDrain': 2, 'fusionLimit': 3, 'tradable': True,
     'levelStats': [{'stats': ['+15% Health']}]},
    # markup in levelStats: the FULL card text survives (stat line + effect prose),
    # cleaned of WFCD markup, one line each
    {'uniqueName': '/Lotus/Upgrades/Mods/Warframe/AvatarAbilityDurationArchon',
     'name': 'Archon Continuity', 'type': 'Warframe Mod', 'compatName': 'WARFRAME',
     'rarity': 'Legendary', 'polarity': 'vazarin', 'baseDrain': 6, 'fusionLimit': 10,
     'tradable': True,
     'levelStats': [{'stats': ['+55% Ability Duration',
                               'Abilities that inflict a <DT_TOXIN_COLOR>Toxin Status Effect '
                               'grant +1% Ability Duration <LINE_SEPARATOR>per status type.']}]},
    # riven rows carry a junk fusionLimit (592); the WFM maxRank has to rescue the cap
    {'uniqueName': '/Lotus/Upgrades/Mods/Randomized/PlayerMeleeWeaponRandomModRare',
     'name': 'Melee Riven Mod', 'type': 'Melee Riven Mod', 'compatName': None,
     'rarity': 'Rare', 'polarity': 'madurai', 'baseDrain': 0, 'fusionLimit': 592,
     'tradable': True},
]
FIXTURE_WFM = [
    {'slug': 'vitality', 'gameRef': '/Lotus/Upgrades/Mods/Warframe/AvatarHealthMaxMod',
     'maxRank': 10, 'tags': ['mod', 'common', 'warframe'], 'i18n': {'en': {'name': 'Vitality'}}},
    {'slug': 'pressure_point', 'gameRef': '/Lotus/Upgrades/Mods/Melee/WeaponMeleeDamageMod',
     'maxRank': 5, 'tags': ['mod', 'common', 'melee'], 'i18n': {'en': {'name': 'Pressure Point'}}},
    {'slug': 'hornet_strike', 'gameRef': '/Lotus/Upgrades/Mods/Pistol/Expert/WeaponPistolDamageModExpert',
     'maxRank': 10, 'tags': ['mod', 'rare', 'pistol'], 'i18n': {'en': {'name': 'Hornet Strike'}}},
    # note the slug: "Hell's Chamber" must NOT be slugified ("hell_s_chamber")
    {'slug': 'hells_chamber', 'gameRef': '/Lotus/Upgrades/Mods/Shotgun/WeaponFireIterationsMod',
     'maxRank': 5, 'tags': ['mod', 'rare', 'shotgun'], 'i18n': {'en': {'name': "Hell's Chamber"}}},
    {'slug': 'primed_continuity', 'gameRef': '/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityDurationModExpert',
     'maxRank': 10, 'tags': ['mod', 'legendary', 'warframe'], 'i18n': {'en': {'name': 'Primed Continuity'}}},
    {'slug': 'live_wire', 'gameRef': '/Lotus/Upgrades/Mods/Parazon/WeaponStunChanceMod',
     'maxRank': 0, 'tags': ['mod', 'rare', 'parazon'], 'i18n': {'en': {'name': 'Live Wire'}}},
    {'slug': 'extra_owned_mod', 'gameRef': '/Lotus/Upgrades/Mods/Melee/NotInCatalog',
     'maxRank': 5, 'tags': ['mod', 'uncommon', 'melee'], 'i18n': {'en': {'name': 'Extra Owned Mod'}}},
    {'slug': 'melee_riven_mod_(veiled)',
     'gameRef': '/Lotus/Upgrades/Mods/Randomized/PlayerMeleeWeaponRandomModRare',
     'maxRank': 8, 'tags': ['mod', 'rare', 'melee'],
     'i18n': {'en': {'name': 'Melee Riven Mod'}}},
]
FIXTURE_OWNED = [
    {'slug': 'vitality', 'name': 'Vitality', 'count': 12, 'tags': ['mod', 'common', 'warframe'],
     'section': 'RawUpgrades', 'path': '/Lotus/Upgrades/Mods/Warframe/AvatarHealthMaxMod'},
    {'slug': 'vitality', 'name': 'Vitality', 'count': 1, 'tags': ['mod', 'common', 'warframe'],
     'section': 'Upgrades', 'path': '/Lotus/Upgrades/Mods/Warframe/AvatarHealthMaxMod'},
    {'slug': 'pressure_point', 'name': 'Pressure Point', 'count': 1, 'tags': ['mod', 'common', 'melee'],
     'section': 'Upgrades', 'path': '/Lotus/Upgrades/Mods/Melee/WeaponMeleeDamageMod'},
    {'slug': 'primed_continuity', 'name': 'Primed Continuity', 'count': 2,
     'tags': ['mod', 'legendary', 'warframe'], 'section': 'Upgrades',
     'path': '/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityDurationModExpert'},
    {'slug': 'extra_owned_mod', 'name': 'Extra Owned Mod', 'count': 1,
     'tags': ['mod', 'uncommon', 'melee'], 'section': 'RawUpgrades',
     'path': '/Lotus/Upgrades/Mods/Melee/NotInCatalog'},
    # arcane row: must be ignored by the mod build
    {'slug': 'arcane_energize', 'name': 'Arcane Energize', 'count': 3,
     'tags': ['arcane_enhancement', 'rare'], 'section': 'RawUpgrades',
     'path': '/Lotus/Upgrades/CosmeticEnhancers/Utility/EnergyPickup'},
]
FIXTURE_SAVE = {'Upgrades': [
    {'ItemType': '/Lotus/Upgrades/Mods/Warframe/AvatarHealthMaxMod', 'UpgradeFingerprint': '{"lvl":10}'},
    {'ItemType': '/Lotus/Upgrades/Mods/Melee/WeaponMeleeDamageMod', 'UpgradeFingerprint': '{"lvl":3}'},
    {'ItemType': '/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityDurationModExpert',
     'UpgradeFingerprint': '{"lvl":7}'},
    {'ItemType': '/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityDurationModExpert',
     'UpgradeFingerprint': '{"lvl":2}'},
    {'ItemType': '/Lotus/Upgrades/Mods/Melee/NotInCatalog', 'UpgradeFingerprint': 'no lvl here'},
]}
FIXTURE_PRICES = {'vitality': {'wts': 2, 'wtb': None}, 'pressure_point': {'wts': 1},
                  'primed_continuity': {'wts': 85, 'wtb': 60}, 'hells_chamber': {'wts': None},
                  'extra_owned_mod': {'wts': 9}}
FIXTURE_STATS = {'vitality': {'med48': 2.5}, 'primed_continuity': {'med48': 85.54},
                 'pressure_point': {'median': 1.5}, 'extra_owned_mod': {'med48': 0}}


def selftest():
    """Offline checks on embedded fixtures - no network, no data/ reads, no writes."""
    checks, fails = [], []

    def chk(name, got, want):
        if got != want:
            fails.append('%s: got %r, want %r' % (name, got, want))
        checks.append(name)

    doc = build_doc(FIXTURE_CATALOG, FIXTURE_WFM, FIXTURE_OWNED, FIXTURE_SAVE,
                    FIXTURE_PRICES, FIXTURE_STATS, {'catalog': {'source_url': 'fixture'}})
    cards = {c['slug']: c for c in doc['cards']}
    keys = {'slug', 'name', 'rarity', 'type', 'polarity', 'base_drain', 'max_rank', 'is_prime',
            'owned_copies', 'owned_rank', 'floor', 'median', 'stats_text', 'icon'}

    chk('top-level keys', set(doc), {'generated', 'generated_iso', 'cards', 'summary', 'sources', 'notes'})
    chk('card keys', set(cards['vitality']), keys)
    chk('summary keys', set(doc['summary']), {'cards', 'owned', 'missing', 'dupes', 'rarities'})
    chk('one card per catalog mod + owned extras', doc['summary']['cards'], 10)
    chk('catalog mods present', sorted(cards), sorted(
        ['vitality', 'pressure_point', 'hornet_strike', 'hells_chamber', 'primed_continuity',
         'live_wire', 'mod_with_no_rarity', 'extra_owned_mod', 'archon_continuity',
         'melee_riven_mod_(veiled)']))

    chk('vitality rarity/type/polarity', (cards['vitality']['rarity'], cards['vitality']['type'],
                                          cards['vitality']['polarity']), ('Common', 'Warframe', 'vazarin'))
    chk('vitality copies (raw 12 + ranked 1)', cards['vitality']['owned_copies'], 13)
    chk('vitality best rank wins', cards['vitality']['owned_rank'], 10)
    chk('pressure point rank', cards['pressure_point']['owned_rank'], 3)
    chk('primed continuity best of 7/2', cards['primed_continuity']['owned_rank'], 7)
    chk('primed continuity is_prime', cards['primed_continuity']['is_prime'], True)
    chk('legendary rarity kept', cards['primed_continuity']['rarity'], 'Legendary')
    chk('stats_text uses MAX rank line', cards['primed_continuity']['stats_text'], '+55% Ability Duration')
    chk('stats_text multi/pipe kept short', len(cards['pressure_point']['stats_text']) <= STATS_MAX,
        True)
    chk('missing mod has 0 copies / null rank', (cards['hornet_strike']['owned_copies'],
                                                 cards['hornet_strike']['owned_rank']), (0, None))
    chk('missing mod no quote -> null floor/median',
        (cards['hornet_strike']['floor'], cards['hornet_strike']['median']), (None, None))
    chk('slugified-name trap avoided', 'hells_chamber' in cards and 'hell_s_chamber' not in cards, True)
    chk('primed name -> is_prime even when unflagged', cards['primed_continuity']['is_prime'], True)
    chk('no rarity -> null + Unknown bucket', (cards['mod_with_no_rarity']['rarity'],
                                               'Unknown' in doc['summary']['rarities']), (None, True))
    chk('riven-style fusionLimit 0 -> 0 cap', cards['live_wire']['max_rank'], 0)
    chk('parazon description fallback bounded + clip adds ellipsis',
        (len(cards['live_wire']['stats_text']) <= STATS_MAX,
         clip(cards['live_wire']['stats_text'], 40).endswith('…')), (True, True))
    chk('raw-only extra mod -> rank 0', cards['extra_owned_mod']['owned_rank'], 0)
    chk('extra owned mod keeps price', cards['extra_owned_mod']['floor'], 9.0)
    chk('zero median dropped by posnum', cards['extra_owned_mod']['median'], None)
    chk('stats fallback to legacy median field', cards['pressure_point']['median'], 1.5)
    chk('floor from wts', cards['primed_continuity']['floor'], 85.0)
    chk('null wts -> null floor', cards['hells_chamber']['floor'], None)
    chk('arcanes excluded from the mod build', 'arcane_energize' not in cards, True)

    chk('summary.cards/owned/missing/dupes',
        (doc['summary']['cards'], doc['summary']['owned'], doc['summary']['missing'], doc['summary']['dupes']),
        (10, 4, 6, 2))
    chk('summary.copies (from cards)', sum(c['owned_copies'] for c in doc['cards']), 17)
    chk('summary.rarities buckets', doc['summary']['rarities'].get('Common'),
        {'total': 2, 'owned': 2})
    chk('summary rarity order (Legendary first)',
        list(doc['summary']['rarities'])[0], 'Legendary')

    # Beginner/Expert duplicates collapse onto one card, and the CANONICAL row wins
    chk('beginner variant did not win the merge', cards['vitality']['max_rank'], 10)
    chk('beginner variant did not win the stat line', cards['vitality']['stats_text'], '+100% Health')
    chk('markup stripped, full card text kept', cards['archon_continuity']['stats_text'],
        '+55% Ability Duration\nAbilities that inflict a Toxin Status Effect '
        'grant +1% Ability Duration per status type.')
    chk('floors are clean ints, medians 1 decimal',
        (cards['vitality']['floor'], cards['primed_continuity']['median']), (2, 85.5))
    chk('junk fusionLimit rescued by the WFM maxRank',
        cards['melee_riven_mod_(veiled)']['max_rank'], 8)
    chk('owned-only extra card takes its WFM cap', cards['extra_owned_mod']['max_rank'], 5)
    chk('clean_stat drops colour tokens',
        clean_stat('+60% <DT_PUNCTURE_COLOR>Puncture'), '+60% Puncture')
    literal_newline = chr(92) + 'n<LINE_SEPARATOR>' + chr(92) + 'n'
    chk('clean_stat drops literal separators', clean_stat('a' + literal_newline + 'b'), 'a b')
    chk('deterministic sort: owned first', [c['owned_copies'] > 0 for c in doc['cards']][:4],
        [True, True, True, True])
    chk('notes mention rank provenance',
        any('owned_rank' in n for n in doc['notes']), True)

    # idempotency: same payload -> stamps reused; a real change -> fresh stamp
    again = build_doc(FIXTURE_CATALOG, FIXTURE_WFM, FIXTURE_OWNED, FIXTURE_SAVE,
                      FIXTURE_PRICES, FIXTURE_STATS, {'catalog': {'source_url': 'fixture'}}, prev=doc)
    chk('unchanged payload reuses the stamp', again['generated'], doc['generated'])
    doc['generated'] = 1
    doc['generated_iso'] = '1970-01-01T00:00:00Z'
    changed = build_doc(FIXTURE_CATALOG, FIXTURE_WFM, FIXTURE_OWNED, FIXTURE_SAVE,
                        FIXTURE_PRICES, FIXTURE_STATS, {'catalog': {'source_url': 'fixture'}},
                        prev=dict(doc, cards=doc['cards'][:1], summary={'cards': 1}))
    chk('changed payload gets a fresh stamp', changed['generated'] != 1, True)

    # helper-level checks
    chk('clip cuts long text', len(clip('x' * 400)) <= STATS_MAX, True)
    chk('clip keeps short text', clip(' +55% Ability Duration '), '+55% Ability Duration')
    chk('slugify fallback', slugify("Hell's Chamber"), 'hell_s_chamber')
    chk('norm_type strips the Mod suffix', norm_type({'type': 'Stance Mod', 'compatName': 'Melee'}), 'Stance')
    chk('norm_type aura override', norm_type({'type': 'Warframe Mod', 'compatName': 'AURA'}), 'Aura')
    chk('sane_rank rejects 592', sane_rank(592), None)
    chk('sane_rank keeps 0', sane_rank(0), 0)
    chk('payload_hash ignores stamps',
        payload_hash({'generated': 1, 'cards': []}) == payload_hash({'generated': 999, 'cards': []}), True)

    bad = len(fails)
    print('selftest: %s %d/%d' % ('FAIL' if bad else 'PASS', len(checks) - bad, len(checks)))
    for line in fails:
        print('  FAIL %s' % line)
    return 1 if bad else 0


# ---------------------------------------------------------------- main
def main(argv=None):
    parser = argparse.ArgumentParser(description='Build data/mod_cards.json (mod cards + collection state).')
    parser.add_argument('--selftest', action='store_true', help='offline fixture checks, writes nothing')
    parser.add_argument('--refresh-catalog', action='store_true',
                        help='ONE GET of the WFCD Mods.json and rewrite the cache')
    parser.add_argument('--no-fetch', action='store_true', dest='no_fetch',
                        help='never touch the network (cache only)')
    parser.add_argument('--top', type=int, default=8, help='how many sample cards to print (default 8)')
    parser.add_argument('--quiet', action='store_true', help='summary lines only')
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    try:
        catalog, catalog_source = load_catalog(refresh=args.refresh_catalog,
                                               offline=args.no_fetch,
                                               log=(lambda *a: None) if args.quiet else print)
    except RuntimeError as exc:
        print('ERROR %s' % exc)
        return 2

    wfm_items = (load('wfm_items_v2.json', {}) or {}).get('data') or []
    owned_rows = load('owned.json', []) or []
    save = load('lastData.dec.json', {}) or {}
    prices = load('prices.json', {}) or {}
    stats = load('stats.json', {}) or {}

    try:
        with open(OUT, encoding='utf-8') as fh:
            prev = json.load(fh)
    except (OSError, ValueError):
        prev = None

    sources = {
        'catalog': catalog_source,
        'wfm_items': {'file': 'data/wfm_items_v2.json', 'items': len(wfm_items)},
        'owned': {'file': 'data/owned.json', 'rows': len(owned_rows)},
        'ranks': {'file': 'data/lastData.dec.json',
                  'upgrades': len((save.get('Upgrades') or []) if isinstance(save, dict) else [])},
    }
    doc = build_doc(catalog, wfm_items, owned_rows, save, prices, stats, sources, prev=prev)
    atomic_write(OUT, doc)

    if not args.quiet:
        print('catalog source: %s (%s rows)' % (catalog_source.get('source_url'),
                                                catalog_source.get('count')))
    print('mod cards -> %s' % ascii_s(OUT.replace('\\', '/')))
    print('  generated %s (utc)  id=%s' % (doc['generated_iso'], doc['generated']))
    summary = doc['summary']
    copies = sum(c['owned_copies'] for c in doc['cards'])
    print('  cards %d | owned %d | missing %d | dupes %d | copies owned %d'
          % (summary['cards'], summary['owned'], summary['missing'], summary['dupes'], copies))
    rar = ' '.join('%s %d/%d' % (k, v['owned'], v['total']) for k, v in summary['rarities'].items())
    print('  rarities (owned/total): %s' % rar)
    for card in doc['cards'][:max(0, args.top)]:
        print('  %-34s %-9s %-12s copies %-3s rank %-4s floor %-6s med %-7s %s'
              % (ascii_s(card['name'])[:34], ascii_s(card['rarity']), ascii_s(card['type'])[:12],
                 card['owned_copies'], card['owned_rank'] if card['owned_rank'] is not None else '-',
                 card['floor'] if card['floor'] is not None else '-',
                 card['median'] if card['median'] is not None else '-',
                 ascii_s(card['stats_text'])[:44]))
    for note in doc['notes']:
        print('  note: %s' % note)
    return 0


if __name__ == '__main__':
    if '--selftest' in sys.argv[1:]:
        sys.exit(selftest())
    sys.exit(main())
