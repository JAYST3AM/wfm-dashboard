"""scripts/dojo_costs.py: schema + parsing contract, all offline.

Every test runs on fixtures in tmp_path - the wiki is never contacted and the repo's real
data/ directory is never read or written. The script is loaded by path through conftest's
load_script() so its DATA/CACHE globals can be redirected per test; the CLI behaviour
(--dry-run writes nothing, --selftest exits 0) is checked in a subprocess with
WFM_DATA_DIR pointing at tmp_path.
"""
import json
import os
import re
import subprocess
import sys

import pytest

from conftest import SCRIPTS, load_script, read_json

DOJO_SRC = os.path.join(SCRIPTS, 'dojo_costs.py')

# ---------------------------------------------------------------- fixtures
# Deliberately independent of the script's own selftest text: two tables sharing one heading
# (tabber tabs), an N/A tier cell, and a section whose room has no table at all.
PAGE = """
==Oracle==
The '''Oracle''' is required before any research lab can be built.
{{DojoRoom
| creditghost            = 1,000
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
| resource4shadow        = N/A
| pic                    = RoomOracle.png
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
|-|Energy={{Quote|Allows for energy focused research projects.}}
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
Observatories allow clan members to access Navigation for missions.
"""

PAGE_KEY = """
==Clan Key==
{{BuildRequire
|buildcredits   = 1,500
|build1        = Morphics
|build1amount  = 1
|build2        = Polymer Bundle
|build2amount  = 500
|build3        = Ferrite
|build3amount  = 500
|build4        =
|build4amount  =
|buildtime     = 12
}}
"""

SCOPE_KEYS = ['fetched', 'fetched_iso', 'materials', 'room_tiers', 'rooms', 'schema',
              'scope', 'skipped', 'source', 'tier_totals', 'tiers']
ROOM_KEYS = ['built', 'costs', 'credits', 'name', 'note', 'slug', 'url']
SKIP_KEYS = ['name', 'reason', 'url']


def spec_of(mod, slug):
    return next(s for s in mod.ROOMS if s['slug'] == slug)


def cache_doc(slug, page, text):
    """A cached raw API response exactly as load_page() stores it."""
    return {'slug': slug, 'requested_title': page, 'resolved_title': page,
            'url': page, 'fetched': 0,
            'api': {'query': {'pages': [{'title': page,
                                         'revisions': [{'slots': {'main': {'content': text}}}]}]}}}


def fixture_pages(text=PAGE):
    """Caches for the rooms the fixture page can answer (Observatory has no table)."""
    return {slug: cache_doc(slug, 'Interactive Rooms', text)
            for slug in ('oracle', 'bio_lab', 'observatory', 'clan_hall')}


def page_for(spec, credits=1000, amount=10):
    """A minimal page carrying one table under this room's heading (and tabber tab, if any)."""
    table = ('{{DojoRoom\n| creditghost            = %d\n| resource1              = Ferrite\n'
             '| resource1ghost         = %d\n}}\n' % (credits, amount))
    if spec['tabber']:
        table = '<tabber>%s={{Quote|stub}}\n%s</tabber>\n' % (spec['tabber'], table)
    return '==%s==\n%sSee also.\n' % (spec['heading'], table)


@pytest.fixture
def dojo(tmp_path, monkeypatch):
    """scripts/dojo_costs.py with DATA redirected into tmp_path."""
    data = tmp_path / 'data'
    data.mkdir()
    mod = load_script('dojo_costs', monkeypatch=monkeypatch, env={'WFM_DATA_DIR': str(data)})
    assert str(data) == mod.DATA
    return mod


# ---------------------------------------------------------------- schema
def test_exact_schema_keys(dojo):
    doc, rows = dojo.build_doc(fixture_pages(), now=1700000000)
    assert sorted(doc.keys()) == SCOPE_KEYS
    assert doc['schema'] == 1
    assert doc['source'] == 'wiki.warframe.com'
    assert isinstance(doc['scope'], str) and doc['scope']
    assert doc['fetched'] == 1700000000 and isinstance(doc['fetched'], int)
    assert doc['fetched_iso'].startswith('2023-11-14T') and doc['fetched_iso'].endswith('Z')
    assert len(doc['rooms']) == 2 and len(rows) == 2

    room = doc['rooms'][0]
    assert sorted(room.keys()) == ROOM_KEYS
    assert room['slug'] == 'oracle' and room['name'] == 'Oracle'
    assert room['url'].startswith('https://wiki.warframe.com/w/')
    assert isinstance(room['credits'], int) and room['credits'] == 1000
    assert isinstance(room['built'], int) and room['built'] == 2
    assert isinstance(room['note'], str)
    assert room['costs'] == {'salvage': 650, 'circuits': 350, 'polymer_bundle': 350, 'forma': 1}
    assert all(re.fullmatch(r'[a-z0-9_]+', slug) for slug in room['costs'])

    for entry in doc['materials'].values():
        assert sorted(entry.keys()) == ['name', 'needed']
        assert isinstance(entry['name'], str) and isinstance(entry['needed'], int)
    for item in doc['skipped']:
        assert sorted(item.keys()) == SKIP_KEYS
        assert item['url'].startswith('https://wiki.warframe.com/w/')


def test_written_file_round_trips(dojo):
    for slug, doc in fixture_pages().items():
        dojo.atomic_write(os.path.join(dojo.cache_dir(), slug + '.json'), doc)
    assert dojo.main(['--once', '--offline']) == 0
    written = read_json(dojo.out_path())
    assert sorted(written.keys()) == SCOPE_KEYS
    assert [r['slug'] for r in written['rooms']] == ['oracle', 'bio_lab']
    assert written['materials']['salvage'] == {'name': 'Salvage', 'needed': 1300}
    assert written['materials']['circuits'] == {'name': 'Circuits', 'needed': 700}


# ---------------------------------------------------------------- slug rule
@pytest.mark.parametrize('name,slug', [
    ('Polymer Bundle', 'polymer_bundle'),
    ('Alloy Plate', 'alloy_plate'),
    ('Orokin Cell', 'orokin_cell'),
    ('Nano Spores', 'nano_spores'),
    ('Control Module', 'control_module'),
    ('Argon Crystal', 'argon_crystal'),
    ('Thermal Sludge', 'thermal_sludge'),
    ('Ferrite', 'ferrite'),
    ('Forma', 'forma'),
])
def test_slug_rule(dojo, name, slug):
    assert dojo.slugify(name) == slug
    assert dojo.slugify(name) == re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')


# ---------------------------------------------------------------- parsing
def test_fixture_page_parses_credits_and_resources(dojo):
    credits, resources, tiers = dojo.parse_room_table(PAGE, spec_of(dojo, 'oracle'))
    assert credits == 1000                      # '1,000' with the thousands separator
    assert resources == [('Salvage', 650), ('Circuits', 350), ('Polymer Bundle', 350),
                         ('Forma', 1)]
    assert [dojo.slugify(n) for n, _a in resources] == ['salvage', 'circuits', 'polymer_bundle',
                                                        'forma']


def test_buildrequire_table_parses(dojo):
    spec = {'slug': 'clan_key', 'name': 'Clan Key', 'page': 'Clan Key', 'heading': 'Clan Key',
            'tabber': None, 'note': ''}
    assert dojo.parse_room_table(PAGE_KEY, spec)[:2] == (
        1500, [('Morphics', 1), ('Polymer Bundle', 500), ('Ferrite', 500)])


def test_tabber_tab_selects_the_right_lab(dojo):
    credits, resources, _tiers = dojo.parse_room_table(PAGE, spec_of(dojo, 'bio_lab'))
    assert (credits, resources) == (1000, [('Salvage', 650), ('Circuits', 350)])
    assert 'Thermal Sludge' not in [n for n, _a in resources]   # Dagath's Hollow's own tab


def test_number_parsing(dojo):
    assert dojo.parse_amount('1,500') == 1500
    assert dojo.parse_amount(' 800 ') == 800
    assert dojo.parse_amount('N/A') is None
    assert dojo.parse_amount('') is None
    with pytest.raises(dojo.ExtractError):
        dojo.parse_amount('lots')


# ---------------------------------------------------------------- totals
def test_totals_sum_across_rooms(dojo):
    pages = fixture_pages()
    pages['energy_lab'] = cache_doc('energy_lab', 'Interactive Rooms', PAGE)
    doc, rows = dojo.build_doc(pages, now=1)
    # oracle + bio_lab + energy_lab in the wiki order of the docs
    assert [r['built'] for r in doc['rooms']] == [2, 3, 6]
    assert [r['slug'] for r in doc['rooms']] == ['oracle', 'energy_lab', 'bio_lab']
    assert doc['materials']['salvage'] == {'name': 'Salvage', 'needed': 1950}
    assert doc['materials']['circuits'] == {'name': 'Circuits', 'needed': 1050}
    assert doc['materials']['polymer_bundle'] == {'name': 'Polymer Bundle', 'needed': 350}
    assert doc['materials']['forma'] == {'name': 'Forma', 'needed': 1}
    assert doc['materials']['circuits']['needed'] == sum(
        r['costs'].get('circuits', 0) for r in doc['rooms'])
    assert sum(r['credits'] for r in doc['rooms']) == 3000
    assert dojo.summary_line(doc) == 'dojo_costs: rooms 3 | materials 4 | credits 3000 | skipped 6'


# ---------------------------------------------------------------- skips
def test_room_without_a_cost_table_is_skipped(dojo):
    doc, _rows = dojo.build_doc(fixture_pages(), now=1)
    assert 'observatory' not in [r['slug'] for r in doc['rooms']]
    skipped = [s for s in doc['skipped'] if s['name'] == 'Observatory']
    assert len(skipped) == 1
    assert skipped[0]['url'] == dojo.page_url(spec_of(dojo, 'observatory'))
    assert 'no cost table' in skipped[0]['reason']


def test_missing_wiki_page_is_skipped(dojo):
    pages = fixture_pages()
    pages['oracle'] = {'slug': 'oracle', 'requested_title': 'Nope', 'resolved_title': 'Nope',
                       'url': 'x', 'fetched': 0,
                       'api': {'query': {'pages': [{'title': 'Nope', 'missing': True}]}}}
    doc, _rows = dojo.build_doc(pages, now=1)
    assert 'oracle' not in [r['slug'] for r in doc['rooms']]
    oracle_skip = next(s for s in doc['skipped'] if s['name'] == 'Oracle')
    assert 'missing' in oracle_skip['reason'] and oracle_skip['url'].startswith('https://')


def test_unreadable_amount_skips_the_room_instead_of_guessing(dojo):
    bad = PAGE.replace('| resource2ghost         = 350\n', '| resource2ghost         = about 350\n')
    assert bad != PAGE
    doc, _rows = dojo.build_doc({'oracle': cache_doc('oracle', 'Interactive Rooms', bad)}, now=1)
    assert doc['rooms'] == []
    assert any('unreadable' in s['reason'] for s in doc['skipped'] if s['name'] == 'Oracle')


def test_empty_parse_never_clobbers_an_existing_document(dojo):
    good, _rows = dojo.build_doc(fixture_pages(), now=1)
    dojo.atomic_write(dojo.out_path(), good)
    assert dojo.main(['--once', '--offline', '--refresh']) == 0
    assert read_json(dojo.out_path())['rooms'] == good['rooms']


# ---------------------------------------------------------------- cache / network
def test_cached_run_needs_no_network(dojo, monkeypatch):
    """Every room cached -> --once must parse all 9 from disk and never call the wiki."""
    for spec in dojo.ROOMS:
        dojo.atomic_write(os.path.join(dojo.cache_dir(), spec['slug'] + '.json'),
                          cache_doc(spec['slug'], spec['page'], page_for(spec)))
    calls = []

    def no_network(*args, **kwargs):
        calls.append(args)
        raise AssertionError('the wiki was contacted although the cache was complete')

    monkeypatch.setattr(dojo.urllib.request, 'urlopen', no_network)
    assert dojo.main(['--once']) == 0
    assert calls == []
    written = read_json(dojo.out_path())
    assert [r['slug'] for r in written['rooms']] == [s['slug'] for s in dojo.ROOMS]
    assert written['skipped'] == []
    assert written['materials']['ferrite'] == {'name': 'Ferrite', 'needed': 90}
    assert written['rooms'][0]['costs'] == {'ferrite': 10}


# ---------------------------------------------------------------- CLI (subprocess)
def run_cli(tmp_path, *args, data_dir=None):
    env = dict(os.environ)
    env['WFM_DATA_DIR'] = str(data_dir or (tmp_path / 'data'))
    return subprocess.run([sys.executable, DOJO_SRC, *args], cwd=str(tmp_path), env=env,
                          capture_output=True, text=True, timeout=120)


def seed_caches(tmp_path):
    """The four fixture caches, so an offline subprocess run parses 2 of 9 rooms."""
    data = tmp_path / 'data'
    cache = data / 'dropdata' / 'wiki_dojo'
    cache.mkdir(parents=True, exist_ok=True)
    for slug, doc in fixture_pages().items():
        (cache / (slug + '.json')).write_text(json.dumps(doc), encoding='utf-8')
    return data


def test_cli_dry_run_writes_nothing(tmp_path):
    data = seed_caches(tmp_path)
    before = sorted(str(p) for p in data.rglob('*'))
    result = run_cli(tmp_path, '--dry-run', '--offline')
    assert result.returncode == 0, result.stderr
    assert 'dojo_costs: rooms 2 | materials 4 | credits 2000 | skipped 7' in result.stdout
    assert 'dry run - wrote nothing' in result.stdout
    assert not (data / 'dojo_costs.json').exists()
    assert sorted(str(p) for p in data.rglob('*')) == before


def test_cli_once_writes_the_document(tmp_path):
    data = seed_caches(tmp_path)
    result = run_cli(tmp_path, '--once', '--offline')
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == ('dojo_costs: rooms 2 | materials 4 | credits 2000 '
                                             '| skipped 7')
    doc = json.loads((data / 'dojo_costs.json').read_text(encoding='utf-8'))
    assert sorted(doc.keys()) == SCOPE_KEYS
    assert doc['materials']['salvage'] == {'name': 'Salvage', 'needed': 1300}


def test_cli_offline_without_a_cache_reports_skips(tmp_path):
    result = run_cli(tmp_path, '--once', '--offline')
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == ('dojo_costs: rooms 0 | materials 0 | credits 0 '
                                             '| skipped 9')
    for line in ('Clan Hall', 'Oracle', 'Energy Lab', 'Dry Dock'):
        assert line in result.stdout
    assert 'offline and no cached page' in result.stdout


def test_cli_out_path_override(tmp_path):
    seed_caches(tmp_path)
    target = tmp_path / 'custom' / 'dojo.json'
    result = run_cli(tmp_path, '--out', str(target))
    assert result.returncode == 0, result.stderr
    assert json.loads(target.read_text(encoding='utf-8'))['source'] == 'wiki.warframe.com'


def test_cli_json_flag_keeps_stdout_parseable(tmp_path):
    seed_caches(tmp_path)
    result = run_cli(tmp_path, '--json', '--offline')
    assert result.returncode == 0, result.stderr
    doc = json.loads(result.stdout)
    assert sorted(doc.keys()) == SCOPE_KEYS
    assert 'dojo_costs: rooms 2 | materials 4 | credits 2000 | skipped 7' in result.stderr


def test_cli_selftest_exits_zero_offline(tmp_path):
    result = run_cli(tmp_path, '--selftest')
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith('selftest: ok (')
    assert not (tmp_path / 'data').exists()          # no writes, no cache, no output file
    assert list(tmp_path.rglob('dojo_costs.json')) == []

def test_all_five_tier_columns_parse(dojo):
    """A room whose table carries all five clan tiers must expose every one of them."""
    spec = spec_of(dojo, 'oracle')
    table = ['{{DojoRoom']
    for tier, scale in (('ghost', 1), ('shadow', 3), ('storm', 10), ('mountain', 30), ('moon', 100)):
        table.append('| credit%-9s= %d' % (tier, 1000 * scale))
    table += ['| resource1              = Salvage']
    for tier, scale in (('ghost', 1), ('shadow', 3), ('storm', 10), ('mountain', 30), ('moon', 100)):
        table.append('| resource1%-8s= %d' % (tier, 650 * scale))
    table.append('}}')
    text = '==%s==\n%s\n' % (spec['heading'], '\n'.join(table))
    if spec['tabber']:
        text = '<tabber>%s={{Quote|stub}}\n%s</tabber>\n' % (spec['tabber'], text)
    credits, resources, tiers = dojo.parse_room_table(text, spec)
    assert credits == 1000 and resources == [('Salvage', 650)]
    assert list(tiers) == ['ghost', 'shadow', 'storm', 'mountain', 'moon']
    assert tiers['ghost']['costs'] == {'salvage': 650}
    assert tiers['shadow']['costs'] == {'salvage': 1950}
    assert tiers['moon']['credits'] == 100000 and tiers['moon']['costs'] == {'salvage': 65000}
    assert tiers['moon']['names'] == {'salvage': 'Salvage'}


def test_tier_totals_only_cover_tiers_the_wiki_lists(dojo):
    """A tier appears exactly where the page lists it - nothing is scaled or invented."""
    doc, _rows = dojo.build_doc(fixture_pages(), now=1700000000)
    assert list(doc['room_tiers']) == ['oracle', 'bio_lab']
    assert set(doc['room_tiers']['oracle']) == {'ghost', 'shadow'}   # fixture lists both
    assert set(doc['room_tiers']['bio_lab']) == {'ghost'}            # this one lists ghost only
    assert list(doc['tier_totals']) == ['ghost', 'shadow']
    assert doc['tier_totals']['ghost']['credits'] == 2000
    assert doc['tier_totals']['ghost']['materials']['salvage'] == {'name': 'Salvage', 'needed': 1300}
    assert doc['tier_totals']['shadow']['credits'] == 3000
    assert doc['tier_totals']['shadow']['materials']['salvage'] == {'name': 'Salvage', 'needed': 1950}
    assert 'forma' not in doc['tier_totals']['shadow']['materials']  # 'N/A' cell dropped, never zeroed

