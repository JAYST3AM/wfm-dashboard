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

Usage
  python scripts/obtain_index.py                # fetch (cached) + build + write
  python scripts/obtain_index.py --offline      # never touch the network
  python scripts/obtain_index.py --selftest     # offline logic checks
  python scripts/obtain_index.py --report       # coverage summary only, no write
"""
import argparse
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
WIKI_CACHE = os.path.join(os.path.dirname(DROP_DIR), 'dropdata', 'wiki')
SECTION_RE = re.compile(r'={2,}\s*(Acquisition|How to Obtain|How to obtain|Obtained|Acquisition and'
                        r' Usage|AcquisitionEdit)\s*={2,}', re.I)
HEAD_RE = re.compile(r'\n={2,}[^=\n]+={2,}')
TRANSCLUDE_RE = re.compile(r'\{\{\s*Transclude\s*\|\s*([^#}|]+?)(?:#([^}|]+?))?\s*\}\}', re.I)


def wiki_slug(title):
    return re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')


def wiki_page(title, offline=False):
    """Cached wikitext for a page title (redirects followed by the API)."""
    path = os.path.join(WIKI_CACHE, wiki_slug(title) + '.json')
    if os.path.exists(path):
        doc = jload(path)
        if doc is not None:
            return doc.get('text'), doc.get('resolved')
    if offline:
        return None, None
    params = urllib.parse.urlencode({'action': 'query', 'prop': 'revisions', 'rvprop': 'content',
                                     'rvslots': 'main', 'redirects': '1', 'titles': title,
                                     'format': 'json', 'formatversion': '2'})
    try:
        raw = urllib.request.urlopen(urllib.request.Request(WIKI_API + '?' + params, headers=UA),
                                     timeout=60).read()
        doc = json.loads(raw)
    except Exception:
        return None, None
    page = (doc.get('query', {}).get('pages') or [{}])[0]
    text = None
    if 'revisions' in page:
        text = page['revisions'][0]['slots']['main'].get('content')
    resolved = page.get('title')
    os.makedirs(WIKI_CACHE, exist_ok=True)
    atomic_write(path, {'title': title, 'resolved': resolved, 'text': text,
                        'fetched': int(time.time())})
    return text, resolved


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


def strip_wiki(text, limit=240):
    """wikitext -> one readable line; templates/refs/tags removed, never inventing words."""
    t = re.sub(r'<ref[^>]*>.*?</ref>', ' ', text, flags=re.S | re.I)
    t = re.sub(r'<ref[^>]*/>', ' ', t, flags=re.I)
    t = re.sub(r'<!--.*?-->', ' ', t, flags=re.S)
    t = re.sub(r'\{\{[^{}]*\}\}', ' ', t)                 # simple templates ({{WF|X}} etc.)
    t = re.sub(r'\{\{[^{}]*\}\}', ' ', t)
    t = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', r'\2', t)  # [[Page|label]] -> label
    t = re.sub(r'\[\[([^\]]+)\]\]', r'\1', t)
    t = re.sub(r'\[https?://\S+\s+([^\]]+)\]', r'\1', t)
    t = re.sub(r'<[^>]+>', ' ', t)
    t = t.replace("'''", '').replace("''", '')
    t = re.sub(r'^[*#:;]+\s*', '', t, flags=re.M)
    t = re.sub(r'\s+', ' ', t).strip(' |·-')
    return t[:limit].rsplit(' ', 1)[0] if len(t) > limit else t


def wiki_note(name, offline=False):
    """Short sourced 'how to obtain' line from the wiki's Acquisition section, or None."""
    text, _resolved = wiki_page(name, offline=offline)
    body = section_of(text)
    for target, section in TRANSCLUDE_RE.findall(body or ''):
        sub, _r = wiki_page(target.strip(), offline=offline)
        body = section_of(sub, re.compile(r'={2,}\s*(%s)\s*={2,}'
                                          % re.escape(section.strip() or 'Acquisition'), re.I)) or body
    note = strip_wiki(body)
    return note or None


def wiki_fill(doc, offline=False, sleep_s=0.4, limit=None):
    """Add `wiki_note` to every item that has no fact-bearing record yet.

    Component-aware: if a row like "Ash Prime Chassis Blueprint" already carries drop facts, the
    parent item is answered and skipped - the wiki is only asked where the tables are silent."""
    index = doc['items']
    fact_names = {k for k, v in index.items()
                  if any(v.get(f) for f in ('relics', 'missions', 'enemies', 'other', 'market',
                                            'research'))}
    filled = tried = 0
    for name, item in index.items():
        if name in fact_names or item.get('wiki_note'):
            continue
        if any(k.startswith(name + ' ') for k in fact_names):
            continue
        tried += 1
        if limit and tried > limit:
            break
        note = wiki_note(name, offline=offline)
        if note:
            item['wiki_note'] = note
            filled += 1
        if not offline and sleep_s:
            time.sleep(sleep_s)
    doc['counts']['with_wiki_note'] = sum(1 for d in index.values() if d.get('wiki_note'))
    return {'tried': tried, 'filled': filled}


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

    print('selftest: %d ok, %d failed' % (ok, fail))
    return fail == 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='Build the obtain index from public drop tables.')
    ap.add_argument('--offline', action='store_true', help='use the cache only')
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--report', action='store_true', help='print coverage, write nothing')
    ap.add_argument('--no-wiki', action='store_true', help='skip the wiki acquisition pass')
    ap.add_argument('--wiki-limit', type=int, default=None, help='cap wiki fetches this run')
    args = ap.parse_args(argv)

    if args.selftest:
        sys.exit(0 if selftest() else 1)

    doc = build(offline=args.offline)
    wiki = {'tried': 0, 'filled': 0}
    if not args.no_wiki:
        wiki = wiki_fill(doc, offline=args.offline, limit=args.wiki_limit)
    cov = coverage(doc)
    print('items indexed      : %d' % doc['counts']['items'])
    print('  with relics      : %d (%d vaulted relics)' % (doc['counts']['with_relics'], doc['counts']['vaulted_relics']))
    print('  with missions    : %d' % doc['counts']['with_missions'])
    print('  with enemies     : %d' % doc['counts']['with_enemies'])
    print('  with other source: %d' % doc['counts']['with_other'])
    print('  market price     : %d' % doc['counts']['with_market'])
    print('  dojo research    : %d' % doc['counts']['with_research'])
    print('  wiki link        : %d' % doc['counts']['with_wiki'])
    print('  wiki note        : %d (fetched %d this run, %d filled)' % (
        doc['counts'].get('with_wiki_note', 0), wiki['tried'], wiki['filled']))
    print('collection items with a record: %d/%d (%s%%)' % (
        cov['with_some_record'], cov['collection_items'], cov['pct']))
    if doc['notes']:
        print('notes:', '; '.join(doc['notes']))
    if args.report:
        print('sample without a record:', ', '.join(cov['sample_misses'][:12]))
        return 0
    atomic_write(out_path(), doc)
    print('wrote %s (%d bytes)' % (os.path.relpath(out_path(), ROOT), os.path.getsize(out_path())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
