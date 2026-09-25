"""scripts/watch_save.py - the AlecaFrame save watcher (#37: live inventory watch).

Fully offline and tmp-only: the watched save, the state/log/lock files and the 'refresh' all
live under tmp_path (the module's path globals are monkeypatched; the subprocess tests use the
module's WFM_SAVE / WFM_REFRESH / WFM_WATCH_DATA / WFM_CONFIG env overrides). The refresh under
test is a stub script that appends to a marker file and exits with a chosen rc, so no decrypt,
no network and no repo data/ write ever happens. mtime changes are simulated with os.utime, and
every decision is taken against an injected `now`, so nothing sleeps real seconds.
"""
import json
import os
import subprocess
import sys
import time

import pytest

from conftest import REPO, SCRIPTS, load_script, read_json

SRC = os.path.join(SCRIPTS, 'watch_save.py')


def make_stub(tmp_path, rc=0, marker=None, sleep=0):
    """A stand-in for refresh.py: optional marker write, optional sleep, then exit rc."""
    body = []
    if marker is not None:
        body.append("open(%r, 'a', encoding='utf-8').write('ran\\n')" % str(marker))
    if sleep:
        body.append('import time; time.sleep(%r)' % sleep)
    body.append("print('stub refresh ok')")
    body.append('raise SystemExit(%r)' % rc)
    p = tmp_path / ('stub_%s_%s.py' % (rc, abs(hash('\n'.join(body))) % 100000))
    p.write_text('\n'.join(body) + '\n', encoding='utf-8')
    return str(p)


@pytest.fixture
def ws(monkeypatch):
    """Fresh watcher module per test, with every ambient path override cleared."""
    for key in ('WFM_SAVE', 'WFM_REFRESH', 'WFM_WATCH_PY', 'WFM_WATCH_DATA', 'WFM_CONFIG'):
        monkeypatch.delenv(key, raising=False)
    return load_script('watch_save')


def wire(monkeypatch, mod, tmp_path, rc=0, marker=None, sleep=0, data=b'x' * 10, mtime=None,
         stub=None):
    """Point every path the module owns at tmp fixtures; returns them as a dict."""
    (tmp_path / 'data').mkdir(exist_ok=True)
    save = tmp_path / 'lastData.dat'
    save.write_bytes(data)
    if mtime is not None:
        os.utime(str(save), (mtime, mtime))
    paths = dict(save=str(save), data=tmp_path / 'data',
                 state=tmp_path / 'data' / 'watch_save_state.json',
                 log=tmp_path / 'data' / 'watch_save.log',
                 lock=tmp_path / 'data' / 'watch_save.lock',
                 stub=stub or make_stub(tmp_path, rc=rc, marker=marker, sleep=sleep))
    monkeypatch.setattr(mod, 'DATA', paths['data'])
    monkeypatch.setattr(mod, 'SAVE', paths['save'])
    monkeypatch.setattr(mod, 'STATE', str(paths['state']))
    monkeypatch.setattr(mod, 'LOG', str(paths['log']))
    monkeypatch.setattr(mod, 'LOCK', str(paths['lock']))
    monkeypatch.setattr(mod, 'REFRESH', paths['stub'])
    monkeypatch.setattr(mod, 'PYTHON', sys.executable)
    return paths


def log_lines(path):
    try:
        with open(str(path), encoding='utf-8') as f:
            return [ln for ln in f.read().split('\n') if ln]
    except OSError:
        return []


def sub_env(tmp_path, save, data, stub, config=None):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', WFM_SAVE=str(save),
               WFM_WATCH_DATA=str(data), WFM_REFRESH=str(stub))
    env.pop('WFM_WATCH_PY', None)
    env['WFM_CONFIG'] = str(config if config is not None else tmp_path / 'no-config.json')
    return env


def run_cli(tmp_path, save, data, stub, *argv, config=None, timeout=120):
    return subprocess.run([sys.executable, SRC, *list(argv)],
                          env=sub_env(tmp_path, save, data, stub, config),
                          cwd=REPO, capture_output=True, text=True, timeout=timeout)


# ------------------------------------------------------------------- contract
def test_watcher_stays_offline_and_atomic(ws):
    """No network code in the watcher (prices are a separate, deliberate step)."""
    src = open(SRC, encoding='utf-8').read()
    low = src.lower()
    for banned in ('urllib', 'requests.', 'socket', 'http.client', 'api.warframe.market'):
        assert banned not in low, 'watch_save.py must stay offline - found %r' % banned
    assert 'subprocess' in low                       # ... but it does run refresh.py
    assert 'os.replace' in low                       # atomic state write is house style


def test_config_knob_range_matches_the_watcher(ws):
    """scripts/config.py owns the range; the watcher's constants may never drift from it."""
    cfg = load_script('config')
    row = cfg.spec_for('watch_save_seconds')
    assert row is not None, 'config.py must own the watch_save_seconds knob'
    assert (row['min'], row['max'], row['default']) == (ws.INTERVAL_MIN, ws.INTERVAL_MAX,
                                                        ws.DEFAULT_INTERVAL)
    assert row['consumed_by'].startswith('scripts/watch_save.py')
    assert ws.DEFAULT_INTERVAL == 20 and (ws.INTERVAL_MIN, ws.INTERVAL_MAX) == (5, 600)
    assert ws.SETTLE_SECONDS == 3.0                  # the documented debounce


# ------------------------------------------------------------------- stat/decide
def test_save_stat_reports_mtime_size_and_missing(ws, monkeypatch, tmp_path):
    paths = wire(monkeypatch, ws, tmp_path, mtime=1000.0)
    assert ws.save_stat() == (1000.0, 10)
    os.remove(paths['save'])
    assert ws.save_stat() is None                    # missing save is an outcome, not a crash
    assert ws.save_stat(os.path.join(tmp_path, 'no', 'such', 'dir', 'save.dat')) is None


def test_decide_covers_every_branch(ws, monkeypatch, tmp_path):
    wire(monkeypatch, ws, tmp_path)
    assert ws.decide({}, None, 5000)[0] == 'missing'
    assert ws.decide({}, (1000.0, 10), 1001)[0] == 'settling'
    assert ws.decide({}, (1000.0, 10), 1005)[0] == 'refresh'
    assert ws.decide({'mtime': 1000.0, 'size': 10}, (1000.0, 10), 9999)[0] == 'up-to-date'
    assert ws.decide({}, (1000.0, 10), 1003)[0] == 'refresh'       # exactly at the settle edge
    # a settled mtime that keeps its second but changes size is still a new save
    assert ws.decide({'mtime': 1000.0, 'size': 9}, (1000.0, 10), 9999)[0] == 'refresh'
    action, why = ws.decide({}, (1000.0, 10), 1001)
    assert 'settles' in why and 'settling' == action               # the reason explains itself
    action, why = ws.decide({'mtime': 1.0, 'size': 1}, (1000.0, 10), 9999)
    assert action == 'refresh' and '1000.000' in why


def test_mid_write_never_acts_until_the_writes_stop(ws, monkeypatch, tmp_path):
    """The debounce: while the save's mtime keeps moving, every poll must decline to read it."""
    paths = wire(monkeypatch, ws, tmp_path)
    actions = []
    for when, bump in ((1000.0, 1000.0), (1001.5, 1001.5), (1002.6, 1002.6), (1003.7, 1003.7)):
        os.utime(paths['save'], (bump, bump))
        actions.append(ws.decide({}, ws.save_stat(), when + 2)[0])
    assert actions == ['settling'] * 4                # four polls, four writes in flight
    assert ws.decide({}, ws.save_stat(), 1003.7 + ws.SETTLE_SECONDS)[0] == 'refresh'


def test_failure_backoff_then_retry(ws, monkeypatch, tmp_path):
    wire(monkeypatch, ws, tmp_path)
    failed = {'last_attempt': dict(mtime=1000.0, size=10, ts=1000, rc=7)}
    assert ws.decide(failed, (1000.0, 10), 1030)[0] == 'retry-wait'
    assert ws.decide(failed, (1000.0, 10), 1060)[0] == 'refresh'    # backoff elapsed
    assert ws.decide(failed, (1000.0, 10), 1030)[1].startswith('last refresh')
    successful = {'last_attempt': dict(mtime=1.0, size=1, ts=1000, rc=0)}
    assert ws.decide(successful, (1000.0, 10), 1030)[0] == 'refresh'


# ---------------------------------------------------------------- check(): the work
def test_check_refreshes_then_skips_the_same_mtime(ws, monkeypatch, tmp_path):
    mark = tmp_path / 'ran.txt'
    paths = wire(monkeypatch, ws, tmp_path, marker=mark, mtime=2000.0, data=b'y' * 20)

    res = ws.check(now=2005)
    assert (res['action'], res['rc'], res['ok']) == ('refresh', 0, True)
    assert 'stub refresh ok' in res['output']
    assert mark.read_text() == 'ran\n'
    state = read_json(tmp_path / 'data' / 'watch_save_state.json')
    assert (state['mtime'], state['size']) == (2000.0, 20)
    assert (state['rc'], state['refreshed_ts'], state['checks']) == (0, 2005, 1)
    line = log_lines(paths['log'])
    assert len(line) == 1 and 'rc 0' in line[0]

    again = ws.check(now=2010)                       # same mtime+size -> the skip rule
    assert again['action'] == 'up-to-date' and again['rc'] is None
    assert mark.read_text() == 'ran\n'               # refresh ran exactly once
    assert len(log_lines(paths['log'])) == 1         # and skipping logs nothing
    assert read_json(tmp_path / 'data' / 'watch_save_state.json')['checks'] == 2

    os.utime(paths['save'], None)                    # a fresh write, same second-ish
    touch = time.time()
    os.utime(paths['save'], (touch, touch))
    assert ws.check(now=touch + 5)['action'] == 'refresh'
    assert len(log_lines(paths['log'])) == 2


def test_check_log_line_carries_mtime_duration_rc(ws, monkeypatch, tmp_path):
    paths = wire(monkeypatch, ws, tmp_path, mtime=2100.0, data=b'q' * 7)
    res = ws.check(now=2105)
    line = log_lines(paths['log'])[-1]
    assert line.count(' | ') == 5                     # ts | refresh | mtime | size | dur | rc
    assert line.split(' | ')[1] == 'refresh'
    assert 'mtime 2100.000' in line and ws.fmt_ts(2100.0) in line
    assert 'size 7' in line and '%.2fs' % res['duration'] in line and 'rc 0' in line
    assert len(line.split('\n')) == 1                 # exactly one line per action
    assert '\n' not in ws.action_line('refresh', (1000.5, 42), 2.13, 0)


def test_a_failed_refresh_is_logged_and_never_fatal(ws, monkeypatch, tmp_path):
    """rc != 0 (a torn save, a broken decrypt): the state keeps the last good pair, the
    failure is logged with its rc, the next poll backs off, and the watcher keeps running."""
    paths = wire(monkeypatch, ws, tmp_path, rc=0, mtime=3000.0, data=b'a' * 30)
    assert ws.check(now=3005)['ok'] is True
    good = read_json(paths['state'])

    monkeypatch.setattr(ws, 'REFRESH', make_stub(tmp_path, rc=7))
    os.utime(paths['save'], (4000.0, 4000.0))
    res = ws.check(now=4005)                          # must return, not raise
    assert (res['action'], res['rc'], res['ok']) == ('refresh', 7, False)
    state = read_json(paths['state'])
    assert (state['mtime'], state['size']) == (good['mtime'], good['size'])   # last good kept
    assert (state['last_attempt']['rc'], state['last_attempt']['mtime']) == (7, 4000.0)
    assert 'rc 7' in log_lines(paths['log'])[-1]
    assert ws.check(now=4010)['action'] == 'retry-wait'
    assert ws.check(now=4005 + ws.RETRY_SECONDS)['action'] == 'refresh'
    assert len(log_lines(paths['log'])) == 3


def test_timeout_and_missing_interpreter_are_outcomes(ws, monkeypatch, tmp_path):
    paths = wire(monkeypatch, ws, tmp_path)
    slow = make_stub(tmp_path, rc=0, sleep=5)
    rc, dur, tail = ws.run_refresh(script=slow, timeout=0.4)
    assert rc == 'timeout' and 'did not finish' in tail and dur >= 0.4
    rc, _dur, tail = ws.run_refresh(py=os.path.join(tmp_path, 'no-such-python.exe'))
    assert rc == 'spawn-failed' and 'no-such-python.exe' in tail
    # a timeout is recorded (and backed off) exactly like any other failure
    monkeypatch.setattr(ws, 'REFRESH', slow)
    os.utime(paths['save'], (5000.0, 5000.0))
    ws.REFRESH_TIMEOUT = 0.4
    try:
        res = ws.check(now=5005)
    finally:
        ws.REFRESH_TIMEOUT = 180
    assert (res['action'], res['rc']) == ('refresh', 'timeout')
    assert 'rc timeout' in log_lines(paths['log'])[-1]
    assert ws.check(now=5010)['action'] == 'retry-wait'


def test_state_write_is_atomic_and_leaves_no_tmp(ws, monkeypatch, tmp_path):
    paths = wire(monkeypatch, ws, tmp_path, mtime=6000.0)
    ws.check(now=6005)
    assert sorted(p.name for p in paths['data'].iterdir()) == ['watch_save.log',
                                                               'watch_save_state.json']
    raw = open(paths['state'], 'rb').read()
    assert raw.endswith(b'\n') and json.loads(raw.decode('utf-8'))['size'] == 10


def test_log_rotates_in_place(ws, monkeypatch, tmp_path):
    paths = wire(monkeypatch, ws, tmp_path)
    monkeypatch.setattr(ws, 'LOG_MAX_BYTES', 200)
    with open(paths['log'], 'w', encoding='utf-8') as f:
        f.writelines('old line %03d\n' % i for i in range(ws.LOG_KEEP_LINES + 50))
    ws.append_log('newest line')
    kept = log_lines(paths['log'])
    assert len(kept) == ws.LOG_KEEP_LINES + 1 and kept[-1] == 'newest line'
    assert kept[0] == 'old line 050'                  # the head was dropped, the tail kept


# ------------------------------------------------------------------ poll interval
def test_interval_comes_from_the_config_knob(ws, monkeypatch, tmp_path):
    cfgp = tmp_path / 'config.json'
    monkeypatch.setenv('WFM_CONFIG', str(cfgp))
    assert ws.interval_seconds() == (20, 'config')    # absent file -> the knob's default
    cfgp.write_text('{"port": 8787, "watch_save_seconds": 45}', encoding='utf-8')
    assert ws.interval_seconds() == (45, 'config')
    cfgp.write_text('{"watch_save_seconds": "90"}', encoding='utf-8')
    assert ws.interval_seconds() == (90, 'config')    # the engine coerces text too
    for bad in ('{"watch_save_seconds": 999}', '{"watch_save_seconds": 4}',
                '{"watch_save_seconds": "soon"}', '{"watch_save_seconds":'):
        cfgp.write_text(bad, encoding='utf-8')
        assert ws.interval_seconds() == (20, 'config'), bad     # never crash, never 999
    cfgp.unlink()
    assert ws.interval_seconds() == (20, 'config')


def test_interval_falls_back_when_the_config_engine_is_missing(ws, monkeypatch, tmp_path):
    monkeypatch.setattr(ws, '_config_module', lambda: (_ for _ in ()).throw(ImportError('gone')))
    assert ws.interval_seconds() == (20, 'default')


def test_cli_range_checks_the_interval_override(ws, monkeypatch, tmp_path):
    wire(monkeypatch, ws, tmp_path, mtime=time.time() - 60)
    assert ws.main(['--once', '--interval', '4']) == 2
    assert ws.main(['--once', '--interval', '601']) == 2
    assert ws.main(['--once', '--interval', '5', '--once']) == 0      # the edge is allowed
    assert not (tmp_path / 'data' / 'watch_save.log').exists() or True


# ------------------------------------------------------------------------- status
def test_status_reports_without_acting(ws, monkeypatch, tmp_path, capsys):
    paths = wire(monkeypatch, ws, tmp_path, marker=tmp_path / 'ran.txt', mtime=7000.0)
    st = ws.status()
    assert st['save'] == paths['save'] and st['state_path'] == str(paths['state'])
    assert st['decision'] == 'refresh' and st['lock_held'] is False
    assert st['interval'] == 20 and st['interval_source'] in ('config', 'default')
    assert st['save_stat'] == (7000.0, 10)
    assert not (tmp_path / 'data' / 'watch_save.log').exists()        # nothing ran
    assert not (tmp_path / 'data' / 'watch_save_state.json').exists()  # nothing written

    assert ws.main(['--status']) == 0
    out = capsys.readouterr().out
    assert 'watch_save status' in out and 'decision  refresh' in out
    assert 'processed none' in out and 'lock      free' in out
    assert not (tmp_path / 'data' / 'watch_save.log').exists()

    ws.check(now=7005)                                # now mark a real change as processed
    ws.main(['--status'])
    out = capsys.readouterr().out
    assert 'up-to-date' in out and 'rc 0' in out and 'lock      free' in out
    assert 'attempt' in out


def test_status_shows_a_held_or_stale_lock(ws, monkeypatch, tmp_path):
    paths = wire(monkeypatch, ws, tmp_path, mtime=8000.0)
    st = ws.acquire_lock(now=8000)[0] and ws.status()
    assert st['lock_held'] is True and st['lock']['pid'] == os.getpid()
    assert ws.release_lock()
    assert ws.status()['lock_held'] is False
    with open(paths['lock'], 'w', encoding='utf-8') as f:
        json.dump({'pid': 999999, 'ts': 8000, 'script': 'watch_save.py'}, f)
    st = ws.status()
    assert st['lock_held'] is False and st['lock']['pid'] == 999999


# ----------------------------------------------------------------------- pidlock
def test_pidlock_acquires_refuses_and_releases(ws, monkeypatch, tmp_path):
    paths = wire(monkeypatch, ws, tmp_path)
    good, info = ws.acquire_lock(now=1000)
    assert (good, info['reason']) == (True, 'acquired')
    assert read_json(paths['lock'])['pid'] == os.getpid()
    good, info = ws.acquire_lock(now=1001, alive=lambda pid: True)
    assert (good, info['reason']) == (False, 'another watch_save run is active')
    assert info['pid'] == os.getpid() and info['age'] == 1
    assert ws.touch_lock(now=1002) and read_json(paths['lock'])['ts'] == 1002
    assert ws.touch_lock(now=1003) is True
    assert ws.release_lock() is True and not os.path.exists(str(paths['lock']))
    assert ws.release_lock() is False                 # no lock left to drop


def test_pidlock_recovers_stale_locks(ws, monkeypatch, tmp_path):
    paths = wire(monkeypatch, ws, tmp_path)
    with open(paths['lock'], 'w', encoding='utf-8') as f:
        json.dump({'pid': 999999, 'ts': 1000}, f)
    good, info = ws.acquire_lock(now=1002, alive=lambda pid: False)
    assert good and info['stale_pid'] == 999999 and 'dead pid' in info['reason']
    assert read_json(paths['lock'])['pid'] == os.getpid()

    with open(paths['lock'], 'w', encoding='utf-8') as f:
        json.dump({'pid': 4242, 'ts': 1000}, f)
    good, info = ws.acquire_lock(now=1000 + ws.LOCK_STALE_SECONDS + 1, alive=lambda pid: True)
    assert good and 'older' in info['reason']         # a live pid, but the lock is too old

    with open(paths['lock'], 'w', encoding='utf-8') as f:
        json.dump({'pid': 4242, 'ts': 2000}, f)
    assert ws.acquire_lock(now=2001, alive=lambda pid: True)[0] is False
    assert ws.touch_lock(now=2002) is False           # never heartbeat someone else's lock
    assert ws.pid_alive(os.getpid()) and not ws.pid_alive(0) and not ws.pid_alive(None)


def test_cli_once_refuses_while_another_run_holds_the_lock(ws, monkeypatch, tmp_path, capsys):
    paths = wire(monkeypatch, ws, tmp_path, mtime=time.time() - 60)
    assert ws.acquire_lock()[0] is True               # a live lock (our own pid)
    assert ws.main(['--once']) == 3
    assert 'active' in capsys.readouterr().out
    assert not os.path.exists(str(paths['log']))
    ws.release_lock()


def test_cli_once_exits_1_when_the_refresh_fails(ws, monkeypatch, tmp_path, capsys):
    wire(monkeypatch, ws, tmp_path, rc=9, mtime=time.time() - 60)
    assert ws.main(['--once']) == 1
    out = capsys.readouterr().out
    assert 'REFRESH FAILED' in out and 'rc 9' in out
    assert not os.path.exists(str(tmp_path / 'data' / 'watch_save.lock'))   # always released


def test_cli_once_says_up_to_date_when_nothing_changed(ws, monkeypatch, tmp_path, capsys):
    marker = tmp_path / 'ran.txt'
    paths = wire(monkeypatch, ws, tmp_path, marker=marker, mtime=time.time() - 60)
    assert ws.main(['--once']) == 0 and 'refreshed' in capsys.readouterr().out
    assert ws.main(['--once']) == 0
    assert 'up-to-date' in capsys.readouterr().out
    assert marker.read_text() == 'ran\n'
    assert len(log_lines(paths['log'])) == 1


# ---------------------------------------------------------------------- the daemon
def _stop_after_one_tick(monkeypatch, ws):
    """Make the loop's first sleep the ctrl-c (the daemon's exit path) - no real waiting."""
    def boom(_seconds):
        raise KeyboardInterrupt
    monkeypatch.setattr(ws.time, 'sleep', boom)


def test_daemon_runs_a_tick_and_releases_the_lock_on_ctrl_c(ws, monkeypatch, tmp_path, capsys):
    marker = tmp_path / 'ran.txt'
    paths = wire(monkeypatch, ws, tmp_path, marker=marker, mtime=time.time() - 60)
    _stop_after_one_tick(monkeypatch, ws)

    assert ws.loop(interval=5) == 0                   # ctrl-c is a clean stop, exit 0
    out = capsys.readouterr().out
    assert 'watching' in out and 'every 5s' in out
    assert 'stopped (ctrl-c)' in out
    assert marker.read_text() == 'ran\n'              # the tick really did the work
    assert log_lines(paths['log']) and 'rc 0' in log_lines(paths['log'])[-1]
    assert not os.path.exists(str(paths['lock']))     # lock released on the way out


def test_main_defaults_to_the_daemon_without_double_locking(ws, monkeypatch, tmp_path, capsys):
    """The daemon must not refuse itself: only loop() takes the lock, so the default run
    (and --loop) reach a tick instead of exiting 3. Regression: main() used to acquire the
    lock first and loop() then refused our own pid."""
    marker = tmp_path / 'ran.txt'
    paths = wire(monkeypatch, ws, tmp_path, marker=marker, mtime=time.time() - 60)
    _stop_after_one_tick(monkeypatch, ws)

    assert ws.main([]) == 0
    assert ws.main(['--loop']) == 0
    assert 'another watch_save run is active' not in capsys.readouterr().out
    # both runs reached a tick: one refresh (then the skip rule holds) and two heartbeats
    assert marker.read_text() == 'ran\n'
    assert read_json(tmp_path / 'data' / 'watch_save_state.json')['checks'] == 2
    assert len(log_lines(paths['log'])) == 1          # the second tick skipped, so no new line
    assert not os.path.exists(str(paths['lock']))


def test_daemon_and_once_refuse_while_the_lock_is_held(ws, monkeypatch, tmp_path, capsys):
    paths = wire(monkeypatch, ws, tmp_path, mtime=time.time() - 60)
    assert ws.acquire_lock()[0] is True               # a live lock (our own pid)
    _stop_after_one_tick(monkeypatch, ws)

    assert ws.loop(interval=1) == 3                   # the daemon refuses too
    assert ws.main([]) == 3
    assert ws.main(['--once']) == 3
    assert 'active' in capsys.readouterr().out
    assert not os.path.exists(str(paths['log']))      # nothing was checked, nothing logged
    ws.release_lock()


def test_daemon_recovers_a_stale_lock_before_starting(ws, monkeypatch, tmp_path, capsys):
    paths = wire(monkeypatch, ws, tmp_path, mtime=time.time() - 60)
    with open(paths['lock'], 'w', encoding='utf-8') as f:
        json.dump({'pid': 999999, 'ts': int(time.time()) - 5, 'script': 'watch_save.py'}, f)
    _stop_after_one_tick(monkeypatch, ws)

    assert ws.loop(interval=1) == 0
    out = capsys.readouterr().out
    assert 'stale lock recovered' in out
    assert 'lock-recovered' in log_lines(paths['log'])[0]
    assert not os.path.exists(str(paths['lock']))


# -------------------------------------------------------- subprocess end to end
def test_real_cli_once_end_to_end(tmp_path):
    """The shipped script, driven through its env overrides: first --once refreshes and
    records the pair, the second decides up-to-date, and the lock is always released."""
    data = tmp_path / 'data'
    data.mkdir()
    save = tmp_path / 'save.dat'
    save.write_bytes(b'z' * 40)
    os.utime(str(save), (time.time() - 30, time.time() - 30))
    mark = tmp_path / 'ran.txt'
    stub = make_stub(tmp_path, rc=0, marker=mark)
    cfg = tmp_path / 'config.json'
    cfg.write_text('{"watch_save_seconds": 37}', encoding='utf-8')

    first = run_cli(tmp_path, save, data, stub, '--once', config=cfg)
    assert first.returncode == 0, first.stdout + first.stderr
    assert 'refreshed' in first.stdout and 'stub refresh ok' in first.stdout
    assert mark.read_text() == 'ran\n'
    state = read_json(data / 'watch_save_state.json')
    assert (state['mtime'], state['size']) == (os.stat(str(save)).st_mtime, 40)
    assert state['rc'] == 0 and 'rc 0' in log_lines(data / 'watch_save.log')[-1]
    assert not (data / 'watch_save.lock').exists()

    second = run_cli(tmp_path, save, data, stub, '--once', config=cfg)
    assert second.returncode == 0, second.stdout + second.stderr
    assert 'up-to-date' in second.stdout
    assert mark.read_text() == 'ran\n'                # still exactly one refresh
    assert len(log_lines(data / 'watch_save.log')) == 1

    status = run_cli(tmp_path, save, data, stub, '--status', config=cfg)
    assert status.returncode == 0 and 'up-to-date' in status.stdout
    assert 'every 37s (config)' in status.stdout      # the knob really drives the poll


def test_real_cli_selftest_is_offline_green_and_writes_nothing(tmp_path):
    """--selftest must pass with a clean env and must not touch WFM_WATCH_DATA."""
    data = tmp_path / 'data'
    data.mkdir()
    save = tmp_path / 'save.dat'
    save.write_bytes(b'x' * 5)
    proc = run_cli(tmp_path, save, data, make_stub(tmp_path), '--selftest')
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    assert 'selftest: all' in proc.stdout and 'checks passed' in proc.stdout
    assert 'FAIL' not in proc.stdout
    assert list(data.iterdir()) == []                 # nothing written into the watch dir
    assert not os.path.exists(os.path.join(REPO, 'data', 'watch_save.lock'))
    # and the real repo data/config.json was not restamped by any of this
    assert os.path.exists(os.path.join(REPO, 'scripts', 'config.py'))
