"""Obtain index - "how do I get this item?" from public drop tables.

Jay (2026-09-26): *"in collection, each item ie ash needs to show how to get it."*

Sources (public JSON, cached under data/dropdata/ so rebuilds work offline):

  WFCD/warframe-drop-data (gh-pages)
    relics.json              relic -> rewards              (prime parts)
    missionRewards.json      planet -> node -> rotation     (everything farmable)
    blueprintLocations.json  item -> enemy blueprint drops
    enemyBlueprintTables.json enemy -> items/mods
    sortieRewards.json, syndicates.json, cetusBountyRewards.json, deimosRewards.json,
    solarisBountyRewards.json, zarimanRewards.json, entratiLabRewards.json,
    hexRewards.json, keyRewards.json, transientRewards.json   (extra sources, soft-fail)

  WFCD/warframe-items
    Relics.json              vaulted flag per relic
    Warframes.json, Primary.json, ...   marketCost / bpCost / tradable per item

Output: data/obtain_index.json - one record per drop-table item name:

  {"name": "Ash Systems Blueprint",
   "relics":   [{"tier": "Axi", "relic": "Axi A1", "rarity": "Rare", "chance": 2, "vaulted": false}],
   "missions": [{"planet": "Venus", "node": "Luckless Expanse", "mode": "Survival",
                 "rotation": "A", "chance": 13.33, "rarity": "Uncommon", "path": "Venus/Luckless Expanse"}],
   "enemies":  [{"enemy": "Demolisher Thrasher", "chance": 20, "rarity": "Uncommon"}],
   "other":    [{"source": "Sortie", "detail": "Sortie Rewards", "chance": 2.5, "rarity": "Rare"}],
   "market":   {"plat": 375, "credits": 35000},
   "tradable": true}

Everything is a recorded fact from those files - nothing is inferred or guessed. A name the
tables do not mention simply gets no record, and the consumer says so out loud.

Wiki pass - "how do I get this?" for the items the drop tables are silent on
  The wiki page is resolved from the catalogue name (as written, then all-caps form, then
  first-letter capitalisation, then underscores for spaces, then the WFCD row's own wikiaUrl
  title, then the wiki search API - the first hit sharing a distinctive word), and the page is
  asked for its own answer: the Acquisition section when it has one (or the {{Acquisition|...}}
  template many weapon pages use instead), otherwise the first sentence that names a real source
  (Market, Research, Dojo, Quest, Syndicate, Standing, Bounty, Invasion, Sortie, Event, Relic,
  Vault, a syndicate vendor) and says the item is actually acquired, quoted verbatim. Pages whose
  text lives on a subpage ({{CompanionPage}} / {{ArchwingPage}} shells) fall through to
  <title>/Main. Anything still unanswered gets the WFCD row's `introduced` update
  ("Added in Update 10.0 (2013-09-13)", url = the wiki update page) - real data, never a guess.
  Each line keeps its provenance (title, resolution step, section, url) under `acq`, and lands
  in the record's `other` bucket so the collection hover card renders it. Pages and search
  hits are cached under data/dropdata/wiki/, so re-runs are offline and idempotent.

WFM_DATA_DIR overrides the data directory (drop tables, wiki cache, output) - for dry runs.

Usage
  python scripts/obtain_index.py                # fetch (cached) + build + write
  python scripts/obtain_index.py --offline      # never touch the network
  python scripts/obtain_index.py --selftest     # offline logic checks
  python scripts/obtain_index.py --report       # coverage summary only, no write
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.environ.get('WFM_DATA_DIR') or os.path.join(ROOT, 'data')
DROP_DIR = os.path.join(DATA, 'dropdata')
DROP_BASE = 'https://raw.githubusercontent.com/WFCD/warframe-drop-data/gh-pages/data/'
ITEM_BASE = 'https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/'
UA = {'User-Agent': 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'}
TIMEOUT = 300
SCHEMA = 1

DROP_FILES = [
    ('relics.json', True),
    ('missionRewards.json', True),
    ('blueprintLocations.json', True),
    ('enemyBlueprintTables.json', True),
    ('sortieRewards.json', False),
    ('syndicates.json', False),
    ('cetusBountyRewards.json', False),
    ('deimosRewards.json', False),
    ('solarisBountyRewards.json', False),
    ('zarimanRewards.json', False),
    ('entratiLabRewards.json', False),
    ('hexRewards.json', False),
    ('keyRewards.json', False),
    ('transientRewards.json', False),
]
ITEM_FILES = ['Warframes', 'Primary', 'Secondary', 'Melee', 'Arch-Gun', 'Arch-Melee', 'Archwing',
              'Sentinels', 'SentinelWeapons', 'Pets', 'Misc']
# mission rows kept per item, best chance first (keeps the payload small and readable)
MAX_MISSIONS = 6
MAX_RELICS = 8
MAX_ENEMIES = 4
MAX_OTHER = 4


def out_path():
    return os.path.join(DATA, 'obtain_index.json')


def jload(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def atomic_write(path, doc):
    tmp = path + '.tmp'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)


def fetch_cached(name, base, offline=False, soft=False):
    """Return (doc, meta). Cached under DROP_DIR/items - refetched only when missing."""
    sub = 'items' if base is ITEM_BASE else ''
    path = os.path.join(DROP_DIR, sub, name) if sub else os.path.join(DROP_DIR, name)
    if os.path.exists(path):
        doc = jload(path)
        if doc is not None:
            return doc, {'cached': True, 'path': os.path.relpath(path, ROOT),
                         'bytes': os.path.getsize(path)}
    if offline:
        return None, {'cached': False, 'error': 'offline and not cached'}
    try:
        raw = urllib.request.urlopen(urllib.request.Request(base + name, headers=UA),
                                     timeout=TIMEOUT).read()
    except Exception as exc:
        if soft:
            return None, {'cached': False, 'error': '%s: %s' % (type(exc).__name__, exc)}
        raise
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(raw)
    try:
        return json.loads(raw), {'cached': False, 'path': os.path.relpath(path, ROOT), 'bytes': len(raw)}
    except Exception as exc:
        if soft:
            return None, {'cached': False, 'error': 'bad json: %s' % exc}
        raise


# ------------------------------------------------------------------ walkers
def walk_rewards(node, chain=()):
    """Yield (context chain, row) for every {'itemName': ...} row anywhere in a drop file."""
    if isinstance(node, dict):
        if 'itemName' in node and isinstance(node.get('itemName'), str):
            yield chain, node
            return
        for key, val in node.items():
            yield from walk_rewards(val, chain + (str(key),))
    elif isinstance(node, list):
        for val in node:
            yield from walk_rewards(val, chain)


def rotation_of(chain):
    for part in reversed(chain):
        if part in ('A', 'B', 'C'):
            return part
    return None


def clean_chain(chain):
    """['Venus', 'Luckless Expanse', 'rewards', 'A'] -> ('Venus/Luckless Expanse', 'A')"""
    keep = [p for p in chain if p not in ('rewards', 'missionRewards', 'items', 'mods')]
    return '/'.join(keep[1:]) or '/'.join(keep)


# ------------------------------------------------------------------ source indexes
def vaulted_map(relics_doc):
    """warframe-items Relics.json -> {'Axi A1': True/False} (any state vaulted counts)."""
    out = {}
    for row in (relics_doc or []):
        if not isinstance(row, dict):
            continue
        name = row.get('name') or ''
        parts = name.split()
        if len(parts) >= 3:
            key = ' '.join(parts[:2])
            flag = bool(row.get('vaulted'))
            out[key] = out.get(key, False) or flag
    return out


def market_map(item_docs):
    """WFCD item rows -> {name: {'plat', 'credits', 'tradable', 'research', 'wiki'}}.

    `research` = the item's uniqueName says ClanTech (Dojo research lab); `wiki` = the WFCD
    row's own wikiaUrl so a record-less item still gives the user somewhere to look."""
    out = {}
    for _fname, rows in item_docs.items():
        for row in (rows or []):
            if not isinstance(row, dict) or not row.get('name'):
                continue
            uniq = row.get('uniqueName') or ''
            plat = row.get('marketCost')
            credits = row.get('bpCost')
            research = 'ClanTech' in uniq or '/Clan/' in uniq
            wiki = row.get('wikiaUrl')
            if plat is None and credits is None and not research and not wiki:
                continue
            out[row['name']] = {'plat': plat, 'credits': credits,
                                'tradable': row.get('tradable') is True,
                                'research': research, 'wiki': wiki}
    return out


PART_TYPES = ('Amp', 'K-Drive Component')


def part_rows(item_docs):
    """{name: row} for Amp / K-Drive component rows - parts the market flags never cover."""
    out = {}
    for rows in item_docs.values():
        for row in (rows or []):
            if isinstance(row, dict) and row.get('name') and row.get('type') in PART_TYPES:
                out[row['name']] = row
    return out


def index_relic_rewards(relics_doc, vaulted):
    """drop-data relics.json -> {itemName: [relic rows]} (Intact chance, deduped by relic)."""
    out = {}
    rows = relics_doc.get('relics') if isinstance(relics_doc, dict) else relics_doc
    for entry in (rows or []):
        if not isinstance(entry, dict):
            continue
        tier, name, state = entry.get('tier'), entry.get('relicName'), entry.get('state')
        if not tier or not name or state != 'Intact':
            continue
        relic = '%s %s' % (tier, name)
        is_vaulted = vaulted.get(relic)
        for reward in (entry.get('rewards') or []):
            item = reward.get('itemName')
            if not item:
                continue
            bucket = out.setdefault(item, [])
            for existing in bucket:                      # one row per relic, best (lowest) chance
                if existing['relic'] == relic:
                    break
            else:
                bucket.append({'tier': tier, 'relic': relic, 'rarity': reward.get('rarity'),
                               'chance': reward.get('chance'),
                               'vaulted': bool(is_vaulted) if is_vaulted is not None else None})
    return out


def index_missions(missions_doc):
    """missionRewards.json -> {itemName: [mission rows]}; every row traces to planet/node/rotation."""
    out = {}
    root = missions_doc.get('missionRewards') if isinstance(missions_doc, dict) else missions_doc
    for chain, row in walk_rewards(root):
        item = row['itemName']
        planet = chain[0] if chain else None
        node = chain[1] if len(chain) > 1 else None
        mode = None
        # mission nodes carry {'gameMode': ..., 'rewards': {...}} next to the node name
        cur = root
        for part in chain[:2]:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
        if isinstance(cur, dict):
            mode = cur.get('gameMode')
        rec = {'planet': planet, 'node': node, 'mode': mode, 'rotation': rotation_of(chain),
               'chance': row.get('chance'), 'rarity': row.get('rarity'),
               'path': clean_chain(chain)}
        out.setdefault(item, []).append(rec)
    return out


def index_enemies(blueprint_doc, enemy_doc):
    """blueprintLocations.json + enemyBlueprintTables.json -> {itemName: [enemy rows]}."""
    out = {}

    def add(item, enemy, chance, rarity):
        if not item or not enemy:
            return
        out.setdefault(item, []).append({'enemy': enemy, 'chance': chance, 'rarity': rarity})

    rows = blueprint_doc.get('blueprintLocations') if isinstance(blueprint_doc, dict) else blueprint_doc
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        for enemy in (row.get('enemies') or []):
            add(row.get('itemName'), enemy.get('enemyName'),
                enemy.get('enemyBlueprintDropChance'), enemy.get('rarity'))
    rows = enemy_doc.get('enemyBlueprintTables') if isinstance(enemy_doc, dict) else enemy_doc
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        for item in (row.get('items') or []):
            add(item.get('itemName'), row.get('enemyName'), item.get('chance'), item.get('rarity'))
        for mod in (row.get('mods') or []):
            add(mod.get('modName'), row.get('enemyName'), mod.get('chance'), mod.get('rarity'))
    return out


def index_other(label, doc):
    """Generic extra source (sortie / syndicate / bounty tables) -> {itemName: [rows]}.

    The context chain of each row is kept as the human label, so a consumer can always
    show where the number came from."""
    out = {}
    for chain, row in walk_rewards(doc):
        item = row['itemName']
        detail = clean_chain(chain) or label
        out.setdefault(item, []).append({'source': label, 'detail': detail,
                                        'chance': row.get('chance'), 'rarity': row.get('rarity')})
    return out


# ------------------------------------------------------------------ build
def rank_missions(rows):
    """Best chance first; equal chances keep stable input order."""
    return sorted(rows, key=lambda r: (-(r.get('chance') or 0), r.get('path') or ''))


def build(offline=False):
    sources, notes = {}, []
    drop_docs = {}
    for name, required in DROP_FILES:
        doc, meta = fetch_cached(name, DROP_BASE, offline=offline, soft=not required)
        sources['dropdata/' + name] = meta
        if doc is None:
            notes.append('drop-data file unavailable: %s' % name)
            continue
        drop_docs[name] = doc

    item_docs = {}
    for name in ITEM_FILES:
        doc, meta = fetch_cached(name + '.json', ITEM_BASE, offline=offline, soft=True)
        sources['items/' + name + '.json'] = meta
        if doc is not None:
            item_docs[name] = doc

    relics_doc, meta = fetch_cached('Relics.json', ITEM_BASE, offline=offline, soft=True)
    sources['items/Relics.json'] = meta
    vaulted = vaulted_map(relics_doc)
    market = market_map(item_docs)

    items = {}
    for item, rows in index_relic_rewards(drop_docs.get('relics.json') or {}, vaulted).items():
        rows = sorted(rows, key=lambda r: (r.get('rarity') or '', r.get('relic') or ''))
        items.setdefault(item, {})['relics'] = rows[:MAX_RELICS]
    for item, rows in index_missions(drop_docs.get('missionRewards.json') or {}).items():
        items.setdefault(item, {})['missions'] = rank_missions(rows)[:MAX_MISSIONS]
    if 'blueprintLocations.json' in drop_docs or 'enemyBlueprintTables.json' in drop_docs:
        for item, rows in index_enemies(drop_docs.get('blueprintLocations.json') or {},
                                        drop_docs.get('enemyBlueprintTables.json') or {}).items():
            rows = sorted(rows, key=lambda r: -(r.get('chance') or 0))
            items.setdefault(item, {})['enemies'] = rows[:MAX_ENEMIES]
    for fname, label in (('sortieRewards.json', 'Sortie'), ('syndicates.json', 'Syndicate'),
                         ('cetusBountyRewards.json', 'Cetus bounty'), ('deimosRewards.json', 'Deimos'),
                         ('solarisBountyRewards.json', 'Solaris'), ('zarimanRewards.json', 'Zariman'),
                         ('entratiLabRewards.json', 'Entrati Lab'), ('hexRewards.json', 'Hex'),
                         ('keyRewards.json', 'Key'), ('transientRewards.json', 'Transient')):
        if fname not in drop_docs:
            continue
        for item, rows in index_other(label, drop_docs[fname]).items():
            bucket = items.setdefault(item, {}).setdefault('other', [])
            for row in rows:
                if len(bucket) >= MAX_OTHER:
                    break
                if row not in bucket:
                    bucket.append(row)

    for item, doc in items.items():
        doc['name'] = item
        mkt = market.get(item)
        if mkt:
            if mkt['plat'] is not None or mkt['credits'] is not None:
                doc['market'] = {'plat': mkt['plat'], 'credits': mkt['credits']}
            doc['tradable'] = bool(mkt['tradable'])
            if mkt['research']:
                doc['research'] = True
            if mkt['wiki']:
                doc['wiki'] = mkt['wiki']

    # market/dojo-only items: no drop-table row, but the game itself sells them - still a fact
    for name, mkt in market.items():
        if name in items:
            continue
        if mkt['plat'] is None and mkt['credits'] is None and not mkt['research'] and not mkt['wiki']:
            continue
        doc = {'name': name, 'tradable': bool(mkt['tradable'])}
        if mkt['plat'] is not None or mkt['credits'] is not None:
            doc['market'] = {'plat': mkt['plat'], 'credits': mkt['credits']}
        if mkt['research']:
            doc['research'] = True
        if mkt['wiki']:
            doc['wiki'] = mkt['wiki']
        items[name] = doc

    # Amp / K-Drive components: parts the game hands out as blueprints rather than as market
    # items, so the WFCD rows carry no market/wiki flags - they still deserve a record and answer.
    for name, row in part_rows(item_docs).items():
        if name in items:
            continue
        doc = {'name': name, 'tradable': bool(row.get('tradable'))}
        if row.get('wikiaUrl'):
            doc['wiki'] = row['wikiaUrl']
        items[name] = doc

    counts = {
        'items': len(items),
        'with_relics': sum(1 for d in items.values() if d.get('relics')),
        'with_missions': sum(1 for d in items.values() if d.get('missions')),
        'with_enemies': sum(1 for d in items.values() if d.get('enemies')),
        'with_other': sum(1 for d in items.values() if d.get('other')),
        'with_market': sum(1 for d in items.values() if d.get('market')),
        'with_research': sum(1 for d in items.values() if d.get('research')),
        'with_wiki': sum(1 for d in items.values() if d.get('wiki')),
        'vaulted_relics': len({r['relic'] for d in items.values() for r in d.get('relics') or []
                               if r.get('vaulted')}),
    }
    return {
        'schema': SCHEMA,
        'generated': int(time.time()),
        'generated_iso': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'sources': sources,
        'counts': counts,
        'notes': notes,
        'items': items,
        # internal: {name: WFCD `introduced` row}, the wiki pass's last-resort line. main() pops
        # it before the write - it is a lookup table, not part of the published payload.
        '_introduced': introduced_map(item_docs),
    }


def coverage(doc, collection=None):
    """How many collection items actually get a fact-bearing record (and how many stay unknown)."""
    index = doc['items']
    if collection is None:
        collection = jload(os.path.join(DATA, 'collection_log.json'), {})
    cats = collection.get('categories') or []
    stats = {'collection_items': 0, 'with_some_record': 0, 'wiki_only': 0}
    misses = []
    for cat in cats:
        for it in (cat.get('items') or []):
            name = it.get('name')
            stats['collection_items'] += 1
            hits = [index[k] for k in index if k == name or k.startswith(name + ' ')]
            facts = [h for h in hits if any(h.get(f) for f in
                                            ('relics', 'missions', 'enemies', 'other', 'market', 'research'))]
            if facts:
                stats['with_some_record'] += 1
            elif hits:
                stats['wiki_only'] += 1
            elif len(misses) < 40:
                misses.append(name)
    total = stats['collection_items']
    stats['pct'] = round(100.0 * stats['with_some_record'] / total, 1) if total else 0.0
    stats['sample_misses'] = misses
    return stats


# ------------------------------------------------------------------ wiki pass
WIKI_API = 'https://wiki.warframe.com/api.php'
WIKI_BASE = 'https://wiki.warframe.com/w/'
WIKI_CACHE = os.path.join(os.path.dirname(DROP_DIR), 'dropdata', 'wiki')
SECTION_RE = re.compile(r'={2,}\s*(Acquisition|How to Obtain|How to obtain|Obtained|Obtaining|'
                        r'Acquisition and Usage|AcquisitionEdit)\s*={2,}', re.I)
HEAD_RE = re.compile(r'\n={2,}[^=\n]+={2,}')
SEC_RE = re.compile(r'^={2,}\s*([^=\n]+?)\s*={2,}\s*$', re.M)
TRANSCLUDE_RE = re.compile(r'\{\{\s*Transclude\s*\|\s*([^#}|]+?)(?:#([^}|]+?))?\s*\}\}', re.I)

# A sentence is only quoted as a line when it names somewhere items really come from.
SOURCE_RE = re.compile(r"\b(?:Market|Tenno Lab|Clan Dojo|Dojo|Research|Quest|Syndicate|Standing|"
                       r"Bounty|Invasion|Sortie|Event|Relic|Vault|Baro Ki'Teer|Cephalon Simaris|"
                       r"Simaris|Quills|Ventkids|Roky|Legs|Little Duck|Necraloid|Kuva Lich|"
                       r"Sisters of Parvos)\b|(?<!Mastery )\bRank\b", re.I)
# words too generic to prove a sentence is about this item ('Hound' alone is every hound's word)
WEAK_WORDS = {'the', 'and', 'for', 'with', 'from', 'into', 'of', 'to', 'in', 'on', 'at', 'by',
              'or', 'is', 'it', 'as', 'an', 'its', 'prime', 'blueprint', 'blueprints', 'weapon',
              'warframe', 'component', 'parts', 'part', 'set', 'moa', 'hound', 'amp', 'kdrive',
              'kitgun', 'archwing', 'necramech', 'mod', 'mods'}
# ...and a prose sentence only becomes a line when it says the item is actually ACQUIRED
ACQ_VERB_RE = re.compile(r'\b(obtain(?:ed|able|s)?|acquir(?:e|ed|es)|purchas(?:e|ed|es|ing)|'
                         r'bought|buy|earn(?:ed|s)?|award(?:ed|s)?|reward(?:ed|s)?|sold|sell|'
                         r'research(?:ed)?|receiv(?:e|ed|es)|giv(?:e|en)|unlock(?:ed)?|'
                         r'complet(?:e|ed|es|ion)|craft(?:ed|ing)?|built|build(?:ing)?|cost(?:s)?|'
                         r'available|found|drop(?:s|ped)?|source(?:d)?|requir(?:e|ed|es))\b', re.I)
# a page's own acquisition text can live in a {{Acquisition|...}} template instead of a heading
ACQ_TPL_RE = re.compile(r'\{\{\s*Acquisition\s*\|', re.I)
# variant markers: a page that lacks the item's qualifier ('Venari' vs 'Venari Prime') is another
# item's page, so its words never answer for this one
QUALIFIER_WORDS = ('prime', 'umbra', 'wraith', 'vandal', 'prisma', 'kuva', 'tenet', 'dex',
                   'sancti', 'synoid', 'telos', 'vaykor', 'rakta', 'secura', 'coda', 'mk1')
# display templates carry visible words ({{cc|25,000}} renders "25,000 credits") - keep the value
TPL_RE = re.compile(r'\{\{\s*([a-zA-Z][\w ]*?)\s*\|([^{}]*?)\}\}')
TPL_WORDS = {'cc': '{v} credits', 'sc': '{v} standing', 'dc': '{v} Ducats',
             'plat': '{v} platinum', 'pc': '{v} platinum', 'faction': '{v}', 'wf': '{v}',
             'weapon': '{v}', 'clan': '{v}', 'a': '{v}', 'e': '{v}', 'd': '{v}', 'm': '{v}'}
UNIT_DUP_RE = re.compile(r'\b(standing|credits|Ducats|platinum)(?:\s+\1\b)+', re.I)
SENT_SPLIT_RE = re.compile(r'(?<=[.!?])\s+')
SECTIONS_BEFORE_LEAD = ('blueprint', 'blueprints', 'crafting', 'construction', 'building',
                        'usage', 'notes', 'obtaining')
MAX_SENTENCES = 2
LINE_LIMIT = 240
MAX_SEARCH_HITS = 4

# the closed component vocabulary collection_log.build_item_obtain attaches a part row with -
# mirrored so the wiki pass skips exactly the items whose card the parts already answer
COMPONENT_WORDS = {
    'blueprint', 'chassis', 'neuroptics', 'helmet', 'systems', 'barrel', 'receiver', 'stock',
    'handle', 'blade', 'hilt', 'guard', 'grip', 'string', 'limb', 'upper', 'lower', 'boot',
    'pouch', 'stars', 'star', 'cerebrum', 'carapace', 'wings', 'wing', 'harness', 'engine',
    'fuselage', 'reactor', 'ornament', 'head', 'gauntlet', 'buckle', 'band', 'chain', 'core',
    'disc', 'drum', 'synergy', 'claw', 'link', 'day', 'night', 'aspect', 'warrant', 'casing',
    'housing', 'motor', 'plate', 'spur', 'talons', 'fur',
}

NET_CALLS = 0                     # how many wiki requests this process has made (for sleep+s tests)


def words_of(text):
    return {w for w in re.findall(r"[a-z0-9']+", (text or '').lower())}


def distinctive_words(name):
    """The words that make this item *this* item ('Lambeo Moa' -> {'lambeo'})."""
    return {w for w in words_of(name) if len(w) >= 2 and w not in WEAK_WORDS}


def title_variants(name):
    """Wiki titles to try for a catalogue name: as written, then the normalised forms."""
    out, seen = [], set()

    def add(title, step):
        if title and title not in seen:
            seen.add(title)
            out.append((title, step))

    add(name, 'exact')
    if name != name.upper() and re.search(r'\d', name):
        add(name.upper(), 'upper')                     # 'Ax-52' -> 'AX-52'
    cap = name[:1].upper() + name[1:]
    if cap != name:
        add(cap, 'capitalised')
    if ' ' in name:
        add(name.replace(' ', '_'), 'underscored')     # a Wiki-style title
        add(name[:1].upper() + name[1:].lower(), 'sentence-case')   # 'Para Moa' -> 'Para moa'
    return out


def attaches_to_parent(name, key):
    """True when `key` ('Ash Systems Blueprint') is a part row the card shows under `name`."""
    words = key[len(name) + 1:].replace('-', ' ').split()
    return 0 < len(words) <= 3 and all(w.lower() in COMPONENT_WORDS for w in words)


def _net_get(url):
    """One network read, counted (callers sleep after a run that actually fetched)."""
    global NET_CALLS
    NET_CALLS += 1
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()


def wiki_slug(title):
    return re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')


def wiki_cache_path(title):
    """(path, cached doc) for a page title. The old cache is keyed by a lower-cased slug, which
    made 'Ax-52' and 'AX-52' share one entry - a legacy file only counts when it was fetched for
    this exact title; anything else gets its own case-hashed file."""
    slug = wiki_slug(title)
    legacy = os.path.join(WIKI_CACHE, slug + '.json')
    doc = jload(legacy) if os.path.exists(legacy) else None
    if doc is not None and doc.get('title') == title:
        return legacy, doc
    exact = os.path.join(WIKI_CACHE, '%s__%s.json'
                         % (slug, hashlib.md5(title.encode('utf-8')).hexdigest()[:8]))
    doc = jload(exact) if os.path.exists(exact) else None
    return exact, doc


def wiki_page(title, offline=False):
    """(text, resolved title) for one wiki page; cached by requested title, redirects followed.

    `text` is None for a page that does not exist (the miss is cached too, so a re-run never
    asks again) and `resolved` is the title the API landed on."""
    path, doc = wiki_cache_path(title)
    if doc is not None:
        return doc.get('text'), doc.get('resolved')
    if offline:
        return None, None
    params = urllib.parse.urlencode({'action': 'query', 'prop': 'revisions', 'rvprop': 'content',
                                     'rvslots': 'main', 'redirects': '1', 'titles': title,
                                     'format': 'json', 'formatversion': '2'})
    try:
        doc = json.loads(_net_get(WIKI_API + '?' + params))
    except Exception:
        return None, None
    page = (doc.get('query', {}).get('pages') or [{}])[0]
    text = None
    if 'revisions' in page:
        text = page['revisions'][0]['slots']['main'].get('content')
    resolved = page.get('title') or title
    os.makedirs(WIKI_CACHE, exist_ok=True)
    atomic_write(path, {'title': title, 'resolved': resolved, 'text': text,
                        'missing': text is None, 'fetched': int(time.time())})
    return text, resolved


def wiki_search(name, offline=False, limit=MAX_SEARCH_HITS):
    """The wiki's own search hits for a name (cached - the last resolution step)."""
    key = 'search__%s__%s' % (wiki_slug(name), hashlib.md5(name.encode('utf-8')).hexdigest()[:8])
    path = os.path.join(WIKI_CACHE, key + '.json')
    doc = jload(path) if os.path.exists(path) else None
    if doc is None:
        if offline:
            return []
        params = urllib.parse.urlencode({'action': 'query', 'list': 'search', 'srsearch': name,
                                         'format': 'json', 'formatversion': '2'})
        try:
            doc = json.loads(_net_get(WIKI_API + '?' + params))
        except Exception:
            return []
        os.makedirs(WIKI_CACHE, exist_ok=True)
        atomic_write(path, doc)
    hits = doc.get('query', {}).get('search') or []
    return [h['title'] for h in hits[:limit] if isinstance(h, dict) and h.get('title')]


def section_of(text, names=SECTION_RE):
    """The named section's raw text ('' when the page has no such section)."""
    if not text:
        return ''
    m = names.search(text)
    if not m:
        return ''
    start = m.end()
    nxt = HEAD_RE.search(text, start)
    return text[start:nxt.start() if nxt else len(text)]


def clean_wiki(text, pagename=None, limit=LINE_LIMIT):
    """wikitext -> one readable line. Markup is only ever removed; display templates keep their
    visible value ({{cc|25,000}} -> '25,000 credits') and {{PAGENAME}} becomes the item name."""
    if not text:
        return ''
    t = text
    if pagename:
        t = re.sub(r'\{\{\s*PAGENAME\s*\}\}', pagename, t, flags=re.I)

    def display(match):
        word = TPL_WORDS.get(match.group(1).strip().lower())
        if not word:
            return ' '                                     # unknown template: markup, dropped
        value = match.group(2).split('|')[0].strip(' |')
        return (word.replace('{v}', value).strip() or ' ') if value else ' '

    t = TPL_RE.sub(display, t)
    t = re.sub(r'<ref[^>]*>.*?</ref>', ' ', t, flags=re.S | re.I)
    t = re.sub(r'<ref[^>]*/>', ' ', t, flags=re.I)
    t = re.sub(r'<!--.*?-->', ' ', t, flags=re.S)
    t = re.sub(r'\{\{[^{}]*\}\}', ' ', t)                  # leftover templates
    t = re.sub(r'\{\{[^{}]*\}\}', ' ', t)
    t = re.sub(r'\[\[\s*(?:File|Image):[^\]]*\]\]', ' ', t, flags=re.I)
    t = re.sub(r'\[\[\s*(?:File|Image):[^\]]*\]?\]?', ' ', t, flags=re.I)
    t = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', r'\2', t)   # [[Page|label]] -> label
    t = re.sub(r'\[\[([^\]]+)\]\]', r'\1', t)
    t = re.sub(r'\[https?://\S+\s+([^\]]+)\]', r'\1', t)
    t = re.sub(r'<[^>]+>', ' ', t)
    t = t.replace("'''", '').replace("''", '')
    t = t.replace('\u200b', '').replace('\u00a0', ' ')
    t = re.sub(r'^\s*(?:\{\||\|\}|[|!]).*$', ' ', t, flags=re.M)   # table rows are not sentences
    t = re.sub(r'^[*#:;]+\s*', '', t, flags=re.M)
    t = re.sub(r'\s+', ' ', t).strip(' |·-')
    t = UNIT_DUP_RE.sub(r'\1', t)
    return t[:limit].rsplit(' ', 1)[0] if len(t) > limit else t


def sentence_line(text, limit=LINE_LIMIT, sentences=MAX_SENTENCES):
    """First `sentences` sentences of cleaned text, capped at `limit` chars ('' when too short)."""
    picked = []
    for raw in SENT_SPLIT_RE.split(text or ''):
        sent = raw.strip()
        if len(sent) < 15:
            continue
        if not picked and len(sent) > limit:
            sent = sent[:limit].rsplit(' ', 1)[0]
        if picked and len(' '.join(picked + [sent])) > limit:
            break
        picked.append(sent)
        if len(picked) >= sentences:
            break
    line = ' '.join(picked).strip()
    return line if len(line) >= 15 else ''


def page_sections(text):
    """[(heading, body)] in page order; the lead paragraph is the '' heading."""
    heads = list(SEC_RE.finditer(text or ''))
    if not heads:
        return [('', text or '')]
    out = [('', (text or '')[:heads[0].start()])]
    for i, match in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text or '')
        out.append((match.group(1).strip(), (text or '')[match.end():end]))
    return out


def prose_line(name, title, text, pagename=None):
    """(section, sentence) - the first sentence on the page that names a real source, says the item
    is acquired, and is about this item: the page itself is about it, or the sentence mentions one
    of its distinctive words. Another item's sentence is never quoted."""
    words = distinctive_words(name)
    sections = page_sections(text)
    preferred = [s for s in sections if s[0] and distinctive_words(s[0]) & words]
    lead = [s for s in sections if not s[0]]
    named = [s for s in sections if s[0] and s[0].lower().split()
             and s[0].lower().split()[0].strip(':') in SECTIONS_BEFORE_LEAD]
    rest = [s for s in sections if s not in preferred and s not in lead and s not in named]
    for heading, body in preferred + lead + named + rest:
        cleaned = clean_wiki(body, pagename=pagename, limit=4000)
        for raw in SENT_SPLIT_RE.split(cleaned):
            sent = raw.strip()
            if len(sent) < 15 or 'Category:' in sent or not sent.endswith(('.', '!', '?')):
                continue                                   # markup leftovers are not sentences
            if not SOURCE_RE.search(sent) or not ACQ_VERB_RE.search(sent):
                continue
            if not line_is_about(name, title, sent):
                continue                                   # never quote another item's sentence
            return heading or 'Lead', (sent[:LINE_LIMIT].rsplit(' ', 1)[0]
                                       if len(sent) > LINE_LIMIT else sent)
    return None, None


def template_body(text, start):
    """Raw text of the template starting at `start` (a '{{'), up to its matching '}}'."""
    depth, i = 0, start
    while i < len(text):
        if text.startswith('{{', i):
            depth += 1
            i += 2
            continue
        if text.startswith('}}', i):
            depth -= 1
            i += 2
            if depth <= 0:
                return text[start:i - 2]
            continue
        i += 1
    return text[start:]


def split_template_args(body):
    """Split a template body on its top-level '|' (nested templates/links stay whole)."""
    out, depth, cur, i = [], 0, [], 0
    while i < len(body):
        pair = body[i:i + 2]
        if pair in ('{{', '[['):
            depth += 1
            cur.append(pair)
            i += 2
            continue
        if pair in ('}}', ']]'):
            depth -= 1
            cur.append(pair)
            i += 2
            continue
        if body[i] == '|' and depth == 0:
            out.append(''.join(cur))
            cur = []
            i += 1
            continue
        cur.append(body[i])
        i += 1
    out.append(''.join(cur))
    return [arg.strip() for arg in out]


def line_is_about(name, title, line):
    """True when a quoted line belongs to this item: the page is about it (title shares a
    distinctive word and the same qualifier - 'Venari' is not 'Venari Prime'), or the line itself
    names one of the item's distinctive words (and the qualifier, when the title lacks it)."""
    words = distinctive_words(name)
    if not words:
        return False
    line_words = words_of(line)
    if not (words & line_words):
        return on_item_page(name, title)
    missing = missing_qualifiers(name, title)
    return not missing or any(q in line_words for q in missing)


def on_item_page(name, title):
    """True when the page title is this item's (shares a distinctive word, same qualifier)."""
    return bool(distinctive_words(name) & words_of(title or '')) \
        and not missing_qualifiers(name, title)


def missing_qualifiers(name, title):
    """Qualifier words the item name has and a candidate title lacks ('Venari' != 'Venari Prime')."""
    title_words = words_of(title or '')
    return [q for q in QUALIFIER_WORDS if q in words_of(name) and q not in title_words]


def acquisition_template(text, pagename=None):
    """(section, line) from a page's own {{Acquisition|...}} template (many weapon pages use it
    instead of a heading). Named parameters ('name=...') are ignored, the text argument is read."""
    match = ACQ_TPL_RE.search(text or '')
    if not match:
        return None, None
    body = template_body(text, match.start())
    inner = body[2:-2] if body.endswith('}}') else body[2:]
    args = split_template_args(inner)[1:]
    positional = [a for a in args if a and not re.match(r'^[\w ]+=', a)]
    body = max(positional or [a for a in args if a], key=len, default='')
    line = sentence_line(clean_wiki(body, pagename=pagename, limit=4000))
    return ('Acquisition', line) if line else (None, None)


def acquisition_section(text, pagename=None, offline=False):
    """(section label, line) from a page's own acquisition section, following one {{Transclude}}."""
    body = section_of(text, SECTION_RE)
    for target, section in TRANSCLUDE_RE.findall(body or ''):
        sub, _resolved = wiki_page(target.strip(), offline=offline)
        body = section_of(sub, re.compile(r'={2,}\s*(%s)\s*={2,}'
                                          % re.escape(section.strip() or 'Acquisition'), re.I)) or body
    if body:
        line = sentence_line(clean_wiki(body, pagename=pagename, limit=4000))
        if line:
            return 'Acquisition', line
    return acquisition_template(text, pagename=pagename)


def wiki_line(name, title, text, pagename=None, offline=False):
    """(section, line) for one page - its acquisition section first, then a sourced sentence.
    A line pulled from another item's page (a search hit) must name this item itself."""
    section, line = acquisition_section(text, pagename=pagename, offline=offline)
    if line and line_is_about(name, title, line):
        return section, line
    return prose_line(name, title, text, pagename=pagename)


def wiki_candidates(name, wiki_url=None, offline=False):
    """(title, step) candidates, most likely first: the name's own variants, the WFCD row's own
    wikiaUrl title, then the wiki search hits - hits whose title shares a distinctive word first,
    then a search on just those words (how 'Bhaira Hound' finds the Model page), then the rest."""
    out, seen = [], set()

    def add(title, step):
        if title and title not in seen:
            seen.add(title)
            out.append((title, step))

    for title, step in title_variants(name):
        add(title, step)
    if wiki_url:
        tail = urllib.parse.unquote(wiki_url.rstrip('/').rsplit('/', 1)[-1]).replace('_', ' ')
        add(tail, 'wfcd-wiki-url')
    words = distinctive_words(name)
    hits = list(wiki_search(name, offline=offline))
    word_hits = []
    if words and not any(words & words_of(h) for h in hits):
        word_hits = [h for h in wiki_search(' '.join(sorted(words)), offline=offline)
                     if h not in hits]
    sharing = [h for h in hits + word_hits if words and words & words_of(h)]
    for hit in (sharing + [h for h in word_hits + hits if h not in sharing])[:MAX_SEARCH_HITS + 2]:
        add(hit, 'search')
    return out


def wiki_acquire(name, wiki_url=None, offline=False):
    """The wiki's own answer to "how do I get this?", or None when it has nothing sourced."""
    for title, step in wiki_candidates(name, wiki_url=wiki_url, offline=offline):
        text, resolved = wiki_page(title, offline=offline)
        if not text:
            continue
        page = resolved or title
        section, line = wiki_line(name, page, text, pagename=name, offline=offline)
        if not line:                                       # template shell -> content subpage
            sub = page + '/Main'
            sub_text, sub_resolved = wiki_page(sub, offline=offline)
            if sub_text:
                section, line = wiki_line(name, sub_resolved or sub, sub_text, pagename=name,
                                          offline=offline)
                if line:
                    page, step = sub_resolved or sub, step + '+main'
        if line:
            return {'kind': 'wiki', 'title': page, 'via': step, 'section': section,
                    'url': WIKI_BASE + urllib.parse.quote(page.replace(' ', '_')), 'text': line}
    return None


def introduced_map(item_docs):
    """{name: introduced row} straight from the WFCD item files - the update that added it."""
    out = {}
    for rows in item_docs.values():
        for row in (rows or []):
            if isinstance(row, dict) and row.get('name') and row.get('introduced'):
                out[row['name']] = row['introduced']
    return out


def introduced_line(intro):
    """The honest last resort: the update that added the item, named by the WFCD row itself."""
    text = 'Added in %s' % (intro.get('name') or 'an unnamed update')
    if intro.get('date'):
        text += ' (%s)' % intro['date']
    return {'kind': 'introduced', 'title': intro.get('name') or '', 'via': 'wfcd',
            'section': 'introduced', 'url': intro.get('url') or '', 'text': text}


def add_line(item, acq):
    """Store the line where the collection card renders it: the record's free-text `other`
    bucket (source label + detail) plus the full provenance under `acq`."""
    source = ('Wiki (%s)' % acq['section']) if acq['kind'] == 'wiki' else 'WFCD (introduced)'
    row = {'source': source, 'detail': acq['text'], 'chance': None, 'rarity': None,
           'url': acq['url']}
    bucket = item.setdefault('other', [])
    if row not in bucket:
        bucket.append(row)
    item['acq'] = acq


def wiki_fill(doc, offline=False, sleep_s=0.4, limit=None, introduced=None):
    """Give every fact-less item a sourced acquisition line: the wiki first, `introduced` last.

    Component-aware: an item whose parts the card already answers through (Ash <- Ash Systems
    Blueprint) is skipped - but only when the part really attaches (Braton is not answered by
    'Braton Prime Blueprint'). Every fetch is cached, so a re-run is offline and idempotent."""
    index = doc['items']
    fact_names = {k for k, v in index.items()
                  if any(v.get(f) for f in ('relics', 'missions', 'enemies', 'other', 'market',
                                            'research'))}
    introduced = introduced or {}
    stats = {'tried': 0, 'wiki': 0, 'introduced': 0, 'empty': 0}
    for name, item in index.items():
        if name in fact_names or item.get('acq'):
            continue
        if any(k.startswith(name + ' ') and attaches_to_parent(name, k) for k in fact_names):
            continue
        tried_before = stats['tried']
        stats['tried'] += 1
        if limit and stats['tried'] > limit:
            stats['tried'] = tried_before
            break
        calls_before = NET_CALLS
        acq = wiki_acquire(name, wiki_url=item.get('wiki'), offline=offline)
        if not acq and introduced.get(name):
            acq = introduced_line(introduced[name])
        if acq:
            add_line(item, acq)
            stats[acq['kind']] += 1
            if acq['kind'] == 'wiki' and not item.get('wiki'):
                item['wiki'] = acq['url']
        else:
            item['acq'] = {'kind': 'none', 'title': '', 'via': 'none', 'section': '',
                           'url': '', 'text': ''}     # looked, found nothing - never invented
            stats['empty'] += 1
        if not offline and sleep_s and NET_CALLS > calls_before:
            time.sleep(sleep_s)
    counts = doc.get('counts') or {}
    counts['with_wiki_line'] = sum(1 for d in index.values()
                                   if (d.get('acq') or {}).get('kind') == 'wiki')
    counts['with_introduced_line'] = sum(1 for d in index.values()
                                         if (d.get('acq') or {}).get('kind') == 'introduced')
    counts['with_wiki_note'] = sum(1 for d in index.values() if d.get('wiki_note'))
    doc['counts'] = counts
    return stats


# ------------------------------------------------------------------ selftest
def selftest():
    ok = fail = 0

    def check(label, cond):
        nonlocal ok, fail
        if cond:
            ok += 1
        else:
            fail += 1
            print('FAIL: %s' % label)

    relics = {'relics': [
        {'tier': 'Axi', 'relicName': 'A1', 'state': 'Intact',
         'rewards': [{'itemName': 'Braton Prime Stock', 'rarity': 'Uncommon', 'chance': 25.33},
                     {'itemName': 'Nikana Prime Blueprint', 'rarity': 'Rare', 'chance': 2}]},
        {'tier': 'Axi', 'relicName': 'A1', 'state': 'Radiant',
         'rewards': [{'itemName': 'Nikana Prime Blueprint', 'rarity': 'Rare', 'chance': 10}]},
    ]}
    rel = index_relic_rewards(relics, {'Axi A1': True})
    check('relic rows indexed', set(rel) == {'Braton Prime Stock', 'Nikana Prime Blueprint'})
    check('radiant rows ignored', len(rel['Nikana Prime Blueprint']) == 1)
    check('intact chance kept', rel['Braton Prime Stock'][0]['chance'] == 25.33)
    check('vaulted flag carried', rel['Braton Prime Stock'][0]['vaulted'] is True)
    check('unknown vaulted stays None', index_relic_rewards(relics, {})['Braton Prime Stock'][0]['vaulted'] is None)

    missions = {'missionRewards': {'Venus': {'Luckless Expanse': {'gameMode': 'Survival', 'rewards': {
        'A': [{'itemName': 'Ash Systems Blueprint', 'chance': 13.33, 'rarity': 'Uncommon'}],
        'B': [{'itemName': 'Ash Systems Blueprint', 'chance': 4.88, 'rarity': 'Rare'}]}}}}}
    m = index_missions(missions)
    rows = m['Ash Systems Blueprint']
    check('both rotations indexed', len(rows) == 2)
    best = rank_missions(rows)[0]
    check('best chance first', best['chance'] == 13.33 and best['rotation'] == 'A')
    check('planet/node/mode carried', (best['planet'], best['node'], best['mode']) == ('Venus', 'Luckless Expanse', 'Survival'))

    enemies = index_enemies({'blueprintLocations': [
        {'itemName': 'Lavan Glazio Mk Iii', 'enemies': [
            {'enemyName': 'Taro Crewship (Level 51 - 100)', 'enemyBlueprintDropChance': 20, 'rarity': 'Uncommon'}]}]},
        {'enemyBlueprintTables': [
            {'enemyName': 'H-09 Apex', 'items': [{'itemName': 'Steel Essence', 'chance': 100, 'rarity': 'Common'}]}]})
    check('blueprint locations indexed', enemies['Lavan Glazio Mk Iii'][0]['enemy'].startswith('Taro Crewship'))
    check('enemy table items indexed', enemies['Steel Essence'][0]['chance'] == 100)

    other = index_other('Sortie', {'sortieRewards': [
        {'itemName': 'Legendary Core', 'chance': 2.5, 'rarity': 'Legendary'}]})
    check('extra source labelled', other['Legendary Core'][0]['source'] == 'Sortie')

    check('vaulted map folds states', vaulted_map([
        {'name': 'Axi A1 Intact', 'vaulted': True}, {'name': 'Axi A1 Radiant', 'vaulted': False},
        {'name': 'Lith B2 Intact', 'vaulted': False}]) == {'Axi A1': True, 'Lith B2': False})
    mm = market_map({'Warframes': [
        {'name': 'Ash', 'marketCost': 375, 'bpCost': 35000, 'tradable': False},
        {'name': 'Ignis', 'uniqueName': '/Lotus/Weapons/ClanTech/Chemical/FlameThrower', 'bpCost': 15000},
        {'name': 'NoData'}]})
    check('market map keeps costs', mm['Ash']['plat'] == 375 and mm['Ash']['credits'] == 35000)
    check('clan-tech flagged as research', mm['Ignis']['research'] is True and mm['Ignis']['plat'] is None)
    check('rows without any fact are skipped', 'NoData' not in mm)
    check('amp / k-drive parts get a record seed', set(part_rows({'Misc': [
        {'name': 'Mote Prism', 'type': 'Amp'}, {'name': 'Bad Baby', 'type': 'K-Drive Component'},
        {'name': 'Ash', 'type': 'Warframe'}]})) == {'Mote Prism', 'Bad Baby'})

    # ---- wiki line pass (pure checks only: no network, no cache)
    check('title variants: exact name first', title_variants('Braton') == [('Braton', 'exact')])
    check('title variants: all-caps form for Ax-52', ('AX-52', 'upper') in title_variants('Ax-52'))
    check('title variants: underscore form for spaces',
          ('Orion_&_Sirius', 'underscored') in title_variants('Orion & Sirius'))
    check('title variants: sentence-case form last',
          title_variants('Para Moa')[-1] == ('Para moa', 'sentence-case'))
    check('distinctive words drop the generic part',
          distinctive_words('Lambeo Moa') == {'lambeo'} and distinctive_words('Hec Hound') == {'hec'})
    check('part attach mirrors the card rule',
          attaches_to_parent('Ash', 'Ash Systems Blueprint') and
          not attaches_to_parent('Braton', 'Braton Prime Blueprint'))
    check('template values kept, markup dropped',
          clean_wiki('A built Strun can be purchased from the [[Market]] for {{cc|25,000}}.') ==
          'A built Strun can be purchased from the Market for 25,000 credits.')
    check('acquisition section is the first answer',
          wiki_line('Braton', 'Braton',
                    'x\n== Acquisition ==\nA fully built Braton can be purchased from the '
                    '[[Market]] for {{cc|25,000}}.\n== Notes ==\ny', offline=True)[1] ==
          'A fully built Braton can be purchased from the Market for 25,000 credits.')
    check('section-less page: the source sentence is quoted verbatim',
          prose_line('Orvius', 'Orvius', '== Notes ==\n* The blueprint can now be obtained from '
                     'Cephalon Simaris for 100,000 standing.')[1] ==
          'The blueprint can now be obtained from Cephalon Simaris for 100,000 standing.')
    check("another item's sentence is never quoted",
          prose_line('Lambeo Moa', 'Model',
                     '== Para ==\nThe Para blueprint can be purchased from Legs for 2,000 '
                     'standing.\n== Lambeo ==\nThe Lambeo blueprint can be purchased from Legs '
                     'for 2,500 standing.') ==
          ('Lambeo', 'The Lambeo blueprint can be purchased from Legs for 2,500 standing.'))
    check('introduced fallback names the update and date',
          introduced_line({'name': 'Update 10.0', 'date': '2013-09-13', 'url': 'u'})['text'] ==
          'Added in Update 10.0 (2013-09-13)')
    check('acquisition template is read when no heading exists',
          acquisition_template('x {{Acquisition|name=Orvius|The blueprint is rewarded on '
                               'completion of [[The War Within]].}} y') ==
          ('Acquisition', 'The blueprint is rewarded on completion of The War Within.'))
    check('table rows never leak into a line',
          clean_wiki('{|\n| [[File:ParaMOA.png|150px]]\n| style="width:100%" |\n|}\n'
                     'The Para blueprint can be purchased from [[Legs]].') ==
          'The Para blueprint can be purchased from Legs.')
    check('a variant page does not answer for a qualified item',
          not line_is_about('Venari Prime', 'Venari',
                            'All postures are available by default when Venari is unlocked at '
                            'Warframe rank 5.'))
    check('the item page itself answers',
          line_is_about('Venari Prime', 'Venari Prime', 'Venari Prime can be traded.'))

    print('selftest: %d ok, %d failed' % (ok, fail))
    return fail == 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='Build the obtain index from public drop tables.')
    ap.add_argument('--offline', action='store_true', help='use the cache only')
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--report', action='store_true', help='print coverage, write nothing')
    ap.add_argument('--no-wiki', action='store_true', help='skip the wiki acquisition pass')
    ap.add_argument('--wiki-limit', type=int, default=None, help='cap wiki fetches this run')
    ap.add_argument('--out', default=None, help='write the index to PATH (default: data/obtain_index.json)')
    args = ap.parse_args(argv)

    if args.selftest:
        sys.exit(0 if selftest() else 1)

    doc = build(offline=args.offline)
    introduced = doc.pop('_introduced', {})       # WFCD `introduced` rows: last-resort lines
    wiki = {'tried': 0, 'wiki': 0, 'introduced': 0, 'empty': 0}
    if not args.no_wiki:
        wiki = wiki_fill(doc, offline=args.offline, limit=args.wiki_limit, introduced=introduced)
    cov = coverage(doc)
    print('items indexed      : %d' % doc['counts']['items'])
    print('  with relics      : %d (%d vaulted relics)' % (doc['counts']['with_relics'], doc['counts']['vaulted_relics']))
    print('  with missions    : %d' % doc['counts']['with_missions'])
    print('  with enemies     : %d' % doc['counts']['with_enemies'])
    print('  with other source: %d' % doc['counts']['with_other'])
    print('  market price     : %d' % doc['counts']['with_market'])
    print('  dojo research    : %d' % doc['counts']['with_research'])
    print('  wiki link        : %d' % doc['counts']['with_wiki'])
    print('  how-to-get line  : %d wiki + %d introduced (tried %d, still empty %d)' % (
        doc['counts'].get('with_wiki_line', 0), doc['counts'].get('with_introduced_line', 0),
        wiki['tried'], wiki['empty']))
    print('  wiki note        : %d (legacy fallback: page text with nothing quotable)' % (
        doc['counts'].get('with_wiki_note', 0)))
    print('collection items with a record: %d/%d (%s%%)' % (
        cov['with_some_record'], cov['collection_items'], cov['pct']))
    if doc['notes']:
        print('notes:', '; '.join(doc['notes']))
    if args.report:
        print('sample without a record:', ', '.join(cov['sample_misses'][:12]))
        return 0
    out = args.out or out_path()
    atomic_write(out, doc)
    try:
        shown = os.path.relpath(out, ROOT)
    except ValueError:
        shown = out
    print('wrote %s (%d bytes)' % (shown.replace('\\', '/'), os.path.getsize(out)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
