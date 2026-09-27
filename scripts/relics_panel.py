#!/usr/bin/env python3
r"""Relics panel - Collection > Relics: where each relic comes from AND what it contains.

Inputs (read-only)
  data/dropdata/items/Relics.json   WFCD warframe-items relic table: one row per relic per
                                    refinement (3204 rows).  scripts/obtain_index.py caches it
                                    under this path; when the cache is missing this script
                                    fetches the same file once (--offline forbids it,
                                    --refresh ignores the cache) so a fresh install - data/
                                    is gitignored - still gets a store.
  data/owned.json                   the account inventory; relic rows carry slug / name /
                                    path (== the relic's uniqueName) / refinement / count.
  data/relic_ev.json                scripts/relic_ev.py output: one row per owned relic +
                                    refinement with EV and an OPEN/SELL/HOLD verdict. Optional.
  data/prices.json                  warframe.market snapshot for owned slugs (wts/wtb).
                                    Optional - the store then carries no market block.
Output
  data/relics_panel.json            the store the Collection > Relics tab reads
  static/relics_panel.json          copy of the same payload, because server.py serves only
                                    static/ (--no-static-copy skips it)

Store shape (schema 1)
  schema, updated, updated_iso, count (base relics), source, generated_from,
  summary {farmable, vaulted, owned_distinct, owned_stacks, refinements}, tiers {tier: count},
  relics[].  One relic:
    name (base name), tier, slug, vaulted, uniqueNames {refinement: uniqueName},
    owned {refinement: count}, owned_total, rewards {refinement: [{item, slug, rarity, chance}]},
    best_reward {item, slug, rarity, chance_radiant} | null, market {slug, wts, wtb, median,
    as_of} | null, ev {refinement: {ev, verdict} | null}, obtain {kind, lines, note, complete}.

Rules
  * rewards come straight from Relics.json per refinement - chances are never rescaled and
    never invented; a refinement whose table is missing stays missing (an empty rewards list
    is still published when the table itself is empty).
  * owned is joined on uniqueName EXACTLY (owned.json 'path' == Relics.json 'uniqueName',
    never by name); a refinement nobody owns stays 0 and the relic is still listed.
  * obtain.kind is 'drop' when Relics.json locations[] has entries (the real "where to get
    it" data), 'vaulted' when every refinement is vaulted and there are no locations, and
    'unknown' for the generic placeholder entries ('Axi Relic' ...) whose row carries no
    refinements, no rewards, no locations and not even a vaulted flag.  A vaulted relic never
    claims a drop location - there is no current source and the store never invents one.
  * obtain keeps the collection log's payload shape (kind / lines of label + detail / note /
    complete) so the collection page's hover card can render a relic unchanged.  complete is
    True when the payload answers the question with everything the data has (a drop relic
    lists every location row; a vaulted relic's answer is complete), False when the data
    cannot answer it (a placeholder).
  * farmable = every relic that is not fully vaulted, so the 6 generic placeholders land
    there; obtain.kind is what separates drop / vaulted / unknown.

Data quirks (verified against the shipped file, 2026-09-27)
  * 'Lith G12' carries two internal variants per refinement (Sevagoth Prime D/E).  The first
    uniqueName is published in uniqueNames, rewards are identical, and owned counts every
    variant - a variant the store did not publish still counts when the account owns it.
  * 'Requiem Eterna Relic' has no refinement suffix in WFCD and an empty locations[]; its two
    Kuva sources live in a top-level drops[] array.  It keeps kind 'vaulted' (its own vaulted
    flag) and its note names those sources instead of claiming there are none.
  * 6 entries ('Axi Relic', 'Lith Relic', 'Meso Relic', 'Neo Relic', 'Requiem Relic',
    'Void Relic' - 'Void Relic' twice) have no 'vaulted' key at all: the placeholders above.

Env overrides (tests): WFM_DATA_DIR (data dir), WFM_STATIC_DIR (static dir).
CLI: --once (default) | --out PATH | --json | --dry-run | --offline | --refresh |
     --no-static-copy | --selftest
Exit codes: 0 ok, 1 no relic table, 2 selftest failure.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get('WFM_DATA_DIR') or os.path.join(ROOT, 'data')
STATIC = os.environ.get('WFM_STATIC_DIR') or os.path.join(ROOT, 'static')

SCHEMA = 1
REFINEMENTS = ['Intact', 'Exceptional', 'Flawless', 'Radiant']     # the four we key on
TIER_ORDER = ['Lith', 'Meso', 'Neo', 'Axi', 'Requiem', 'Vanguard', 'Void']
SOURCE = 'WFCD warframe-items Relics.json + data/owned.json + data/relic_ev.json + data/prices.json'
RELICS_URL = 'https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/Relics.json'
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'
TIMEOUT = 60

# notes render in the hover card, so they stay at label length (Jay, 2026-09-27: no prose)
VAULTED_NOTE = 'Vaulted'
PLACEHOLDER_NOTE = 'placeholder entry - no drop table, no rewards'
NO_SOURCE_NOTE = 'no drop source'


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
    return datetime.fromtimestamp(int(epoch), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


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


def slugify(name):
    """'Lith F1' -> 'lith_f1' (the dashboard-wide slug rule, owned.json / prices.json keys)."""
    s = str(name or '').strip().lower().replace('&', ' and ')
    return re.sub(r'[^a-z0-9]+', '_', s).strip('_')


def num_or_none(value):
    """int/float (bools rejected) else None - a snapshot cell that was never a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def fmt_num(value):
    """0.29 -> '0.29', 13 -> '13', 3.0 -> '3' (display only; None stays None)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value == int(value):
        return str(int(value))
    return ('%f' % value).rstrip('0').rstrip('.')


def strip_refinement(name):
    """'Axi A1 Exceptional' -> ('Axi A1', 'Exceptional'); no suffix -> (name, None)."""
    for ref in REFINEMENTS:
        suffix = ' ' + ref
        if name.endswith(suffix):
            return name[:-len(suffix)], ref
    return name, None


def relic_slug(base):
    """'Lith F1' -> 'lith_f1_relic' (the market/owned slug; 'Requiem Eterna Relic' kept as is)."""
    return slugify(base if base.endswith('Relic') else base + ' Relic')


# --------------------------------------------------------------------- paths
def dropdata_path():
    return os.path.join(DATA, 'dropdata', 'items', 'Relics.json')


def out_path():
    return os.path.join(DATA, 'relics_panel.json')


def static_copy_path():
    return os.path.join(STATIC, 'relics_panel.json')


def owned_path():
    return os.path.join(DATA, 'owned.json')


def ev_path():
    return os.path.join(DATA, 'relic_ev.json')


def prices_path():
    return os.path.join(DATA, 'prices.json')


def file_meta(path, count=None):
    """{'path', 'present', 'mtime_iso', 'bytes', 'count'} - what a store input really is."""
    meta = {'path': rel(path), 'present': os.path.exists(path)}
    if not meta['present']:
        return meta
    meta['mtime_iso'] = iso_z(os.path.getmtime(path))
    meta['bytes'] = os.path.getsize(path)
    if count is not None:
        meta['count'] = count
    return meta


def valid_relic_table(doc):
    """True when doc looks like the WFCD relic table (a non-empty list of named rows)."""
    if not isinstance(doc, list) or not doc:
        return False
    row = doc[0]
    return (isinstance(row, dict) and isinstance(row.get('name'), str) and row.get('name')
            and isinstance(row.get('uniqueName'), str) and row.get('uniqueName')
            and 'rewards' in row)


def fetch_json(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8', 'replace'))


# --------------------------------------------------------------------- inputs
def load_relics(offline=False, refresh=False, write=True, path=None):
    """(entries | None, meta) - the WFCD relic table, from the dropdata cache or the CDN.

    The cache is only re-fetched when it is missing or unreadable (--refresh forces it);
    --offline never touches the network.  `write` is False on --dry-run, so a dry run fetches
    (when needed) but caches nothing.
    """
    path = path or dropdata_path()
    error = None
    if not refresh:
        doc = jload(path)
        if valid_relic_table(doc):
            return doc, dict(file_meta(path, len(doc)), cached=True)
        error = ('no readable relic table at %s' % rel(path) if doc is None
                 else '%s is not a WFCD relic table' % rel(path))
    if offline:
        return None, dict(file_meta(path), cached=False,
                          error=(error or '--refresh --offline: nothing to read') + ' (offline)')
    try:
        doc = fetch_json(RELICS_URL)
    except Exception as exc:                            # noqa: BLE001 - network/parse anything
        return None, dict(file_meta(path), cached=False,
                          error='%s: %s - %s' % (type(exc).__name__, exc, error or RELICS_URL))
    if not valid_relic_table(doc):
        return None, dict(file_meta(path), cached=False,
                          error='%s is not a WFCD relic table' % RELICS_URL)
    if write:
        atomic_write(path, doc)
    return doc, {'path': rel(path), 'present': True, 'cached': False, 'url': RELICS_URL,
                 'fetched': int(time.time()), 'fetched_iso': iso_z(time.time()),
                 'entries': len(doc)}


def load_owned(path=None):
    """(rows, meta) - owned.json's relic stacks (tag 'relic', with a uniqueName path)."""
    path = path or owned_path()
    doc = jload(path, [])
    if isinstance(doc, dict):
        doc = list(doc.values())
    rows = [r for r in (doc or []) if isinstance(r, dict) and r.get('path')
            and 'relic' in {str(t).lower() for t in (r.get('tags') or [])}]
    meta = file_meta(path, len(rows))
    meta['rows'] = len(doc or [])
    return rows, meta


def load_ev(path=None):
    """(rows, meta) - relic_ev.json's per relic+refinement EV rows (optional input)."""
    path = path or ev_path()
    doc = jload(path, None)
    rows = doc.get('rows') if isinstance(doc, dict) else None
    rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    meta = file_meta(path, len(rows))
    if isinstance(doc, dict) and doc.get('generated'):
        meta['generated'] = doc['generated']           # relic_ev.json's own stamp
    return rows, meta


def load_prices(path=None):
    """(prices, meta) - the price snapshot; meta.as_of is the file's mtime (no stamp inside)."""
    path = path or prices_path()
    doc = jload(path, {})
    prices = doc if isinstance(doc, dict) else {}
    meta = file_meta(path, len(prices))
    meta['rows'] = len(prices)
    if meta.get('present'):
        meta['as_of'] = meta['mtime_iso']
    return prices, meta


# --------------------------------------------------------------------- rows
def reward_rows(rewards):
    """One refinement's reward table, verbatim: [{item, slug, rarity, chance}, ...].

    slug is the warframe.market urlName (the UI links items by it); a reward the market does
    not carry (Forma Blueprint, Kuva, ...) keeps slug null - a made-up slug would 404.
    """
    out = []
    for rew in rewards or []:
        if not isinstance(rew, dict):
            continue
        item = rew.get('item') if isinstance(rew.get('item'), dict) else {}
        market = item.get('warframeMarket') if isinstance(item.get('warframeMarket'), dict) else {}
        out.append({'item': item.get('name'), 'slug': market.get('urlName') or None,
                    'rarity': rew.get('rarity'), 'chance': num_or_none(rew.get('chance'))})
    return out


def best_reward_of(radiant_rows):
    """The radiant table's chase item: the Rare slot (one per table), else the rarest row."""
    if not radiant_rows:
        return None
    rare = [r for r in radiant_rows if str(r.get('rarity') or '').lower() == 'rare']
    pool = rare or radiant_rows
    pick = min(pool, key=lambda r: (r.get('chance') if r.get('chance') is not None else 101,
                                    str(r.get('item') or '')))
    return {'item': pick['item'], 'slug': pick['slug'], 'rarity': pick['rarity'],
            'chance_radiant': pick['chance']}


def obtain_lines(rows):
    """locations[] -> [{label, detail}, ...], highest chance first.

    label is the location string verbatim, detail is '<chance>% · <rarity>' - the same shape
    the collection page's hover card already renders.  The same row repeated across
    refinements (WFCD lists identical locations for every refinement) collapses to one line.
    """
    seen, lines = set(), []
    for _ref, entry in rows:
        for loc in (entry.get('locations') or []):
            if not isinstance(loc, dict):
                continue
            label = loc.get('location')
            if not isinstance(label, str) or not label:
                continue
            chance = num_or_none(loc.get('chance'))
            detail = '%s%% \u00b7 %s' % (fmt_num(chance) if chance is not None else '?',
                                         loc.get('rarity') or '?')
            if (label, detail) in seen:
                continue
            seen.add((label, detail))
            lines.append({'label': label, 'detail': detail,
                          'chance': chance if chance is not None else -1.0})
    lines.sort(key=lambda r: (-r['chance'], r['label']))
    return [{'label': r['label'], 'detail': r['detail']} for r in lines]


def build_obtain(base, rows):
    """The relic's 'where to get it' payload (kind / lines / note / complete)."""
    lines = obtain_lines(rows)
    if lines:
        return {'kind': 'drop', 'lines': lines, 'note': None, 'complete': True}
    entries = [entry for _ref, entry in rows]
    no_ref = not any(ref in REFINEMENTS for ref, _entry in rows)
    if (no_ref and not any(entry.get('rewards') for entry in entries)
            and not any(entry.get('locations') for entry in entries)
            and not any('vaulted' in entry for entry in entries)):
        return {'kind': 'unknown', 'lines': [], 'note': PLACEHOLDER_NOTE, 'complete': False}
    if entries and all(entry.get('vaulted') for entry in entries):
        # the WFCD 'drops' array (only 'Requiem Eterna Relic' has one without locations[])
        # names real sources, so the note must not claim the data lists none.
        sources = []
        for entry in entries:
            for drop in (entry.get('drops') or []):
                loc = drop.get('location') if isinstance(drop, dict) else None
                if isinstance(loc, str) and loc and loc not in sources:
                    sources.append(loc)
        note = VAULTED_NOTE
        if sources:
            note = 'Vaulted - %s' % ' / '.join(sources[:3])
        return {'kind': 'vaulted', 'lines': [], 'note': note, 'complete': True}
    return {'kind': 'unknown', 'lines': [], 'note': NO_SOURCE_NOTE, 'complete': False}


# --------------------------------------------------------------------- store
def build_store(entries, owned_rows, ev_rows, prices=None, prices_as_of=None, now=None,
                sources=None):
    """(doc, stats) - the data/relics_panel.json payload from raw input rows.

    entries    raw WFCD Relics.json rows (one per relic per refinement)
    owned_rows raw owned.json relic rows (path == uniqueName, refinement, count)
    ev_rows    raw relic_ev.json rows (optional; [] when the file is absent)
    prices     {slug: {wts, wtb, ...}} from data/prices.json (optional)
    sources    per-input provenance blocks from main() (paths / mtimes), or {} for tests
    """
    sources = sources or {}
    prices = prices or {}
    now = int(time.time() if now is None else now)

    groups = {}                                         # base name -> [(refinement|None, row)]
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        name, uniq = entry.get('name'), entry.get('uniqueName')
        if not isinstance(name, str) or not name or not isinstance(uniq, str) or not uniq:
            continue
        base, refinement = strip_refinement(name)
        groups.setdefault(base, []).append((refinement, entry))

    path_base = {}                                      # every uniqueName -> its base relic
    for base, rows in groups.items():
        for _ref, entry in rows:
            path_base[entry['uniqueName']] = base

    owned_by_base, unmatched, no_ref_label, stacks = {}, [], [], 0
    for row in owned_rows or []:
        base = path_base.get(row.get('path'))
        if base is None:
            unmatched.append(row.get('slug') or row.get('name') or '?')
            continue
        refinement = row.get('refinement')
        if refinement not in REFINEMENTS:
            no_ref_label.append(row.get('slug') or '?')
            continue
        count = row.get('count') if isinstance(row.get('count'), int) \
            and not isinstance(row.get('count'), bool) else 1
        owned = owned_by_base.setdefault(base, {})
        owned[refinement] = owned.get(refinement, 0) + count
        stacks += 1

    ev_index = {}
    for row in ev_rows or []:
        slug, refinement = row.get('slug'), row.get('refinement')
        if slug and isinstance(refinement, str):
            ev_index[(str(slug), refinement.lower())] = row

    relics, dup_variants = [], []
    for base, rows in groups.items():
        first = {}                                      # refinement -> first row of the base
        variants = {}                                   # refinement -> [every uniqueName]
        for refinement, entry in rows:
            if refinement not in REFINEMENTS:
                continue
            first.setdefault(refinement, entry)
            names = variants.setdefault(refinement, [])
            if entry['uniqueName'] not in names:
                names.append(entry['uniqueName'])
        unique_names = {ref: first[ref]['uniqueName'] for ref in REFINEMENTS if ref in first}
        rewards = {ref: reward_rows(first[ref].get('rewards')) for ref in REFINEMENTS if ref in first}
        if any(len(names) > 1 for names in variants.values()):
            dup_variants.append(base)

        owned = {ref: 0 for ref in unique_names}        # unmatched refinements stay 0
        for ref, count in (owned_by_base.get(base) or {}).items():
            owned[ref] = owned.get(ref, 0) + count      # adds labels owned.json carries alone

        slug = relic_slug(base)
        ev = {}
        for ref in owned:
            row = ev_index.get((slug, ref.lower()))
            ev[ref] = ({'ev': row.get('ev_unit_wts'), 'verdict': row.get('action')}
                       if row else None)

        prow = prices.get(slug) if isinstance(prices.get(slug), dict) else None
        market = None
        if prow is not None:
            wts, wtb = num_or_none(prow.get('wts')), num_or_none(prow.get('wtb'))
            if wts is not None and wtb is not None:
                median = round((wts + wtb) / 2.0, 2)
            else:
                median = wts if wts is not None else wtb
            market = {'slug': slug, 'wts': wts, 'wtb': wtb, 'median': median,
                      'as_of': prices_as_of}

        entries_of_base = [entry for _ref, entry in rows]
        vaulted = bool(entries_of_base) and all(bool(e.get('vaulted')) for e in entries_of_base)
        relics.append({
            'name': base,
            'tier': base.split(' ', 1)[0],
            'slug': slug,
            'vaulted': vaulted,
            'uniqueNames': unique_names,
            'owned': owned,
            'owned_total': sum(owned.values()),
            'rewards': rewards,
            'best_reward': best_reward_of(rewards.get('Radiant') or []),
            'market': market,
            'ev': ev,
            'obtain': build_obtain(base, rows),
        })

    tier_rank = {tier: i for i, tier in enumerate(TIER_ORDER)}
    relics.sort(key=lambda r: (tier_rank.get(r['tier'], len(TIER_ORDER)), r['name'].lower(),
                               r['name']))
    tiers = {}
    for relic in relics:
        tiers[relic['tier']] = tiers.get(relic['tier'], 0) + 1
    tiers = {t: tiers[t] for t in sorted(tiers, key=lambda t: (tier_rank.get(t, 99), t))}

    stats = {
        'count': len(relics),
        'farmable': sum(1 for r in relics if not r['vaulted']),
        'vaulted': sum(1 for r in relics if r['vaulted']),
        'drop_located': sum(1 for r in relics if r['obtain']['kind'] == 'drop'),
        'owned_distinct': sum(1 for r in relics if r['owned_total'] > 0),
        'owned_stacks': stacks,
        'unmatched': len(unmatched),
    }

    notes = [
        'rewards are WFCD Relics.json per refinement, verbatim - chances are never rescaled.',
        'obtain lines are the WFCD locations[] rows (label = location, detail = chance% · '
        'rarity), highest chance first; rows repeated across refinements collapse to one line.',
        'farmable counts every relic that is not fully vaulted - the 6 generic placeholder '
        'entries land there; obtain.kind separates drop / vaulted / unknown.',
        "market.median is the midpoint of the snapshot wts/wtb (data/prices.json has no median "
        "of its own); market.as_of is that file's mtime.",
        'ev = data/relic_ev.json: per relic+refinement unit EV in platinum and its '
        'OPEN/SELL/HOLD verdict (null while that relic+refinement has no EV row).',
    ]
    if not ev_rows:
        notes.append('no data/relic_ev.json rows - run scripts/relic_ev.py to fill the ev block.')
    if not prices:
        notes.append('no data/prices.json - run scripts/fetch_prices.py to fill the market block.')
    if dup_variants:
        notes.append('%d relic(s) carry several internal variants per refinement %s: uniqueNames '
                     'publishes the first, owned counts every variant.'
                     % (len(dup_variants), '(%s)' % ', '.join(dup_variants[:5])))
    if no_ref_label:
        notes.append('%d owned relic stack(s) carried no refinement label and were not counted '
                     '(%s).' % (len(no_ref_label), ', '.join(no_ref_label[:5])))
    if unmatched:
        notes.append('%d owned relic stack(s) are not in the relic table (%s).'
                     % (len(unmatched), ', '.join(unmatched[:5])))

    generated_from = {
        'relics': dict(sources.get('relics') or {}, rows=len(entries or []),
                       base_relics=len(groups)),
        'owned': dict(sources.get('owned') or {}, relic_rows=len(owned_rows or []),
                      matched=stacks, unmatched=unmatched[:20]),
        'relic_ev': dict(sources.get('relic_ev') or {}, rows=len(ev_rows or [])),
        'prices': dict(sources.get('prices') or {}, rows=len(prices), as_of=prices_as_of),
        'notes': notes,
    }
    doc = {
        'schema': SCHEMA,
        'updated': now,
        'updated_iso': iso_z(now),
        'count': len(relics),
        'source': SOURCE,
        'generated_from': generated_from,
        'summary': {
            'farmable': stats['farmable'],
            'vaulted': stats['vaulted'],
            'owned_distinct': stats['owned_distinct'],
            'owned_stacks': stats['owned_stacks'],
            'refinements': list(REFINEMENTS),
        },
        'tiers': tiers,
        'relics': relics,
    }
    return doc, stats


def summary_line(stats):
    """'relics_panel: 805 relics | farmable 40 | vaulted 765 | owned 134 stacks | drop-located 34'"""
    return ('relics_panel: %d relics | farmable %d | vaulted %d | owned %d stacks | drop-located %d'
            % (stats['count'], stats['farmable'], stats['vaulted'], stats['owned_stacks'],
               stats['drop_located']))


# --------------------------------------------------------------------- selftest
def _fixture_relics():
    """A miniature Relics.json: a farmable relic, a vaulted one, two variants, a placeholder."""
    def rewards(rare_chance, rare_market=True):
        rare = {'chance': rare_chance, 'rarity': 'Rare',
                'item': {'name': 'Akstiletto Prime Barrel',
                         'uniqueName': '/Lotus/Types/Recipes/Weapons/WeaponParts/AkstilettoPrimeBarrel'}}
        if rare_market:
            rare['item']['warframeMarket'] = {'id': 'x', 'urlName': 'akstiletto_prime_barrel'}
        return [{'chance': 25.33, 'rarity': 'Uncommon',
                 'item': {'name': 'Forma Blueprint',
                          'uniqueName': '/Lotus/Types/Recipes/Components/FormaBlueprint'}},
                rare]

    def relic(name, uniq, vaulted, chance, locations, extra=None):
        row = {'name': name, 'uniqueName': uniq, 'type': 'Relic', 'vaulted': vaulted,
               'tradable': True, 'rewards': rewards(chance), 'locations': locations}
        row.update(extra or {})
        return row

    locations = [{'chance': 4.5, 'location': 'Earth/Cetus (Bounty), Rotation A', 'rarity': 'Rare'},
                 {'chance': 0.29, 'location': 'Void/Mithra (Interception), Rotation C',
                  'rarity': 'Legendary'}]
    out = [
        relic('Lith A1 Intact', '/Lotus/Types/Game/Projections/T1VoidProjectionAABronze', False, 2, locations),
        relic('Lith A1 Exceptional', '/Lotus/Types/Game/Projections/T1VoidProjectionAASilver', False, 4, locations),
        relic('Lith A1 Flawless', '/Lotus/Types/Game/Projections/T1VoidProjectionAAGold', False, 6, locations),
        relic('Lith A1 Radiant', '/Lotus/Types/Game/Projections/T1VoidProjectionAAPlatinum', False, 10, locations),
        relic('Meso B2 Intact', '/Lotus/Types/Game/Projections/T2VoidProjectionBBBronze', True, 2, []),
        relic('Meso B2 Radiant', '/Lotus/Types/Game/Projections/T2VoidProjectionBBPlatinum', True, 10, []),
        # two internal variants of one relic, same refinement: both must count as owned
        relic('Lith C3 Intact', '/Lotus/Types/Game/Projections/T1VoidProjectionCCBronze', True, 2, []),
        relic('Lith C3 Intact', '/Lotus/Types/Game/Projections/T1VoidProjectionCCBronzeB', True, 2, []),
        # no refinement, nothing at all (the generic placeholder shape)
        {'name': 'Axi Relic', 'uniqueName': '/Lotus/Types/Game/Projections/T4VoidProjection',
         'type': 'Relic', 'tradable': True, 'rewards': [], 'locations': []},
        # no refinement, a real table, sources in drops[] instead of locations[] (Requiem Eterna)
        relic('Requiem Eterna Relic', '/Lotus/Types/Game/Projections/T5VoidProjectionImmortalOmniA',
              True, 9.5, [], {'drops': [{'location': 'Kuva Flood', 'chance': 100, 'rarity': 'Common'},
                                        {'location': 'Kuva Siphon', 'chance': 50, 'rarity': 'Common'}]}),
    ]
    return out


FIXTURE_OWNED = [
    {'slug': 'lith_a1_relic', 'name': 'Lith A1 Relic', 'count': 3, 'tags': ['relic', 'lith'],
     'path': '/Lotus/Types/Game/Projections/T1VoidProjectionAABronze', 'refinement': 'Intact'},
    {'slug': 'lith_c3_relic', 'name': 'Lith C3 Relic', 'count': 2, 'tags': ['relic', 'lith'],
     'path': '/Lotus/Types/Game/Projections/T1VoidProjectionCCBronzeB', 'refinement': 'Intact'},
    {'slug': 'requiem_eterna_relic', 'name': 'Requiem Eterna Relic', 'count': 8,
     'tags': ['relic', 'requiem'],
     'path': '/Lotus/Types/Game/Projections/T5VoidProjectionImmortalOmniA', 'refinement': 'Intact'},
    {'slug': 'gone_relic', 'name': 'Gone Relic', 'count': 1, 'tags': ['relic'],
     'path': '/Lotus/Types/Game/Projections/NotInTable', 'refinement': 'Intact'},
]
FIXTURE_EV = {'generated': '2026-09-26T00:00:00', 'rows': [
    {'relic': 'Lith A1 Relic', 'slug': 'lith_a1_relic', 'refinement': 'Intact', 'count': 3,
     'ev_unit_wts': 4.87, 'action': 'OPEN'},
]}
FIXTURE_PRICES = {'lith_a1_relic': {'wts': 3, 'wtb': 1, 'n_sell': 3, 'n_buy': 1}}


def selftest():
    """Offline fixture checks: stripping, the join, the three obtain kinds, schema keys."""
    checks = []

    def ok(cond, what):
        if not cond:
            raise AssertionError(what)
        checks.append(what)

    def eq(got, want, what):
        if got != want:
            raise AssertionError('%s: got %r, want %r' % (what, got, want))
        checks.append(what)

    try:
        # --- refinement stripping
        eq(strip_refinement('Axi A1 Exceptional'), ('Axi A1', 'Exceptional'), 'strips Exceptional')
        eq(strip_refinement('Lith G12 Radiant'), ('Lith G12', 'Radiant'), 'strips Radiant')
        eq(strip_refinement('Axi Relic'), ('Axi Relic', None), 'placeholder has no refinement')
        eq(strip_refinement('Requiem Eterna Relic'), ('Requiem Eterna Relic', None),
           'a name inside the name is not a refinement')
        eq(relic_slug('Lith F1'), 'lith_f1_relic', 'relic slug rule')
        eq(relic_slug('Requiem Eterna Relic'), 'requiem_eterna_relic', 'slug is not doubled')
        eq(fmt_num(0.29), '0.29', 'float formatting')
        eq(fmt_num(13), '13', 'int formatting')
        eq(fmt_num(3.0), '3', 'whole float formatting')

        # --- rebuild the store over the fixtures
        doc, stats = build_store(_fixture_relics(), FIXTURE_OWNED, FIXTURE_EV['rows'],
                                 FIXTURE_PRICES, prices_as_of='2026-09-25T11:01:26Z',
                                 now=1700000000)
        by = {r['name']: r for r in doc['relics']}
        eq(doc['schema'], 1, 'schema is 1')
        eq(doc['updated'], 1700000000, 'updated is the passed epoch')
        eq(doc['updated_iso'], '2023-11-14T22:13:20Z', 'updated_iso is ISO Z')
        eq(sorted(doc), ['count', 'generated_from', 'relics', 'schema', 'source', 'summary',
                         'tiers', 'updated', 'updated_iso'], 'top-level keys')
        eq(sorted(by['Lith A1']), ['best_reward', 'ev', 'market', 'name', 'obtain', 'owned',
                                   'owned_total', 'rewards', 'slug', 'tier', 'uniqueNames',
                                   'vaulted'], 'relic keys')
        eq(sorted(doc['summary']), ['farmable', 'owned_distinct', 'owned_stacks', 'refinements',
                                    'vaulted'], 'summary keys')
        eq(doc['summary']['refinements'], REFINEMENTS, 'summary refinements')
        eq(sorted(by['Lith A1']['obtain']), ['complete', 'kind', 'lines', 'note'], 'obtain keys')
        eq(sorted(by['Lith A1']['rewards']['Intact'][0]), ['chance', 'item', 'rarity', 'slug'],
           'reward keys')
        eq(sorted(by['Lith A1']['best_reward']), ['chance_radiant', 'item', 'rarity', 'slug'],
           'best_reward keys')
        eq(sorted(by['Lith A1']['market']), ['as_of', 'median', 'slug', 'wtb', 'wts'],
           'market keys')

        # --- counts + sorting
        eq(doc['count'], 5, '5 base relics')
        eq(list(doc['tiers']), ['Lith', 'Meso', 'Axi', 'Requiem'], 'tiers in canonical order')
        eq(doc['tiers'], {'Lith': 2, 'Meso': 1, 'Axi': 1, 'Requiem': 1}, 'tier counts')
        eq([r['name'] for r in doc['relics']],
           ['Lith A1', 'Lith C3', 'Meso B2', 'Axi Relic', 'Requiem Eterna Relic'],
           'sorted by tier then name')
        eq(stats, {'count': 5, 'farmable': 2, 'vaulted': 3, 'drop_located': 1,
                   'owned_distinct': 3, 'owned_stacks': 3, 'unmatched': 1}, 'stats')
        eq(summary_line(stats),
           'relics_panel: 5 relics | farmable 2 | vaulted 3 | owned 3 stacks | drop-located 1',
           'summary line')

        # --- the uniqueName join
        a1 = by['Lith A1']
        eq(a1['owned'], {'Intact': 3, 'Exceptional': 0, 'Flawless': 0, 'Radiant': 0},
           'join lands on the owned refinement, others stay 0')
        eq(a1['owned_total'], 3, 'owned_total')
        eq(by['Lith C3']['owned'], {'Intact': 2}, 'the second variant counts too')
        eq(by['Meso B2']['owned'], {'Intact': 0, 'Radiant': 0}, 'not owned -> zeros, still listed')
        eq(by['Meso B2']['owned_total'], 0, 'unowned owned_total')
        eq(by['Requiem Eterna Relic']['owned'], {'Intact': 8},
           "owned.json's own refinement label keeps a no-refinement relic visible")
        eq(doc['generated_from']['owned']['matched'], 3, 'matched stacks')
        eq(doc['generated_from']['owned']['unmatched'], ['gone_relic'],
           'an owned row outside the table is reported, not dropped silently')

        # --- the three obtain kinds
        eq(a1['obtain']['kind'], 'drop', 'locations -> drop')
        eq([l['detail'] for l in a1['obtain']['lines']],
           ['4.5% \u00b7 Rare', '0.29% \u00b7 Legendary'], 'lines carry chance% · rarity')
        eq([l['label'] for l in a1['obtain']['lines']],
           ['Earth/Cetus (Bounty), Rotation A', 'Void/Mithra (Interception), Rotation C'],
           'highest chance first')
        eq(a1['obtain']['note'], None, 'a drop relic needs no note')
        eq(a1['obtain']['complete'], True, 'a drop relic is complete')
        eq(by['Meso B2']['obtain']['kind'], 'vaulted', 'vaulted + no locations -> vaulted')
        eq(by['Meso B2']['obtain']['lines'], [], 'a vaulted relic claims no location')
        eq(by['Meso B2']['obtain']['note'], VAULTED_NOTE, 'vaulted note')
        eq(by['Axi Relic']['obtain']['kind'], 'unknown', 'placeholder -> unknown')
        eq(by['Axi Relic']['obtain']['note'], PLACEHOLDER_NOTE, 'placeholder note')
        eq(by['Axi Relic']['obtain']['complete'], False, 'a placeholder cannot answer')
        eq(by['Requiem Eterna Relic']['obtain']['kind'], 'vaulted', 'Requiem Eterna stays vaulted')
        ok('Kuva Siphon' in by['Requiem Eterna Relic']['obtain']['note'],
           'the vaulted note names the drops[] sources instead of denying them')

        # --- rewards / best_reward / market / ev
        eq([r['item'] for r in a1['rewards']['Radiant']],
           ['Forma Blueprint', 'Akstiletto Prime Barrel'], 'rewards per refinement, verbatim')
        eq(a1['rewards']['Intact'][1]['chance'], 2, 'intact chance untouched')
        eq(a1['rewards']['Radiant'][1]['chance'], 10, 'radiant chance untouched')
        eq(a1['rewards']['Intact'][0]['slug'], None, 'a reward the market does not carry keeps null')
        eq(a1['best_reward'], {'item': 'Akstiletto Prime Barrel', 'slug': 'akstiletto_prime_barrel',
                               'rarity': 'Rare', 'chance_radiant': 10}, 'best_reward from Radiant')
        eq(by['Axi Relic']['best_reward'], None, 'a placeholder has no best_reward')
        eq(a1['market'], {'slug': 'lith_a1_relic', 'wts': 3, 'wtb': 1, 'median': 2,
                          'as_of': '2026-09-25T11:01:26Z'}, 'market snapshot block')
        eq(by['Meso B2']['market'], None, 'no snapshot row -> market null')
        eq(a1['ev']['Intact'], {'ev': 4.87, 'verdict': 'OPEN'}, 'EV joined by slug+refinement')
        eq(a1['ev']['Radiant'], None, 'no EV row -> null, never a guess')

        # --- atomic write round-trip
        with tempfile.TemporaryDirectory(prefix='relics_panel_selftest_') as tmp:
            path = os.path.join(tmp, 'relics_panel.json')
            atomic_write(path, doc)
            ok(os.path.exists(path) and not os.path.exists(path + '.tmp'), 'atomic write')
            eq(jload(path)['count'], doc['count'], 'payload round-trips')
    except AssertionError as exc:
        print('selftest: FAILED - %s' % ascii_s(exc))
        return 2
    print('selftest: ok (%d checks) offline - no network, tmp files only' % len(checks))
    return 0


# --------------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='relics_panel.py',
        description='Build data/relics_panel.json (+ the static/ copy) from the WFCD relic '
                    'table, data/owned.json, data/relic_ev.json and data/prices.json.',
        epilog='Exit codes: 0 ok, 1 no relic table, 2 selftest failure.')
    ap.add_argument('--once', action='store_true', default=True,
                    help='single pass (default; kept for cron lines)')
    ap.add_argument('--out', metavar='PATH', help='store path (default data/relics_panel.json)')
    ap.add_argument('--json', action='store_true', help='print the store JSON to stdout')
    ap.add_argument('--dry-run', action='store_true', help='print the plan and write nothing')
    ap.add_argument('--offline', action='store_true', help='never fetch the relic table')
    ap.add_argument('--refresh', action='store_true', help='ignore the cached relic table')
    ap.add_argument('--no-static-copy', action='store_true',
                    help='do not write static/relics_panel.json')
    ap.add_argument('--selftest', action='store_true',
                    help='offline fixture checks (no network, no repo writes)')
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    write = not args.dry_run
    entries, relics_meta = load_relics(offline=args.offline, refresh=args.refresh, write=write)
    if entries is None:
        print('relics_panel: no relic table - %s' % ascii_s(relics_meta.get('error')))
        print('  run scripts/obtain_index.py to cache it, or drop --offline to fetch it now.')
        return 1
    owned_rows, owned_meta = load_owned()
    ev_rows, ev_meta = load_ev()
    prices, prices_meta = load_prices()

    doc, stats = build_store(entries, owned_rows, ev_rows, prices,
                             prices_as_of=prices_meta.get('as_of'),
                             sources={'relics': relics_meta, 'owned': owned_meta,
                                      'relic_ev': ev_meta, 'prices': prices_meta})
    line = summary_line(stats)
    if args.json:
        print(line, file=sys.stderr)
        print(json.dumps(doc, ensure_ascii=False, separators=(',', ':')))
    else:
        print(line)                                     # summary line FIRST
        print('  tiers: ' + ' | '.join('%s %d' % (t, n) for t, n in doc['tiers'].items()))
        print('  own : %d distinct relics owned in %d stacks | drop-located %d | unmatched %d'
              % (stats['owned_distinct'], stats['owned_stacks'], stats['drop_located'],
                 stats['unmatched']))

    if args.dry_run:
        if not args.json:
            print('plan : write %d relics -> %s' % (stats['count'],
                                                    rel(args.out or out_path())))
            print('plan : dry-run - nothing written')
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
    if not args.json:
        print('store: %s (%.1f KB)' % (rel(target), os.path.getsize(target) / 1024.0))
        print('  %s' % static_note)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
