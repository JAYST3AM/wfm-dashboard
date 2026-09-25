"""Live inventory watch (#37): refresh the derived data when AlecaFrame rewrites the game save.

Watches the AlecaFrame save's *stat* only - %LOCALAPPDATA%\\AlecaFrame\\lastData.dat - every
watch_save_seconds (the scripts/config.py knob: 5..600, default 20). When the save's mtime+size
change and the write has settled, scripts/refresh.py runs once in a subprocess (decrypt ->
data/lastData.dec.json + data/owned.json). One line per action lands in data/watch_save.log
(mtime, duration, rc). Prices are deliberately NOT fetched here: scripts/fetch_prices.py is a
network sweep and stays a separate, deliberate step.

Debounce ("mtime stable for >= 3s so we never read mid-write"): the test is
`now - mtime >= SETTLE_SECONDS` - the game has not touched the file for at least 3 seconds.
Two identical polls 20s apart pass the same test a poll later, so a change is never read while
its mtime is younger than SETTLE_SECONDS, whether the watcher is a daemon or a cron --once.

Skip rule: the (mtime, size) pair that was last *processed* is persisted in
data/watch_save_state.json, so a re-run (or a restarted daemon) never refreshes the same save
twice. A failed refresh is logged, kept in the state (rc), and retried at most every
RETRY_SECONDS - it never kills the daemon.

Usage:
  python scripts/watch_save.py                 # daemon: poll until ctrl-c (the default)
  python scripts/watch_save.py --once          # one check now (cron / the run queue)
  python scripts/watch_save.py --status        # state + last action + what a check would do
  python scripts/watch_save.py --selftest      # offline checks on tmp fixtures (no network)
  python scripts/watch_save.py --interval 60   # poll override for this run (5..600)
Exit codes: 0 ok | 1 --once refresh failed (or selftest checks failed) | 2 bad --interval |
            3 another watch_save run is active (pidlock).

Reads : the save's stat() - never its bytes (refresh.py owns the decrypt) - plus
        data/watch_save_state.json and, for the poll interval, scripts/config.py.
Writes: data/watch_save_state.json, data/watch_save.log, data/watch_save.lock and whatever
        refresh.py itself writes (data/owned.json, data/lastData.dec.json).
Env: WFM_SAVE (the .dat to watch), WFM_REFRESH (the refresh script), WFM_WATCH_PY (the
     interpreter refresh.py runs under), WFM_WATCH_DATA (where state/log/lock live),
     WFM_CONFIG (config.py's own override). Tests point these at tmp fixtures; the defaults
     are the real paths.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.environ.get('WFM_WATCH_DATA') or os.path.join(ROOT, 'data')
AF = os.path.expandvars(r'%LOCALAPPDATA%\AlecaFrame')
SAVE = os.environ.get('WFM_SAVE') or os.path.join(AF, 'lastData.dat')
REFRESH = os.environ.get('WFM_REFRESH') or os.path.join(HERE, 'refresh.py')
PYTHON = os.environ.get('WFM_WATCH_PY') or sys.executable
STATE = os.path.join(DATA, 'watch_save_state.json')
LOG = os.path.join(DATA, 'watch_save.log')
LOCK = os.path.join(DATA, 'watch_save.lock')

DEFAULT_INTERVAL = 20                # config.py watch_save_seconds default (5..600)
INTERVAL_MIN, INTERVAL_MAX = 5, 600
SETTLE_SECONDS = 3.0                 # act only once the save has been untouched this long
RETRY_SECONDS = 60                   # a failed refresh is retried at most this often
REFRESH_TIMEOUT = 180                # refresh.py decrypts + joins offline; generous cap
LOCK_STALE_SECONDS = 1800            # a lock older than this is stale even if the pid lives
LOG_MAX_BYTES = 256 * 1024           # rotate watch_save.log in place past this size
LOG_KEEP_LINES = 400


def jload(p, default=None):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def write_state(doc):
    """Atomic state write (same-dir tmp + os.replace): a cron --once never reads a torn file."""
    d = os.path.dirname(os.path.abspath(STATE)) or '.'
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.watch_save.', suffix='.tmp', dir=d)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(doc, f, indent=1)
            f.write('\n')
        os.replace(tmp, STATE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_stat(path=None):
    """(mtime, size) of the watched save, or None when it is absent/unreadable (never raises)."""
    try:
        st = os.stat(path or SAVE)
    except OSError:
        return None
    return (st.st_mtime, st.st_size)


def fmt_ts(ts):
    try:
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(float(ts)))
    except Exception:
        return str(ts)


def fmt_save(cur):
    """'mtime 1790458200.123 (2026-09-25 22:50:00) | size 1234567'."""
    return 'mtime %.3f (%s) | size %d' % (cur[0], fmt_ts(cur[0]), cur[1])


def action_line(action, cur=None, duration=None, rc=None, note=''):
    """The one-line-per-action record appended to data/watch_save.log."""
    parts = [time.strftime('%Y-%m-%d %H:%M:%S'), action]
    if cur:
        parts += ['mtime %.3f (%s)' % (cur[0], fmt_ts(cur[0])), 'size %d' % cur[1]]
    if duration is not None:
        parts.append('%.2fs' % duration)
    if rc is not None:
        parts.append('rc %s' % rc)
    if note:
        parts.append(note)
    return ' | '.join(parts)


def append_log(line):
    """Append one line to data/watch_save.log (in-place rotation past LOG_MAX_BYTES).
    Never raises: a broken log must not break the watch."""
    try:
        os.makedirs(DATA, exist_ok=True)
        if os.path.exists(LOG) and os.path.getsize(LOG) > LOG_MAX_BYTES:
            with open(LOG, encoding='utf-8') as f:
                keep = f.readlines()[-LOG_KEEP_LINES:]
            with open(LOG, 'w', encoding='utf-8') as f:
                f.writelines(keep)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(str(line).rstrip('\n') + '\n')
    except Exception:
        pass


# ------------------------------------------------------------------ the decision
def decide(state, cur, now, settle=SETTLE_SECONDS, retry_after=RETRY_SECONDS):
    """('action', 'reason') for one observation of the save.

    up-to-date  (mtime, size) is the pair the last successful refresh processed
    missing     there is no save file
    settling    the mtime is younger than `settle` - a write may be in flight, never read it
    retry-wait  this same change already failed once and the retry backoff has not elapsed
    refresh     actionable: a settled change that has not been processed yet
    """
    if cur is None:
        return 'missing', 'no save at %s' % SAVE
    if state.get('mtime') is not None and (state.get('mtime'), state.get('size')) == cur:
        return 'up-to-date', 'unchanged since the last refresh (%s)' % fmt_save(cur)
    age = now - cur[0]
    if age < settle:
        return 'settling', ('save written %.1fs ago (< %.0fs) - leaving it alone until it '
                            'settles' % (age, settle))
    att = state.get('last_attempt') or {}
    if (att.get('mtime'), att.get('size')) == cur and att.get('rc') not in (0, None):
        since = now - float(att.get('ts') or 0)
        if since < retry_after:
            return 'retry-wait', ('last refresh of this change failed (rc %s) %.0fs ago - '
                                  'retrying in %.0fs' % (att.get('rc'), since, retry_after - since))
    return 'refresh', 'save changed (%s)' % fmt_save(cur)


def run_refresh(py=None, script=None, timeout=None):
    """Run the refresh script once. Returns (rc, duration, tail) - rc is an int, or
    'timeout' / 'spawn-failed'. Never raises: a broken refresh is an outcome, not a crash."""
    py = py or PYTHON
    script = script or REFRESH
    timeout = REFRESH_TIMEOUT if timeout is None else timeout
    t0 = time.time()
    try:
        proc = subprocess.run([py, script], capture_output=True, text=True, timeout=timeout,
                              cwd=ROOT)
    except subprocess.TimeoutExpired:
        return 'timeout', time.time() - t0, 'refresh did not finish within %ss' % timeout
    except OSError as e:
        return 'spawn-failed', time.time() - t0, ('could not run %s: %s' % (py, e))[:200]
    out = (proc.stdout or '').strip() or (proc.stderr or '').strip()
    return proc.returncode, time.time() - t0, out[-400:]


def check(now=None):
    """One poll: decide, refresh when the decision is 'refresh', heartbeat the state.

    Returns dict(action, reason, save, rc, duration, output, refreshed). The heartbeat
    (checked_ts/checks) only moves on a real poll - --status probes with decide() instead.
    """
    now = float(now if now is not None else time.time())
    cur = save_stat()
    state = jload(STATE, {}) or {}
    action, reason = decide(state, cur, now)
    res = dict(action=action, reason=reason, save=cur, rc=None, duration=None, output=None,
               refreshed=False)
    new = dict(state, checked_ts=int(now), checks=int(state.get('checks') or 0) + 1)
    if action != 'refresh':
        write_state(new)
        return res
    rc, dur, tail = run_refresh()
    new['last_attempt'] = dict(mtime=cur[0], size=cur[1], ts=int(now), rc=rc,
                               duration=round(dur, 2))
    res.update(rc=rc, duration=round(dur, 2), output=tail, refreshed=True)
    if rc == 0:
        new.update(mtime=cur[0], size=cur[1], refreshed_ts=int(now), rc=0,
                   duration=round(dur, 2), output=tail[-200:])
        res['ok'] = True
    else:
        res['ok'] = False
    write_state(new)
    append_log(action_line('refresh', cur, dur, rc))
    return res


def say(res):
    """One-line human report of a check() result (the --once stdout / daemon trace)."""
    cur = res.get('save')
    action = res['action']
    if action == 'missing':
        print('watch_save: no save at %s - nothing to do' % SAVE)
    elif action == 'up-to-date':
        print('watch_save: up-to-date | %s' % fmt_save(cur))
    elif action in ('settling', 'retry-wait'):
        print('watch_save: %s | %s' % (action, res['reason']))
    else:                                        # refresh
        if res.get('ok'):
            print('watch_save: refreshed | %s | %.2fs | rc 0' % (fmt_save(cur), res['duration']))
        else:
            print('watch_save: REFRESH FAILED | %s | %.2fs | rc %s'
                  % (fmt_save(cur), res['duration'], res['rc']))
    if res.get('output'):
        print('   %s' % res['output'])


# ------------------------------------------------------------------ poll interval
def _config_module():
    """scripts/config.py as a module object, imported by path (no name collisions, cached)."""
    import importlib.util
    name = 'wfm_watch_config'
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, 'config.py'))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


def interval_seconds():
    """(seconds, source) from config.py's watch_save_seconds knob.

    Any problem - config.py missing, unreadable file, bad or out-of-range value - falls back
    to DEFAULT_INTERVAL: the watcher must never depend on the config engine to run.
    """
    try:
        secs = int(_config_module().read().get('watch_save_seconds'))
        if not (INTERVAL_MIN <= secs <= INTERVAL_MAX):
            raise ValueError(secs)
        return secs, 'config'
    except Exception:
        return DEFAULT_INTERVAL, 'default'


def status():
    """The --status document: paths, state, last action, lock and what a check would decide."""
    cur = save_stat()
    state = jload(STATE, {}) or {}
    action, reason = decide(state, cur, time.time())
    secs, src = interval_seconds()
    lock = jload(LOCK) or {}
    held = bool(lock.get('pid')) and pid_alive(lock.get('pid'))
    lines = 0
    if os.path.exists(LOG):
        try:
            with open(LOG, encoding='utf-8') as f:
                lines = sum(1 for _ in f)
        except OSError:
            lines = 0
    return dict(save=SAVE, save_stat=cur, state_path=STATE, state=state, log_path=LOG,
                log_lines=lines, decision=action, reason=reason, interval=secs,
                interval_source=src, lock_held=held, lock=lock, refresh=REFRESH, python=PYTHON)


def status_cmd():
    """Print the status block; returns 0."""
    st = status()
    cur = st['save_stat']
    state = st['state']
    print('watch_save status')
    print('  save      %s' % st['save'])
    print('            %s' % (fmt_save(cur) if cur else 'missing - nothing to watch yet'))
    if state.get('mtime') is not None:
        print('  processed mtime %.3f (%s) | size %d | %s | rc %s | %.2fs'
              % (state['mtime'], fmt_ts(state['mtime']), state.get('size') or 0,
                 fmt_ts(state.get('refreshed_ts')), state.get('rc'), state.get('duration')))
    else:
        print('  processed none - no refresh has run yet')
    print('  checks    %s (last %s)'
          % (state.get('checks', 0), fmt_ts(state['checked_ts']) if state.get('checked_ts')
             else 'never'))
    att = state.get('last_attempt')
    if att:
        print('  attempt   rc %s in %.2fs at %s' % (att.get('rc'), att.get('duration') or 0,
                                                    fmt_ts(att.get('ts'))))
    if state.get('output'):
        print('            %s' % state['output'])
    print('  decision  %s - %s' % (st['decision'], st['reason']))
    print('  interval  every %ss (%s)' % (st['interval'], st['interval_source']))
    if st['lock_held']:
        print('  lock      held by pid %s since %s' % (st['lock'].get('pid'),
                                                       fmt_ts(st['lock'].get('ts'))))
    elif st['lock'].get('pid'):
        print('  lock      stale file (pid %s not running) - the next run recovers it'
              % st['lock'].get('pid'))
    else:
        print('  lock      free')
    print('  log       %s (%d lines)' % (st['log_path'], st['log_lines']))
    return 0


# --------------------------------------------------------------------- pidlock
def pid_alive(pid):
    """True when pid is a running process. Never raises and never signals the target
    (os.kill(pid, 0) is a TerminateProcess call on Windows, so it is not used there)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except Exception:
            return False
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259                       # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    except Exception:
        return False


def acquire_lock(path=None, now=None, stale_after=LOCK_STALE_SECONDS, alive=None):
    """(ok, info): take the single-run pidlock, recovering a stale one.

    Stale = the pid recorded in the lock is not running, or the lock is older than stale_after
    seconds. ok=False means another live watch_save run holds it.
    """
    path = path or LOCK
    alive = alive or pid_alive
    now = int(now if now is not None else time.time())
    holder = dict(pid=os.getpid(), ts=now, script='watch_save.py',
                  started=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now)))
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        info = jload(path) or {}
        pid = info.get('pid')
        age = now - int(info.get('ts') or 0)
        try:
            dead = not alive(pid)
        except Exception:
            dead = True
        if dead or age > stale_after:
            why = 'dead pid' if dead else 'lock older than %ds' % stale_after
            holder['recovered'] = dict(pid=pid, age=age, why=why)
            try:
                write_lock(holder, path)
            except Exception as e:
                return False, dict(reason='stale lock not writable: %s' % str(e)[:80], pid=pid)
            return True, dict(reason='stale lock recovered (%s)' % why, stale_pid=pid,
                              stale_age=age)
        return False, dict(reason='another watch_save run is active', pid=pid, age=age)
    except OSError as e:
        return False, dict(reason='lock not writable: %s' % str(e)[:80])
    try:
        os.write(fd, json.dumps(holder).encode('utf-8'))
    finally:
        os.close(fd)
    return True, dict(reason='acquired', pid=os.getpid())


def write_lock(doc, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(doc, f)


def release_lock(path=None):
    """Drop the pidlock - only when this process owns it (never steals another run's)."""
    path = path or LOCK
    try:
        if int((jload(path) or {}).get('pid') or 0) == os.getpid():
            os.remove(path)
            return True
    except Exception:
        pass
    return False


def touch_lock(path=None, now=None):
    """Heartbeat the lock so a long daemon run never looks stale to a new start."""
    path = path or LOCK
    try:
        info = jload(path) or {}
        if int(info.get('pid') or 0) != os.getpid():
            return False
        write_lock(dict(info, ts=int(now if now is not None else time.time())), path)
        return True
    except Exception:
        return False


# ------------------------------------------------------------------------- loop
def loop(interval=None):
    """Daemon: one check per interval until ctrl-c (exit 0). The pidlock keeps a second run
    out; a failed refresh is logged and retried, never fatal. A config interval is re-read
    every tick, so a knob change takes effect without a restart."""
    ok, info = acquire_lock()
    if not ok:
        print("another watch_save run is active (pid %s, %ss old) - refusing to run"
              % (info.get('pid'), info.get('age')))
        return 3
    try:
        if info.get('stale_pid') is not None:
            print('stale lock recovered (pid %s, %ss old)'
                  % (info['stale_pid'], info.get('stale_age')))
            append_log(action_line('lock-recovered', None, note='stale pid %s' % info['stale_pid']))
        secs = interval
        src = '--interval'
        if secs is None:
            secs, src = interval_seconds()
        print('watch_save: watching %s every %ss via %s (settle %.0fs, pid %s, ctrl-c to stop)'
              % (SAVE, secs, src, SETTLE_SECONDS, os.getpid()))
        while True:
            if interval is None:
                secs, src = interval_seconds()
            try:
                res = check()
                if res['action'] != 'up-to-date':
                    say(res)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print('check error: %r' % (e,))
                append_log(action_line('check-error', None, note=str(e)[:120]))
            touch_lock()
            time.sleep(secs)
    except KeyboardInterrupt:
        print('watch_save stopped (ctrl-c) - lock released')
        return 0
    finally:
        release_lock()


# --------------------------------------------------------------------- selftest
def selftest():
    """Offline checks: stat/decide paths, the mid-write debounce, the same-mtime skip, a
    refresh failure that is logged but not fatal, the pidlock and the interval knob. tmp
    fixtures only - the real save, the repo's data/ directory and the network are untouched
    (the 'refresh' used here is a stub script)."""
    checks, fails = [], []
    saved = {}
    env_saved = {k: os.environ.get(k) for k in ('WFM_CONFIG', 'WFM_WATCH_DATA')}

    def chk(name, got, want):
        checks.append(name)
        if got != want:
            fails.append('%s: got %r, want %r' % (name, got, want))

    def ok(name, cond, detail=''):
        checks.append(name)
        if not cond:
            fails.append('%s: %s' % (name, detail or 'failed'))

    def touch(path, data=b'x', mtime=None):
        with open(path, 'wb') as f:
            f.write(data)
        if mtime is not None:
            os.utime(path, (mtime, mtime))

    def stub(rc, body=''):
        """A stand-in for refresh.py that prints one line and exits with `rc`."""
        p = os.path.join(td, 'stub_refresh_%s_%s.py'
                         % (rc, abs(hash(body)) % 100000))
        with open(p, 'w', encoding='utf-8') as f:
            f.write('%s\nprint("stub refresh ok")\nraise SystemExit(%s)\n' % (body, rc))
        return p

    td = tempfile.mkdtemp(prefix='watch_save_selftest_')
    try:
        for name in ('SAVE', 'STATE', 'LOG', 'LOCK', 'REFRESH', 'PYTHON', 'DATA', 'AF',
                     'LOG_MAX_BYTES'):
            saved[name] = globals()[name]
        globals()['DATA'] = os.path.join(td, 'data')
        globals()['SAVE'] = os.path.join(td, 'lastData.dat')
        globals()['STATE'] = os.path.join(DATA, 'watch_save_state.json')
        globals()['LOG'] = os.path.join(DATA, 'watch_save.log')
        globals()['LOCK'] = os.path.join(DATA, 'watch_save.lock')
        globals()['REFRESH'] = stub(0)
        globals()['PYTHON'] = sys.executable
        os.environ.pop('WFM_CONFIG', None)

        # --- save_stat ---
        chk('stat: missing save -> None', save_stat(), None)
        touch(SAVE, b'abc', mtime=1000.0)
        chk('stat: (mtime, size) of the save', save_stat(), (1000.0, 3))
        touch(SAVE, b'abcdef', mtime=1000.0)
        chk('stat: size change alone is visible', save_stat(), (1000.0, 6))

        # --- decide ---
        chk('decide: missing -> missing', decide({}, None, 5000)[0], 'missing')
        chk('decide: never seen, settled -> refresh', decide({}, (1000.0, 6), 1005)[0], 'refresh')
        a, why = decide({}, (1000.0, 6), 1001)
        chk('decide: fresh mtime -> settling', a, 'settling')
        ok('decide: settling says why', 'settles' in why)
        chk('decide: exactly at the settle edge -> refresh', decide({}, (1000.0, 6), 1003)[0],
            'refresh')
        chk('decide: processed pair -> up-to-date',
            decide({'mtime': 1000.0, 'size': 6}, (1000.0, 6), 9999)[0], 'up-to-date')
        chk('decide: same mtime, new size -> refresh',
            decide({'mtime': 1000.0, 'size': 6}, (1000.0, 7), 9999)[0], 'refresh')
        chk('decide: processed then reverted mtime -> refresh',
            decide({'mtime': 900.0, 'size': 6}, (1000.0, 6), 9999)[0], 'refresh')
        failed = {'last_attempt': dict(mtime=1000.0, size=6, ts=1000, rc=7)}
        chk('decide: failed change inside the backoff -> retry-wait',
            decide(failed, (1000.0, 6), 1030)[0], 'retry-wait')
        chk('decide: failed change after the backoff -> refresh',
            decide(failed, (1000.0, 6), 1061)[0], 'refresh')
        chk('decide: a *successful* attempt is not a backoff',
            decide({'last_attempt': dict(mtime=1.0, size=1, ts=1000, rc=0)},
                   (1000.0, 6), 1030)[0], 'refresh')

        # --- mid-write debounce: keep the mtime moving, nothing may act ---
        acts = []
        for bump in (1000.0, 1001.5, 1002.5, 1003.5):
            touch(SAVE, b'x' * 10, mtime=bump)
            acts.append(decide({}, save_stat(), bump + 2)[0])
        chk('debounce: 4 polls while the write is live all settle', acts,
            ['settling'] * 4)
        chk('debounce: the first check after the writes stop refreshes',
            decide({}, save_stat(), 1003.5 + SETTLE_SECONDS)[0], 'refresh')

        # --- the same-mtime skip, end to end through check() ---
        touch(SAVE, b'y' * 20, mtime=2000.0)
        res = check(now=2005)
        chk('check: a settled change refreshes', (res['action'], res['rc']), ('refresh', 0))
        ok('check: refresh output is kept', 'stub refresh ok' in (res.get('output') or ''))
        st = jload(STATE)
        chk('check: state records the processed pair', (st['mtime'], st['size']), (2000.0, 20))
        chk('check: state records the rc and duration',
            (st['rc'], st['duration']), (0, round(res['duration'], 2)))
        again = check(now=2010)
        chk('check: the same mtime is skipped', again['action'], 'up-to-date')
        chk('check: the skip writes no log line', sum(1 for _ in open(LOG, encoding='utf-8')), 1)
        chk('check: no tmp file is left behind', [f for f in os.listdir(DATA)
                                                  if f.startswith('.watch_save')], [])
        touch(SAVE, b'y' * 21, mtime=2000.0)
        chk('check: a new size under the same mtime refreshes', check(now=2010)['action'],
            'refresh')

        # --- a failing refresh is logged and never fatal ---
        globals()['REFRESH'] = stub(7)
        touch(SAVE, b'z' * 30, mtime=3000.0)
        res = check(now=3005)
        chk('failure: the check still returns', (res['action'], res['rc']), ('refresh', 7))
        chk('failure: not ok, but not raised', res.get('ok'), False)
        st = jload(STATE)
        chk('failure: the state keeps the last *good* pair', (st['mtime'], st['size']), (2000.0, 21))
        chk('failure: the failed attempt is recorded for the backoff',
            (st['last_attempt']['rc'], st['last_attempt']['mtime']), (7, 3000.0))
        log = open(LOG, encoding='utf-8').read().rstrip('\n').split('\n')
        ok('failure: the log line carries mtime, duration and rc',
           'rc 7' in log[-1] and '3000.000' in log[-1] and 's |' in log[-1])
        chk('failure: the next check backs off', check(now=3010)['action'], 'retry-wait')
        chk('failure: after the backoff it retries', check(now=3005 + RETRY_SECONDS)['action'],
            'refresh')
        chk('failure: the retry is logged too',
            sum(1 for _ in open(LOG, encoding='utf-8')), 4)

        # --- a timeout and a missing interpreter are outcomes, not crashes ---
        slow = stub(0, body='import time\ntime.sleep(5)')
        rc, dur, tail = run_refresh(script=slow, timeout=0.4)
        chk('timeout: reported as rc timeout', rc, 'timeout')
        ok('timeout: the tail says what happened', 'did not finish' in tail)
        rc, _dur, tail = run_refresh(py=os.path.join(td, 'no-such-python.exe'))
        chk('spawn-failed: a missing interpreter is reported', rc, 'spawn-failed')
        ok('spawn-failed: the tail names the command', 'no-such-python.exe' in tail)

        # --- the log line / rotation ---
        line = action_line('refresh', (1000.5, 42), duration=2.13, rc=0)
        ok('log line: exactly one line', '\n' not in line)
        ok('log line: mtime, duration and rc are on it',
           'mtime 1000.500' in line and '2.13s' in line and 'rc 0' in line)
        chk('log line: fixed field order', line.split(' | ')[1], 'refresh')
        globals()['LOG_MAX_BYTES'] = 200
        with open(LOG, 'w', encoding='utf-8') as f:
            f.writelines('old line %03d\n' % i for i in range(LOG_KEEP_LINES + 50))
        append_log('newest line')
        kept = [x for x in open(LOG, encoding='utf-8').read().split('\n') if x]
        ok('log rotation: the newest line survives at the end', kept[-1] == 'newest line')
        chk('log rotation: the file shrinks to the kept tail', len(kept), LOG_KEEP_LINES + 1)
        chk('log rotation: the oldest lines were dropped', kept[0], 'old line 050')
        globals()['LOG_MAX_BYTES'] = saved['LOG_MAX_BYTES']

        # --- pidlock ---
        lock = os.path.join(td, 'lock_test.lock')
        good, info = acquire_lock(lock, now=1000)
        chk('lock: acquired', (good, info['reason']), (True, 'acquired'))
        chk('lock: records our pid', (jload(lock) or {}).get('pid'), os.getpid())
        good, info = acquire_lock(lock, now=1001, alive=lambda pid: True)
        chk('lock: refuses a live holder', (good, info['reason']),
            (False, 'another watch_save run is active'))
        chk('lock: the refusal names the holder', info.get('pid'), os.getpid())
        chk('lock: heartbeat by its owner', touch_lock(lock, now=1002), True)
        chk('lock: the heartbeat moved ts', (jload(lock) or {}).get('ts'), 1002)
        chk('lock: released by its owner', release_lock(lock), True)
        chk('lock: gone after release', os.path.exists(lock), False)
        chk('lock: release without a lock is a no-op', release_lock(lock), False)
        write_lock({'pid': 999999, 'ts': 1000}, lock)
        good, info = acquire_lock(lock, now=1002, alive=lambda pid: False)
        ok('lock: stale (dead pid) recovered', good and info.get('stale_pid') == 999999)
        chk('lock: the recovered lock is ours', (jload(lock) or {}).get('pid'), os.getpid())
        write_lock({'pid': 4242, 'ts': 1000}, lock)
        good, info = acquire_lock(lock, now=1000 + LOCK_STALE_SECONDS + 1, alive=lambda pid: True)
        ok('lock: stale (too old) recovered', good and 'older' in str(info.get('reason')))
        write_lock({'pid': 4242, 'ts': 2000}, lock)
        chk('lock: a fresh live lock is still refused',
            acquire_lock(lock, now=2001, alive=lambda pid: True)[0], False)
        chk('lock: heartbeat refuses a lock it does not own', touch_lock(lock, now=1), False)
        release_lock(lock)
        chk('pid_alive(self)', pid_alive(os.getpid()), True)
        chk('pid_alive(0)', pid_alive(0), False)
        chk('pid_alive(None)', pid_alive(None), False)

        # --- the interval knob ---
        cfgp = os.path.join(td, 'config.json')
        os.environ['WFM_CONFIG'] = cfgp
        chk('interval: missing config -> the default', interval_seconds(), (20, 'config'))
        with open(cfgp, 'w', encoding='utf-8') as f:
            json.dump({'port': 8787, 'watch_save_seconds': 45}, f)
        chk('interval: the knob is honoured', interval_seconds(), (45, 'config'))
        with open(cfgp, 'w', encoding='utf-8') as f:
            json.dump({'watch_save_seconds': 999}, f)
        chk('interval: out of range -> the default', interval_seconds(), (20, 'config'))
        with open(cfgp, 'w', encoding='utf-8') as f:
            f.write('{"watch_save_seconds": 4, "port": 8787,')
        chk('interval: a corrupt config -> the default', interval_seconds(), (20, 'config'))
        chk('interval: the range matches the knob', (INTERVAL_MIN, INTERVAL_MAX, DEFAULT_INTERVAL),
            (5, 600, 20))

        # --- status reads, and never acts ---
        st = status()
        chk('status: reports the decision without acting', st['decision'] in
            ('refresh', 'up-to-date', 'settling'), True)
        ok('status: carries the paths and the lock state',
           st['save'] == SAVE and st['state_path'] == STATE and st['lock_held'] is False)
        chk('status: the interval comes from the config engine', st['interval_source'], 'config')
        before = sorted(os.listdir(DATA))
        status()
        chk('status: writes nothing', sorted(os.listdir(DATA)), before)

        # --- decide() is pure: a status probe must not change the state file ---
        blob = open(STATE, 'rb').read()
        decide(jload(STATE) or {}, save_stat(), time.time())
        chk('decide: leaves the state file byte-identical', open(STATE, 'rb').read(), blob)
    finally:
        for name, value in saved.items():
            globals()[name] = value
        for key, value in env_saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import shutil
        shutil.rmtree(td, ignore_errors=True)

    for f in fails:
        print('FAIL %s' % f)
    bad = len(fails)
    print('selftest: %s %d/%d checks passed' % ('FAIL' if bad else 'all', len(checks) - bad,
                                                len(checks)))
    return 1 if bad else 0


# ------------------------------------------------------------------------- cli
def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Watch the AlecaFrame save; refresh owned.json when the game rewrites it.')
    ap.add_argument('--loop', action='store_true', help='daemon: poll until ctrl-c (the default)')
    ap.add_argument('--once', action='store_true', help='one check now (cron / the run queue)')
    ap.add_argument('--status', action='store_true', help='print state + last action, do no work')
    ap.add_argument('--selftest', action='store_true', help='offline checks on tmp fixtures')
    ap.add_argument('--interval', type=int, default=None, metavar='SECONDS',
                    help='poll override for this run (%d..%d)' % (INTERVAL_MIN, INTERVAL_MAX))
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.interval is not None and not (INTERVAL_MIN <= a.interval <= INTERVAL_MAX):
        print('error: --interval expects %d..%d seconds (got %s)'
              % (INTERVAL_MIN, INTERVAL_MAX, a.interval), file=sys.stderr)
        return 2
    if a.status:
        return status_cmd()
    if not a.once:
        return loop(interval=a.interval)          # loop() takes the pidlock itself

    ok, info = acquire_lock()
    if not ok:
        print("another watch_save run is active (pid %s, %ss old) - refusing to run"
              % (info.get('pid'), info.get('age')))
        return 3
    try:
        if info.get('stale_pid') is not None:
            print('stale lock recovered (pid %s, %ss old)'
                  % (info['stale_pid'], info.get('stale_age')))
            append_log(action_line('lock-recovered', None, note='stale pid %s' % info['stale_pid']))
        res = check()
        say(res)
        return 1 if (res['action'] == 'refresh' and res.get('rc') != 0) else 0
    finally:
        release_lock()


if __name__ == '__main__':
    sys.exit(main())
