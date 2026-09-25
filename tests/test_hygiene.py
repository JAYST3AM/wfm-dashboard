"""scripts/trader/hygiene.py - the listing-hygiene planner (plans only, never executes).

scripts/trader/ is private and gitignored, so this file skips itself when the script is not
present (clean CI checkout). hygiene.py is stdlib-only and import-safe by design - no
wfm_session, no HTTP, no work at import - which is why it can be loaded directly here
(unlike lister / watcher / detector, which sign in during module import and need stubbing).

Covered: output contract, rule behaviour (empty state, bulk hide / show, auto-hide-offline,
stale refresh, first-seen age memory), the settings write-race fallback, the killswitch gate,
and one real CLI run against a copied harness proving the tool writes a plan and nothing else.
"""
import os
import shutil
import subprocess
import sys

import pytest

from conftest import SCRIPTS, load_script, read_json, write_json

SRC = os.path.join(SCRIPTS, 'trader', 'hygiene.py')
pytestmark = pytest.mark.skipif(not os.path.exists(SRC),
                                reason='scripts/trader is private (gitignored) - nothing to test')

NOW = 1790341352
DAY = 86400

# --- fixtures: the trader_state.json snapshot shape + the trader_plan.json row shape --------
STATE = {
    'ts': NOW - 60, 'account': 'TestAcct', 'plat': 1247, 'orders': {
        'o1': {'slug': 'primed_continuity', 'name': 'Primed Continuity', 'type': 'sell', 'qty': 3,
               'plat': 47, 'visible': True, 'created': NOW - 2 * DAY},
        'o2': {'slug': 'neo_d3_relic', 'name': 'Neo D3 Relic', 'type': 'sell', 'qty': 18,
               'plat': 7, 'visible': True, 'created': NOW - 9 * DAY},
        'o3': {'slug': 'hildryn_prime_chassis_blueprint', 'name': 'Hildryn Prime Chassis Blueprint',
               'type': 'sell', 'qty': 10, 'plat': 9, 'visible': False, 'created': NOW - DAY},
        'o4': {'slug': 'carrier_prime_set', 'name': 'Carrier Prime Set', 'type': 'buy', 'qty': 1,
               'plat': 80, 'visible': True},
    }}
PLAN = {'generated': NOW - 3 * DAY, 'plan': [
    {'slug': 'primed_continuity', 'name': 'Primed Continuity', 'qty': 3, 'price': 47,
     'section': 'mod', 'lane': 'rank 0'},
    {'slug': 'neo_d3_relic', 'name': 'Neo D3 Relic', 'qty': 18, 'price': 7,
     'section': 'relic', 'lane': 'intact'},
    {'slug': 'hildryn_prime_chassis_blueprint', 'name': 'Hildryn Prime Chassis Blueprint',
     'qty': 10, 'price': 9, 'section': 'prime_part', 'lane': ''},
    # never listed: the hygiene planner treats it as a pending listing of its own
    {'slug': 'axi_s17_relic', 'name': 'Axi S17 Relic', 'qty': 9, 'price': 9,
     'section': 'relic', 'lane': 'intact'},
]}
SETTINGS = {'dry_run': True}


@pytest.fixture
def hyg(monkeypatch):
    """Fresh module object per test, so monkeypatched path globals cannot leak."""
    monkeypatch.delenv('WFM_HYGIENE_DATA', raising=False)   # ignore ambient overrides
    return load_script('trader/hygiene')


def doc_of(hyg, state=None, plan=None, settings=None, memory=None, now=NOW, **kw):
    """build_doc over fixtures - pure: no files, no network."""
    return hyg.build_doc(STATE if state is None else state, PLAN if plan is None else plan,
                         SETTINGS if settings is None else settings, memory or {}, now, **kw)


def run_cli(hyg, monkeypatch, tmp_path, argv=('--once',)):
    """Drive the real CLI in-process against throwaway files (never the repo's data/)."""
    data = tmp_path / 'data'
    data.mkdir(exist_ok=True)
    monkeypatch.setattr(hyg, 'DATA', str(data))
    monkeypatch.setattr(hyg, 'OUT', str(data / 'hygiene_plan.json'))
    monkeypatch.setattr(hyg, 'SETTINGS', str(tmp_path / 'settings.json'))
    monkeypatch.setattr(sys, 'argv', ['hygiene.py'] + list(argv))
    return hyg.main(), data


def write_fixtures(tmp_path):
    """state + plan + settings on disk, the way the trader engines leave them."""
    write_json(tmp_path / 'data' / 'trader_state.json', STATE)
    write_json(tmp_path / 'data' / 'trader_plan.json', PLAN)
    write_json(tmp_path / 'settings.json', SETTINGS)


# ---------------------------------------------------------------- contract / safety
def test_planner_has_no_network_or_session_code():
    """Reads local JSON and nothing else: no HTTP, no sign-in, no shells, no writes elsewhere."""
    with open(SRC, encoding='utf-8') as fh:
        src = fh.read().lower()
    for banned in ('urllib', 'requests.', 'socket', 'subprocess', 'wfm_session', 'signin',
                   'api.warframe.market'):
        assert banned not in src, 'hygiene.py must stay offline - found %r' % banned
    assert 'os.replace' in src, 'atomic write (tmp + os.replace) is house style'


def test_empty_state_writes_a_dry_run_plan(tmp_path, hyg, monkeypatch):
    """No live orders and no plan rows: still a valid, empty, dry-run document."""
    write_json(tmp_path / 'data' / 'trader_state.json', {'ts': NOW - 60, 'account': 'Acct',
                                                         'orders': {}})
    write_json(tmp_path / 'data' / 'trader_plan.json', {'generated': NOW, 'plan': []})
    write_json(tmp_path / 'settings.json', SETTINGS)

    code, data = run_cli(hyg, monkeypatch, tmp_path)

    assert code == 0
    doc = read_json(data / 'hygiene_plan.json')
    assert {'actions', 'apply_dry_run', 'generated', 'mode', 'rules', 'summary'} <= set(doc)
    assert doc['mode'] == 'dry-run'
    assert doc['actions'] == []
    assert doc['summary'] == {'hide': 0, 'show': 0, 'refresh': 0, 'total': 0}
    assert isinstance(doc['rules']['auto_hide_offline'], bool)
    assert doc['rules']['auto_hide_offline'] is False
    assert doc['rules']['stale_refresh_days'] == 7
    assert doc['generated_utc'].endswith('Z') and doc['order_first_seen'] == {}
    assert any('no own listings' in n for n in doc['notes'])
    assert 'hygiene_plan.json.tmp' not in os.listdir(data)


def test_apply_dry_run_note_explains_the_replay_contract(hyg):
    note = doc_of(hyg)['apply_dry_run']
    assert 'posting engine' in note          # what will consume the same array once it ships
    assert 'verbatim' in note and 'deduped' in note
    assert 'no session, no HTTP' in note     # and that nothing ran here


def test_plan_only_never_writes_state_or_plan(tmp_path, hyg, monkeypatch):
    """The planner is read-only apart from its own output file."""
    write_fixtures(tmp_path)
    data = tmp_path / 'data'
    before = {p: (data / p).read_bytes() for p in ('trader_state.json', 'trader_plan.json')}

    code, _ = run_cli(hyg, monkeypatch, tmp_path, ['--once', '--offline-window', '240'])

    assert code == 0
    after = {p: (data / p).read_bytes() for p in before}
    assert after == before
    assert sorted(os.listdir(data)) == ['hygiene_plan.json', 'trader_plan.json',
                                        'trader_state.json']


def test_action_rows_match_the_contract(hyg):
    doc = doc_of(hyg, offline_window=240)
    assert doc['actions'], 'offline window should plan hides for these fixtures'
    for a in doc['actions']:
        assert sorted(a) == ['action', 'item', 'lane', 'order_id', 'reason']
        assert a['action'] in ('hide', 'show', 'refresh')
        assert isinstance(a['reason'], str) and a['reason']
    assert doc['summary']['total'] == len(doc['actions'])
    assert doc['summary'] == {'hide': 3, 'show': 0, 'refresh': 0, 'total': 3}


def test_killswitch_blocks_a_run_and_writes_nothing(tmp_path, hyg, monkeypatch):
    write_fixtures(tmp_path)
    write_json(tmp_path / 'data' / 'kill_switch.json', {'active': True, 'note': 'test'})

    code, data = run_cli(hyg, monkeypatch, tmp_path)

    assert code == 2
    assert not (data / 'hygiene_plan.json').exists()


# ---------------------------------------------------------------- rules
@pytest.mark.parametrize('flt,expected', [
    ('kind=mod', ['o1']),
    ('kind:mod', ['o1']),                       # ':' separator
    ('section=relic', ['o2', 'plan:axi_s17_relic:intact']),
    ('lane=intact', ['o2', 'plan:axi_s17_relic:intact']),
    ('slug=neo_d3', ['o2']),
    ('relic', ['o2', 'plan:axi_s17_relic:intact']),   # bare term: kind + lane + slug
    ('KIND=MOD', ['o1']),                       # case-insensitive
])
def test_bulk_hide_filters(hyg, flt, expected):
    """stale_days=30 keeps the refresh rule out of the way so only the filter can fire."""
    doc = doc_of(hyg, hide=[flt], stale_days=30)
    assert sorted(a['order_id'] for a in doc['actions']) == sorted(expected)
    assert {a['action'] for a in doc['actions']} == {'hide'}
    assert doc['rules']['hide_filters'] == [flt]


def test_bulk_hide_repeated_flags_or_together_and_skip_hidden(hyg):
    or_doc = doc_of(hyg, hide=['kind=mod', 'kind=prime'], stale_days=30)
    assert sorted(a['order_id'] for a in or_doc['actions']) == ['o1']      # o3 is hidden already
    assert or_doc['summary'] == {'hide': 1, 'show': 0, 'refresh': 0, 'total': 1}


def test_bulk_show_only_targets_hidden_listings(hyg):
    doc = doc_of(hyg, show=['kind=prime'], stale_days=30)
    assert [(a['action'], a['order_id']) for a in doc['actions']] == [('show', 'o3')]
    assert doc['rules']['show_filters'] == ['kind=prime']
    # a show filter must never touch a listing that is already visible
    assert doc_of(hyg, show=['kind=mod'], stale_days=30)['actions'] == []


def test_auto_hide_offline_needs_a_window_longer_than_the_threshold(hyg):
    long_doc = doc_of(hyg, offline_window=240)
    assert long_doc['rules']['auto_hide_offline'] is True
    assert long_doc['rules']['offline_window_minutes'] == 240
    assert long_doc['rules']['offline_threshold_minutes'] == 60
    assert sorted(a['order_id'] for a in long_doc['actions']) == ['o1', 'o2',
                                                                  'plan:axi_s17_relic:intact']
    # ... the hidden listing stays out of it, and the pending row says what its action means
    assert 'o3' not in [a['order_id'] for a in long_doc['actions']]
    pend = [a for a in long_doc['actions'] if a['order_id'].startswith('plan:')][0]
    assert 'post hidden' in pend['reason']

    short_doc = doc_of(hyg, offline_window=30, stale_days=30)      # refresh parked at 30d
    assert short_doc['rules']['auto_hide_offline'] is False
    assert short_doc['actions'] == []

    at_doc = doc_of(hyg, offline_window=60, stale_days=30)
    assert at_doc['rules']['auto_hide_offline'] is False            # the threshold is strict
    assert at_doc['actions'] == []


def test_auto_hide_offline_from_settings(tmp_path, hyg, monkeypatch):
    """Config flag alone: minutes when present, else the detector gap as the offline estimate."""
    flagged = {'dry_run': True, 'hygiene': {'auto_hide_offline': True,
                                            'auto_hide_offline_minutes': 480,
                                            'auto_hide_offline_threshold_minutes': 60}}
    doc = doc_of(hyg, settings=flagged)
    assert (doc['rules']['auto_hide_offline'], doc['rules']['offline_window_minutes']) == (True, 480)
    assert doc['summary']['hide'] == 3

    gap_settings = {'dry_run': True, 'auto_hide_offline': True, 'auto_hide_offline_minutes': None}
    stale_state = dict(STATE, ts=NOW - 300 * 60)          # detector silent for 5h
    assert doc_of(hyg, state=stale_state, settings=gap_settings)['rules']['auto_hide_offline'] is True
    fresh_state = dict(STATE, ts=NOW - 5 * 60)
    assert doc_of(hyg, state=fresh_state, settings=gap_settings)['rules']['auto_hide_offline'] is False


def test_stale_orders_become_refresh_suggestions(hyg):
    doc = doc_of(hyg)                                          # filters and offline rule off
    assert [(a['action'], a['order_id']) for a in doc['actions']] == [('refresh', 'o2')]
    assert doc['summary'] == {'hide': 0, 'show': 0, 'refresh': 1, 'total': 1}
    assert doc['actions'][0]['lane'] == 'intact'                # lane enriched from the plan row
    assert doc['actions'][0]['reason'].startswith('listed 9d ago (> 7d)')
    # nothing is refreshed inside the window, or when it is hidden from buyers already
    assert doc_of(hyg, stale_days=30)['actions'] == []
    assert 'o3' not in [a['order_id'] for a in doc['actions']]


def test_first_seen_memory_ages_orders_without_a_stamp(hyg):
    """An order the snapshot does not date ages from the first run that saw it."""
    stamp_less = {'ts': NOW - 60, 'orders': {'o1': {k: v for k, v in STATE['orders']['o1'].items()
                                                    if k != 'created'}}}
    uni = hyg.build_universe(stamp_less, {}, {'o1': NOW - 8 * DAY}, NOW)
    assert uni['first_seen']['o1'] == NOW - 8 * DAY
    acts, _, _ = hyg.plan_actions(uni['entries'], hyg.resolve_offline(None, SETTINGS, None, NOW),
                                  [], [], 7, NOW)
    assert [a['order_id'] for a in acts] == ['o1']
    # no stamp anywhere: age stays unknown rather than being invented
    uni2 = hyg.build_universe(stamp_less, {}, {}, NOW)
    assert uni2['entries'][0]['ts'] is None
    assert hyg.plan_actions(uni2['entries'], hyg.resolve_offline(None, SETTINGS, None, NOW),
                            [], [], 7, NOW)[0] == []


def test_one_action_per_order_hide_beats_refresh(hyg):
    doc = doc_of(hyg, offline_window=240)                       # o2 is stale AND going offline
    o2 = [a for a in doc['actions'] if a['order_id'] == 'o2'][0]
    assert o2['action'] == 'hide'
    assert 'lower-precedence rule(s) skipped' in o2['reason']
    assert len([a for a in doc['actions'] if a['order_id'] == 'o2']) == 1
    assert any('more than one rule' in n for n in doc['notes'])


def test_buy_orders_are_not_hygiene_targets(hyg):
    assert 'o4' not in [a['order_id'] for a in doc_of(hyg, offline_window=240)['actions']]
    assert doc_of(hyg)['inputs']['trader_state.json']['buy_skipped'] == 1


# ---------------------------------------------------------------- resilience + CLI
def test_settings_write_race_falls_back_to_defaults(tmp_path, hyg, monkeypatch):
    """settings.json is owned by another engine: a half-written file must not stop a plan."""
    write_json(tmp_path / 'data' / 'trader_state.json', STATE)
    write_json(tmp_path / 'data' / 'trader_plan.json', PLAN)
    (tmp_path / 'settings.json').write_text('{"dry_run": tr', encoding='utf-8')   # mid-write

    code, data = run_cli(hyg, monkeypatch, tmp_path, ['--once', '--offline-window', '240'])

    assert code == 0
    doc = read_json(data / 'hygiene_plan.json')
    assert doc['rules']['auto_hide_offline'] is True            # the flag still planned the hides
    assert doc['inputs']['settings.json'] == {'read': False}
    assert any('settings.json unreadable' in n for n in doc['notes'])


def test_state_file_half_written_still_plans_from_the_plan(tmp_path, hyg, monkeypatch):
    """A torn trader_state.json costs the live-order detail, not the whole run."""
    (tmp_path / 'data').mkdir(exist_ok=True)
    write_json(tmp_path / 'data' / 'trader_plan.json',
               {'generated': NOW - 10 * DAY, 'plan': PLAN['plan']})
    (tmp_path / 'data' / 'trader_state.json').write_text('{"ts": 1790341292, "ord',
                                                         encoding='utf-8')
    write_json(tmp_path / 'settings.json', SETTINGS)

    code, data = run_cli(hyg, monkeypatch, tmp_path)

    assert code == 0
    doc = read_json(data / 'hygiene_plan.json')
    assert doc['inputs']['entries'] == {'live': 0, 'pending': 4}   # every plan row is pending
    assert doc['inputs']['trader_state.json'] == {'read': False, 'orders': 0, 'buy_skipped': 0,
                                                  'ts': None}
    # a stale plan ages its own never-listed rows, so they read as refresh suggestions
    assert [a['action'] for a in doc['actions']] == ['refresh'] * 4
    assert sorted(a['order_id'] for a in doc['actions']) == [
        'plan:axi_s17_relic:intact', 'plan:hildryn_prime_chassis_blueprint:-',
        'plan:neo_d3_relic:intact', 'plan:primed_continuity:rank 0']


def build_harness(tmp_path, settings=None, state=None):
    """A private copy of the script with its own scripts/trader + data (source never touched)."""
    root = tmp_path / 'harness'
    (root / 'scripts' / 'trader').mkdir(parents=True)
    (root / 'data').mkdir()
    shutil.copyfile(SRC, root / 'scripts' / 'trader' / 'hygiene.py')
    write_json(root / 'scripts' / 'trader' / 'settings.json', settings or SETTINGS)
    write_json(root / 'data' / 'trader_state.json', state or STATE)
    write_json(root / 'data' / 'trader_plan.json', PLAN)
    return root


def harness_run(root, argv):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    env.pop('WFM_HYGIENE_DATA', None)      # an ambient override must not redirect the harness
    return subprocess.run([sys.executable, str(root / 'scripts' / 'trader' / 'hygiene.py')] + argv,
                          cwd=str(root), env=env, capture_output=True, text=True, timeout=120)


def test_cli_run_writes_the_plan_file(tmp_path):
    """End to end: config-flagged auto-hide plus a bulk filter, offline, nothing else written."""
    root = build_harness(tmp_path, settings={'dry_run': True, 'hygiene': {
        'auto_hide_offline': True, 'auto_hide_offline_minutes': 480}})

    proc = harness_run(root, ['--once', '--hide', 'kind=mod'])

    assert proc.returncode == 0, proc.stderr[-2000:]
    doc = read_json(root / 'data' / 'hygiene_plan.json')
    assert doc['mode'] == 'dry-run'
    assert doc['rules']['auto_hide_offline'] is True
    assert doc['rules']['hide_filters'] == ['kind=mod']
    assert doc['rules']['show_filters'] == [] and doc['rules']['stale_refresh_days'] == 7
    assert doc['summary'] == {'hide': 3, 'show': 0, 'refresh': 0, 'total': 3}
    assert doc['account'] == 'TestAcct'
    assert 'hygiene plan | mode dry-run' in proc.stdout
    assert 'summary: 3 hide | 0 show | 0 refresh | 3 total' in proc.stdout
    assert sorted(os.listdir(root / 'data')) == ['hygiene_plan.json', 'trader_plan.json',
                                                 'trader_state.json']
    assert read_json(root / 'data' / 'trader_state.json') == STATE     # inputs untouched


def test_cli_selftest_is_offline_and_passes(tmp_path):
    root = build_harness(tmp_path)
    proc = harness_run(root, ['--selftest'])
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    assert 'selftest: PASS' in proc.stdout
    assert not (root / 'data' / 'hygiene_plan.json').exists()          # selftest writes nothing
