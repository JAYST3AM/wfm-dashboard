"""scripts/profiles.py: the multi-account profile manager (manifest, create, switch, safety).

Every test runs in tmp_path: WFM_DATA_DIR + WFM_PROFILES_ROOT are set before the module is
imported (conftest.load_script applies env pre-exec), so the repo's real data/ directory is
never read or written - the last test proves that by hashing the repo data dir before/after.
"""
import hashlib
import json
import os

import pytest

from conftest import REPO, load_script, read_json, write_json

PROFILES = 'profiles'
OWNED_A = [{'slug': 'primed_continuity', 'name': 'Primed Continuity', 'count': 2}]
OWNED_B = OWNED_A + [{'slug': 'archon_flow', 'name': 'Archon Flow', 'count': 1}]
SHARED_FILE = 'gamenews.json'
KILL_SWITCH = 'kill_switch.json'


def write_text(path, text):
    path = str(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)
    return path


def sha(path):
    try:
        with open(str(path), 'rb') as fh:
            return hashlib.sha1(fh.read()).hexdigest()
    except OSError:
        return None


@pytest.fixture(scope='module')
def manifest_names():
    """Manifest entry names, read straight from the real module (import only)."""
    return [e['name'] for e in load_script('profiles').MANIFEST]


def repo_guard_state(names):
    """State of the repo data/ files THIS tool could touch: the manifest names + profile root.

    Deliberately narrow: data/supervisor.log and friends churn while the dashboard's own
    background jobs run, so hashing the whole data dir would make this guard flaky.
    """
    d = os.path.join(REPO, 'data')
    state = {}
    for name in list(names) + [PROFILES]:
        full = os.path.join(d, name)
        if os.path.isdir(full):
            for base, _dirs, files in os.walk(full):
                for f in files:
                    rel = os.path.relpath(os.path.join(base, f), d)
                    state[rel] = sha(os.path.join(base, f))
        else:
            state[name] = sha(full)
    return state


@pytest.fixture
def live(tmp_path):
    """A tmp live data dir with some (not all) manifest files present."""
    d = tmp_path / 'data'
    (d / 'inventory_snapshots').mkdir(parents=True)
    write_json(d / 'owned.json', OWNED_A)
    write_json(d / 'trade_log.json', [{'kind': 'sale', 'total': 20, 'qty': 1}])
    write_json(d / 'trader_state.json', {'account': 'TESTER', 'plat': 500, 'trades_left': 12})
    write_json(d / 'lastData.dec.json', {'PremiumCredits': 500, 'PlayerLevel': 22})
    write_json(d / KILL_SWITCH, {'active': False, 'note': '', 'ts': 0})
    write_json(d / SHARED_FILE, {'items': [1]})             # shared: must never be copied
    write_json(d / 'inventory_snapshots' / 'owned_2026-01-01.json', [{'slug': 'x'}])
    return d


@pytest.fixture
def prof(live, monkeypatch):
    """profiles.py imported with the live data dir + profile root pointed at tmp_path."""
    return load_script('profiles', monkeypatch=monkeypatch,
                       env={'WFM_DATA_DIR': str(live),
                            'WFM_PROFILES_ROOT': str(live / PROFILES)})


@pytest.fixture
def run(prof, capsys):
    """(exit code, stdout+stderr) for one CLI invocation."""
    def _run(*argv):
        code = prof.main([str(a) for a in argv])
        return code, capsys.readouterr().out
    return _run


def alpha_dir(live):
    return live / PROFILES / 'alpha'


# --------------------------------------------------------------------------- manifest
def test_manifest_lists_account_files_with_reasons(prof):
    names = [e['name'] for e in prof.MANIFEST]
    assert len(names) == len(set(names))
    for entry in prof.MANIFEST:
        assert entry['kind'] in ('json', 'text', 'dir')
        assert entry['why'] and len(entry['why']) > 20, entry['name']
    # every file the task names as account data is in the manifest
    for required in ('owned.json', 'prices.json', 'stats.json', 'trade_log.json', 'plat_history.json',
                     'report.json', 'trader_plan.json', 'trader_state.json', 'inuse.json',
                     'trader_limits.json', 'wishlist_config.json', 'watchlist_config.json',
                     'wishlist.json', 'watchlist.json', 'trader_undercuts.json'):
        assert required in names, required


def test_manifest_excludes_globals_and_the_kill_switch(prof):
    names = [e['name'] for e in prof.MANIFEST]
    for excluded in (KILL_SWITCH, 'secrets.json', prof.PROFILE_META, 'wfm_items_v2.json',
                     'recipes_cache.json', 'gamenews.json', 'trends_cache.json'):
        assert excluded not in names, excluded
    shared = [n for n, _why in prof.SHARED]
    assert KILL_SWITCH in shared and 'secrets.json' in shared


def test_manifest_json_defaults_are_serialisable_and_library_safe(prof):
    for entry in prof.MANIFEST:
        if entry['kind'] == 'json':
            assert json.loads(json.dumps(entry['default'])) == entry['default'], entry['name']
            assert isinstance(entry['default'], (dict, list)) or entry['default'] == '', entry['name']


# --------------------------------------------------------------------------- names
@pytest.mark.parametrize('bad', ['..', '.', '.hidden', 'a/b', 'a\\b', 'two words', '', 'x' * 65, 'current'])
def test_bad_profile_names_are_refused(prof, run, bad):
    code, out = run('--create', bad)
    assert code == 2
    assert 'refused' in out


def test_good_profile_name_helper(prof):
    assert prof.check_name('SampleTennoIX') == (True, '')
    assert prof.check_name('alt-2.0') == (True, '')
    assert prof.check_name('nope/../x')[0] is False


# --------------------------------------------------------------------------- create
def test_create_copies_live_state_and_completes_the_manifest(prof, run, live):
    code, out = run('--create', 'alpha')
    assert code == 0
    pdir = alpha_dir(live)
    assert pdir.is_dir()
    assert prof.manifest_gaps(str(pdir)) == []                  # completeness invariant
    assert read_json(pdir / 'owned.json') == OWNED_A            # copied from live
    assert read_json(pdir / 'stats.json') == {}                 # missing live file -> default
    assert read_json(pdir / 'wishlist_config.json') == {'entries': []}
    assert (pdir / 'report.md').is_file() and (pdir / 'report.md').read_text() == ''
    assert read_json(pdir / 'inventory_snapshots' / 'owned_2026-01-01.json') == [{'slug': 'x'}]
    assert read_json(pdir / prof.PROFILE_META)['name'] == 'alpha'
    assert 'copied from live' in out and 'live data/ untouched' in out


def test_create_never_copies_shared_files_or_the_kill_switch(prof, run, live):
    run('--create', 'alpha')
    pdir = alpha_dir(live)
    assert not (pdir / KILL_SWITCH).exists()
    assert not (pdir / SHARED_FILE).exists()
    assert not (pdir / 'backups').exists()


def test_create_refuses_an_existing_name_and_leaves_it_alone(prof, run, live):
    run('--create', 'alpha')
    pdir = alpha_dir(live)
    before = prof.scan_tree(str(pdir))
    code, out = run('--create', 'alpha')
    assert code == 2
    assert 'already exists' in out and '--switch' in out
    assert prof.scan_tree(str(pdir)) == before


def test_create_does_not_move_the_marker(prof, run, live):
    run('--create', 'alpha')
    assert not (live / PROFILES / 'current.json').exists()
    code, out = run('--current')
    assert code == 0 and 'unmanaged' in out


# --------------------------------------------------------------------------- list/current
def test_list_and_current_without_any_profile(prof, run, live):
    code, out = run('--list')
    assert code == 0 and 'no profiles yet' in out
    assert 'live data' in out
    code, out = run('--current')
    assert code == 0 and 'unmanaged' in out


def test_list_marks_the_current_profile(prof, run, live):
    run('--create', 'alpha')
    run('--switch', 'alpha', '--apply')
    code, out = run('--list')
    assert code == 0
    assert 'alpha' in out and '* current' in out
    assert 'current      : alpha' in out
    code, out = run('--current')
    assert code == 0
    assert 'current profile  alpha' in out
    assert 'switched' in out and 'live data' in out


def test_corrupt_marker_is_tolerated(prof, run, live):
    run('--create', 'alpha')
    run('--switch', 'alpha', '--apply')
    write_text(live / PROFILES / 'current.json', '{ not json')
    code, out = run('--current')
    assert code == 0 and 'warning' in out.lower() and 'unmanaged' in out
    code, out = run('--list')
    assert code == 0


# --------------------------------------------------------------------------- dry run
def test_switch_dry_run_prints_the_plan_and_writes_nothing(prof, run, live):
    run('--create', 'alpha')
    run('--create', 'beta')
    write_json(live / 'owned.json', OWNED_B)                    # live drifts after the profiles
    live_before = prof.scan_tree(str(live))
    code, out = run('--switch', 'alpha')
    assert code == 0
    assert 'DRY RUN' in out and 'SWITCH PLAN' in out
    assert 'owned.json' in out and 'replace' in out             # the drifted file is listed
    assert 'identical' in out and 'nothing is ever deleted' in out
    assert '--apply' in out and 'current.json' in out
    assert prof.scan_tree(str(live)) == live_before              # nothing written
    assert not (live / PROFILES / 'current.json').exists()


def test_switch_dry_run_lists_files_live_is_missing_as_restore(prof, run, live):
    run('--create', 'alpha')
    code, out = run('--switch', 'alpha')
    assert code == 0
    # alpha holds defaults for files the live dir never had - the plan shows them coming back
    assert '0 replaced' in out and 'stats.json' in out and 'restore' in out


def test_switch_missing_profile_is_an_error(prof, run):
    code, out = run('--switch', 'ghost')
    assert code == 1 and 'no profile' in out


# --------------------------------------------------------------------------- apply
def test_switch_apply_round_trip(prof, run, live):
    run('--create', 'alpha')
    run('--create', 'beta')
    beta_before = prof.scan_tree(str(live / PROFILES / 'beta'))

    code, out = run('--switch', 'alpha', '--apply')              # live (owned_a) -> alpha
    assert code == 0
    assert read_json(live / PROFILES / 'current.json')['current'] == 'alpha'
    assert read_json(live / PROFILES / 'current.json')['previous'] is None
    assert 'restart the server to apply' in out
    assert 'safety backup' in out and 'scripts/backup.py' in out
    assert len(list((live / 'backups').glob('*.zip'))) == 1       # pre-switch zip
    assert prof.manifest_gaps(str(live)) == []
    assert read_json(live / SHARED_FILE) == {'items': [1]}       # shared file untouched
    assert prof.scan_tree(str(live / PROFILES / 'beta')) == beta_before   # other profile untouched

    # drift the live state WHILE alpha is current, then switch away: alpha must keep the drift
    write_json(live / 'owned.json', OWNED_B)
    write_json(live / 'stats.json', {'x': {'vol48': 5}})
    code, _ = run('--switch', 'beta', '--apply')
    assert code == 0
    assert read_json(live / 'owned.json') == OWNED_A             # beta's own state restored
    assert read_json(live / 'stats.json') == {}
    assert read_json(live / PROFILES / 'alpha' / 'owned.json') == OWNED_B   # drift preserved
    assert read_json(live / PROFILES / 'current.json')['current'] == 'beta'
    assert read_json(live / PROFILES / 'current.json')['previous'] == 'alpha'

    # ... and switching back restores exactly that preserved state
    code, _ = run('--switch', 'alpha', '--apply')
    assert code == 0
    assert read_json(live / 'owned.json') == OWNED_B
    assert not (live / PROFILES / 'alpha' / KILL_SWITCH).exists()


def test_switch_apply_never_deletes_a_live_file_the_profile_lacks(prof, run, live):
    run('--create', 'alpha')
    os.remove(str(alpha_dir(live) / 'sets.json'))                # target profile incomplete
    write_json(live / 'sets.json', {'live': True})
    code, out = run('--switch', 'alpha', '--apply')
    assert code == 0
    assert read_json(live / 'sets.json') == {'live': True}       # copy-only: still there
    assert 'left in place' in out
    assert read_json(live / PROFILES / 'current.json')['current'] == 'alpha'


def test_switch_to_the_current_profile_is_a_noop(prof, run, live):
    run('--create', 'alpha')
    run('--switch', 'alpha', '--apply')
    before = prof.scan_tree(str(live))
    code, out = run('--switch', 'alpha')
    assert code == 1 and 'already current' in out
    assert prof.scan_tree(str(live)) == before


def test_switch_apply_works_with_an_unmanaged_live_state(prof, run, live):
    run('--create', 'alpha')
    write_json(live / 'owned.json', OWNED_B)
    code, out = run('--switch', 'alpha', '--apply')
    assert code == 0
    assert 'no outgoing profile' in out                          # nothing was saved anywhere else
    assert 'backup zip above is the only copy' in out
    assert read_json(live / 'owned.json') == OWNED_A


def test_interrupted_switch_reports_the_safety_zip(prof, run, live, monkeypatch):
    run('--create', 'alpha')
    run('--create', 'beta')
    run('--switch', 'alpha', '--apply')
    write_json(live / 'owned.json', OWNED_B)

    def boom(*_args, **_kwargs):
        raise OSError('disk full')

    monkeypatch.setattr(prof, 'copy_entry', boom)
    code, out = run('--switch', 'beta', '--apply')
    assert code == 1
    assert 'switch interrupted' in out and 'safety zip' in out
    assert read_json(live / PROFILES / 'current.json')['current'] == 'alpha'   # marker not moved
    assert len(list((live / 'backups').glob('*.zip'))) >= 1                    # safety zip kept


# --------------------------------------------------------------------------- safety
def test_switch_apply_refuses_while_the_kill_switch_is_engaged(prof, run, live):
    run('--create', 'alpha')
    run('--create', 'beta')
    run('--switch', 'alpha', '--apply')
    write_json(live / 'owned.json', OWNED_B)
    write_json(live / KILL_SWITCH, {'active': True, 'note': 'hold', 'ts': 0})
    marker_before = sha(live / PROFILES / 'current.json')
    live_before = prof.scan_tree(str(live))
    code, out = run('--switch', 'beta', '--apply')
    assert code == 2
    assert 'kill switch engaged' in out and 'hold' in out
    assert sha(live / PROFILES / 'current.json') == marker_before
    assert prof.scan_tree(str(live)) == live_before
    # the dry run is still allowed, and warns that --apply would refuse
    code, out = run('--switch', 'beta')
    assert code == 0
    assert '--apply would refuse' in out


def test_apply_without_switch_is_refused(prof, run):
    code, out = run('--apply')
    assert code == 2 and '--switch' in out


def test_no_action_prints_help(prof, run):
    code, out = run()
    assert code == 2
    assert 'usage: profiles.py' in out and '--switch' in out


def test_manifest_command_lists_both_scopes(prof, run):
    code, out = run('--manifest')
    assert code == 0
    assert 'PROFILE-SCOPED FILES' in out and 'owned.json  [json]' in out
    assert 'SHARED FILES' in out and '%s  [shared]' % KILL_SWITCH in out


# --------------------------------------------------------------------------- selftest + repo guard
def test_selftest_passes(prof):
    assert prof.selftest() == 0


def test_selftest_and_cli_never_touch_the_repo_data_dir(prof, run, live, tmp_path, manifest_names):
    assert str(tmp_path) in prof.data_dir()
    assert str(tmp_path) in prof.profiles_root()
    repo_profiles = os.path.join(REPO, 'data', PROFILES)
    existed = os.path.isdir(repo_profiles)
    before = repo_guard_state(manifest_names)
    run('--list')
    run('--manifest')
    run('--create', 'alpha')
    run('--switch', 'alpha')
    run('--switch', 'alpha', '--apply')
    prof.selftest()
    assert repo_guard_state(manifest_names) == before
    if not existed:
        assert not os.path.exists(repo_profiles)


# --------------------------------------------------------------------------- --json (dashboard card)
def test_json_list_reports_marker_state_and_profiles(prof, run):
    code, out = run('--list', '--json')
    assert code == 0
    doc = json.loads(out)
    assert doc['managed'] is False and doc['current'] is None
    assert doc['profiles'] == []
    assert doc['live'].endswith('manifest files present')
    assert doc['marker'].endswith('current.json')

    assert run('--create', 'alpha')[0] == 0
    assert run('--switch', 'alpha', '--apply')[0] == 0
    code, out = run('--list', '--json')
    doc = json.loads(out)
    assert doc['managed'] is True and doc['current'] == 'alpha'
    assert [p['name'] for p in doc['profiles']] == ['alpha']
    assert doc['profiles'][0]['current'] is True
    assert doc['profiles'][0]['files'] >= 1 and doc['profiles'][0]['bytes'] > 0
    assert doc['switched']


def test_json_current_payload(prof, run, live):
    code, out = run('--current', '--json')
    assert code == 0
    doc = json.loads(out)
    assert doc['managed'] is False and doc['current'] is None
    assert run('--create', 'alpha')[0] == 0
    assert run('--switch', 'alpha', '--apply')[0] == 0
    code, out = run('--current', '--json')
    doc = json.loads(out)
    assert doc['current'] == 'alpha' and doc['managed'] is True
    assert doc['profile_dir_exists'] is True
    assert 'profiles' in doc['profile_dir']


def test_json_flag_is_gated_to_list_and_current(prof, run):
    code, out = run('--json')
    assert code == 2 and '--list or --current' in out
    assert run('--create', 'alpha', '--json')[0] == 2


def test_json_flag_never_leaks_into_the_text_output(prof, run):
    code, out = run('--list')
    assert code == 0 and out.lstrip().startswith('profiles root:')
    code, out = run('--current')
    assert code == 0 and 'current profile' in out


# --------------------------------------------------------------------------- dashboard surface
def test_settings_accounts_card_and_server_routes_exist():
    """The switcher's dashboard surface: /api/profiles + the Settings > Accounts card."""
    srv = open(os.path.join(REPO, 'server.py'), encoding='utf-8').read()
    assert "if p == '/api/profiles': return self._send(200, profiles_payload())" in srv
    assert "action not in ('create', 'switch')" in srv
    assert "'--list', '--json'" in srv
    assert "'--create' if action == 'create' else '--switch'" in srv

    html = open(os.path.join(REPO, 'static', 'settings.html'), encoding='utf-8').read()
    for need in ('id="h-accounts"', 'id="acctName"', 'id="acctCreate"',
                 'id="list-accounts"', 'id="acctPlan"', 'id="status-accounts"'):
        assert need in html, need

    js = open(os.path.join(REPO, 'static', 'settings.js'), encoding='utf-8').read()
    for need in ('loadAccounts', 'switchProfile', 'createProfile',
                 'Apply switch to ', "'/api/profiles'", 'loadAccounts();'):
        assert need in js, need


def test_server_profiles_payload_shells_out_and_parses(server_mod, monkeypatch, tmp_path):
    """profiles_payload() runs the real engine: unmanaged + empty profile list on a clean dir."""
    data = tmp_path / 'data'
    data.mkdir(exist_ok=True)
    monkeypatch.setattr(server_mod, 'ROOT', REPO)   # the fixture points ROOT at tmp; the engine lives in the repo
    monkeypatch.setenv('WFM_DATA_DIR', str(data))
    monkeypatch.setenv('WFM_PROFILES_ROOT', str(data / 'profiles'))
    doc = server_mod.profiles_payload()
    assert doc['ok'] is True
    assert doc['managed'] is False and doc['current'] is None
    assert doc['profiles'] == []
