"""scripts/trader/auto.py: the supervised dry-run cycle, its gates and the report contract.

scripts/trader/ is private (gitignored), so the whole module skips cleanly on a public checkout.

Nothing here reaches the network: every engine call is replaced by a fake (or, for the
missing-file case, by the real _spawn against a root with no scripts/ folder), settings /
limits / report files all live in tmp_path, and the module's own source is scanned to prove it
carries no market write path. The one CLI run is --selftest, which is offline by construction.
"""
import os
import subprocess
import sys

import pytest

from conftest import SCRIPTS, load_script, read_json, write_json

AUTO_PATH = os.path.join(SCRIPTS, 'trader', 'auto.py')
pytestmark = pytest.mark.skipif(not os.path.exists(AUTO_PATH),
                                reason='scripts/trader/ is private (not in the public tree)')

STEP_NAMES = ('killswitch', 'settings', 'limits', 'plan', 'detector', 'watcher', 'runqueue', 'notify')
ENGINE_SEQUENCE = ['plan', 'detector', 'watcher', 'runqueue']
SESSION_MARKER = 'sign' + 'in failed'            # split so auto.py's own scan stays honest


@pytest.fixture
def auto(monkeypatch):
    """Fresh scripts/trader/auto.py module object (fresh module keeps patched globals local)."""
    return load_script('trader/auto', monkeypatch=monkeypatch)


class Fake:
    """Stands in for every engine hook: records calls, writes the fake engine outputs.

    Knobs mirror the ones the selftest uses - kill / kill_after (switch state), limits (the
    data/trader_limits.json body), limits_ok (False = the refresh fails), live_listings + state
    (what the plan/state files say), results (per-engine spawn overrides).
    """

    def __init__(self, root, results=None, kill=False, kill_after=0, limits=None, limits_ok=True,
                 live_listings=0, state=None, sleep_raises=False, notify_result=None):
        self.root = root
        self.results = results or {}
        self.kill = kill
        self.kill_after = kill_after
        self.cycles = 0
        self.calls = []
        self.sleeps = []
        self.notify_calls = []
        self.sleep_raises = sleep_raises
        self.notify_result = notify_result
        self.live_listings = live_listings
        self.state = state
        self.limits = limits if limits is not None else {
            'trades_left': 7, 'trade_cap': 22, 'plat': 100, 'status': 'OK',
            'seconds_until_reset': 600, 'reset_melbourne': '2026-09-26T10:00:00+10:00'}
        self.limits_ok = limits_ok

    def install(self, mod, monkeypatch):
        monkeypatch.setattr(mod, '_killswitch_blocked', self.killswitch_blocked)
        monkeypatch.setattr(mod, '_killswitch_state', self.killswitch_state)
        monkeypatch.setattr(mod, '_refresh_limits', self.refresh_limits)
        monkeypatch.setattr(mod, '_spawn', self.spawn)
        monkeypatch.setattr(mod, '_notify', self.notify)
        monkeypatch.setattr(mod, '_sleep', self.sleep)
        return self

    # hooks ------------------------------------------------------------------
    def _armed(self):
        return bool(self.kill or (self.kill_after and self.cycles > self.kill_after))

    def killswitch_blocked(self):
        self.cycles += 1
        return self._armed()

    def killswitch_state(self):
        armed = self._armed()
        return {'active': armed, 'note': 'test arm' if armed else '', 'source': 'fake',
                'error': None}

    def refresh_limits(self, root=None):
        if not self.limits_ok:
            return False, 'limits refresh failed (fake) - reading the last file', None
        write_json(os.path.join(self.root, 'data', 'trader_limits.json'), self.limits)
        return True, 'fake limits refreshed', dict(self.limits)

    def spawn(self, name, root=None):
        self.calls.append(name)
        r = dict(self.results.get(name) or {'rc': 0, 'out': '', 'err': '', 'error': None})
        if name == 'plan' and not r.get('error') and r.get('rc') == 0:
            write_json(os.path.join(self.root, 'data', 'trader_plan.json'),
                       {'plan': [{'slug': 'x', 'name': 'X', 'qty': 1, 'price': 5}],
                        'live_orders': self.live_listings})
            if self.state is not None:
                write_json(os.path.join(self.root, 'data', 'trader_state.json'), self.state)
        if r.get('rc') == 0 and not r.get('out'):
            r['out'] = {'plan': 'plan written -> data/trader_plan.json\\nplan: 1 listings',
                        'runqueue': 'orderbooks fetched: 1 | queue: 0 rows',
                        'detector': 'orders 0 | events: 0',
                        'watcher': 'summary: 0 ok | 0 reprice'}.get(name, '')
        return dict(r, seconds=0.0, argv=['python', name])

    def notify(self, summary, report):
        self.notify_calls.append(summary)
        return self.notify_result or (True, 'fake notify ok')

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        if self.sleep_raises:
            raise KeyboardInterrupt()


def make_root(tmp_path, name='root', dry_run=True, poll_seconds=90, settings=True):
    """tmp_path root shaped like the repo: data/ plus scripts/trader/settings.json."""
    root = tmp_path / name
    (root / 'data').mkdir(parents=True, exist_ok=True)
    if settings:
        write_json(root / 'scripts' / 'trader' / 'settings.json',
                   {'dry_run': dry_run, 'poll_seconds': poll_seconds,
                    'max_new_listings_per_day': 20, 'undercut_platinum': 1})
    return str(root)


def step_of(report, name):
    return next(s for s in report['steps'] if s['name'] == name)


def log_lines(root):
    with open(os.path.join(root, 'data', 'auto.log'), encoding='utf-8') as fh:
        return [ln for ln in fh.read().splitlines() if ln.strip()]


# --------------------------------------------------------------- offline, no write path

def test_selftest_runs_offline_and_passes(tmp_path):
    proc = subprocess.run([sys.executable, AUTO_PATH, '--selftest'],
                          capture_output=True, text=True, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.startswith('selftest: PASS'), proc.stdout
    assert 'FAIL' not in proc.stdout
    assert not (tmp_path / 'data').exists()          # the selftest only writes under its own tmp


def test_script_has_no_market_write_path(auto):
    with open(AUTO_PATH, encoding='utf-8') as fh:
        src = fh.read()
    for token in ("'POST'", "'PATCH'", "'DELETE'", 'signin', 'create_order', 'patch_order',
                  'delete_order', 'close_order', 'secrets.json', 'urlopen'):
        assert token not in src, f'auto.py must never post or hold a session: found {token!r}'
    assert not hasattr(auto, 'signin')               # no session object exists at all


# --------------------------------------------------------------- the happy cycle

def test_happy_cycle_runs_the_server_engine_sequence(auto, monkeypatch, tmp_path):
    root = make_root(tmp_path)
    fake = Fake(root, live_listings=3).install(auto, monkeypatch)

    report, code = auto.cycle(root=root)

    assert code == 0
    assert [s['name'] for s in report['steps']] == list(STEP_NAMES)
    assert [s for s in report['steps'] if not s['ok']] == []
    assert fake.calls == ENGINE_SEQUENCE              # plan -> detector -> watcher -> runqueue
    assert report['mode'] == 'dry_run'
    assert report['stopped'] == ''
    assert report['next_interval_s'] == 90
    assert report['ok'] is True
    assert step_of(report, 'settings')['summary'] == 'dry_run=true (locked)'
    assert 'trades_left 7' in step_of(report, 'limits')['summary']


def test_report_contract_and_log_line(auto, monkeypatch, tmp_path):
    root = make_root(tmp_path)
    Fake(root, live_listings=0).install(auto, monkeypatch)

    report, _code = auto.cycle(root=root)

    for key in ('ts', 'mode', 'steps', 'next_interval_s'):
        assert key in report, f'missing report key {key}'
    assert isinstance(report['ts'], int) and report['ts'] > 1_600_000_000
    assert report['mode'] == 'dry_run'
    assert isinstance(report['next_interval_s'], int) and report['next_interval_s'] >= 60
    for row in report['steps']:
        assert sorted(row) == ['name', 'ok', 'summary']
        assert isinstance(row['name'], str) and isinstance(row['ok'], bool)
        assert isinstance(row['summary'], str) and row['summary']

    on_disk = read_json(os.path.join(root, 'data', 'auto_report.json'))
    assert on_disk == report                                          # JSON round-trip
    lines = log_lines(root)
    assert len(lines) == 1
    assert lines[0].startswith(report['ts_iso'] + ' | dry_run')
    assert 'stopped=none' in lines[0] and 'next 90s' in lines[0]
    n = len(report['steps'])                                          # notify included
    assert f'steps {n}/{n} ok' in lines[0]                            # the log counts the same set


def test_one_cycle_appends_exactly_one_log_line(auto, monkeypatch, tmp_path):
    root = make_root(tmp_path)
    Fake(root, live_listings=0).install(auto, monkeypatch)
    auto.cycle(root=root)
    auto.cycle(root=root)
    assert len(log_lines(root)) == 2


# --------------------------------------------------------------- gates

def test_armed_kill_switch_refuses_exit_2_and_calls_no_engine(auto, monkeypatch, tmp_path):
    root = make_root(tmp_path)
    fake = Fake(root, kill=True).install(auto, monkeypatch)

    report, code = auto.cycle(root=root)

    assert code == 2
    assert fake.calls == []                                           # not one engine call
    assert step_of(report, 'killswitch')['ok'] is False
    assert step_of(report, 'killswitch')['summary'] == 'ARMED - refusing the cycle (note: test arm)'
    assert report['stopped'] == 'kill switch armed'
    assert [step_of(report, n)['summary'] for n in ENGINE_SEQUENCE] == \
        ['skipped: kill switch armed'] * 4
    assert report['next_interval_s'] == 300                           # quick re-check window
    assert os.path.exists(os.path.join(root, 'data', 'auto_report.json'))   # report still written
    assert len(log_lines(root)) == 1
    assert len(fake.notify_calls) == 1                                # the hook still hears about it


def test_trades_left_zero_stops_before_listing_work(auto, monkeypatch, tmp_path):
    root = make_root(tmp_path)
    fake = Fake(root, limits={'trades_left': 0, 'trade_cap': 22, 'plat': 12, 'status': 'OK',
                              'seconds_until_reset': 99999}).install(auto, monkeypatch)

    report, code = auto.cycle(root=root)

    assert code == 0                                                  # a limit stop is not an error
    assert fake.calls == []                                           # no listing work at all
    assert step_of(report, 'limits')['ok'] is False
    assert step_of(report, 'limits')['summary'].startswith('trade limit:')
    assert report['stopped'] == 'trade limit'
    assert report['next_interval_s'] == 7200                          # backoff capped at 2h
    assert os.path.exists(os.path.join(root, 'data', 'auto_report.json'))
    assert len(log_lines(root)) == 1


def test_trades_left_zero_short_reset_window_is_honoured(auto, monkeypatch, tmp_path):
    root = make_root(tmp_path)
    Fake(root, limits={'trades_left': 0, 'trade_cap': 22, 'plat': 12, 'status': 'OK',
                       'seconds_until_reset': 120}).install(auto, monkeypatch)
    report, _code = auto.cycle(root=root)
    assert report['next_interval_s'] == 120


def test_unknown_trades_left_stops_before_listing_work(auto, monkeypatch, tmp_path):
    root = make_root(tmp_path)
    fake = Fake(root, limits={'trades_left': None, 'trade_cap': None, 'plat': None,
                              'status': 'DEGRADED'}).install(auto, monkeypatch)

    report, code = auto.cycle(root=root)

    assert (code, fake.calls, report['stopped']) == (0, [], 'trade limit')
    assert 'unknown' in step_of(report, 'limits')['summary']
    assert report['next_interval_s'] == 90                            # retry at the base cadence


def test_non_dry_run_settings_refuse_every_engine(auto, monkeypatch, tmp_path):
    root = make_root(tmp_path, dry_run=False)
    fake = Fake(root).install(auto, monkeypatch)

    report, code = auto.cycle(root=root)

    assert code == 2
    assert fake.calls == []
    assert step_of(report, 'settings')['ok'] is False
    assert 'dry-run only' in step_of(report, 'settings')['summary']
    assert report['stopped'] == 'dry_run lock'
    assert report['mode'] == 'dry_run'                                # still a dry-run cycle
    assert os.path.exists(os.path.join(root, 'data', 'auto_report.json'))


def test_missing_settings_file_refuses(auto, monkeypatch, tmp_path):
    root = make_root(tmp_path, settings=False)
    fake = Fake(root).install(auto, monkeypatch)
    report, code = auto.cycle(root=root)
    assert code == 2 and fake.calls == [] and report['stopped'] == 'dry_run lock'


# --------------------------------------------------------------- live-listing gate

def test_detector_and_watcher_skip_without_live_listings(auto, monkeypatch, tmp_path):
    root = make_root(tmp_path)
    fake = Fake(root, live_listings=0).install(auto, monkeypatch)

    report, _code = auto.cycle(root=root)

    assert fake.calls == ['plan', 'runqueue']
    assert step_of(report, 'detector')['summary'] == 'skipped: no live listings (0 live sell orders)'
    assert step_of(report, 'watcher')['summary'] == 'skipped: no live listings (0 live sell orders)'
    assert step_of(report, 'detector')['ok'] is True and step_of(report, 'watcher')['ok'] is True


def test_live_sell_order_in_state_runs_detector_and_watcher(auto, monkeypatch, tmp_path):
    root = make_root(tmp_path)
    fake = Fake(root, live_listings=0,
                state={'account': 'A', 'orders': {'o1': {'type': 'sell', 'visible': True},
                                                  'o2': {'type': 'buy', 'visible': True}}}).install(auto, monkeypatch)
    _report, _code = auto.cycle(root=root)
    assert fake.calls == ENGINE_SEQUENCE


def test_plan_live_orders_run_detector_and_watcher(auto, monkeypatch, tmp_path):
    root = make_root(tmp_path)
    fake = Fake(root, live_listings=2).install(auto, monkeypatch)
    _report, _code = auto.cycle(root=root)
    assert fake.calls == ENGINE_SEQUENCE


# --------------------------------------------------------------- engine trouble

def test_engine_failure_is_logged_and_not_fatal(auto, monkeypatch, tmp_path):
    root = make_root(tmp_path)
    fake = Fake(root, results={'plan': {'rc': 1, 'out': '', 'err': 'no data/report.json',
                                        'error': None}}).install(auto, monkeypatch)

    report, code = auto.cycle(root=root)

    assert code == 0                                                  # the cycle still completed
    assert step_of(report, 'plan')['ok'] is False
    assert report['ok'] is False
    assert 'runqueue' in fake.calls                                   # later engines still ran
    line = log_lines(root)[0]
    assert 'plan=FAIL' in line and 'first problem:' in line


def test_engine_error_strings_are_reported_verbatim(auto, monkeypatch, tmp_path):
    root = make_root(tmp_path)
    Fake(root, results={'runqueue': {'rc': None, 'out': '', 'err': '',
                                     'error': 'timeout after 240s'}}).install(auto, monkeypatch)
    report, _code = auto.cycle(root=root)
    assert step_of(report, 'runqueue')['ok'] is False
    assert step_of(report, 'runqueue')['summary'] == 'timeout after 240s'


def test_soft_session_failure_marks_the_step_degraded(auto, monkeypatch, tmp_path):
    root = make_root(tmp_path)
    Fake(root, live_listings=1,
         results={'watcher': {'rc': 0, 'out': SESSION_MARKER + ': 401\n', 'err': '',
                              'error': None}}).install(auto, monkeypatch)
    report, _code = auto.cycle(root=root)
    assert step_of(report, 'watcher')['ok'] is False
    assert 'degraded' in step_of(report, 'watcher')['summary']


def test_limits_refresh_failure_falls_back_to_the_last_file(auto, monkeypatch, tmp_path):
    root = make_root(tmp_path)
    write_json(os.path.join(root, 'data', 'trader_limits.json'),
               {'trades_left': 5, 'trade_cap': 22, 'plat': 3, 'status': 'OK'})
    fake = Fake(root, limits_ok=False, live_listings=0).install(auto, monkeypatch)

    report, _code = auto.cycle(root=root)

    assert fake.calls == ['plan', 'runqueue']                         # the stale gate still held
    assert 'trades_left 5' in step_of(report, 'limits')['summary']
    assert 'refresh failed' in step_of(report, 'limits')['summary']


def test_missing_engine_file_degrades_to_a_logged_skip(auto, tmp_path):
    """The real _spawn (no fake): a root without scripts/ must return a skip, never raise."""
    bare = tmp_path / 'bare'
    bare.mkdir()
    for name, argv in (('plan', ['lister.py']), ('detector', ['detector.py', '--once']),
                       ('watcher', ['watcher.py', '--once']), ('runqueue', ['runqueue.py'])):
        r = auto._spawn(name, str(bare))
        assert r['rc'] is None and r['error'].startswith('skipped:')
        assert [os.path.basename(x) for x in r['argv'][1:]] == argv    # server.py's invocation
        assert r['argv'][0] == sys.executable
    assert auto._spawn('nope', str(bare))['error'] == "unknown engine 'nope'"


def test_cycle_degrades_when_the_engines_are_missing(auto, monkeypatch, tmp_path):
    """A root with no scripts/trader/*.py: real _spawn -> every engine step is a logged skip."""
    root = make_root(tmp_path, 'bare')                 # data/ + settings.json, no engine files
    write_json(os.path.join(root, 'data', 'trader_limits.json'),
               {'trades_left': 9, 'trade_cap': 22, 'plat': 4, 'status': 'OK'})
    monkeypatch.setattr(auto, '_killswitch_blocked', lambda: False)
    monkeypatch.setattr(auto, '_killswitch_state',
                        lambda: {'active': False, 'note': '', 'error': None})
    monkeypatch.setattr(auto, '_refresh_limits', lambda root=None: (True, 'fake limits', {}))
    monkeypatch.setattr(auto, '_notify', lambda summary, report: (True, 'fake notify'))

    report, code = auto.cycle(root=root)

    assert code == 0                                   # a missing sibling never crashes the cycle
    assert report['stopped'] == ''
    assert step_of(report, 'limits')['ok'] is True
    assert step_of(report, 'plan')['summary'] == 'skipped: lister.py not found'
    assert step_of(report, 'runqueue')['summary'] == 'skipped: runqueue.py not found'
    assert step_of(report, 'plan')['ok'] is False


# --------------------------------------------------------------- intervals

def test_base_interval_floor_and_config(auto, tmp_path):
    root = make_root(tmp_path, poll_seconds=90)
    assert auto.base_interval(5, root) == 60
    assert auto.base_interval(300, root) == 300
    assert auto.base_interval(None, root) == 90
    assert auto.base_interval(None, make_root(tmp_path, 'p45', poll_seconds=45)) == 60
    assert auto.base_interval(None, make_root(tmp_path, 'p180', poll_seconds=180)) == 180
    assert auto.base_interval(None, make_root(tmp_path, 'noset', settings=False)) == 90
    assert auto.base_interval('nonsense', root) == 90
    assert auto.MIN_INTERVAL == 60


def test_next_interval_rules(auto):
    assert auto._next_interval(90, '', 22, {}) == 90
    assert auto._next_interval(90, 'kill switch armed', 5, {}) == 300
    assert auto._next_interval(600, 'kill switch armed', 5, {}) == 600
    assert auto._next_interval(90, 'trade limit', 0, {'seconds_until_reset': 99999}) == 7200
    assert auto._next_interval(90, 'trade limit', 0, {'seconds_until_reset': 120}) == 120
    assert auto._next_interval(90, 'trade limit', None, {}) == 90
    assert auto._next_interval(90, 'dry_run lock', 7, {}) == 90


# --------------------------------------------------------------- the loop

def test_loop_rechecks_the_kill_switch_every_cycle(auto, monkeypatch, tmp_path):
    root = make_root(tmp_path)
    fake = Fake(root, kill_after=1, live_listings=0).install(auto, monkeypatch)   # arms for cycle 2

    code = auto.loop(root=root, max_cycles=3)

    assert code == 0
    assert len(log_lines(root)) == 3                                  # three cycles, always logged
    assert fake.calls == ['plan', 'runqueue']                         # engines only while disarmed
    assert fake.sleeps == [90, 300]                                   # then the 5-minute re-check
    assert read_json(os.path.join(root, 'data', 'auto_report.json'))['stopped'] == 'kill switch armed'


def test_loop_ctrl_c_is_clean(auto, monkeypatch, tmp_path, capsys):
    root = make_root(tmp_path)
    fake = Fake(root, sleep_raises=True, live_listings=0).install(auto, monkeypatch)

    code = auto.loop(root=root)

    assert code == 0 and len(log_lines(root)) == 1
    assert 'stopped by ctrl-c' in capsys.readouterr().out


# --------------------------------------------------------------- status

def test_status_prints_the_last_report(auto, monkeypatch, tmp_path, capsys):
    root = make_root(tmp_path)
    Fake(root, live_listings=0).install(auto, monkeypatch)
    auto.cycle(root=root)
    capsys.readouterr()

    assert auto.status(root=root) == 0
    out = capsys.readouterr().out
    assert 'auto report (last cycle)' in out and 'killswitch' in out and 'next_interval_s' in out


def test_status_without_a_report_exits_1(auto, tmp_path, capsys):
    root = make_root(tmp_path)
    assert auto.status(root=root) == 1
    assert 'no auto report yet' in capsys.readouterr().out


# --------------------------------------------------------------- notify hook (optional sibling)

def test_notify_is_never_fatal_when_the_module_is_missing(auto, monkeypatch):
    monkeypatch.delitem(sys.modules, 'notify_rules', raising=False)
    ok, summary = auto._notify('a line', {'ts': 1, 'steps': []})
    assert ok is True and summary                                 # a skip is fine, a crash is not


def test_notify_hook_is_called_with_only_its_own_kwargs(auto, monkeypatch):
    mod = type(sys)('notify_rules')
    seen = {}
    mod.notify_cycle = lambda summary, mode=None: seen.update(args=(summary, mode))
    monkeypatch.setitem(sys.modules, 'notify_rules', mod)

    ok, summary = auto._notify('the line', {'ts': 1, 'steps': [], 'mode': 'dry_run'})

    assert ok is True and seen['args'] == ('the line', 'dry_run')
    assert 'notify_cycle' in summary


def test_notify_hook_with_no_known_entry_point_is_a_skip(auto, monkeypatch):
    monkeypatch.setitem(sys.modules, 'notify_rules', type(sys)('notify_rules'))
    ok, summary = auto._notify('x', {'ts': 1})
    assert ok is True and 'no cycle hook' in summary


def test_raising_notify_hook_is_swallowed(auto, monkeypatch):
    mod = type(sys)('notify_rules')

    def boom(**kw):
        raise RuntimeError('test boom')

    mod.notify_cycle = boom
    monkeypatch.setitem(sys.modules, 'notify_rules', mod)

    ok, summary = auto._notify('x', {'ts': 1})
    assert ok is True and 'RuntimeError' in summary


# --------------------------------------------------------------- dry run never touches the wire

def test_no_cycle_path_needs_the_network(auto, monkeypatch, tmp_path):
    import socket

    def no_net(*_a, **_k):
        raise AssertionError('a cycle path tried to use the network')

    monkeypatch.setattr(socket, 'socket', no_net)
    monkeypatch.setattr(socket, 'create_connection', no_net)
    monkeypatch.setattr(socket, 'getaddrinfo', no_net)

    refused = make_root(tmp_path, 'refused', dry_run=False)
    fake = Fake(refused).install(auto, monkeypatch)
    assert auto.cycle(root=refused)[1] == 2 and fake.calls == []

    happy = make_root(tmp_path, 'happy')
    fake2 = Fake(happy, live_listings=3).install(auto, monkeypatch)
    report, code = auto.cycle(root=happy)
    assert code == 0 and fake2.calls == ENGINE_SEQUENCE
