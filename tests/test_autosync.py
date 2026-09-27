"""Auto sync, server side.

Jay (2026-09-27): *"can we get an auto sync with settings ie 5m 10m 15m 30m 1hr"*. The cadence is
the dashboard knob `auto_refresh_seconds` (0 = manual only); while the server runs,
`sync_tick()` runs the LOCAL pipeline (refresh.py -> invdiff.py -> progress.py) on that cadence so
the numbers the UI polls are refreshed, not just re-rendered.

These tests never shell out: subprocess.run is stubbed. They pin the decision logic (off / waiting /
due), the failure path, the config read, and the /api/sync contract the UI consumes.
"""
import os
import re
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(REPO, rel), encoding='utf-8') as fh:
        return fh.read()


def blank(mod):
    mod.SYNC.update({'seconds': 0, 'last_sync': None, 'last_ok': None, 'last_ms': None,
                     'next_at': None, 'for_secs': None, 'running': False, 'error': None})


def cfg(seconds, mod, missing=False):
    """Point the module's config handle at a stub returning `seconds` (or nothing)."""
    data = {} if missing else {'auto_refresh_seconds': seconds}
    mod._dashcfg = types.SimpleNamespace(read=lambda: dict(data))


class FakeProc:
    def __init__(self, rc=0, out='', err=''):
        self.returncode, self.stdout, self.stderr = rc, out, err


def fake_run(calls, rc_by_index=None):
    def _run(cmd, **kw):
        calls.append(cmd)
        i = len(calls) - 1
        rc = (rc_by_index or {}).get(i, 0)
        return FakeProc(rc=rc, out='ok' if rc == 0 else '', err='boom' if rc else '')
    return _run


# ------------------------------------------------------------------ what the sync runs

def test_sync_runs_the_local_pipeline_only(server_mod):
    names = [n for n, _ in server_mod.SYNC_STEPS]
    assert names == ['refresh.py', 'invdiff.py', 'progress.py']
    # the ~2 minute network job stays out of a 5-minute cadence
    assert not any('fetch_prices' in n or 'fetch_stats' in n for n in names)
    assert server_mod.SYNC_STEPS[2][1] == ['--once'], 'progress.py takes --once'


# ------------------------------------------------------------------ the cadence knob

def test_cadence_comes_from_the_dashboard_knob(server_mod):
    for stored, want in ((300, 300), (900, 900), (3600, 3600), (0, 0), ('600', 600),
                         (99999, 3600), (-5, 0)):
        cfg(stored, server_mod)
        assert server_mod.sync_config_seconds() == want, stored


def test_cadence_falls_back_to_15_minutes_when_unreadable(server_mod):
    cfg(0, server_mod, missing=True)
    assert server_mod.sync_config_seconds() == 900
    cfg('nonsense', server_mod)
    assert server_mod.sync_config_seconds() == 900

    def boom():
        raise OSError('config unreadable')
    server_mod._dashcfg = types.SimpleNamespace(read=boom)
    assert server_mod.sync_config_seconds() == 900


def test_no_config_module_at_all_still_yields_a_default(server_mod):
    server_mod._dashcfg = None
    assert server_mod.sync_config_seconds() == 900


# ------------------------------------------------------------------ tick logic

def test_zero_means_manual_only_and_never_runs(server_mod, monkeypatch):
    blank(server_mod)
    cfg(0, server_mod)
    calls = []
    monkeypatch.setattr(server_mod.subprocess, 'run', lambda *a, **k: calls.append(a) or FakeProc())
    assert server_mod.sync_tick(now=1000) == 'off'
    assert server_mod.SYNC['next_at'] is None and calls == []
    p = server_mod.sync_payload()
    assert p['enabled'] is False and p['seconds'] == 0 and p['next_in'] is None


def test_tick_waits_a_full_cadence_then_runs_once(server_mod, monkeypatch):
    blank(server_mod)
    cfg(900, server_mod)
    calls = []
    monkeypatch.setattr(server_mod.subprocess, 'run', fake_run(calls))
    assert server_mod.sync_tick(now=1000) == 'waiting'          # arms the timer
    assert server_mod.SYNC['next_at'] == 1900
    assert server_mod.sync_tick(now=1899) == 'waiting'
    assert calls == [], 'nothing runs before the cadence elapses'
    assert server_mod.sync_tick(now=1900) == 'ran'
    assert len(calls) == 3, 'all three steps ran'
    assert server_mod.SYNC['last_ok'] is True and server_mod.SYNC['running'] is False
    assert server_mod.SYNC['last_ms'] is not None and server_mod.SYNC['next_at'] > 1900
    p = server_mod.sync_payload()
    assert p['enabled'] is True and p['last_ok'] is True
    assert p['steps'] == ['refresh.py', 'invdiff.py', 'progress.py']
    assert isinstance(p['next_in'], int) and 0 <= p['next_in'] <= 900


def test_a_failing_step_is_reported_and_the_rest_still_run(server_mod, monkeypatch):
    blank(server_mod)
    cfg(300, server_mod)
    calls = []
    monkeypatch.setattr(server_mod.subprocess, 'run', fake_run(calls, rc_by_index={1: 2}))
    assert server_mod.sync_tick(now=500) == 'waiting'
    assert server_mod.sync_tick(now=800) == 'failed'
    assert len(calls) == 3, 'later steps still ran after invdiff failed'
    assert 'invdiff.py rc=2' in (server_mod.SYNC['error'] or '')
    assert server_mod.SYNC['last_ok'] is False and server_mod.SYNC['running'] is False


def test_a_crashing_runner_never_kills_the_loop(server_mod, monkeypatch):
    blank(server_mod)
    cfg(300, server_mod)

    def boom(*a, **k):
        raise RuntimeError('no interpreter')
    monkeypatch.setattr(server_mod.subprocess, 'run', boom)
    assert server_mod.sync_tick(now=100) == 'waiting'
    assert server_mod.sync_tick(now=400) == 'failed'
    assert server_mod.SYNC['running'] is False and server_mod.SYNC['error']


def test_changing_the_cadence_off_stops_the_next_run(server_mod, monkeypatch):
    blank(server_mod)
    cfg(300, server_mod)
    calls = []
    monkeypatch.setattr(server_mod.subprocess, 'run', fake_run(calls))
    server_mod.sync_tick(now=1000)
    cfg(0, server_mod)
    assert server_mod.sync_tick(now=2000) == 'off'
    assert calls == [] and server_mod.SYNC['next_at'] is None


def test_shortening_the_cadence_does_not_wait_out_the_old_one(server_mod, monkeypatch):
    """1 hour -> 5 minutes must take effect now, not in an hour (found live, 2026-09-27)."""
    blank(server_mod)
    cfg(3600, server_mod)
    calls = []
    monkeypatch.setattr(server_mod.subprocess, 'run', fake_run(calls))
    assert server_mod.sync_tick(now=1000) == 'waiting'          # arms a 1-hour wait
    assert server_mod.SYNC['next_at'] == 4600
    cfg(300, server_mod)                                        # the knob moves down
    assert server_mod.sync_tick(now=1010) == 'waiting'
    assert server_mod.SYNC['next_at'] == 1310, 're-timed from now, not from the old 4600'
    assert calls == []
    assert server_mod.sync_tick(now=1310) == 'ran'              # and it fires on the new cadence


def test_a_shortened_cadence_re_times_from_the_last_run(server_mod, monkeypatch):
    blank(server_mod)
    cfg(3600, server_mod)
    monkeypatch.setattr(server_mod.subprocess, 'run', fake_run([]))
    monkeypatch.setattr(server_mod.time, 'time', lambda: 5000)
    server_mod.sync_tick(now=1000)
    assert server_mod.sync_tick(now=5000) == 'ran'              # the hourly run lands at 5000
    assert server_mod.SYNC['next_at'] == 8600
    cfg(300, server_mod)
    assert server_mod.sync_tick(now=5010) == 'waiting'          # due at last run + 5 minutes
    assert server_mod.SYNC['next_at'] == 5300
    assert server_mod.sync_tick(now=5300) == 'ran'


def test_lengthening_the_cadence_pushes_the_next_run_out(server_mod, monkeypatch):
    blank(server_mod)
    cfg(300, server_mod)
    monkeypatch.setattr(server_mod.subprocess, 'run', fake_run([]))
    monkeypatch.setattr(server_mod.time, 'time', lambda: 7000)
    server_mod.sync_tick(now=1000)
    server_mod.sync_tick(now=1300)                              # runs, last_sync = 7000
    cfg(3600, server_mod)
    assert server_mod.sync_tick(now=7100) == 'waiting'
    assert server_mod.SYNC['next_at'] == 7000 + 3600


# ------------------------------------------------------------------ wiring pins

def test_status_endpoint_and_daemon_thread_are_wired():
    src = read('server.py')
    assert re.search(r"if p == '/api/sync': return self\._send\(200, sync_payload\(\)\)", src)
    assert re.search(r"threading\.Thread\(target=autosync_loop, daemon=True\)\.start\(\)", src)
    assert re.search(r'^import .*\bthreading\b', src, re.M), 'threading is imported'


def test_the_loop_sleeps_in_slices_so_a_cadence_change_lands_quickly():
    src = read('server.py')
    m = re.search(r'def autosync_loop\(\):(.*?)\nclass H', src, re.S)
    assert m, 'autosync_loop is gone'
    body = m.group(1)
    assert 'WFM_SYNC_SLICE' in body, 'the slice must be overridable for tests'
    assert 'sync_tick()' in body, 'the loop must drive sync_tick'
    assert 'min(slice_s' in body, 'a long cadence must not mean a long sleep'


def test_each_run_is_recorded_for_later(server_mod, monkeypatch):
    """pythonw swallows the loop's print, so the history goes to data/sync_log.json."""
    import json
    blank(server_mod)
    cfg(300, server_mod)
    calls = []
    monkeypatch.setattr(server_mod.subprocess, 'run', fake_run(calls))
    server_mod.sync_tick(now=1000)
    server_mod.sync_tick(now=1300)
    rows = json.load(open(os.path.join(server_mod.DATA, 'sync_log.json'), encoding='utf-8'))
    assert len(rows) == 1 and rows[0]['ok'] is True and rows[0]['ms'] is not None


def test_sync_history_is_capped_and_unreadable_history_is_replaced(server_mod, monkeypatch):
    import json
    blank(server_mod)
    cfg(300, server_mod)
    monkeypatch.setattr(server_mod.subprocess, 'run', fake_run([]))
    path = os.path.join(server_mod.DATA, 'sync_log.json')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('{ not a list }')
    server_mod.sync_tick(now=100)
    server_mod.SYNC.update(last_sync=1, last_ok=True, last_ms=5, error=None)
    for i in range(60):
        server_mod.sync_log_write(keep=50)
    rows = json.load(open(path, encoding='utf-8'))
    assert len(rows) == 50
