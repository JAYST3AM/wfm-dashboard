"""scripts/tray.py: icon bytes, menu map, kill-switch read, CLI contract.

tray.py is stdlib-only and every Win32 call sits behind `os.name == 'nt'` plus a lazy DLL
load, so the byte/menu/state helpers are asserted on any platform (this suite runs on Linux
in CI) while the shell pieces are skipped off-Windows. The module is loaded by path via
conftest.load_script and importing it must stay inert: no DLL, no window, no subprocess, and
no writes - the repo's real data/ directory is never touched (KILL_SWITCH_PATH points every
state read at tmp_path).
"""
import ast
import os
import struct
import subprocess
import sys
import threading
import time
import zlib

import pytest

from conftest import SCRIPTS, load_script, write_json

TRAY_SRC = os.path.join(SCRIPTS, 'tray.py')
MODULE_IMPORTS = {'argparse', 'ctypes', 'json', 'os', 'shutil', 'struct', 'subprocess',
                  'sys', 'tempfile', 'threading', 'time', 'webbrowser', 'zlib'}
PRIVATE_TRADER = {'killswitch', 'lister', 'detector', 'limits', 'wfm_session'}
WIN_ONLY = pytest.mark.skipif(os.name != 'nt', reason='the tray widget is Windows-only')
NOT_WIN = pytest.mark.skipif(os.name == 'nt', reason='the non-Windows guard only fires there')


@pytest.fixture
def tray():
    return load_script('tray')


@pytest.fixture
def ks(tmp_path, monkeypatch):
    """Kill-switch state file in tmp_path, wired in through the env var killswitch.py reads."""
    path = tmp_path / 'data' / 'kill_switch.json'
    path.parent.mkdir()
    monkeypatch.setenv('KILL_SWITCH_PATH', str(path))
    return path


def module_imports(src):
    names = set()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Import):
            names.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split('.')[0])
    return names


# ------------------------------------------------------------------------ import contract

def test_importing_the_module_is_inert(tray):
    assert tray.loaded_libs() == []                    # nothing was loaded at import time
    assert tray._TRAY_CREATED is False                 # no tray was ever created
    assert tray.LOG_PATH == ''
    assert (tray.Tray is None) is (os.name != 'nt')    # the shell class exists only on Windows


def test_module_level_imports_are_stdlib_only():
    names = module_imports(open(TRAY_SRC, encoding='utf-8').read())

    assert names <= MODULE_IMPORTS
    assert 'ctypes' in names and 'subprocess' in names


def test_the_private_trader_scripts_are_never_imported():
    src = open(TRAY_SRC, encoding='utf-8').read()

    assert not module_imports(src) & PRIVATE_TRADER
    assert not [n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.Import) and n.names[0].name in PRIVATE_TRADER]
    assert 'killswitch.py' in src                      # they are run as subprocesses instead
    assert "'kill_switch.json'" in src


# ------------------------------------------------------------------------- icon bytes

def test_ico_is_one_32x32_png_image(tray):
    ico = tray.ico_bytes()

    reserved, kind, count = struct.unpack('<HHH', ico[:6])
    assert (reserved, kind, count) == (0, 1, 1)       # ICONDIR: 0, 1 (icon), one image
    w, h, colors, res, planes, bpp, nbytes, offset = struct.unpack('<BBBBHHII', ico[6:22])
    assert (w, h, colors, res, planes, bpp) == (32, 32, 0, 0, 1, 32)
    assert offset == 22 and nbytes == len(ico) - 22 and nbytes > 0
    assert ico[22:30] == b'\x89PNG\r\n\x1a\n'          # the payload really is a PNG


def test_a_256px_image_is_recorded_as_zero(tray):
    assert tray.ico_bytes(256)[6:8] == b'\x00\x00'     # the .ico spec's escape for 256
    assert tray.parse_ico(tray.ico_bytes(256))['width'] == 256


def test_png_payload_is_a_walkable_32x32_rgba_png(tray):
    png = tray.ico_bytes()[22:]
    chunks, pos, ihdr, idat = [], 8, None, b''
    while pos + 8 <= len(png):
        length = struct.unpack('>I', png[pos:pos + 4])[0]
        tag, body = png[pos + 4:pos + 8], png[pos + 8:pos + 8 + length]
        crc = struct.unpack('>I', png[pos + 8 + length:pos + 12 + length])[0]
        assert zlib.crc32(tag + body) & 0xFFFFFFFF == crc, tag
        chunks.append(tag)
        if tag == b'IHDR':
            ihdr = body
        if tag == b'IDAT':
            idat += body
        pos += 12 + length

    assert pos == len(png) and chunks == [b'IHDR', b'IDAT', b'IEND']
    width, height, depth, color, comp, filt, interlace = struct.unpack('>IIBBBBB', ihdr)
    assert (width, height, depth, color, comp, filt, interlace) == (32, 32, 8, 6, 0, 0, 0)
    raw = zlib.decompress(idat)
    assert len(raw) == 32 * (1 + 32 * 4)               # 32 filter-0 scanlines of RGBA
    assert all(raw[i * 129] == 0 for i in range(32))

    parsed = tray.parse_png(png)
    assert parsed['width'] == 32 and parsed['colortype'] == 6 and parsed['raw'] == raw


def test_parsers_reject_corrupt_input(tray):
    ico, png = tray.ico_bytes(), tray.ico_bytes()[22:]

    with pytest.raises(ValueError):
        tray.parse_ico(ico[:10])
    with pytest.raises(ValueError):
        tray.parse_png(png[:50] + bytes([png[50] ^ 0xFF]) + png[51:])   # CRC guard is live
    with pytest.raises(ValueError):
        tray.parse_png(b'not a png at all')


def test_pixels_draw_an_accent_diamond_on_a_dark_disc(tray):
    rows = tray.icon_pixels()
    px = lambda x, y: tuple(rows[y][x * 4:x * 4 + 4])               # noqa: E731

    assert len(rows) == 32 and all(len(r) == 32 * 4 for r in rows)
    assert px(16, 16) == tray.ACCENT_OFF + (255,)                   # diamond centre
    assert px(0, 0)[3] == px(31, 31)[3] == 0                        # transparent corners
    assert px(16, 5) == tray.DISC + (255,)                          # dark disc ring
    assert px(16, 2) == tuple(int(c * 0.55) for c in tray.ACCENT_OFF) + (255,)   # the rim
    assert px(10, 16)[:3] == tray.ACCENT_OFF and px(4, 16)[:3] != tray.ACCENT_OFF


def test_the_armed_variant_repaints_the_diamond(tray):
    off, armed = tray.icon_pixels(32, tray.ACCENT_OFF), tray.icon_pixels(32, tray.ACCENT_ARMED)

    assert tuple(armed[16][64:67]) == tray.ACCENT_ARMED
    assert off != armed
    assert tray.ACCENT_ARMED != tray.ACCENT_OFF


# -------------------------------------------------------------------------------- menu

def test_menu_lists_the_five_commands_in_order(tray):
    labels = [label for _cid, label, _en in tray.menu_items(False) if label]

    assert labels == ['Open dashboard', 'Rebuild plan (lister)', 'Run detector',
                      'Kill switch: arm', 'Quit tray']


def test_the_kill_switch_label_follows_the_state(tray):
    armed = next(row for row in tray.menu_items(True) if row[0] == tray.MENU_KILL)
    off = next(row for row in tray.menu_items(False) if row[0] == tray.MENU_KILL)

    assert armed[1] == 'Kill switch: disarm (ARMED)' and off[1] == 'Kill switch: arm'


def test_every_command_row_maps_to_an_action(tray):
    rows = [row for row in tray.menu_items(False) if row[0] != tray.MENU_SEPARATOR]
    ids = [cid for cid, _l, _e in rows]

    assert sorted(ids) == sorted(tray.ACTIONS)
    assert len(set(ids)) == len(ids)
    assert all(enabled for _c, _l, enabled in rows)
    assert [tray.action_for(i) for i in ids] == [tray.ACTIONS[i] for i in ids]


def test_separators_and_junk_ids_have_no_action(tray):
    separators = [row for row in tray.menu_items(True) if row[0] == tray.MENU_SEPARATOR]

    assert len(separators) == 2 and all(row[1] is None for row in separators)
    assert tray.action_for(tray.MENU_SEPARATOR) is None
    assert tray.action_for(99) is None and tray.action_for(None) is None


def test_tooltip_tracks_the_state_and_fits_the_notifyicondata_buffer(tray):
    assert 'ARMED' in tray.tip_text(True) and 'off' in tray.tip_text(False)
    assert len(tray.tip_text(True)) < 128


def test_tray_callback_lparam_decodes_for_v3_v4_and_v0(tray):
    assert tray.tray_event((1 << 16) | tray.WM_RBUTTONUP) == tray.WM_RBUTTONUP   # v3/v4 packed
    assert tray.tray_event(tray.WM_LBUTTONUP) == tray.WM_LBUTTONUP               # v0 raw
    assert tray.tray_event(0x4242) == 0x4242                                     # unknown passes


# -------------------------------------------------------------------------- kill switch

def make_gate(tray, release=None):
    """KillSwitchGate wired to a stub runner: -> (gate, calls, done). No process, no window."""
    calls, done = [], []
    release = release or threading.Event()

    def runner(target):
        calls.append(target)
        release.wait(10)
        return {'ok': True, 'code': 0, 'cmd': ['stub'], 'tail': '', 'error': None}

    def on_done(target, result):
        done.append(target)

    return tray.KillSwitchGate(runner, on_done), calls, done


def wait_until(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return bool(pred())


def test_gate_runs_a_command_for_an_idle_request(tray):
    gate, calls, _done = make_gate(tray)

    assert gate.request(True) is True
    assert wait_until(lambda: bool(calls))
    assert calls == [True] and gate.busy is True and gate.pending is None


def test_gate_never_drops_a_click_during_a_run(tray):
    release = threading.Event()
    gate, calls, done = make_gate(tray, release)

    gate.request(True)
    assert wait_until(lambda: bool(calls))
    assert gate.request(False) is False            # queued behind the live command
    assert gate.pending is False
    assert gate.request(True) is False             # the newest click replaces it
    assert gate.pending is True
    release.set()
    assert wait_until(lambda: len(done) == 2)
    assert calls == [True, True]                   # the superseded click never ran
    assert done == [True, True] and gate.busy is False and gate.pending is None


def test_gate_serialises_the_runs(tray):
    """Runs must never overlap: the CLI writes one state file."""
    live, overlap, guard = [], [], threading.Lock()
    release = threading.Event()

    def runner(target):
        with guard:
            live.append(target)
            if len(live) > 1:
                overlap.append(target)
        release.wait(10)
        with guard:
            live.pop()
        return {'ok': True, 'code': 0, 'cmd': ['stub'], 'tail': '', 'error': None}

    gate = tray.KillSwitchGate(runner, lambda t, r: None)
    gate.request(True)
    assert wait_until(lambda: bool(live))
    gate.request(False)
    release.set()

    assert wait_until(lambda: not gate.busy)
    assert overlap == [] and live == []


def test_absent_state_file_reads_as_off_and_is_not_created(tray, ks):
    state = tray.read_kill_switch()

    assert state == {'active': False, 'note': '', 'ts': 0, 'source': 'absent', 'error': None}
    assert not ks.exists()                             # the tray is a read-only observer


def test_armed_state_file_is_reported_with_note_and_ts(tray, ks):
    write_json(ks, {'active': True, 'note': 'hold the line', 'ts': 1790000000})

    state = tray.read_kill_switch()

    assert state['active'] is True and state['note'] == 'hold the line'
    assert state['ts'] == 1790000000 and state['source'] == 'file' and state['error'] is None


def test_disarmed_state_file_reads_as_off(tray, ks):
    write_json(ks, {'active': False, 'note': '', 'ts': 1790000001})

    assert tray.read_kill_switch()['active'] is False


def test_unreadable_or_parsed_state_is_fail_closed_armed(tray, ks):
    for payload in ('{ not json', '{"active": "yes"}', '["nope"]', '{"note": "no active key"}'):
        ks.write_text(payload, encoding='utf-8')
        state = tray.read_kill_switch()
        assert state['active'] is True, payload        # a broken switch never reads as off
        assert state['source'] == 'fail_closed' and state['error'], payload


def test_an_explicit_path_wins_over_the_environment(tray, ks, tmp_path):
    write_json(ks, {'active': True})
    other = tmp_path / 'other.json'
    write_json(other, {'active': False})

    assert tray.read_kill_switch()['active'] is True
    assert tray.read_kill_switch(str(other))['active'] is False


def test_kill_switch_path_env_var_matches_the_module_default_name(tray, ks, monkeypatch):
    monkeypatch.delenv('KILL_SWITCH_PATH', raising=False)

    assert tray._kill_path() == tray.KILL_SWITCH_PATH
    assert tray.KILL_SWITCH_PATH.replace('\\', '/').endswith('data/kill_switch.json')
    monkeypatch.setenv('KILL_SWITCH_PATH', str(ks))
    assert tray._kill_path() == str(ks)


# ------------------------------------------------------------------------------ commands

def test_engines_run_through_pythonw_and_the_trader_scripts(tray):
    lister, detector = tray.engine_command('lister'), tray.engine_command('detector')

    assert lister[1].replace('\\', '/').endswith('scripts/trader/lister.py')
    assert detector[1].replace('\\', '/').endswith('scripts/trader/detector.py')
    if os.name == 'nt':
        assert os.path.basename(lister[0]).lower() == 'pythonw.exe'
        assert os.path.basename(tray.killswitch_command(True)[0]).lower() == 'python.exe'


def test_killswitch_argv_uses_its_on_off_cli(tray):
    arm, disarm = tray.killswitch_command(True), tray.killswitch_command(False)

    assert arm[1].replace('\\', '/').endswith('scripts/trader/killswitch.py')
    assert '--on' in arm and '--off' not in arm
    assert '--off' in disarm and '--on' not in disarm
    assert arm[-2] == '--note' and arm[-1] == tray.KILL_SWITCH_NOTE


def test_python_paths_prefer_siblings_but_fall_back(tray):
    assert tray.pythonw_path('C:/py/pythonw.exe').replace('\\', '/') == 'C:/py/pythonw.exe'
    missing = 'C:/definitely-not-here/python.exe'
    assert tray.pythonw_path(missing) == missing and tray.python_path(missing) == missing


def test_dashboard_url_defaults_and_honours_wfm_port(tray, monkeypatch):
    monkeypatch.delenv('WFM_PORT', raising=False)
    assert tray.dashboard_url() == 'http://127.0.0.1:8787/'

    monkeypatch.setenv('WFM_PORT', '8899')
    assert tray.dashboard_url() == 'http://127.0.0.1:8899/'

    for junk in ('0', 'garbage', ''):
        monkeypatch.setenv('WFM_PORT', junk)
        assert tray.dashboard_url() == 'http://127.0.0.1:8787/'


def test_spawning_a_missing_engine_never_raises(tray, monkeypatch, tmp_path):
    monkeypatch.setattr(tray, 'TRADER_DIR', str(tmp_path / 'nowhere'))

    result = tray.spawn_engine('lister')

    assert result['ok'] is False and 'missing' in result['error'] and result['pid'] is None


def test_a_broken_killswitch_interpreter_is_reported_not_raised(tray, monkeypatch):
    monkeypatch.setattr(tray, 'python_path', lambda exe=None: 'C:/definitely-not-here/python.exe')

    result = tray.run_killswitch(True)

    assert result['ok'] is False and result['error'] and result['code'] is None
    assert '--on' in result['cmd']


def test_say_survives_pythonw_and_can_tee_to_a_log(tray, monkeypatch, tmp_path):
    log = tmp_path / 'tray.log'
    monkeypatch.setattr(tray, 'LOG_PATH', '')
    saved = sys.stdout
    try:
        sys.stdout = None                              # exactly what pythonw hands us
        tray.say('this must not raise')
    finally:
        sys.stdout = saved

    monkeypatch.setattr(tray, 'LOG_PATH', str(log))
    tray.say('logged line')

    assert 'logged line' in log.read_text(encoding='utf-8')


# ---------------------------------------------------------------------------------- CLI

def run_cli(*args, timeout=180):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    return subprocess.run([sys.executable, TRAY_SRC] + list(args), cwd=os.path.dirname(SCRIPTS),
                          capture_output=True, text=True, timeout=timeout, env=env,
                          encoding='utf-8', errors='replace')


def test_selftest_cli_passes_and_writes_nothing():
    before = os.path.exists(os.path.join(os.path.dirname(SCRIPTS), 'data'))
    proc = run_cli('--selftest')

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert 'selftest:' in proc.stdout and '0 failed' in proc.stdout
    assert 'FAIL' not in proc.stdout
    assert os.path.exists(os.path.join(os.path.dirname(SCRIPTS), 'data')) == before


def test_selftest_main_returns_zero_in_process(tray, capsys):
    assert tray.main(['--selftest']) == 0

    out = capsys.readouterr().out
    assert 'selftest:' in out and 'no tray, no DLL, no subprocess, no network' in out


def test_help_lists_the_flags(tray, capsys):
    with pytest.raises(SystemExit) as exc:
        tray.main(['--help'])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert '--selftest' in out and '--smoke' in out


@NOT_WIN
def test_smoke_refuses_to_run_without_windows():
    proc = run_cli('--smoke')

    assert proc.returncode == 1
    assert 'needs Windows' in proc.stdout


@WIN_ONLY
@pytest.mark.skipif(not os.environ.get('WFM_TRAY_SMOKE'),
                    reason='opt-in: pops a real tray icon (WFM_TRAY_SMOKE=1)')
def test_smoke_creates_and_removes_a_real_tray():
    proc = run_cli('--smoke', '--smoke-ms', '1500')

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert 'the icon is in the notification area' in proc.stdout
    assert 'CreateIconFromResourceEx(png)' in proc.stdout
    assert 'stopped (clean)' in proc.stdout


@WIN_ONLY
def test_smoke_only_autoquits_after_the_requested_delay(tray):
    args = tray.build_parser().parse_args(['--smoke', '--smoke-ms', '1500'])

    assert args.smoke is True and args.smoke_ms == 1500
    assert tray.build_parser().parse_args(['--smoke']).smoke_ms == tray.SMOKE_MS
