#!/usr/bin/env python3
"""Craft-profit calculator (#22): build it, or just buy it?

Inputs : data/recipes_cache.json (WFCD crafting recipes), data/wfm_items_v2.json (market catalog),
         data/owned.json, data/prices.json (+ optional live /top for slugs prices.json has no floor for)
Output : data/craft.json

WFCD recipes carry Lotus paths only, so every path is converted into a WFM slug before it is trusted:

    assembled result -> catalog gameRef / owned.path / name fallback -> '<item>_set' (WFM trades the
                        bundle, not built gear)
    ingredient       -> tradeable component slug, else the recipe whose result IS that component
                        (blueprints: 'AshPrimeHelmetComponent' -> 'ash_prime_neuroptics_blueprint')
    resources        -> 'Orokin Cell', Plastids, ... map to no market slug: never priced, always noted

For every recipe where the account owns the blueprint OR at least one component:

    buy_cost    = sum(floor * units missing)          (only WARFRAME.MARKET parts are priced)
    built_floor = sell floor of the assembled result
    profit      = built_floor - buy_cost              (negative -> buy the assembled item instead)

verdict: CRAFT (profit >= 0, every missing unit priced) / BUY (profit < 0) / SKIP (cannot be priced:
resource-only recipe, unpriced missing part, or no assembled floor).

Run: python scripts/craft.py [--live] [--live-max 250] [--refresh] [--refresh-live] [--offline]
     python scripts/craft.py --selftest          (offline fixtures, no network, no files touched)
"""
import argparse
import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'
SLEEP = 0.35                      # seconds between live /top calls
LIVE_MAX = 250                    # cap on live /top calls per run
TIMEOUT = 30
CACHE_SCHEMA = 1
RECIPE_CACHE = 'recipes_cache.json'
OUT = 'craft.json'
VERDICTS = ('CRAFT', 'BUY', 'SKIP')
# catalog tags that mean 'this is tradeable gear on WARFRAME.MARKET' (vs a resource/misc item)
PART_TAGS = frozenset(('prime', 'set', 'mod', 'arcane_enhancement', 'component', 'blueprint', 'relic'))

# 'data/json/Recipes.json' is the historical WFCD path (404 upstream since recipes moved into the
# public export that warframe.market tooling reads); sources are tried in order, a cache wins.
RECIPE_URLS = (
    'https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/Recipes.json',
    'https://raw.githubusercontent.com/calamity-inc/warframe-public-export-plus/master/ExportRecipes.json',
)


def load(name, default=None):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return default
    try:
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return default


def save_json(path, obj):
    """tmp file + os.replace, so a half-written craft.json never lands."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, indent=1)
    os.replace(tmp, path)


def now_utc():
    return datetime.now(timezone.utc)


def utc_stamp(dt=None):
    return (dt or now_utc()).strftime('%Y-%m-%d %H:%M UTC')


# --------------------------------------------------------------------- slug conversion

def slugify(name):
    """WFM slug form: lowercase, runs of non-alphanumerics -> single underscore."""
    return re.sub(r'[^a-z0-9]+', '_', str(name or '').lower()).strip('_')


def name_from_path(path):
    """CamelCase Lotus tail -> spaced name: 'PrimeBowLowerLimb' -> 'Prime Bow Lower Limb'."""
    tail = str(path or '').rstrip('/').split('/')[-1].replace('_', ' ')
    tail = re.sub(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])', ' ', tail)
    return re.sub(r'\s+', ' ', tail).strip()


def build_indexes(catalog, owned):
    """path -> slug (market ids), name -> slug, slug -> display name, slug -> catalog tags."""
    path2slug, name2slug, slug2name, slug2tags = {}, {}, {}, {}
    for it in catalog:
        slug = it.get('slug')
        if not slug:
            continue
        if it.get('gameRef'):
            path2slug.setdefault(it['gameRef'], slug)
        if it.get('tags'):
            slug2tags.setdefault(slug, set(it['tags']))
        nm = ((it.get('i18n') or {}).get('en') or {}).get('name') or ''
        if nm:
            name2slug.setdefault(slugify(nm), slug)
            slug2name.setdefault(slug, nm)
    for o in owned:                                  # owned.json carries the game path too
        if o.get('path') and o.get('slug'):
            path2slug.setdefault(o['path'], o['slug'])
            slug2name.setdefault(o['slug'], o.get('name') or o['slug'])
        if o.get('tags'):
            slug2tags.setdefault(o['slug'], set(o['tags']))
    return dict(path2slug=path2slug, name2slug=name2slug, slug2name=slug2name, slug2tags=slug2tags)


def is_market_part(slug, index):
    """Tradeable gear (prime parts, blueprints, sets, mods, arcanes, relics) vs in-game resources.

    A slug with no catalog row stays a part (the market may still list it); 'Orokin Cell'-style
    resources ARE catalogued and must not be priced as if they were build components.
    """
    tags = index['slug2tags'].get(slug)
    return True if not tags else bool(tags & PART_TAGS)


def result2slug_index(recipes, index):
    """component path -> the TRADEABLE recipe-key slug that produces it.

    Only paths that some recipe actually CONSUMES count (the component recipes' results), so an
    assembled item's own path never maps back to its own blueprint recipe.
    """
    consumed = {p for rec in recipes.values() for p, _ in rec['ingredients']}
    out = {}
    for key, rec in recipes.items():
        ks, rt = index['path2slug'].get(key), rec.get('result')
        if ks and rt in consumed:
            out.setdefault(rt, ks)
    return out


def part_slug(path, index, res2slug):
    """Lotus ingredient path -> WFM slug, exactly the slug the market catalog uses (or None)."""
    return (index['path2slug'].get(path) or res2slug.get(path)
            or index['name2slug'].get(slugify(name_from_path(path))))


# --------------------------------------------------------------------- recipes cache / fetch

def normalize_recipes(raw):
    """ExportRecipes-style {blueprintPath: {resultType, num, tradable, ingredients:[{ItemType,ItemCount}]}}
    or the older items-style [{uniqueName, components:[...]}] -> ({key: {result, num, tradable, ingredients}}, dropped)."""
    out, dropped = {}, 0
    if isinstance(raw, list):                        # items-style: one entry per craftable item
        for it in raw:
            if not isinstance(it, dict) or not it.get('uniqueName'):
                dropped += 1
                continue
            ings = [[c['uniqueName'], int(c.get('itemCount') or c.get('ItemCount') or 1)]
                    for c in (it.get('components') or []) if isinstance(c, dict) and c.get('uniqueName')]
            if ings:
                out[it['uniqueName']] = {'result': it['uniqueName'], 'num': 1,
                                         'tradable': bool(it.get('tradable')), 'ingredients': ings}
            else:
                dropped += 1
        return out, dropped
    for key, rec in (raw or {}).items():
        if not isinstance(rec, dict):
            dropped += 1
            continue
        ings = []
        for ing in (rec.get('ingredients') or []):
            if isinstance(ing, dict) and ing.get('ItemType'):
                ings.append([ing['ItemType'], int(ing.get('ItemCount') or 1)])
        if not rec.get('resultType') or not ings:
            dropped += 1
            continue
        out[key] = {'result': rec['resultType'], 'num': int(rec.get('num') or 1),
                    'tradable': bool(rec.get('tradable')), 'ingredients': ings}
    return out, dropped


def fetch_bytes(url, tries=3):
    """-> (bytes, None) or (None, error text). Retries throttling/5xx only."""
    err = 'no attempt'
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read(), None
        except urllib.error.HTTPError as e:
            err = 'http %d' % e.code
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(3 + 2 * a)
                continue
            return None, err
        except Exception as e:                       # DNS, timeout, TLS, ...
            err = type(e).__name__
            time.sleep(2 + 2 * a)
    return None, err


def fetch_recipes(urls=RECIPE_URLS):
    """-> (normalized recipes, cache doc) or (None, error text). First source that answers wins."""
    tried = []
    for url in urls:
        blob, err = fetch_bytes(url)
        if blob is None:
            tried.append('%s -> %s' % (url.split('/')[-1], err))
            continue
        try:
            raw = json.loads(blob.decode('utf-8'))
        except Exception as e:
            tried.append('%s -> bad json (%s)' % (url.split('/')[-1], type(e).__name__))
            continue
        recipes, dropped = normalize_recipes(raw)
        if not recipes:
            tried.append('%s -> no usable recipes' % url.split('/')[-1])
            continue
        doc = dict(schema=CACHE_SCHEMA, source_url=url, fetched_utc=utc_stamp(),
                   count=len(recipes), dropped=dropped)
        return recipes, doc
    return None, '; '.join(tried) or 'no sources configured'


def load_recipes(refresh=False, offline=False, urls=RECIPE_URLS):
    """Cache first; a missing cache (or --refresh) fetches. -> (recipes|None, note)."""
    cached = load(RECIPE_CACHE) or {}
    have = cached.get('recipes') or None
    if have and not refresh:
        return have, ('data/%s cache: %d recipes (fetched %s)'
                      % (RECIPE_CACHE, len(have), cached.get('fetched_utc') or '?'))
    if offline:
        return ((have, 'data/%s cache (--offline): %d recipes' % (RECIPE_CACHE, len(have))) if have
                else (None, 'no data/%s and --offline says do not fetch' % RECIPE_CACHE))
    recipes, doc = fetch_recipes(urls)
    if recipes is None:
        if have:                                     # keep working off a valid cache, say so loudly
            return have, ('refresh failed (%s) - using the cached %d recipes from %s'
                          % (doc, len(have), cached.get('fetched_utc') or '?'))
        return None, 'fetch failed (%s)' % doc
    save_json(os.path.join(DATA, RECIPE_CACHE), dict(doc, recipes=recipes))
    return recipes, ('data/%s <- %s (%d recipes%s)' % (RECIPE_CACHE, doc['source_url'], len(recipes),
                                                       ', %d dropped' % doc['dropped'] if doc['dropped'] else ''))


# --------------------------------------------------------------------- pricing

def floor_of(entry):
    """prices.json row / live row -> sell floor (wts), or None when nothing is listed."""
    v = (entry or {}).get('wts') if isinstance(entry, dict) else entry
    return None if v is None else float(v)


def fetch_top_floor(item_id):
    """Live warframe.market /top: lowest visible sell listing. -> (floor|None, error|None)."""
    blob, err = fetch_bytes('https://api.warframe.market/v2/orders/item/%s/top' % item_id, tries=2)
    if blob is None:
        return None, err
    try:
        data = (json.loads(blob.decode('utf-8')) or {}).get('data') or {}
    except Exception as e:
        return None, 'bad json (%s)' % type(e).__name__
    sells = [o.get('platinum') for o in (data.get('sell') or []) if o.get('visible') and o.get('platinum')]
    return (min(sells) if sells else None), (None if sells else 'no visible sellers')


# --------------------------------------------------------------------- the calculation

def walk(recipes, index, res2slug, owned_counts):
    """Yield one dict per recipe the account can act on (owns the blueprint or >=1 component)."""
    for key in sorted(recipes):
        rec = recipes[key]
        key_slug = index['path2slug'].get(key)
        units, ignored = {}, {}
        for path, cnt in rec['ingredients']:
            slug = part_slug(path, index, res2slug)
            if slug and is_market_part(slug, index):
                units[slug] = units.get(slug, 0) + cnt
            else:                                     # Orokin Cell / Plastids / ... : never priced
                tail = name_from_path(path)
                ignored[tail] = ignored.get(tail, 0) + cnt
        owned_parts = sorted(s for s in units if owned_counts.get(s))
        if not (key_slug and owned_counts.get(key_slug)) and not owned_parts:
            continue
        yield dict(key=key, key_slug=key_slug, units=units, ignored=ignored, owned_parts=owned_parts,
                   # a component's tradeable face is its blueprint recipe ('...HelmetComponent' ->
                   # 'x_prime_neuroptics_blueprint'), an assembled item's is the '<item>_set' bundle
                   result_slug=(index['path2slug'].get(rec['result']) or res2slug.get(rec['result'])),
                   owns_blueprint=bool(key_slug and owned_counts.get(key_slug)))


def missing_units(units, owned_counts):
    """-> {slug: units still to buy}, count-aware (2 needed, 1 owned -> 1)."""
    return {s: n - owned_counts.get(s, 0) for s, n in units.items() if n > owned_counts.get(s, 0)}


def analyse(recipes, index, res2slug, owned_counts, floors):
    """-> (rows, skipped, ignored_ingredients, detail) for the data/craft.json row contract.

    ``detail`` maps result_slug -> the units the recipe needs and the units owned, so the self-check
    can re-derive buy_cost exactly (a recipe can need 2 of a part, e.g. Akbronco = 2x Bronco Prime).
    Pure: no I/O.
    """
    rows, skipped, ignored_all, seen, detail = [], [], {}, {}, {}
    for cand in walk(recipes, index, res2slug, owned_counts):
        for tail in cand['ignored']:
            ignored_all[tail] = ignored_all.get(tail, 0) + 1
        slug, units = cand['result_slug'], cand['units']
        if not slug:
            skipped.append(dict(result_slug=cand['key_slug'] or cand['key'], recipe=cand['key'],
                                reason='assembled result is not on warframe.market'))
            continue
        if slug in seen:                              # two recipes producing one market item: keep the richer
            if len(units) <= len(seen[slug]['units']):
                continue
            rows = [r for r in rows if r['result_slug'] != slug]
        missing = missing_units(units, owned_counts)
        unpriced = sorted(s for s in missing if s not in floors)
        buy_cost = round(float(sum(floors[s] * n for s, n in missing.items() if s in floors)), 1)
        built = floors.get(slug)
        if not units:
            verdict, reason = 'SKIP', 'resource-only recipe (no market parts to buy)'
        elif built is None:
            verdict, reason = 'SKIP', 'no price for the assembled %s' % slug
        elif unpriced:
            verdict, reason = 'SKIP', 'no price for missing part(s): ' + ', '.join(unpriced[:3])
        else:
            verdict = 'CRAFT' if round(built - buy_cost, 1) >= 0 else 'BUY'
            reason = ('build it: assembled %sp vs %sp of missing parts' % (round(built, 1), buy_cost)
                      if verdict == 'CRAFT' else
                      'buy the assembled for %sp instead of %sp of parts' % (round(built, 1), buy_cost))
        row = dict(
            result_name=index['slug2name'].get(slug, slug),
            result_slug=slug,
            built_floor=None if built is None else round(built, 1),
            buy_cost=buy_cost,
            profit=None if verdict == 'SKIP' else round(built - buy_cost, 1),
            missing_parts=[dict(slug=s, floor=None if s not in floors else round(floors[s], 1))
                           for s in sorted(missing)],
            owned_parts=list(cand['owned_parts']),
            verdict=verdict)
        rows.append(row)
        seen[slug] = dict(units=units, row=row)
        detail[slug] = dict(key=cand['key'], units=dict(units),
                            have={s: owned_counts.get(s, 0) for s in units if owned_counts.get(s)},
                            missing=dict(missing))
        if verdict == 'SKIP':
            skipped.append(dict(result_slug=slug, recipe=cand['key'], reason=reason,
                                unpriced=unpriced or None, missing=sorted(missing)))
    order = {v: i for i, v in enumerate(VERDICTS)}
    rows.sort(key=lambda r: (order[r['verdict']],
                             -(r['profit'] if r['profit'] is not None else -1e9), r['result_slug']))
    return rows, skipped, ignored_all, detail


def price_targets(recipes, index, res2slug, owned_counts, floors):
    """Market slugs a live /top call could price: missing parts + unpriced assembled results."""
    targets = set()
    for cand in walk(recipes, index, res2slug, owned_counts):
        if not cand['result_slug'] or not cand['units']:
            continue
        for s in missing_units(cand['units'], owned_counts):
            if s not in floors:
                targets.add(s)
        if cand['result_slug'] not in floors:
            targets.add(cand['result_slug'])
    return sorted(targets)


def live_floors(slugs, catalog_by_slug, cached=None, max_calls=LIVE_MAX, sleep=SLEEP, log=print):
    """-> ({slug: floor}, stats). Cached live prices are reused; only the rest costs a /top call."""
    out, cache_hits, calls, errors = {}, 0, 0, []
    for slug in slugs:
        hit = (cached or {}).get(slug) or {}
        if hit.get('wts') is not None:
            out[slug] = float(hit['wts'])
            cache_hits += 1
    todo = [s for s in slugs if s not in out]
    if len(todo) > max_calls:
        log('live: %d slug(s) need a price, capping this run at %d (--live-max)' % (len(todo), max_calls))
        todo = todo[:max_calls]
    for i, slug in enumerate(todo, 1):
        item = catalog_by_slug.get(slug) or {}
        if not item.get('id'):
            errors.append('%s: not in the market catalog' % slug)
            continue
        wts, err = fetch_top_floor(item['id'])
        calls += 1
        if wts is not None:
            out[slug] = wts
        elif err:
            errors.append('%s: %s' % (slug, err))
        if i % 25 == 0 or i == len(todo):
            log('live /top %d/%d (priced %d)' % (i, len(todo), len(out)))
        time.sleep(sleep)
    return out, dict(cache_hits=cache_hits, calls=calls, known=len(out), errors=errors)


def self_check(rows, skipped, summary, detail=None):
    """The invariants data/craft.json has to hold. ``detail`` comes from analyse() (units per recipe)."""
    detail = detail or {}
    keys = {'result_name', 'result_slug', 'built_floor', 'buy_cost', 'profit', 'missing_parts',
            'owned_parts', 'verdict'}

    def expected_cost(row):
        d = detail.get(row['result_slug'])
        if not d:
            return None                              # every row must have been computed by analyse()
        return round(sum(p['floor'] * (d['missing'].get(p['slug']) or 1)
                         for p in row['missing_parts'] if p['floor'] is not None), 1)

    return dict(
        rows_unique=len({r['result_slug'] for r in rows}) == len(rows),
        row_keys_exact=all(set(r) == keys for r in rows),
        verdicts_known=all(r['verdict'] in VERDICTS for r in rows),
        counts_add_up=summary['craft'] + summary['buy'] + summary['skip'] == summary['total'] == len(rows),
        counted_from_rows=(summary['craft'] == len([r for r in rows if r['verdict'] == 'CRAFT'])
                           and summary['buy'] == len([r for r in rows if r['verdict'] == 'BUY'])
                           and summary['skip'] == len([r for r in rows if r['verdict'] == 'SKIP'])),
        profit_matches_floors=all(r['profit'] is None
                                  or abs(r['profit'] - (r['built_floor'] - r['buy_cost'])) < 1e-6 for r in rows),
        buy_cost_matches_parts=all(expected_cost(r) is not None and abs(r['buy_cost'] - expected_cost(r)) < 1e-6
                                   for r in rows),
        priced_rows_complete=all(all(p['floor'] is not None for p in r['missing_parts'])
                                 for r in rows if r['verdict'] != 'SKIP'),
        parts_listed_once=all(len({p['slug'] for p in r['missing_parts']}) == len(r['missing_parts'])
                              and len(set(r['owned_parts'])) == len(r['owned_parts']) for r in rows),
        costs_non_negative=all(r['buy_cost'] >= 0 and (r['built_floor'] is None or r['built_floor'] >= 0)
                               for r in rows),
        skipped_documented=all(s.get('reason') for s in skipped))


# --------------------------------------------------------------------- reporting

def report(doc, note):
    s, rows = doc['summary'], doc['rows']
    lines = ['craft.py -> data/craft.json   %s' % doc['generated'],
             'recipes : %s' % note,
             'rows %d | CRAFT %d | BUY %d | SKIP %d' % (s['total'], s['craft'], s['buy'], s['skip']),
             'missing parts %d plat | assembled floors %d plat | prices: %s'
             % (round(s['missing_plat']), round(s['assembled_plat']), s['prices']),
             'self-check: ' + ('OK (%d checks)' % len(doc['self_check'])
                               if all(doc['self_check'].values()) else
                               'FAILED -> ' + ', '.join(k for k, v in doc['self_check'].items() if not v))]
    for want in ('CRAFT', 'BUY'):
        picks = [r for r in rows if r['verdict'] == want]
        lines += ['', '%s (%d)' % (want, s['craft'] if want == 'CRAFT' else s['buy'])]
        lines += ['  %-32s built=%6s buy=%6.1f profit=%7s  missing: %s'
                  % (r['result_slug'], r['built_floor'], r['buy_cost'], r['profit'],
                     ', '.join('%s %s' % (p['slug'], p['floor']) for p in r['missing_parts']) or '-')
                  for r in picks[:8]]
    reasons = {x['result_slug']: x['reason'] for x in doc['skipped']}
    skips = [r['result_slug'] for r in rows if r['verdict'] == 'SKIP']
    skips += [x['result_slug'] for x in doc['skipped'] if x['result_slug'] not in skips]
    if skips:
        lines += ['', 'SKIP (%d) - unpriced, resource-only, or not on the market' % len(skips)]
        lines += ['  %-32s %s' % (s, reasons.get(s) or 'unpriced - rerun with --live')
                  for s in skips[:8]]
    if doc['ignored_ingredients']:
        lines += ['', 'never priced (resources, not on the market): '
                  + ', '.join('%s x%d' % kv for kv in list(doc['ignored_ingredients'].items())[:8])]
    print('\n'.join(lines))


# --------------------------------------------------------------------- selftest (offline)

CATALOG = {'data': [
    {'slug': 'widget_prime_set', 'gameRef': '/Lotus/Weapons/WidgetPrime', 'tags': ['prime', 'set'],
     'i18n': {'en': {'name': 'Widget Prime Set'}}},
    {'slug': 'widget_prime_blueprint', 'gameRef': '/Lotus/Types/Recipes/Weapons/WidgetPrimeBlueprint',
     'tags': ['prime', 'blueprint'], 'i18n': {'en': {'name': 'Widget Prime Blueprint'}}},
    {'slug': 'widget_prime_barrel', 'gameRef': '/Lotus/Types/Recipes/Weapons/WeaponParts/WidgetPrimeBarrel',
     'tags': ['prime', 'component'], 'i18n': {'en': {'name': 'Widget Prime Barrel'}}},
    {'slug': 'widget_prime_handle', 'gameRef': '/Lotus/Types/Recipes/Weapons/WeaponParts/WidgetPrimeHandle',
     'tags': ['prime', 'component'], 'i18n': {'en': {'name': 'Widget Prime Handle'}}},
    {'slug': 'gizmo_prime_set', 'gameRef': '/Lotus/Powersuits/GizmoPrime', 'tags': ['prime', 'set'],
     'i18n': {'en': {'name': 'Gizmo Prime Set'}}},
    {'slug': 'gizmo_prime_blueprint', 'gameRef': '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeBlueprint',
     'tags': ['prime', 'blueprint'], 'i18n': {'en': {'name': 'Gizmo Prime Blueprint'}}},
    # in game the head part is a 'Helmet' component; the market only sells the NEUROPTICS blueprint
    {'slug': 'gizmo_prime_neuroptics_blueprint',
     'gameRef': '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeHelmetBlueprint',
     'tags': ['prime', 'blueprint'], 'i18n': {'en': {'name': 'Gizmo Prime Neuroptics Blueprint'}}},
    {'slug': 'gizmo_prime_chassis_blueprint',
     'gameRef': '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeChassisBlueprint',
     'tags': ['prime', 'blueprint'], 'i18n': {'en': {'name': 'Gizmo Prime Chassis Blueprint'}}},
    {'slug': 'gadget_prime_set', 'gameRef': '/Lotus/Weapons/GadgetPrime', 'tags': ['prime', 'set'],
     'i18n': {'en': {'name': 'Gadget Prime Set'}}},
    {'slug': 'gadget_prime_blueprint', 'gameRef': '/Lotus/Types/Recipes/Weapons/GadgetPrimeBlueprint',
     'tags': ['prime', 'blueprint'], 'i18n': {'en': {'name': 'Gadget Prime Blueprint'}}},
    # a component whose Lotus tail does not name the market item (Paris: PrimeBowLowerLimb -> Lower Limb)
    {'slug': 'prime_bow_lower_limb', 'gameRef': '/Lotus/Types/Recipes/Weapons/WeaponParts/BowLowerLimbGeneric',
     'tags': ['prime', 'component'], 'i18n': {'en': {'name': 'Prime Bow Lower Limb'}}},
    {'slug': 'doohickey_set', 'gameRef': '/Lotus/Weapons/Doohickey', 'tags': ['prime', 'set'],
     'i18n': {'en': {'name': 'Doohickey Set'}}},
    {'slug': 'doohickey_blueprint', 'gameRef': '/Lotus/Types/Recipes/Weapons/DoohickeyBlueprint',
     'tags': ['prime', 'blueprint'], 'i18n': {'en': {'name': 'Doohickey Blueprint'}}},
    {'slug': 'thingamajig_set', 'gameRef': '/Lotus/Weapons/Thingamajig', 'tags': ['prime', 'set'],
     'i18n': {'en': {'name': 'Thingamajig Set'}}},
    {'slug': 'thingamajig_blueprint', 'gameRef': '/Lotus/Types/Recipes/Weapons/ThingamajigBlueprint',
     'tags': ['prime', 'blueprint'], 'i18n': {'en': {'name': 'Thingamajig Blueprint'}}},
    {'slug': 'thingamajig_barrel', 'gameRef': '/Lotus/Types/Recipes/Weapons/WeaponParts/ThingamajigBarrel',
     'tags': ['prime', 'component'], 'i18n': {'en': {'name': 'Thingamajig Barrel'}}},
    {'slug': 'whatsit_set', 'gameRef': '/Lotus/Weapons/Whatsit', 'tags': ['prime', 'set'],
     'i18n': {'en': {'name': 'Whatsit Set'}}},
    {'slug': 'whatsit_blueprint', 'gameRef': '/Lotus/Types/Recipes/Weapons/WhatsitBlueprint',
     'tags': ['prime', 'blueprint'], 'i18n': {'en': {'name': 'Whatsit Blueprint'}}},
    {'slug': 'whatsit_barrel', 'gameRef': '/Lotus/Types/Recipes/Weapons/WeaponParts/WhatsitBarrel',
     'tags': ['prime', 'component'], 'i18n': {'en': {'name': 'Whatsit Barrel'}}},
    {'slug': 'whatsit_stock', 'gameRef': '/Lotus/Types/Recipes/Weapons/WeaponParts/WhatsitStock',
     'tags': ['prime', 'component'], 'i18n': {'en': {'name': 'Whatsit Stock'}}},
    {'slug': 'whatchamacallit_set', 'gameRef': '/Lotus/Weapons/Whatchamacallit', 'tags': ['prime', 'set'],
     'i18n': {'en': {'name': 'Whatchamacallit Set'}}},
    {'slug': 'whatchamacallit_barrel',
     'gameRef': '/Lotus/Types/Recipes/Weapons/WeaponParts/WhatchamacallitBarrel',
     'tags': ['prime', 'component'], 'i18n': {'en': {'name': 'Whatchamacallit Barrel'}}},
    {'slug': 'orokin_cell', 'tags': ['resource'], 'i18n': {'en': {'name': 'Orokin Cell'}}},
]}

RECIPES_RAW = {
    '/Lotus/Types/Recipes/Weapons/WidgetPrimeBlueprint': {
        'resultType': '/Lotus/Weapons/WidgetPrime', 'num': 1, 'tradable': True, 'ingredients': [
            {'ItemType': '/Lotus/Types/Recipes/Weapons/WeaponParts/WidgetPrimeBarrel', 'ItemCount': 1},
            {'ItemType': '/Lotus/Types/Recipes/Weapons/WeaponParts/WidgetPrimeHandle', 'ItemCount': 1},
            {'ItemType': '/Lotus/Types/Items/MiscItems/OrokinCell', 'ItemCount': 10}]},
    '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeBlueprint': {
        'resultType': '/Lotus/Powersuits/GizmoPrime', 'num': 1, 'tradable': True, 'ingredients': [
            {'ItemType': '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeHelmetComponent', 'ItemCount': 1},
            {'ItemType': '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeChassisComponent', 'ItemCount': 1},
            {'ItemType': '/Lotus/Types/Items/MiscItems/Plastids', 'ItemCount': 500}]},
    '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeChassisBlueprint': {
        'resultType': '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeChassisComponent', 'num': 1,
        'tradable': True, 'ingredients': [
            {'ItemType': '/Lotus/Types/Items/MiscItems/Rubedo', 'ItemCount': 400}]},
    # the component recipe whose result the warframe recipe consumes (Helmet in game = Neuroptics on WFM)
    '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeHelmetBlueprint': {
        'resultType': '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeHelmetComponent', 'num': 1,
        'tradable': True, 'ingredients': [
            {'ItemType': '/Lotus/Types/Items/MiscItems/Rubedo', 'ItemCount': 750}]},
    # Akbronco-style: the recipe eats two built weapons
    '/Lotus/Types/Recipes/Weapons/GadgetPrimeBlueprint': {
        'resultType': '/Lotus/Weapons/GadgetPrime', 'num': 1, 'tradable': True, 'ingredients': [
            {'ItemType': '/Lotus/Weapons/WidgetPrime', 'ItemCount': 1},
            {'ItemType': '/Lotus/Weapons/WidgetPrime', 'ItemCount': 1},
            {'ItemType': '/Lotus/Types/Items/MiscItems/OrokinCell', 'ItemCount': 1}]},
    # component path no catalog gameRef names -> the name-derived slug fallback has to catch it
    '/Lotus/Types/Recipes/Weapons/DoohickeyBlueprint': {
        'resultType': '/Lotus/Weapons/Doohickey', 'num': 1, 'tradable': True, 'ingredients': [
            {'ItemType': '/Lotus/Types/Recipes/Weapons/WeaponParts/PrimeBowLowerLimb', 'ItemCount': 1}]},
    '/Lotus/Types/Recipes/Weapons/ThingamajigBlueprint': {
        'resultType': '/Lotus/Weapons/Thingamajig', 'num': 1, 'tradable': True, 'ingredients': [
            {'ItemType': '/Lotus/Types/Recipes/Weapons/WeaponParts/ThingamajigBarrel', 'ItemCount': 1},
            {'ItemType': '/Lotus/Types/Items/MiscItems/AlloyPlate', 'ItemCount': 150}]},
    '/Lotus/Types/Recipes/Weapons/WhatsitBlueprint': {
        'resultType': '/Lotus/Weapons/Whatsit', 'num': 1, 'tradable': True, 'ingredients': [
            {'ItemType': '/Lotus/Types/Recipes/Weapons/WeaponParts/WhatsitBarrel', 'ItemCount': 1},
            {'ItemType': '/Lotus/Types/Recipes/Weapons/WeaponParts/WhatsitStock', 'ItemCount': 1}]},
    # the account holds ONLY a component here: the trigger is 'owns the blueprint OR a component'
    '/Lotus/Types/Recipes/Weapons/WhatchamacallitBlueprint': {
        'resultType': '/Lotus/Weapons/Whatchamacallit', 'num': 1, 'tradable': True, 'ingredients': [
            {'ItemType': '/Lotus/Types/Recipes/Weapons/WeaponParts/WhatchamacallitBarrel', 'ItemCount': 1},
            {'ItemType': '/Lotus/Types/Items/MiscItems/Plastids', 'ItemCount': 100}]},
    # triggered (blueprint owned) but the assembled result is not a market item
    '/Lotus/Types/Recipes/Weapons/GhostedBlueprint': {
        'resultType': '/Lotus/Weapons/Ghosted', 'num': 1, 'tradable': False, 'ingredients': [
            {'ItemType': '/Lotus/Types/Recipes/Weapons/WeaponParts/WidgetPrimeBarrel', 'ItemCount': 1}]},
    # nothing owned at all: must never appear as a row or as a skip
    '/Lotus/Types/Recipes/Weapons/UntouchedPrimeBlueprint': {
        'resultType': '/Lotus/Weapons/UntouchedPrime', 'num': 1, 'tradable': True, 'ingredients': [
            {'ItemType': '/Lotus/Types/Items/MiscItems/Ferrite', 'ItemCount': 100}]},
}

OWNED = [
    {'slug': 'widget_prime_blueprint', 'name': 'Widget Prime Blueprint', 'count': 1,
     'path': '/Lotus/Types/Recipes/Weapons/WidgetPrimeBlueprint'},
    {'slug': 'widget_prime_barrel', 'name': 'Widget Prime Barrel', 'count': 1,
     'path': '/Lotus/Types/Recipes/Weapons/WeaponParts/WidgetPrimeBarrel'},
    {'slug': 'gizmo_prime_blueprint', 'name': 'Gizmo Prime Blueprint', 'count': 1,
     'path': '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeBlueprint'},
    {'slug': 'gadget_prime_blueprint', 'name': 'Gadget Prime Blueprint', 'count': 1,
     'path': '/Lotus/Types/Recipes/Weapons/GadgetPrimeBlueprint'},
    {'slug': 'widget_prime_set', 'name': 'Widget Prime Set', 'count': 1,
     'path': '/Lotus/Weapons/WidgetPrime'},                      # 1 of the 2 Gadget Prime needs
    {'slug': 'doohickey_blueprint', 'name': 'Doohickey Blueprint', 'count': 1,
     'path': '/Lotus/Types/Recipes/Weapons/DoohickeyBlueprint'},
    {'slug': 'thingamajig_blueprint', 'name': 'Thingamajig Blueprint', 'count': 1,
     'path': '/Lotus/Types/Recipes/Weapons/ThingamajigBlueprint'},
    {'slug': 'whatsit_blueprint', 'name': 'Whatsit Blueprint', 'count': 1,
     'path': '/Lotus/Types/Recipes/Weapons/WhatsitBlueprint'},
    {'slug': 'whatsit_barrel', 'name': 'Whatsit Barrel', 'count': 1,
     'path': '/Lotus/Types/Recipes/Weapons/WeaponParts/WhatsitBarrel'},
    {'slug': 'whatchamacallit_barrel', 'name': 'Whatchamacallit Barrel', 'count': 1,
     'path': '/Lotus/Types/Recipes/Weapons/WeaponParts/WhatchamacallitBarrel'},
    {'slug': 'ghosted_blueprint', 'name': 'Ghosted Blueprint', 'count': 1,
     'path': '/Lotus/Types/Recipes/Weapons/GhostedBlueprint'},
    {'slug': 'gizmo_prime_chassis_blueprint', 'name': 'Gizmo Prime Chassis Blueprint', 'count': 1,
     'path': '/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeChassisBlueprint'},
]

# no thingamajig_set and no whatsit_stock on purpose (those rows must SKIP on missing prices)
FLOORS = {'widget_prime_set': 40.0, 'widget_prime_barrel': 4.0, 'widget_prime_handle': 50.0,
          'gizmo_prime_set': 25.0, 'gizmo_prime_neuroptics_blueprint': 3.0,
          'gizmo_prime_chassis_blueprint': 7.0, 'gadget_prime_set': 15.0,
          'doohickey_set': 6.0, 'prime_bow_lower_limb': 6.0, 'thingamajig_barrel': 9.0,
          'whatsit_set': 30.0, 'whatchamacallit_set': 12.0, 'whatchamacallit_barrel': 5.0}


def _fixture_run():
    """Fixtures in memory -> everything analyse() needs (used by selftest and the tests)."""
    recipes, _ = normalize_recipes(RECIPES_RAW)
    index = build_indexes(CATALOG['data'], OWNED)
    res2slug = result2slug_index(recipes, index)
    owned_counts = {}
    for o in OWNED:
        owned_counts[o['slug']] = owned_counts.get(o['slug'], 0) + (o.get('count') or 1)
    rows, skipped, ignored, detail = analyse(recipes, index, res2slug, owned_counts, FLOORS)
    return dict(recipes=recipes, index=index, res2slug=res2slug, owned_counts=owned_counts,
                rows=rows, skipped=skipped, ignored=ignored, detail=detail, floors=FLOORS,
                by={r['result_slug']: r for r in rows})


def selftest():
    """Fully offline: fixtures in memory, no network, no files touched. -> 0 ok / 1 failed."""
    checks, out = [], []

    def check(name, ok):
        checks.append(bool(ok))
        out.append('%s %s' % ('PASS' if ok else 'FAIL', name))

    f = _fixture_run()
    rows, skipped, by = f['rows'], f['skipped'], f['by']
    names = {s['result_slug']: s['reason'] for s in skipped}

    # --- slug conversion
    check('slugify: Orokin Cell -> orokin_cell', slugify('Orokin Cell') == 'orokin_cell')
    check('slugify: punctuation collapses to one underscore',
          slugify('Cobra & Crane Prime') == 'cobra_crane_prime' and slugify('MK1-Braton') == 'mk1_braton'
          and slugify('  ') == '')
    check('name_from_path camel split',
          name_from_path('/Lotus/Types/Recipes/Weapons/WeaponParts/BurstonPrimeStock')
          == 'Burston Prime Stock')
    check('name_from_path keeps numerals', name_from_path('/Lotus/Types/Items/MK1Braton') == 'MK1 Braton')
    check('Helmet component -> neuroptics blueprint slug',
          part_slug('/Lotus/Types/Recipes/WarframeRecipes/GizmoPrimeHelmetComponent',
                    f['index'], f['res2slug']) == 'gizmo_prime_neuroptics_blueprint')
    check('a resource slug is never treated as a part',
          not is_market_part('orokin_cell', f['index'])
          and is_market_part('widget_prime_barrel', f['index']))
    check('name-fallback slug for a generic component path',
          part_slug('/Lotus/Types/Recipes/Weapons/WeaponParts/PrimeBowLowerLimb',
                    f['index'], f['res2slug']) == 'prime_bow_lower_limb')

    # --- verdicts
    check('BUY when the missing parts cost more than the assembled item',
          by['widget_prime_set']['verdict'] == 'BUY'
          and (by['widget_prime_set']['built_floor'], by['widget_prime_set']['buy_cost'],
               by['widget_prime_set']['profit']) == (40.0, 50.0, -10.0))
    check('CRAFT when the assembled item costs more',
          by['gizmo_prime_set']['verdict'] == 'CRAFT'
          and (by['gizmo_prime_set']['buy_cost'], by['gizmo_prime_set']['profit']) == (3.0, 22.0)
          and [p['slug'] for p in by['gizmo_prime_set']['missing_parts']]
          == ['gizmo_prime_neuroptics_blueprint'])
    check('CRAFT at break-even (profit 0)',
          by['doohickey_set']['verdict'] == 'CRAFT' and by['doohickey_set']['profit'] == 0.0)
    check('a component alone is enough to trigger a row',
          by['whatchamacallit_set']['verdict'] == 'CRAFT'
          and by['whatchamacallit_set']['missing_parts'] == []
          and by['whatchamacallit_set']['owned_parts'] == ['whatchamacallit_barrel']
          and by['whatchamacallit_set']['profit'] == 12.0)
    check('count-aware shortfall (2 needed, 1 owned -> 1)',
          by['gadget_prime_set']['buy_cost'] == 40.0
          and [p['slug'] for p in by['gadget_prime_set']['missing_parts']] == ['widget_prime_set']
          and by['gadget_prime_set']['profit'] == -25.0)
    check('owned_parts list held components (short ones too)',
          by['widget_prime_set']['owned_parts'] == ['widget_prime_barrel']
          and by['gadget_prime_set']['owned_parts'] == ['widget_prime_set'])
    check('unpriced assembled result -> SKIP',
          by['thingamajig_set']['verdict'] == 'SKIP'
          and by['thingamajig_set']['built_floor'] is None and by['thingamajig_set']['profit'] is None
          and by['thingamajig_set']['buy_cost'] == 9.0
          and names.get('thingamajig_set', '').startswith('no price for the assembled'))
    check('unpriced missing part -> SKIP',
          by['whatsit_set']['verdict'] == 'SKIP'
          and [p['slug'] for p in by['whatsit_set']['missing_parts']] == ['whatsit_stock']
          and by['whatsit_set']['missing_parts'][0]['floor'] is None
          and names.get('whatsit_set', '').startswith('no price for missing part'))
    check('resource-only recipe -> SKIP with a note',
          names.get('gizmo_prime_chassis_blueprint', '').startswith('resource-only'))

    # --- trigger + ingestion
    check('only triggered recipes become rows (8)',
          len(rows) == 8 and 'untouched_prime_set' not in by
          and not any('Untouched' in s['recipe'] for s in skipped))
    check('owned blueprint with an off-market result -> skipped, no row',
          names.get('ghosted_blueprint', '').startswith('assembled result is not on')
          and 'ghosted_blueprint' not in by)
    check('resources never priced, always noted (spaced tails)',
          f['ignored'].get('Orokin Cell') == 2 and f['ignored'].get('Plastids') == 2
          and f['ignored'].get('Rubedo') == 1 and f['ignored'].get('Alloy Plate') == 1)
    check('live targets = missing parts + unpriced results',
          price_targets(f['recipes'], f['index'], f['res2slug'], f['owned_counts'], FLOORS)
          == ['thingamajig_set', 'whatsit_stock'])
    check('live cache is reused without any call',
          live_floors(['whatsit_stock'], {}, cached={'whatsit_stock': {'wts': 12}},
                      max_calls=0, sleep=0, log=lambda *a: None)[0] == {'whatsit_stock': 12.0})

    # --- contract + invariants
    summary = dict(craft=len([r for r in rows if r['verdict'] == 'CRAFT']),
                   buy=len([r for r in rows if r['verdict'] == 'BUY']),
                   skip=len([r for r in rows if r['verdict'] == 'SKIP']), total=len(rows))
    for k, v in self_check(rows, skipped, summary, f['detail']).items():
        check('self_check.' + k, v)
    check('rows are ordered CRAFT -> BUY -> SKIP',
          [r['verdict'] for r in rows] == sorted([r['verdict'] for r in rows],
                                                 key=lambda v: VERDICTS.index(v)))
    check('row keys are exactly the documented eight',
          all(set(r) == {'result_name', 'result_slug', 'built_floor', 'buy_cost', 'profit',
                         'missing_parts', 'owned_parts', 'verdict'} for r in rows))
    check('missing_parts carry slug+floor only',
          all(set(p) == {'slug', 'floor'} for r in rows for p in r['missing_parts']))
    check('display names come from the catalog',
          by['widget_prime_set']['result_name'] == 'Widget Prime Set')
    no_owned = dict(f['owned_counts'])
    no_owned.pop('widget_prime_set')                 # now the 2x part is short twice over
    r2 = {r['result_slug']: r for r in analyse(f['recipes'], f['index'], f['res2slug'], no_owned,
                                               FLOORS)[0]}['gadget_prime_set']
    check('a part needed twice is bought twice (2 x 40)',
          r2['buy_cost'] == 80.0 and r2['profit'] == -65.0)
    tampered = [dict(r) for r in rows]
    tampered[0] = dict(tampered[0], buy_cost=tampered[0]['buy_cost'] + 1)
    check('self_check catches a tampered buy_cost',
          self_check(tampered, skipped, summary, f['detail'])['buy_cost_matches_parts'] is False)

    # --- cache/fetch failsafe: clear note, exit 0, nothing written
    saved = globals()['DATA']
    real_fetch = globals()['fetch_recipes']
    tmp = tempfile.mkdtemp(prefix='craft_selftest_')
    try:
        globals()['DATA'] = tmp
        recs, note = load_recipes(refresh=True, offline=True)
        check('offline with no cache -> clear note, no write',
              recs is None and 'no data/recipes_cache.json' in note and not os.listdir(tmp))
        globals()['fetch_recipes'] = lambda urls=RECIPE_URLS: (None, 'simulated: Recipes.json -> http 404')
        recs, note = load_recipes(refresh=True, offline=False)
        check('dead recipe source -> note, no write, no traceback',
              recs is None and 'fetch failed' in note and 'Recipes.json -> http 404' in note
              and not os.listdir(tmp))
        save_json(os.path.join(tmp, RECIPE_CACHE), {'schema': CACHE_SCHEMA, 'count': 1,
                                                    'recipes': {'/p': {'result': '/r', 'num': 1,
                                                                       'tradable': True,
                                                                       'ingredients': [['/i', 1]]}}})
        recs, note = load_recipes(refresh=True, offline=False)
        check('failed refresh keeps serving the cached recipes',
              list(recs) == ['/p'] and note.startswith('refresh failed'))
        globals()['fetch_recipes'] = real_fetch
        save_json(os.path.join(tmp, 'x.json'), {'a': 1})
        check('atomic write lands intact and leaves no .tmp',
              json.load(open(os.path.join(tmp, 'x.json'), encoding='utf-8')) == {'a': 1}
              and not os.path.exists(os.path.join(tmp, 'x.json.tmp')))
    finally:
        globals()['DATA'] = saved
        globals()['fetch_recipes'] = real_fetch
        shutil.rmtree(tmp, ignore_errors=True)

    failed = len(checks) - sum(checks)
    print('\n'.join(out))
    print('selftest %s (%d checks, %d failed, offline fixtures - no network, no repo files touched)'
          % ('OK' if not failed else 'FAILED', len(checks), failed))
    return 0 if not failed else 1


# --------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description='Craft-profit calculator: build it, or buy it?')
    ap.add_argument('--live', action='store_true',
                    help='price missing parts / assembled results live via warframe.market /top')
    ap.add_argument('--live-max', type=int, default=LIVE_MAX,
                    help='cap live /top calls this run (default %d)' % LIVE_MAX)
    ap.add_argument('--refresh-live', action='store_true',
                    help='ignore the live prices cached in craft.json')
    ap.add_argument('--refresh', action='store_true', help='refetch the WFCD recipe source')
    ap.add_argument('--offline', action='store_true', help='never touch the network (cache only)')
    ap.add_argument('--sleep', type=float, default=SLEEP,
                    help='seconds between /top calls (default %.2f)' % SLEEP)
    ap.add_argument('--limit', type=int, default=0, help='debug: trim the printed report to N rows')
    ap.add_argument('--selftest', action='store_true', help='offline fixture selftest, writes nothing')
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    catalog = ((load('wfm_items_v2.json') or {}).get('data') or [])
    owned = load('owned.json', []) or []
    prices = load('prices.json', {}) or {}
    if not catalog or not owned:
        print('craft: data/wfm_items_v2.json and data/owned.json are required (run scripts/refresh.py)')
        return 0
    recipes, note = load_recipes(refresh=args.refresh, offline=args.offline)
    if recipes is None:
        print('craft: no crafting recipes available - %s' % note)
        print('       sources tried: %s' % ' > '.join(RECIPE_URLS))
        print('       nothing written; data/%s left untouched' % OUT)
        return 0

    index = build_indexes(catalog, owned)
    res2slug = result2slug_index(recipes, index)
    owned_counts = {}
    for o in owned:
        owned_counts[o['slug']] = owned_counts.get(o['slug'], 0) + (o.get('count') or 1)
    floors = {}
    for s, e in prices.items():                       # prices.json wins over any live cache
        f = floor_of(e)
        if f is not None:
            floors[s] = f
    catalog_by_slug = {i['slug']: i for i in catalog}

    prev_live = (load(OUT, {}) or {}).get('live_prices') or {}
    live_doc, live_note = {}, 'off'
    if args.live and not args.offline:
        want = price_targets(recipes, index, res2slug, owned_counts, floors)
        fresh, stats = live_floors(want, catalog_by_slug,
                                   cached={} if args.refresh_live else prev_live,
                                   max_calls=args.live_max, sleep=args.sleep)
        for s, f in fresh.items():
            floors.setdefault(s, f)
        for s, f in fresh.items():
            at = (prev_live.get(s) or {}).get('at')
            live_doc[s] = dict(wts=f, at=at if at and (prev_live.get(s) or {}).get('wts') == f else utc_stamp())
        for s, e in prev_live.items():
            live_doc.setdefault(s, e)
        live_note = ('/top: %d slugs known (%d reused, %d fetched, %d unpriced)'
                     % (stats['known'], stats['cache_hits'], stats['calls'], len(stats['errors'])))
        if stats['errors']:
            print('live /top left %d slug(s) unpriced, first: %s' % (len(stats['errors']), stats['errors'][0]))
    else:
        live_doc = prev_live
        for s, e in live_doc.items():                 # reruns stay useful offline
            f = floor_of(e)
            if f is not None:
                floors.setdefault(s, f)
        live_note = ('%d live prices reused from an earlier run' % len(live_doc) if live_doc
                     else 'off (no live prices cached; run --live to price missing parts)')

    rows, skipped, ignored, detail = analyse(recipes, index, res2slug, owned_counts, floors)
    summary = dict(craft=len([r for r in rows if r['verdict'] == 'CRAFT']),
                   buy=len([r for r in rows if r['verdict'] == 'BUY']),
                   skip=len([r for r in rows if r['verdict'] == 'SKIP']),
                   total=len(rows), prices=live_note, missing_units=len({p['slug'] for r in rows
                                                                        for p in r['missing_parts']}),
                   missing_plat=round(sum(r['buy_cost'] for r in rows), 1),
                   assembled_plat=round(sum(r['built_floor'] or 0 for r in rows), 1),
                   multi_unit_parts=sorted([dict(result_slug=s, part=p, need=d['units'][p],
                                                 owned=d['have'].get(p, 0))
                                            for s, d in detail.items() for p in d['units'] if d['units'][p] > 1],
                                           key=lambda x: x['result_slug'])[:20])
    summary['note'] = ('%d rows: %d craft / %d buy / %d skip. buy_cost = floors of the MISSING market '
                       'parts; built_floor = sell floor of the assembled result (<item>_set, because '
                       'built warframes/weapons are not tradeable); profit = built_floor - buy_cost and '
                       'a negative number means buy the assembled item instead. In-game resources are '
                       'never priced.'
                       % (summary['total'], summary['craft'], summary['buy'], summary['skip']))
    doc = dict(
        generated=utc_stamp(),
        source=('WFCD recipes (%s) + data/wfm_items_v2.json catalog + data/owned.json + data/prices.json'
                % note),
        params=dict(live=bool(args.live and not args.offline), live_max=args.live_max, sleep=args.sleep,
                    offline=args.offline, recipe_urls=list(RECIPE_URLS)),
        assumptions=[
            'a recipe becomes a row only when the account owns its blueprint or >= 1 of its parts',
            'buy_cost prices WARFRAME.MARKET parts only: in-game resources (Orokin Cell, Plastids, '
            'Rubedo, ...) are left out of the maths and listed under ignored_ingredients',
            'units are count-aware: a recipe needing 2 of a part the account owns 1 of buys the shortfall',
            'built_floor is the assembled result as the market trades it (the <item>_set bundle); '
            'WFM does not trade built warframes/weapons themselves',
            'a missing part with no market price makes the row SKIP instead of guessing a cost',
            'floors are lowest visible sell listings (prices.json wts, or live /top with --live)'],
        summary=summary, self_check={}, skipped=skipped,
        ignored_ingredients=dict(sorted(ignored.items(), key=lambda kv: -kv[1])),
        live_prices=live_doc, rows=rows)
    doc['self_check'] = self_check(rows, skipped, summary, detail)
    save_json(os.path.join(DATA, OUT), doc)
    if args.limit:
        doc = dict(doc, rows=rows[:args.limit], skipped=skipped[:args.limit])
        note += '  [report trimmed to %d rows]' % args.limit
    report(doc, note)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
