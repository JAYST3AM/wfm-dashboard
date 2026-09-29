"""The planner API contract (Phase 2).

Every endpoint is exercised against a real socket, an ingested fixture database and the same
"exec server.py, talk HTTP" pattern as tests/test_session_api.py - no stubs between the route
and the engine, because the point of these routes is that they hand the Phase 1 engine's own
answers to the UI.

The database is picked by WFM_BUILD_DB, so these tests build a small one from the engine's
fixtures and never touch the 5 MB data/build_data.json.
"""
import importlib.util
import json
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from builds import ingest  # noqa: E402
from test_builds_engine import (FIXTURE_EQUIPMENT, FIXTURE_MODS,  # noqa: E402
                                _mod_row)

DB_FILE = None       # built once per session


@pytest.fixture(scope='session')
def db_file(tmp_path_factory):
    """One ingested fixture database on disk: the same code path the real ingest uses."""
    global DB_FILE
    if DB_FILE is None:
        slugs = {'/Fixture/BratonPrime': 'braton_prime', '/Fixture/Excalibur': 'excalibur'}
        src = {'file': 'planner-api-test'}
        mods = [ingest.normalise_mod(_mod_row(*row), slugs, src) for row in FIXTURE_MODS]
        equipment = [ingest.normalise_equipment(dict(raw, uniqueName=unique, name=name),
                                                kind, slugs, {}, src)
                     for unique, name, kind, raw in FIXTURE_EQUIPMENT]
        db = ingest.build_database(mods, equipment,
                                   {'generated_iso': 'planner-api-test',
                                    'game_version': 'planner-api-test'})
        out = tmp_path_factory.mktemp('planner_db') / 'build_data.json'
        out.write_text(json.dumps(db, indent=1, sort_keys=True), encoding='utf-8')
        DB_FILE = str(out)
    return DB_FILE


class Harness:
    """The server as a module on a real socket, with the planner pointed at the fixture DB."""

    def __init__(self, root, data, db):
        self.root, self.data, self.db = str(root), str(data), str(db)
        self.server = None

    def __enter__(self):
        spec = importlib.util.spec_from_file_location('planner_test_server',
                                                      str(Path(self.root) / 'server.py'))
        self.mod = importlib.util.module_from_spec(spec)
        os.environ['WFM_BUILD_DB'] = self.db
        spec.loader.exec_module(self.mod)
        self.mod.ROOT = self.root
        self.mod.DATA = self.data                 # never the repo's data/
        self.mod._PLANNER.clear()                 # bind to this database, not a cached one
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.mod.H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = 'http://127.0.0.1:%d' % self.server.server_address[1]
        return self

    def __exit__(self, *exc):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        os.environ.pop('WFM_BUILD_DB', None)

    def get(self, path):
        return self._call(path, None)

    def post(self, path, body):
        return self._call(path, json.dumps(body).encode())

    def _call(self, path, data):
        req = urllib.request.Request(self.base + path, data=data,
                                     method='POST' if data else 'GET')
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode('utf-8') or '{}')


@pytest.fixture(scope='module')
def api(tmp_path_factory, db_file):
    with Harness(REPO, tmp_path_factory.mktemp('planner_data'), db_file) as h:
        yield h


def _quote(key):
    return urllib.parse.quote(key, safe='')


def build_with(slots=None, **over):
    """The engine-test build shape: Braton Prime, rank 30, catalysed, MR 30."""
    build = {'config': 'A', 'equipment_id': '/Fixture/BratonPrime', 'equipment_rank': 30,
             'orokin': True, 'mastery_rank': 30, 'slots': []}
    for index, (mod_id, rank) in enumerate(slots or ()):
        build['slots'].append({'kind': 'normal', 'index': index, 'polarity': None,
                               'mod': {'id': mod_id, 'rank': rank}})
    build.update(over)
    return build


def set_polarity(build, index, polarity):
    build['slots'][index]['polarity'] = polarity
    return build


# --------------------------------------------------------------------- routes exist at all

def test_a_planner_route_answers_and_an_unknown_one_does_not(api):
    status, body = api.get('/api/planner/meta')
    assert status == 200 and body['ok'] is True
    status, body = api.get('/api/planner/no_such_thing')
    assert status == 404 and body['ok'] is False


def test_meta_names_the_database_the_planner_is_serving(api):
    _, meta = api.get('/api/planner/meta')
    assert meta['schema_version'] == ingest.SCHEMA_VERSION
    assert meta['storage_version'] >= 1
    assert meta['content_hash']
    kinds = {k['kind']: k for k in meta['kinds']}
    assert kinds['primary']['slots'] == ['normal', 'exilus']
    assert kinds['warframe']['slots'] == ['normal', 'aura', 'exilus']
    assert kinds['primary']['normal_slots'] == 8
    assert kinds['primary']['max_rank'] == 30 and kinds['warframe']['max_rank'] == 30
    assert meta['unsupported'] >= 1                      # the refusal registry is real
    assert meta['equipment_total'] == len(FIXTURE_EQUIPMENT)


def test_a_missing_engine_is_an_answer_not_a_crash(monkeypatch):
    """A checkout without builds/ must keep the rest of the app alive and say what is wrong."""
    spec = importlib.util.spec_from_file_location('planner_no_engine', str(REPO / 'server.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setitem(mod._PLANNER, 'mod', None)
    out = mod.planner_meta()
    assert out['ok'] is False and 'engine' in out['error']


# --------------------------------------------------------------------- equipment search

def test_equipment_search_ranks_the_exact_name_first(api):
    _, body = api.get('/api/planner/equipment?q=braton')
    assert [r['name'] for r in body['rows']] == ['Braton Prime']
    _, body = api.get('/api/planner/equipment?q=' + urllib.parse.quote_plus('Braton Prime'))
    assert body['rows'][0]['name'] == 'Braton Prime'
    row = body['rows'][0]
    assert row['mastery_req'] == 8 and row['kind'] == 'primary'
    assert row['damage_total'] == 35 and row['crit_chance'] == 12


def test_equipment_search_filters_by_kind(api):
    _, body = api.get('/api/planner/equipment?q=braton&kind=melee')
    assert body['rows'] == [] and body['total'] == 0
    _, body = api.get('/api/planner/equipment?kind=warframe')
    assert {r['kind'] for r in body['rows']} == {'warframe'}
    assert body['total'] == 1


def test_an_unknown_equipment_key_is_a_clean_error(api):
    status, body = api.get('/api/planner/equipment/does_not_exist')
    assert status == 200 and body['ok'] is False and 'no equipment' in body['error']


def test_detail_hands_back_the_slot_layout_the_engine_will_validate(api):
    _, body = api.get('/api/planner/equipment/' + _quote('/Fixture/BratonPrime'))
    assert body['ok'] is True
    assert [s['kind'] for s in body['slots']] == ['normal'] * 8 + ['exilus']
    assert [s['polarity'] for s in body['slots'][:3]] == ['madurai', 'naramon', None]
    assert all(s['unlocked'] for s in body['slots'][:8])
    assert body['slots'][8]['unlocked'] is False           # exilus needs its adapter
    assert body['slots'][8]['polarity'] == 'naramon'
    assert body['equipment']['name'] == 'Braton Prime'
    assert body['equipment']['damage_total'] == 35         # the stat panel's base
    assert body['equipment']['damage']['impact'] == 1.75   # and its split


def test_a_warframe_detail_carries_an_aura_slot(api):
    _, body = api.get('/api/planner/equipment/' + _quote('/Fixture/Excalibur'))
    kinds = [s['kind'] for s in body['slots']]
    assert kinds.count('aura') == 1 and kinds.count('exilus') == 1
    aura = body['slots'][kinds.index('aura')]
    assert aura['polarity'] == 'naramon'
    assert [s['polarity'] for s in body['slots'][:2]] == ['vazarin', 'madurai']
    assert body['polarities_from_export'] is True


# --------------------------------------------------------------------- mod library

def test_the_library_holds_the_mods_that_install_on_the_item(api):
    _, body = api.get('/api/planner/mods?equipment=' + _quote('/Fixture/BratonPrime'))
    assert body['ok'] is True and body['total'] >= 5
    assert body['equipment'] == {'id': '/Fixture/BratonPrime', 'name': 'Braton Prime',
                                 'kind': 'primary'}
    ser = next(r for r in body['rows'] if r['name'] == 'Serration')
    assert not ser['variant']                            # the standard copy sorts first
    assert ser['polarity'] == 'madurai' and ser['base_drain'] == 4 and ser['max_rank'] == 10
    assert ser['drain_max'] == 14                          # the engine's drain rule, not the UI's
    assert ser['lines'] == ['+165% Damage']
    assert ser['slot'] == 'normal' and ser['targets'] == ['primary']
    assert 'Point Strike' in {r['name'] for r in body['rows']}
    # the starter copy is a separate row and sorts after the standard one
    copies = [i for i, r in enumerate(body['rows']) if r['name'] == 'Serration']
    assert copies == sorted(copies) and not body['rows'][copies[0]]['variant']
    assert body['rows'][copies[-1]]['variant'] == 'beginner'


def test_the_library_names_what_it_will_not_calculate(api):
    _, body = api.get('/api/planner/mods?equipment=' + _quote('/Fixture/BratonPrime'))
    galv = next(r for r in body['rows'] if r['name'] == 'Galvanized Chamber')
    assert galv['support']['unmodelled'] >= 1
    assert galv['support']['unmodelled_examples']
    assert galv['support']['conditional'] >= 1
    assert galv['support']['conditional_examples']
    assert galv['flags'] == ['galvanized']
    # the base value is on the card line; the on-kill rider is named, not mixed in
    assert galv['lines'] == ['+80.3% Multishot']
    assert not any('On Kill' in line for line in galv['lines'])
    assert all('Multishot' in t for t in galv['support']['conditional_examples'])


def test_a_bad_equipment_key_in_the_library_is_a_clean_error(api):
    status, body = api.get('/api/planner/mods?equipment=nope')
    assert status == 200 and body['ok'] is False and 'no equipment' in body['error']


# --------------------------------------------------------------------- compute / preview / explain

def test_compute_answers_with_the_engines_own_numbers(api):
    build = build_with([('/Fixture/Serration', 10), ('/Fixture/PointStrike', 5)])
    set_polarity(build, 0, 'madurai')
    status, body = api.post('/api/planner/compute', build)
    assert status == 200 and body['ok'] is True
    assert body['validation']['ok'] is True
    stats = body['result']['stats']
    assert stats['modded_base_damage'] == 92.75            # 35 * 2.65, the engine's figure
    assert stats['critical_chance'] == 30                  # 12% + Point Strike R5
    assert body['baseline']['stats']['modded_base_damage'] == 35
    assert body['capacity']['capacity']['total'] == 60     # rank 30, catalysed
    assert body['capacity_used'] == 7 + 9                  # matched 14/2; a vacant slot is free
    assert body['engine']['schema_version'] == ingest.SCHEMA_VERSION
    assert body['result']['traces']['damage']


def test_a_wrong_polarity_costs_more_and_the_engine_says_so(api):
    """Vacant, matching and mismatched are three different rules - the UI shows the engine's."""
    def used(index_polarity):
        build = build_with([('/Fixture/Serration', 10), ('/Fixture/PointStrike', 5)])
        set_polarity(build, 0, 'madurai')
        if index_polarity is not None:
            set_polarity(build, 1, index_polarity)
        _, out = api.post('/api/planner/compute', build)
        return out

    vacant = used(None)['capacity']['drain']['per_slot'][1]
    matched = used('madurai')['capacity']['drain']['per_slot'][1]
    wrong = used('naramon')['capacity']['drain']['per_slot'][1]
    assert (vacant['rule'], vacant['adjusted_drain']) == ('vacant', 9)
    assert (matched['rule'], matched['adjusted_drain']) == ('matching', 5)
    assert (wrong['rule'], wrong['adjusted_drain']) == ('mismatched', 11)
    assert wrong['raw_drain'] == 9                         # the row the UI paints


def test_compute_reports_capacity_overrun_as_a_validation_error(api):
    build = build_with([('/Fixture/Serration', 10)] * 6)
    _, body = api.post('/api/planner/compute', build)
    assert body['ok'] is False
    codes = [e['code'] for e in body['validation']['errors']]
    assert 'capacity_exceeded' in codes
    assert body['validation']['errors'][0]['message']      # it explains itself


def test_compute_reports_refusals_instead_of_dropping_them(api):
    build = build_with([('/Fixture/Serration', 10), ('/Fixture/GalvanizedChamber', 10)])
    _, body = api.post('/api/planner/compute', build)
    assert body['unsupported'], 'the galvanized rider must be named, not silently dropped'
    assert 'multishot' in json.dumps(body['unsupported']).lower()
    assert body['unsupported_registry'] or body['unsupported'][0].get('reason')


def test_compute_never_raises_on_junk(api):
    for body_in in ({}, {'slots': 'nope'}, {'equipment_id': 5, 'slots': [1, 2]},
                    {'equipment_id': 'nope', 'slots': []}):
        status, out = api.post('/api/planner/compute', body_in)
        assert status == 200 and out.get('ok') is False
        assert out.get('validation') or out.get('error')


def test_preview_diffs_the_hypothetical_edit_against_the_build(api):
    base = set_polarity(build_with([('/Fixture/Serration', 10)]), 0, 'madurai')
    nxt = json.loads(json.dumps(base))
    nxt['slots'].append({'kind': 'normal', 'index': 1, 'polarity': None,
                         'mod': {'id': '/Fixture/PointStrike', 'rank': 5}})
    _, body = api.post('/api/planner/preview', {'build': base, 'next': nxt})
    assert body['ok'] is True
    diff = {d['stat']: d for d in body['diff']}
    assert diff['critical_chance']['a'] == 12 and diff['critical_chance']['b'] == 30
    assert body['b']['validation']['ok'] is True            # the fit check a drop shows
    assert body['b']['capacity_used'] == 7 + 9
    assert body['a']['capacity_used'] == 7
    assert body['b']['stats']['modded_base_damage'] == 92.75


def test_preview_shows_a_hypothetical_edit_that_does_not_fit(api):
    base = build_with([('/Fixture/Serration', 10)])
    nxt = build_with([('/Fixture/Serration', 10)] * 6)
    _, body = api.post('/api/planner/preview', {'build': base, 'next': nxt})
    codes = [e['code'] for e in body['b']['validation']['errors']]
    assert 'capacity_exceeded' in codes
    assert body['b']['capacity_used'] > body['b']['capacity']['capacity']['total']


def test_preview_rejects_junk_bodies(api):
    status, body = api.post('/api/planner/preview', {'build': 1, 'next': 2})
    assert status == 200 and body['ok'] is False and 'objects' in body['error']


def test_explain_reports_the_trace_and_what_can_be_explained(api):
    build = set_polarity(build_with([('/Fixture/Serration', 10)]), 0, 'madurai')
    _, body = api.post('/api/planner/explain', {'build': build, 'stat': 'damage'})
    assert body['ok'] is True and body['stat'] == 'damage'
    assert 'Base: 35' in body['text'] and 'Final: 92.75' in body['text']
    assert 'damage' in body['available'] and 'critical_chance' in body['available']
    assert body['result']['stats']['modded_base_damage'] == 92.75
    _, body = api.post('/api/planner/explain', {'build': build, 'stat': 'no_such_stat'})
    assert body['ok'] is False and body['available']


def test_unsupported_registry_is_served_to_the_ui(api):
    _, body = api.get('/api/planner/unsupported')
    assert body['ok'] is True and body['rows']
    assert isinstance(body['marker_keys'], dict) and body['marker_keys']


def test_a_post_with_a_broken_body_is_a_400_not_a_traceback(api):
    req = urllib.request.Request(api.base + '/api/planner/compute', data=b'{not json',
                                 method='POST')
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=30)
    assert e.value.code == 400


def test_the_planner_payloads_are_json_safe_and_sized_for_a_ui(api):
    """Every payload the page fetches must serialise and stay small enough to cache."""
    for path in ('/api/planner/meta', '/api/planner/unsupported',
                 '/api/planner/equipment?kind=primary',
                 '/api/planner/equipment/' + _quote('/Fixture/BratonPrime'),
                 '/api/planner/mods?equipment=' + _quote('/Fixture/BratonPrime')):
        status, body = api.get(path)
        assert status == 200 and body.get('ok') is True, path
        assert len(json.dumps(body)) < 400_000, path
