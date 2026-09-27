"""scripts/mastery.py: the save join, the wiki-derived value table + rank curve, the queue order,
MR gating, the XP cross-check and the CLI contract.

Every test is offline: WFM_DATA_DIR / WFM_STATIC_DIR / WFM_ALECA_DIR are redirected into tmp_path
before the module is imported, the wiki pages are seeded into the tmp data dir as cached raw API
responses (the shape scripts/mastery.py writes), and the AlecaFrame directory points at a
non-existent path - so no network is touched and the repo's real data/, static/ and save are
never read or written.
"""
import json
import os
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

from conftest import load_script, read_json, write_json

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), 'scripts', 'mastery.py')

STORE_KEYS = ['schema', 'updated', 'updated_iso', 'source', 'mr', 'summary', 'categories', 'next',
              'items']
MR_KEYS = ['rank', 'xp_total', 'xp_into_rank', 'xp_for_next', 'pct', 'next_rank',
           'xp_per_rank_source']
SUMMARY_KEYS = ['tracked', 'mastered', 'owned_unmastered', 'missing', 'buildable_now', 'gated_by_mr']
ROW_KEYS = ['name', 'category', 'slug', 'unique_name', 'state', 'xp_value', 'build', 'obtain',
            'mastery_req', 'gated']
CATEGORY_KEYS = ['key', 'name', 'total', 'mastered', 'owned_unmastered', 'missing', 'pct']
SUMMARY_RE = re.compile(
    r'^mastery: MR \d+ \([\d.]+% to \d+\) \| tracked \d+ \| mastered \d+ \| owned \d+ '
    r'\| missing \d+ \| buildable now \d+ \| next queue \d+$')

# ---------------------------------------------------------------- fixture save / log / craft
FIXTURE_SAVE = {'PlayerLevel': 2, 'XPInfo': [
    {'ItemType': '/Lotus/Powersuits/Ninja/Ninja', 'XP': 500000},
    {'ItemType': '/Lotus/Weapons/Tenno/Rifle/Braton', 'XP': 400000},
    {'ItemType': '/Lotus/Weapons/Tenno/Rifle/BratonPrime', 'XP': 200},       # below its value
    {'ItemType': '/Lotus/Powersuits/EntratiMech/NechroTech', 'XP': 800000},
    {'ItemType': '/Lotus/Types/CrewShip/RailJack/DefaultHarness', 'XP': 100000},  # outside the log
]}

ASH_OBTAIN = {'short': 'Venus - X', 'lanes': 1, 'parts': 0, 'complete': True,
              'lines': [{'k': 'mission', 'part': None, 'label': 'Venus - X',
                         'detail': 'Skirmish \u00b7 rotation A \u00b7 13.33%'}]}


def item(name, path, slug=None, owned=False, mastered=False, req=0, obtain=None):
    return {'name': name, 'slug': slug or name.lower().replace(' ', '_'), 'unique_name': path,
            'owned': owned, 'mastered': mastered, 'mastery_req': req, 'obtain': obtain}


FIXTURE_LOG = {'version': 1, 'categories': [
    {'key': 'warframes', 'name': 'Warframes', 'items': [
        item('Ash', '/Lotus/Powersuits/Ninja/Ninja', mastered=True, obtain=ASH_OBTAIN),
        item('Nezha', '/Lotus/Powersuits/Odalisk/Odalisk', slug='nezha', req=5),   # gated at MR 2
    ]},
    {'key': 'primary', 'name': 'Primary', 'items': [
        item('Braton', '/Lotus/Weapons/Tenno/Rifle/Braton', mastered=True),
        item('Braton Prime', '/Lotus/Weapons/Tenno/Rifle/BratonPrime', slug='braton_prime',
             mastered=True, req=8),
        item('Braton Vandal', '/Lotus/Weapons/Tenno/Rifle/BratonVandal', slug='braton_vandal'),
        item('Latron', '/Lotus/Weapons/Tenno/Rifle/Latron', slug='latron'),
        item('Boltor', '/Lotus/Weapons/Tenno/Rifle/Boltor', slug='boltor'),
        item('Tetra', '/Lotus/Weapons/Tenno/Rifle/Tetra', slug='tetra'),
    ]},
    {'key': 'archwing', 'name': 'Archwing', 'items': [
        item('Itzal', '/Lotus/Powersuits/Archwing/Itzal', slug='itzal', owned=True),
    ]},
    {'key': 'other', 'name': 'Other', 'items': [
        item('Voidrig', '/Lotus/Powersuits/EntratiMech/NechroTech', slug='voidrig', owned=True,
             mastered=True),
        item('Bonewidow', '/Lotus/Powersuits/EntratiMech/ThanoTech', slug='bonewidow'),
        item('Stray Module', '/Lotus/Types/Stray/Module', slug='stray_module'),
    ]},
    {'key': 'lab_parts', 'name': 'Lab Parts', 'items': [
        item('Weird Thing', '/Lotus/Types/Lab/Thing', slug='weird_thing'),
    ]},
]}

FIXTURE_CRAFT = {'rows': [
    {'result_slug': 'braton_vandal_set', 'result_name': 'Braton Vandal Set', 'verdict': 'CRAFT',
     'buy_cost': 0.0, 'missing_parts': [], 'built_floor': 10.0, 'owned_parts': ['x']},
    {'result_slug': 'latron_set', 'result_name': 'Latron Set', 'verdict': 'CRAFT', 'buy_cost': 7.0,
     'missing_parts': ['latron_barrel'], 'built_floor': 8.0, 'owned_parts': []},
    {'result_slug': 'boltor_blueprint', 'result_name': 'Boltor Blueprint', 'verdict': 'BUY',
     'buy_cost': 12.0, 'missing_parts': ['boltor_stock'], 'built_floor': 4.0, 'owned_parts': []},
    {'result_slug': 'voidrig_set', 'result_name': 'Voidrig Set', 'verdict': 'CRAFT',
     'buy_cost': 3.0, 'missing_parts': ['voidrig_casing'], 'built_floor': 5.0, 'owned_parts': []},
]}

FIXTURE_PAGE = """Wiki prose.
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
a later table that must not leak into the rank parse
{| class="article-table"
! Category !! Count !! Mastery
|-
| [[Warframes]] || 120 || 720,000
|-
|}
"""
FIXTURE_MODULE = """-- helper module for Mastery Rank tables
local baseMasteryXp = {
    warframes = 6000,
    primaries = 3000,
    secondaries = 3000,
    melee = 3000,
    amps = 3000,
    sentinels = 6000,
    sentinelWeapons = 3000,
    companions = 6000,
    archwings = 6000,
    archGuns = 3000,
    archMelees = 3000,
    ['k-drives'] = 6000,
    necramechs = 8000,
}
local function getRankXP(Rank)
    local legRank = math.max(0, Rank - 30)
    Rank = math.min(Rank, 30)
    return 2500 * Rank ^ 2  +  legRank * 147500
end
"""


def wiki_doc(title, text):
    """The cached raw-API-response shape scripts/mastery.py writes to data/dropdata/mastery/."""
    page = {'pageid': 1, 'ns': 0, 'title': title,
            'revisions': [{'slots': {'main': {'contentmodel': 'wikitext', 'content': text}}}]}
    return {'title': title, 'resolved': title, 'missing': False, 'fetched': 1700000000,
            'url': 'https://wiki.warframe.com/api.php?fixture=' + title,
            'response': {'batchcomplete': True, 'query': {'pages': [page]}}, 'text': text}


@pytest.fixture
def ms(tmp_path, monkeypatch):
    """mastery.py loaded with every path redirected into tmp_path (fully offline)."""
    data, static, af = tmp_path / 'data', tmp_path / 'static', tmp_path / 'no-alecaframe'
    data.mkdir()
    write_json(data / 'collection_log.json', FIXTURE_LOG)
    write_json(data / 'craft.json', FIXTURE_CRAFT)
    write_json(data / 'lastData.dec.json', FIXTURE_SAVE)
    wiki = data / 'dropdata' / 'mastery'
    write_json(wiki / 'mastery_rank.json', wiki_doc('Mastery Rank', FIXTURE_PAGE))
    write_json(wiki / 'module_masteryrank.json', wiki_doc('Module:MasteryRank', FIXTURE_MODULE))
    mod = load_script('mastery', monkeypatch=monkeypatch, env={
        'WFM_DATA_DIR': str(data), 'WFM_STATIC_DIR': str(static), 'WFM_ALECA_DIR': str(af)})
    return SimpleNamespace(mod=mod, tmp=tmp_path, data=data, static=static, af=af,
                           save=data / 'lastData.dec.json', out=data / 'mastery.json',
                           stat=static / 'mastery.json')


def run(ms, argv=None):
    return ms.mod.main(argv or [])


def build(ms, argv=None):
    """Run the CLI and return the written store (fails the test when the exit code is not 0)."""
    code = run(ms, argv)
    assert code == 0
    return read_json(ms.out)


def test_env_paths_override_repo_data(ms):
    assert ms.mod.DATA == str(ms.data) and ms.mod.STATIC == str(ms.static)
    assert ms.mod.AF == str(ms.af)
    assert str(ms.mod.out_path()).startswith(str(ms.tmp))
    assert str(ms.mod.static_copy_path()).startswith(str(ms.tmp))
    assert str(ms.mod.wiki_cache_dir()).startswith(str(ms.tmp))


def test_missing_save_returns_1_and_writes_nothing(ms, capsys):
    os.remove(str(ms.save))
    assert run(ms) == 1
    assert 'run scripts/refresh.py' in capsys.readouterr().out
    assert not ms.out.exists() and not ms.stat.exists()


def test_missing_collection_log_returns_1(ms, capsys):
    os.remove(str(ms.data / 'collection_log.json'))
    assert run(ms) == 1
    assert 'no collection log' in capsys.readouterr().out
    assert not ms.out.exists()


def test_plaintext_abs_missing_uses_the_cached_save(ms):
    doc = build(ms)                                     # no live save: falls back to the dec.json
    assert doc['summary']['mastered'] == 4


def test_store_schema_keys_exact(ms):
    doc = build(ms)
    assert list(doc) == STORE_KEYS and doc['schema'] == 1
    assert isinstance(doc['updated'], int) and doc['updated'] > 1_600_000_000
    assert doc['updated_iso'].endswith('Z') and 'T' in doc['updated_iso']
    assert isinstance(doc['source'], str) and 'collection_log.json' in doc['source']
    assert list(doc['mr']) == MR_KEYS
    assert list(doc['summary']) == SUMMARY_KEYS
    assert [list(c) for c in doc['categories']] == [CATEGORY_KEYS] * len(doc['categories'])
    for row in doc['items'] + doc['next']:
        assert list(row) == ROW_KEYS


def test_mr_block_from_the_save_and_the_wiki_curve(ms):
    doc = build(ms)
    mr = doc['mr']
    assert mr['rank'] == 2 and mr['next_rank'] == 3
    assert mr['xp_total'] == 6000 + 3000 + 200 + 8000      # min(save XP, category value)
    assert mr['xp_for_next'] == 12500                      # 2500*3^2 - 2500*2^2
    assert mr['xp_into_rank'] == 7200                      # 17200 - 10000
    assert mr['pct'] == 57.6
    assert 'Mastery Ranks Allocation' in mr['xp_per_rank_source']
    assert 'baseMasteryXp' in mr['xp_per_rank_source'] and 'Mastery Points' in mr['xp_per_rank_source']
    assert '10,000' not in mr['xp_per_rank_source']         # never a per-account number


def test_join_states_and_xp_values(ms):
    doc = build(ms)
    by = {r['name']: r for r in doc['items']}
    assert by['Ash']['state'] == 'mastered' and by['Itzal']['state'] == 'owned'
    assert by['Nezha']['state'] == 'missing' and by['Tetra']['state'] == 'missing'
    assert by['Ash']['xp_value'] == 6000 and by['Braton']['xp_value'] == 3000
    assert by['Itzal']['xp_value'] == 6000                 # archwings = 6,000
    assert by['Voidrig']['xp_value'] == 8000               # the 'other' necramech bucket
    assert by['Stray Module']['xp_value'] is None          # 'other' but NOT a necramech path
    assert by['Weird Thing']['xp_value'] is None           # a category the wiki table lacks
    assert by['Weird Thing']['category'] == 'lab_parts'


def test_build_and_obtain_pass_through(ms):
    doc = build(ms)
    by = {r['name']: r for r in doc['items']}
    assert by['Braton Vandal']['build'] == {'verdict': 'CRAFT', 'cost': 0.0, 'missing_parts': []}
    assert by['Latron']['build'] == {'verdict': 'CRAFT', 'cost': 7.0,
                                     'missing_parts': ['latron_barrel']}
    assert by['Boltor']['build']['verdict'] == 'BUY'
    assert by['Tetra']['build'] is None and by['Ash']['build'] is None
    assert by['Ash']['obtain'] == {'short': 'Venus - X', 'first': ASH_OBTAIN['lines'][0],
                                   'text': 'Venus - X \u00b7 Skirmish \u00b7 rotation A \u00b7 13.33%'}
    assert by['Nezha']['obtain'] is None                   # the log had no obtain payload
    assert by['Ash']['mastery_req'] == 0 and by['Braton Prime']['mastery_req'] == 8


def test_summary_totals(ms):
    doc = build(ms)
    assert doc['summary'] == {'tracked': 13, 'mastered': 4, 'owned_unmastered': 1, 'missing': 8,
                              'buildable_now': 1, 'gated_by_mr': 1}
    assert doc['summary']['tracked'] == len(doc['items'])
    assert (doc['summary']['mastered'] + doc['summary']['owned_unmastered']
            + doc['summary']['missing']) == doc['summary']['tracked']
    buildable = [r['name'] for r in doc['items']
                 if r['state'] != 'mastered' and r['build']
                 and r['build']['verdict'] == 'CRAFT' and not r['build']['missing_parts']]
    assert buildable == ['Braton Vandal']
    gated = [r['name'] for r in doc['items'] if r['gated']]
    assert gated == ['Nezha']


def test_categories_keep_log_order_and_counts(ms):
    doc = build(ms)
    assert [c['key'] for c in doc['categories']] == ['warframes', 'primary', 'archwing', 'other',
                                                     'lab_parts']
    by = {c['key']: c for c in doc['categories']}
    assert by['warframes'] == {'key': 'warframes', 'name': 'Warframes', 'total': 2, 'mastered': 1,
                               'owned_unmastered': 0, 'missing': 1, 'pct': 50.0}
    assert by['archwing']['owned_unmastered'] == 1 and by['lab_parts']['mastered'] == 0
    assert by['lab_parts']['pct'] == 0.0
    assert sum(c['total'] for c in doc['categories']) == len(doc['items']) == 13


def test_queue_order_and_no_mastered_rows(ms):
    doc = build(ms)
    names = [r['name'] for r in doc['next']]
    assert names == ['Itzal', 'Braton Vandal', 'Latron', 'Bonewidow', 'Boltor', 'Tetra',
                     'Stray Module', 'Weird Thing', 'Nezha']
    assert not ({'Ash', 'Braton', 'Braton Prime', 'Voidrig'} & set(names))
    assert len(names) == len(doc['items']) - doc['summary']['mastered']
    assert doc['next'][0]['state'] == 'owned' and doc['next'][0]['xp_value'] == 6000
    assert [r['build']['cost'] for r in doc['next'][1:3]] == [0.0, 7.0]   # CRAFT cheapest first
    assert doc['next'][-1]['name'] == 'Nezha' and doc['next'][-1]['gated'] is True


def test_gated_rows_sort_after_ungated_ones(ms):
    """A gated owned row must not head the queue: the game will not let it be equipped yet."""
    log = json.loads(json.dumps(FIXTURE_LOG))
    log['categories'][0]['items'][1]['mastery_req'] = 0            # Nezha ungated
    log['categories'][2]['items'][0]['mastery_req'] = 9            # Itzal gated instead
    write_json(ms.data / 'collection_log.json', log)
    doc = build(ms)
    by = {r['name']: r for r in doc['items']}
    assert by['Itzal']['gated'] is True and by['Nezha']['gated'] is False
    assert [r['name'] for r in doc['next']][-1] == 'Itzal'         # gated -> last, owned or not
    assert doc['summary']['gated_by_mr'] == 1


def test_items_keep_the_collection_logs_own_order(ms):
    doc = build(ms)
    log = read_json(ms.data / 'collection_log.json')
    order = [i['name'] for c in log['categories'] for i in c['items']]
    assert [r['name'] for r in doc['items']] == order


def test_xp_cross_check_reports_the_below_value_row(ms):
    doc = build(ms)
    assert 'XP BELOW VALUE (1' in doc['source'] and 'Braton Prime' in doc['source']
    assert 'xp check: 3 of 4 compared mastered rows' in doc['source']
    check = ms.mod.xp_cross_check([r for r in doc['items']], ms.mod.xpinfo_map(FIXTURE_SAVE))
    assert check['checked'] == 4 and check['ok'] == 3
    assert [m['name'] for m in check['below_value']] == ['Braton Prime']
    gone = ms.mod.xp_cross_check([dict(r, unique_name='/Lotus/Gone') for r in doc['items']
                                  if r['state'] == 'mastered'],
                                 ms.mod.xpinfo_map(FIXTURE_SAVE))
    assert len(gone['uncheckable']) == 4 and gone['checked'] == 0


def test_source_names_the_uncounted_xpinfo_row(ms):
    doc = build(ms)
    assert 'XPInfo rows match no collection row' in doc['source']
    assert '/Lotus/Types/CrewShip/RailJack/DefaultHarness' in doc['source']


def test_log_flag_disagreement_is_reported_not_hidden(ms):
    log = json.loads(json.dumps(FIXTURE_LOG))
    log['categories'][1]['items'][5]['mastered'] = True            # Tetra: log says mastered
    write_json(ms.data / 'collection_log.json', log)
    doc = build(ms)
    by = {r['name']: r for r in doc['items']}
    assert by['Tetra']['state'] == 'missing'                       # the save wins, silently?  no:
    assert 'collection_log.json mastered flag != this save XPInfo' in doc['source']
    assert 'Tetra' in doc['source']
    assert doc['summary']['mastered'] == 4


def test_summary_line_first_and_regex(ms, capsys):
    doc = build(ms)
    lines = capsys.readouterr().out.splitlines()
    assert SUMMARY_RE.match(lines[0])
    assert lines[0] == ('mastery: MR 2 (57.6% to 3) | tracked 13 | mastered 4 | owned 1 | '
                        'missing 8 | buildable now 1 | next queue 9')
    assert lines[0] == ms.mod.summary_line(doc)
    assert any('xp check: 3 of 4' in ln for ln in lines)
    assert any(ln.startswith('store  :') for ln in lines)


def test_static_copy_written_and_matching(ms):
    build(ms)
    assert ms.out.exists() and ms.stat.exists()
    assert read_json(ms.out) == read_json(ms.stat)
    assert not (ms.data / 'mastery.json.tmp').exists()


def test_dry_run_prints_the_plan_and_writes_nothing(ms, capsys):
    assert run(ms, ['--dry-run']) == 0
    out = capsys.readouterr().out
    assert SUMMARY_RE.match(out.splitlines()[0])
    assert 'dry-run - nothing written' in out
    assert not ms.out.exists() and not ms.stat.exists()


def test_json_flag_prints_the_store_after_the_summary_line(ms, capsys):
    build(ms, ['--json'])
    lines = capsys.readouterr().out.splitlines()
    payloads = [ln for ln in lines if ln.startswith('{')]
    assert len(payloads) == 1
    assert json.loads(payloads[0]) == read_json(ms.out)


def test_out_flag_writes_only_there(ms, capsys):
    custom = ms.tmp / 'elsewhere' / 'mastery.json'
    assert run(ms, ['--out', str(custom)]) == 0
    assert read_json(custom)['summary']['tracked'] == 13
    assert not ms.out.exists()                              # the default store is untouched
    assert str(custom).replace(os.sep, '/') in capsys.readouterr().out


def test_no_static_copy_flag(ms):
    build(ms, ['--no-static-copy'])
    assert ms.out.exists() and not ms.stat.exists()


def test_no_fetch_without_a_cache_degrades_to_null_and_says_so(ms, capsys):
    import shutil
    shutil.rmtree(str(ms.data / 'dropdata'))
    assert run(ms, ['--no-fetch']) == 0
    out = capsys.readouterr().out
    assert 'UNAVAILABLE' in out and 'no wiki table cached' in out
    doc = read_json(ms.out)
    assert all(r['xp_value'] is None for r in doc['items'])
    assert doc['mr']['rank'] == 2 and doc['mr']['next_rank'] == 3
    assert doc['mr']['xp_for_next'] is None and doc['mr']['pct'] is None
    assert 'unavailable' in doc['mr']['xp_per_rank_source']
    assert out.splitlines()[0].startswith('mastery: MR 2 (?% to 3)')


def test_no_fetch_uses_the_cached_wiki_and_never_writes_the_cache(ms):
    cache = ms.data / 'dropdata' / 'mastery' / 'mastery_rank.json'
    before = cache.read_bytes()
    doc = build(ms, ['--no-fetch'])
    assert cache.read_bytes() == before
    assert doc['items'][0]['xp_value'] == 6000


def test_curve_parse_ignores_other_tables_and_needs_both_sources(ms):
    assert ms.mod.parse_rank_table(FIXTURE_PAGE) == {0: 0, 1: 2500, 2: 10000, 3: 22500,
                                                     31: 2397500}
    assert '720,000' not in str(ms.mod.parse_rank_table(FIXTURE_PAGE))   # the Total Mastery table
    curve, meta = ms.mod.build_curve(FIXTURE_PAGE, FIXTURE_MODULE)
    assert meta['mismatches'] == [] and meta['base'] == 2500 and meta['step'] == 147500
    assert curve(2) == 10000 and curve(31) == 2397500
    assert ms.mod.build_curve('', None)[0] is None
    assert 'Mastery Ranks Allocation' in meta['source'] and 'wiki.warframe.com' in meta['source']


def test_category_value_table_parses_the_modules_own_keys(ms):
    table = ms.mod.parse_category_xp(FIXTURE_MODULE)
    assert table['warframes'] == 6000 and table['primaries'] == 3000
    assert table['k-drives'] == 6000 and table['necramechs'] == 8000
    assert ms.mod.parse_category_xp('no table here') == {}
    assert ms.mod.xp_value_for({'unique_name': '/x'}, 'lab_parts', table) == (None, None)


def test_selftest_is_offline_and_exits_zero(tmp_path, monkeypatch, capsys):
    mod = load_script('mastery', monkeypatch=monkeypatch, env={
        'WFM_DATA_DIR': str(tmp_path / 'nope' / 'data'),
        'WFM_STATIC_DIR': str(tmp_path / 'nope' / 'static'),
        'WFM_ALECA_DIR': str(tmp_path / 'nope' / 'af')})
    assert mod.main(['--selftest']) == 0
    out = capsys.readouterr().out
    assert 'selftest : ok' in out and 'no network' in out
    assert os.listdir(str(tmp_path)) == []                 # nothing landed outside its own tmp dir


def test_selftest_subprocess_without_alecaframe(tmp_path):
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path / 'empty_af'), WFM_ALECA_DIR=str(tmp_path / 'af'))
    r = subprocess.run([sys.executable, SCRIPT, '--selftest'], cwd=str(tmp_path), env=env,
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'selftest : ok' in r.stdout
