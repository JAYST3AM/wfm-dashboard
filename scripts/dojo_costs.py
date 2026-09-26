#!/usr/bin/env python3
"""Dojo costs - material cost of the standard Clan Dojo buildout (wiki.warframe.com).

The dashboard joins these numbers against the player's own materials, so every figure is
transcribed verbatim from the wiki's room requirement tables. A room whose table cannot be
read is reported in `skipped` with its page URL and the reason - a number is never guessed.

Where the numbers live (found with the wiki search API, not guessed):

  * `Clan Hall` has NO wiki page - the room table is under [[Organization Rooms#Clan Halls]]
    (heading "Clan Halls", tabber tab "Clan").
  * `Oracle`, `Observatory` and `Dry Dock` are redirects: the first lands on [[Research]]
    (which has no room table), the other two redirect into [[Interactive Rooms]] - the room
    tables live on [[Interactive Rooms]] sections "Oracle" / "Observatory" / "Dry Dock".
  * the five labs share the section "Research Labs" as tabber tabs (Bio, Chem, Energy,
    Tenno, Orokin). That section also carries Dagath's Hollow and the Ventkids' Bash Lab,
    which are NOT part of the standard buildout - hence the (heading, tabber) selector
    instead of "first table in the section".
  * the rooms' own pages (Research/Energy Lab, ...) list RESEARCH project costs, not the
    room construction cost, so they are deliberately not used as the room source.

The wiki room tables are {{DojoRoom}} transclusions with one column per clan tier
(Ghost/Shadow/Storm/Mountain/Moon); the base Ghost-clan column is used (the tier every clan
starts at, and the one a solo player's own materials have to cover). {{BuildRequire}} (the
wiki's "Manufacturing Requirements" template, e.g. the Clan Key) is parsed too.

Cached raw API responses live under data/dropdata/wiki_dojo/<room slug>.json, so a re-run
parses from disk without touching the network (use --refresh to force a re-fetch).

Usage
  python scripts/dojo_costs.py --once        # fetch missing, parse all, write (default)
  python scripts/dojo_costs.py --refresh     # ignore the cache and re-fetch every page
  python scripts/dojo_costs.py --dry-run     # parse + print, write nothing at all
  python scripts/dojo_costs.py --json        # dump the document to stdout
  python scripts/dojo_costs.py --offline     # never touch the network (cache only)
  python scripts/dojo_costs.py --out PATH    # write somewhere else
  python scripts/dojo_costs.py --selftest    # offline parsing checks, no network, no writes
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.environ.get('WFM_DATA_DIR') or os.path.join(ROOT, 'data')
WIKI_API = 'https://wiki.warframe.com/api.php'
WIKI_BASE = 'https://wiki.warframe.com/w/'
UA = {'User-Agent': 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'}
TIMEOUT = 60
SCHEMA = 1
SOURCE = 'wiki.warframe.com'
SCOPE = ('standard Clan Dojo buildout (Ghost clan): Clan Hall, Oracle, Energy Lab, Chem Lab, '
         'Tenno Lab, Bio Lab, Orokin Lab, Observatory, Dry Dock. Room construction costs only '
         '(lab research project costs are separate); figures are the Ghost-clan column of the '
         'wiki DojoRoom tables on Organization Rooms / Interactive Rooms.')

# slug, name, wiki page, section heading, tabber tab (None = no tabber), build-order note
ROOMS = [
    {'slug': 'clan_hall', 'name': 'Clan Hall', 'page': 'Organization Rooms',
     'heading': 'Clan Halls', 'tabber': 'Clan',
     'note': "No 'Clan Hall' wiki page - table is on Organization Rooms#Clan_Halls. "
             'The first Clan Hall is auto-built for new clans; this is the rebuild cost.'},
    {'slug': 'oracle', 'name': 'Oracle', 'page': 'Interactive Rooms',
     'heading': 'Oracle', 'tabber': None,
     'note': "'Oracle' redirects to the Research page, which has no room table; "
             'the room table is on Interactive Rooms#Oracle.'},
    {'slug': 'energy_lab', 'name': 'Energy Lab', 'page': 'Interactive Rooms',
     'heading': 'Research Labs', 'tabber': 'Energy',
     'note': "Room construction cost; the lab's own page (Research/Energy Lab) lists "
             'research project costs instead.'},
    {'slug': 'chem_lab', 'name': 'Chem Lab', 'page': 'Interactive Rooms',
     'heading': 'Research Labs', 'tabber': 'Chem',
     'note': "Room construction cost; the lab's own page (Research/Chem Lab) lists "
             'research project costs instead.'},
    {'slug': 'tenno_lab', 'name': 'Tenno Lab', 'page': 'Interactive Rooms',
     'heading': 'Research Labs', 'tabber': 'Tenno',
     'note': "Room construction cost; the lab's own page (Research/Tenno Lab) lists "
             'research project costs instead.'},
    {'slug': 'bio_lab', 'name': 'Bio Lab', 'page': 'Interactive Rooms',
     'heading': 'Research Labs', 'tabber': 'Bio',
     'note': "Room construction cost; the lab's own page (Research/Bio Lab) lists "
             'research project costs instead.'},
    {'slug': 'orokin_lab', 'name': 'Orokin Lab', 'page': 'Interactive Rooms',
     'heading': 'Research Labs', 'tabber': 'Orokin',
     'note': "Room construction cost; the lab's own page (Research/Orokin Lab) lists "
             'research project costs instead.'},
    {'slug': 'observatory', 'name': 'Observatory', 'page': 'Interactive Rooms',
     'heading': 'Observatory', 'tabber': None,
     'note': "'Observatory' redirects to Interactive Rooms#Observatory."},
    {'slug': 'dry_dock', 'name': 'Dry Dock', 'page': 'Interactive Rooms',
     'heading': 'Dry Dock', 'tabber': None,
     'note': "'Dry Dock' redirects to Interactive Rooms#Dry_Dock. Optional Railjack room "
             '(Rising Tide quest) - extra to the base buildout.'},
]

HEADING_RE = re.compile(r'^(={1,6})\s*(.*?)\s*\1\s*$')
# <tabber>First={{...}}  ... |-|Second={{...}}  (both forms carry a template after '=')
TABBER_LABEL_RE = re.compile(r'(?:<tabber>|\|-\|)\s*([A-Za-z][^=|\n{}]{0,40}?)\s*=\s*\{\{')
TEMPLATE_RE = re.compile(r'\{\{\s*(DojoRoom|BuildRequire)\b\s*(?=\||\n|\})')
PARAM_RE = re.compile(r'^\s*\|\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$')
NOT_A_NUMBER_RE = re.compile(r'^(?:n/?a|-+|\?*)$', re.I)


class ExtractError(Exception):
    """The room's cost table could not be read - the room goes to `skipped`."""


# ------------------------------------------------------------------ helpers
def slugify(name):
    """Material slug - must match the rule data/materials.json joins on."""
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')


def cache_dir():
    return os.path.join(DATA, 'dropdata', 'wiki_dojo')


def out_path():
    return os.path.join(DATA, 'dojo_costs.json')


def page_url(spec):
    """Exact wiki URL for the room's table (page + section anchor)."""
    return WIKI_BASE + spec['page'].replace(' ', '_') + '#' + spec['heading'].replace(' ', '_')


def jload(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return None


def atomic_write(path, doc):
    tmp = path + '.tmp'
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
        fh.write('\n')
    os.replace(tmp, path)


def iso_z(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_amount(value):
    """Wiki amount -> int, or None when the table shows no number ('' / N/A)."""
    if value is None:
        return None
    text = value.replace('&nbsp;', ' ').replace(',', '').strip()
    if not text or NOT_A_NUMBER_RE.match(text):
        return None
    if re.fullmatch(r'\d+', text):
        return int(text)
    raise ExtractError('unreadable amount %r' % value)


# ------------------------------------------------------------------ wikitext parsing
def template_body(text, start):
    """Raw body of the {{template}} that starts at `start` (nested braces respected)."""
    depth, i = 0, start
    while i < len(text):
        if text.startswith('{{', i):
            depth += 1
            i += 2
            continue
        if text.startswith('}}', i):
            depth -= 1
            i += 2
            if depth == 0:
                return text[start + 2:i - 2]
            continue
        i += 1
    raise ExtractError('unterminated template')


def parse_params(body):
    params = {}
    for line in body.splitlines()[1:]:
        m = PARAM_RE.match(line)
        if m:
            params[m.group(1).lower()] = m.group(2)
    return params


def _scan_context(chunk, heading, tabber):
    """Walk the text between two tables, tracking the current heading and tabber tab."""
    for line in chunk.splitlines():
        line = line.strip()
        if '</tabber>' in line:
            tabber = None
            line = line.split('</tabber>')[0].strip()
        m = HEADING_RE.match(line)
        if m:
            heading, tabber = m.group(2), None
            continue
        t = TABBER_LABEL_RE.search(line)
        if t:
            tabber = t.group(1).strip()
    return heading, tabber


def iter_templates(text):
    """Yield every DojoRoom/BuildRequire table with the heading + tabber tab it sits under."""
    heading, tabber, pos = None, None, 0
    for m in TEMPLATE_RE.finditer(text):
        heading, tabber = _scan_context(text[pos:m.start()], heading, tabber)
        pos = m.start()
        yield {'kind': m.group(1), 'heading': heading, 'tabber': tabber,
               'params': parse_params(template_body(text, m.start()))}


TIERS = ('ghost', 'shadow', 'storm', 'mountain', 'moon')   # the wiki DojoRoom template's five clan tiers


def parse_room_table(text, spec):
    """(credits, [(material name, amount), ...]) for one room, verbatim from its table."""
    hits = [t for t in iter_templates(text)
            if (t['heading'] or '').strip().lower() == spec['heading'].lower()
            and (t['tabber'] or '').strip().lower() == (spec['tabber'] or '').strip().lower()]
    for kind in ('DojoRoom', 'BuildRequire'):
        found = [t for t in hits if t['kind'] == kind]
        if len(found) == 1:
            credits, resources, tiers = _costs_from_params(kind, found[0]['params'], spec)
            return credits, resources, tiers
        if len(found) > 1:
            raise ExtractError('%d %s tables under heading %r - ambiguous'
                               % (len(found), kind, spec['heading']))
    raise ExtractError('no cost table under heading %r (tabber %r)'
                       % (spec['heading'], spec['tabber']))


def _costs_from_params(kind, params, spec):
    if kind == 'DojoRoom':
        credit_key, res, amt = 'creditghost', 'resource%d', 'resource%dghost'
    else:  # BuildRequire / "Manufacturing Requirements"
        credit_key, res, amt = 'buildcredits', 'build%d', 'build%damount'
    try:
        credits = parse_amount(params.get(credit_key))
    except ExtractError as exc:
        raise ExtractError('%s: %s' % (spec['name'], exc))
    if credits is None:
        raise ExtractError('no credit amount (%s) in the table' % credit_key)
    resources = []
    for idx in range(1, 5):
        name = (params.get(res % idx) or '').strip()
        if not name:
            continue
        try:
            amount = parse_amount(params.get(amt % idx))
        except ExtractError as exc:
            raise ExtractError('%s: %s' % (name, exc))
        if amount is None:
            continue  # tier shows N/A for this resource
        resources.append((name, amount))
    if not resources:
        raise ExtractError('table lists credits but no resources')
    tiers = {}
    if kind == 'DojoRoom':
        for tier in TIERS:
            tier_credits = parse_amount(params.get('credit' + tier))
            tier_costs, tier_names = {}, {}
            for idx in range(1, 5):
                name = (params.get(res % idx) or '').strip()
                if not name:
                    continue
                if kind == 'DojoRoom':
                    raw = params.get('resource%d%s' % (idx, tier))      # resource1ghost .. resource4moon
                else:
                    raw = params.get('%s%s' % (amt % idx, tier))
                try:
                    amount = parse_amount(raw)
                except ExtractError:
                    amount = None
                if amount is None:
                    continue
                slug = slugify(name)
                tier_costs[slug] = tier_costs.get(slug, 0) + amount
                tier_names[slug] = name
            if tier_credits is not None and tier_costs:
                tiers[tier] = {'credits': tier_credits, 'costs': tier_costs, 'names': tier_names}
    return credits, resources, tiers


# ------------------------------------------------------------------ page cache + fetch
def fetch_api(title):
    params = urllib.parse.urlencode({'action': 'query', 'prop': 'revisions', 'rvprop': 'content',
                                     'rvslots': 'main', 'redirects': '1', 'titles': title,
                                     'format': 'json', 'formatversion': '2'})
    req = urllib.request.Request(WIKI_API + '?' + params, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode('utf-8'))


def wikitext_of(api_doc):
    """(wikitext|None, resolved page title) from a formatversion=2 query response."""
    page = ((api_doc.get('query') or {}).get('pages') or [{}])[0]
    title = page.get('title')
    if page.get('missing'):
        return None, title
    revs = page.get('revisions') or []
    if not revs:
        return None, title
    return (revs[0].get('slots', {}).get('main', {}) or {}).get('content'), title


def load_page(spec, refresh=False, offline=False, write=True):
    """Raw API response for a room's page, from the per-slug cache or the wiki."""
    path = os.path.join(cache_dir(), spec['slug'] + '.json')
    if not refresh:
        cached = jload(path)
        if isinstance(cached, dict) and cached.get('api'):
            return cached, None
    if offline:
        return None, 'offline and no cached page'
    try:
        api_doc = fetch_api(spec['page'])
    except Exception as exc:
        return None, '%s: %s' % (type(exc).__name__, exc)
    cache_doc = {'slug': spec['slug'], 'requested_title': spec['page'],
                 'resolved_title': wikitext_of(api_doc)[1], 'url': page_url(spec),
                 'fetched': int(time.time()), 'api': api_doc}
    if write:
        atomic_write(path, cache_doc)
    return cache_doc, None


# ------------------------------------------------------------------ document
def build_doc(pages, load_errors=None, now=None):
    """(doc, room rows) - pages maps room slug to its cached raw API response."""
    load_errors = load_errors or {}
    rows, skipped, names = [], [], {}
    for order, spec in enumerate(ROOMS, start=1):
        url = page_url(spec)
        cache_doc = pages.get(spec['slug'])
        try:
            if cache_doc is None:
                raise ExtractError(load_errors.get(spec['slug'], 'page not fetched'))
            text, _resolved = wikitext_of(cache_doc.get('api') or {})
            if text is None:
                raise ExtractError('wiki page %r is missing' % cache_doc.get('requested_title'))
            credits, resources, tiers = parse_room_table(text, spec)
        except ExtractError as exc:
            skipped.append({'name': spec['name'], 'url': url, 'reason': str(exc)})
            continue
        costs = {}
        for name, amount in resources:
            slug = slugify(name)
            costs[slug] = costs.get(slug, 0) + amount
            names.setdefault(slug, name)
        for tier, tdata in (tiers or {}).items():
            for slug, name in tdata['names'].items():
                names.setdefault(slug, name)
        rows.append({'slug': spec['slug'], 'name': spec['name'], 'url': url, 'credits': credits,
                     'costs': costs, 'built': order, 'note': spec['note'],
                     'resources': resources, 'tiers': tiers or {}})
    materials = {}
    for row in rows:
        for slug, qty in row['costs'].items():
            entry = materials.setdefault(slug, {'name': names.get(slug, slug), 'needed': 0})
            entry['needed'] += qty
    ts = int(time.time() if now is None else now)
    tier_totals = {}
    for tier in TIERS:
        credits_sum, mat = 0, {}
        for row in rows:
            tdata = (row.get('tiers') or {}).get(tier)
            if not tdata:
                continue
            credits_sum += tdata['credits']
            for slug, qty in tdata['costs'].items():
                entry = mat.setdefault(slug, {'name': names.get(slug, slug), 'needed': 0})
                entry['needed'] += qty
        if mat:
            tier_totals[tier] = {'credits': credits_sum,
                                 'materials': {slug: mat[slug] for slug in sorted(mat)}}
    doc = {'schema': SCHEMA, 'source': SOURCE, 'fetched': ts, 'fetched_iso': iso_z(ts),
           'scope': SCOPE, 'tiers': list(TIERS),
           'rooms': [{k: v for k, v in row.items() if k not in ('resources', 'tiers')} for row in rows],
           'room_tiers': {row['slug']: {t: {'credits': d['credits'], 'costs': d['costs']}
                                        for t, d in (row.get('tiers') or {}).items()} for row in rows},
           'materials': {slug: materials[slug] for slug in sorted(materials)},
           'tier_totals': tier_totals,
           'skipped': skipped}
    return doc, rows


def summary_line(doc):
    return 'dojo_costs: rooms %d | materials %d | credits %d | skipped %d' % (
        len(doc['rooms']), len(doc['materials']),
        sum(r['credits'] for r in doc['rooms']), len(doc['skipped']))


def print_human(doc, rows):
    print('scope: %s' % doc['scope'])
    print('source: https://%s (fetched %s)' % (doc['source'], doc['fetched_iso']))
    print('rooms (build order):')
    for row in rows:
        costs = ', '.join('%s %s' % (name, format(amount, ',')) for name, amount in row['resources'])
        print('  %d. %-12s %-13s credits %-7s | %s'
              % (row['built'], row['slug'], row['name'], format(row['credits'], ','), costs))
        if row['note']:
            print('       note: %s' % row['note'])
    print('materials (per-slug totals over all rooms):')
    print('  ' + ' | '.join('%s %s' % (m['name'], format(m['needed'], ','))
                            for m in doc['materials'].values()))
    for item in doc['skipped']:
        print('skipped: %s - %s (%s)' % (item['name'], item['reason'], item['url']))


# ------------------------------------------------------------------ selftest
FIXTURE_PAGE = """=Interactive Rooms=
==Oracle==
{{Quote|The Oracle system is the basis of adding research facilities.}}
{{DojoRoom
| creditghost            = 1000
| creditshadow           = 3000
| resource1              = Salvage
| resource1ghost         = 650
| resource1shadow        = 1950
| resource2              = Circuits
| resource2ghost         = 350
| resource3              = Polymer Bundle
| resource3ghost         = 350
| resource4              = Forma
| resource4ghost         = 1
| buildtime              = 24
}}

==Research Labs==
<tabber>Bio={{Quote|Allows for biologically focused reseach projects.}}
{{DojoRoom
| creditghost            = 1000
| resource1              = Salvage
| resource1ghost         = 650
| resource2              = Circuits
| resource2ghost         = 350
}}
|-|Dagath's Hollow={{Quote|Resurrect a Naberus legend.}}
{{DojoRoom
| creditghost            = 1000
| resource1              = Ferrite
| resource1ghost         = 800
| resource2              = Thermal Sludge
| resource2ghost         = 100
}}
</tabber>

==Observatory==
No table on this fixture page.
"""

FIXTURE_CLAN_KEY = """=Clan Key=
{{BuildRequire
|buildcredits= 1,500
|build1= Morphics
|build1amount=1
|build2= Polymer Bundle
|build2amount=500
|build3= Ferrite
|build3amount=500
|build4=
|build4amount=
|buildtime=12
}}
"""


def _fixture_cache(slug, page, text):
    return {'slug': slug, 'requested_title': page, 'resolved_title': page, 'url': page,
            'fetched': 0,
            'api': {'query': {'pages': [{'title': page,
                                         'revisions': [{'slots': {'main': {'content': text}}}]}]}}}


def selftest():
    """Offline parsing checks - no network, no writes outside a throwaway temp dir."""
    checks = []

    def check(label, fn):
        fn()
        checks.append(label)

    def eq(got, want, label):
        assert got == want, '%s: got %r, want %r' % (label, got, want)

    check('slug rule', lambda: [eq(slugify(n), s, n) for n, s in [
        ('Polymer Bundle', 'polymer_bundle'), ('Alloy Plate', 'alloy_plate'),
        ('Orokin Cell', 'orokin_cell'), ('Nano Spores', 'nano_spores'),
        ('Control Module', 'control_module'), ('Argon Crystal', 'argon_crystal'),
        ('Ferrite', 'ferrite'), ('Thermal Sludge', 'thermal_sludge')]])

    oracle = next(r for r in ROOMS if r['slug'] == 'oracle')
    bio = next(r for r in ROOMS if r['slug'] == 'bio_lab')
    obs = next(r for r in ROOMS if r['slug'] == 'observatory')

    check('DojoRoom ghost column', lambda: eq(
        parse_room_table(FIXTURE_PAGE, oracle)[0], 1000, 'oracle credits'))
    check('DojoRoom resources', lambda: eq(
        parse_room_table(FIXTURE_PAGE, oracle)[1],
        [('Salvage', 650), ('Circuits', 350), ('Polymer Bundle', 350), ('Forma', 1)],
        'oracle resources'))

    def bio_tab():
        credits, resources, _tiers = parse_room_table(FIXTURE_PAGE, bio)
        eq(credits, 1000, 'bio credits')
        eq(resources, [('Salvage', 650), ('Circuits', 350)], 'bio resources')
    check('tabber tab selection (Bio, not Dagath\'s Hollow)', bio_tab)

    key = {'slug': 'clan_key', 'name': 'Clan Key', 'page': 'Clan Key',
           'heading': 'Clan Key', 'tabber': None, 'note': ''}
    check('BuildRequire / Manufacturing Requirements', lambda: eq(
        parse_room_table(FIXTURE_CLAN_KEY, key)[:2],
        (1500, [('Morphics', 1), ('Polymer Bundle', 500), ('Ferrite', 500)]), 'clan key'))

    check('amount parsing', lambda: [
        eq(parse_amount('1,500'), 1500, '1,500'), eq(parse_amount('N/A'), None, 'N/A'),
        eq(parse_amount(' 12 '), 12, ' 12 '), eq(parse_amount(''), None, 'empty')])

    pages = {'oracle': _fixture_cache('oracle', 'Interactive Rooms', FIXTURE_PAGE),
             'bio_lab': _fixture_cache('bio_lab', 'Interactive Rooms', FIXTURE_PAGE),
             'observatory': _fixture_cache('observatory', 'Interactive Rooms', FIXTURE_PAGE)}
    doc, rows = build_doc(pages, now=1700000000)

    check('room without a table -> skipped, not in rooms', lambda: (
        eq([r['slug'] for r in doc['rooms']], ['oracle', 'bio_lab'], 'parsed rooms'),
        eq([s['name'] for s in doc['skipped'] if s['url'] == page_url(obs)], ['Observatory'],
           'skipped names'),
        eq(next(s['url'] for s in doc['skipped'] if s['name'] == 'Observatory'), page_url(obs),
           'skipped url'),
        assert_true(next(s['reason'] for s in doc['skipped'] if s['name'] == 'Observatory'),
                    'reason present')))
    check('unfetched pages are reported, not guessed', lambda: (
        assert_true(all(r['slug'] in ('oracle', 'bio_lab') for r in doc['rooms']), 'rooms only'),
        assert_true(any(s['name'] == 'Dry Dock' for s in doc['skipped']), 'dry dock reported')))

    check('materials totals sum over rooms', lambda: (
        eq(doc['materials']['salvage'], {'name': 'Salvage', 'needed': 1300}, 'salvage'),
        eq(doc['materials']['circuits'], {'name': 'Circuits', 'needed': 700}, 'circuits'),
        eq(sum(r['credits'] for r in doc['rooms']), 2000, 'credits total')))

    check('schema keys', lambda: (
        eq(sorted(doc.keys()), ['fetched', 'fetched_iso', 'materials', 'room_tiers', 'rooms',
                                'schema', 'scope', 'skipped', 'source', 'tier_totals', 'tiers'],
           'top-level keys'),
        eq(sorted(doc['rooms'][0].keys()), ['built', 'costs', 'credits', 'name', 'note', 'slug',
                                            'url'], 'room keys'),
        eq(doc['fetched'], 1700000000, 'fetched'),
        assert_true(doc['fetched_iso'].endswith('Z'), 'iso Z')))

    def write_probe():
        tmp = tempfile.mkdtemp(prefix='dojo_costs_selftest_')
        path = os.path.join(tmp, 'dojo_costs.json')
        atomic_write(path, doc)
        with open(path, encoding='utf-8') as fh:
            back = json.load(fh)
        eq(back['schema'], SCHEMA, 'schema')
        eq(back['source'], SOURCE, 'source')
        eq(back['rooms'][0]['costs']['forma'], 1, 'forma')
    check('json round-trip', write_probe)

    print('selftest: ok (%d checks)' % len(checks))
    return 0


def assert_true(value, label):
    assert value, label + ': expected a truthy value'


# ------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--once', action='store_true', default=True,
                    help='fetch missing, parse all, write (default)')
    ap.add_argument('--refresh', action='store_true', help='ignore the cache, re-fetch every page')
    ap.add_argument('--out', default=None, help='output path (default data/dojo_costs.json)')
    ap.add_argument('--json', action='store_true', help='dump the document to stdout')
    ap.add_argument('--dry-run', action='store_true', help='parse + print, write nothing')
    ap.add_argument('--offline', action='store_true', help='use the cache only, never fetch')
    ap.add_argument('--selftest', action='store_true', help='offline parsing checks, then exit')
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    write = not args.dry_run
    pages, errors = {}, {}
    for spec in ROOMS:
        cache_doc, err = load_page(spec, refresh=args.refresh, offline=args.offline, write=write)
        if cache_doc is None:
            if err:
                errors[spec['slug']] = err
            continue
        pages[spec['slug']] = cache_doc

    doc, rows = build_doc(pages, errors)
    line = summary_line(doc)
    if args.json:
        print(line, file=sys.stderr)
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print(line)
        print_human(doc, rows)

    if write:
        target = args.out or out_path()
        if doc['rooms'] or not os.path.exists(target):
            atomic_write(target, doc)
            if not args.json:
                print('wrote %s' % os.path.abspath(target))
        else:  # nothing parsed - never clobber a good document with an empty one
            print('no room parsed - left %s untouched' % os.path.abspath(target))
    else:
        print('dry run - wrote nothing')
    return 0


if __name__ == '__main__':
    sys.exit(main())
