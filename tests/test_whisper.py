"""scripts/whisper.py: the whisper line, the Windows seams, the gates and the ledger.

whisper.py keeps the Win32 half behind `os.name == 'nt'` plus a lazy DLL load, so the
message, window-selection, gate and ledger logic is asserted on any platform (this suite
runs on Linux in CI) while the clipboard and the keystrokes are exercised with fakes - and
on Windows, for the clipboard, once for real. The real data/ files are never read or
written: every path global is pointed at tmp_path.

Nothing here types a key: `press_paste_and_enter` is tested through a fake user32 whose
SendInput records the batches, and send() is tested with find_game/copy/focus swapped for
stubs. The keystroke sequence itself is asserted exactly (Ctrl down, V down, V up, Ctrl up,
then Return down, Return up) because that sequence is the whole point of the module.
"""
import ast
import os
import subprocess
import sys

import pytest

from conftest import SCRIPTS, load_script, read_json, write_json

WHISPER_SRC = os.path.join(SCRIPTS, 'whisper.py')
MODULE_IMPORTS = {'argparse', 'contextlib', 'ctypes', 'io', 'json', 'os', 're', 'shutil',
                  'subprocess', 'sys', 'tempfile', 'time'}
PRIVATE_TRADER = {'killswitch', 'lister', 'detector', 'limits', 'wfm_session', 'auto'}
WIN_ONLY = pytest.mark.skipif(os.name != 'nt', reason='the whisper sender is Windows-only')
NOT_WIN = pytest.mark.skipif(os.name == 'nt', reason='the non-Windows guard only fires there')

BUY = 'Hi! I want to buy: "Primed Continuity" for 120 platinum. (warframe.market)'
BUY_R0 = ('Hi! I want to buy: "Primed Continuity (rank 0)" for 120 platinum. (warframe.market)')
SELL = 'Hi! I am selling: "Neo D3 Relic" for 7 platinum. (warframe.market)'


@pytest.fixture
def whisper(tmp_path, monkeypatch):
    """Fresh module object per test, with every path global inside tmp_path."""
    mod = load_script('whisper', monkeypatch=monkeypatch)
    data = tmp_path / 'data'
    data.mkdir()
    monkeypatch.setattr(mod, 'ROOT', str(tmp_path))
    monkeypatch.setattr(mod, 'DATA', str(data))
    monkeypatch.setattr(mod, 'LOG_PATH', str(data / 'whisper_log.json'))
    monkeypatch.setattr(mod, 'STATE_PATH', str(data / 'trader_state.json'))
    monkeypatch.setattr(mod, 'FOCUS_SETTLE', 0.0)          # no sleeping in tests
    monkeypatch.setattr(mod, 'PASTE_GAP', 0.0)
    monkeypatch.setattr(mod, 'CLIP_WAIT', 0.0)
    mod.reset()
    return mod


class FakeClock:
    """Stands in for whisper.clock() - the gates are pure arithmetic on it."""

    def __init__(self, start=5000.0):
        self.t = float(start)

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += float(seconds)
        return self.t


class FakeUser32:
    """Records SendInput batches; enough of user32 for press_paste_and_enter()."""

    def __init__(self, foreground=None, clipboard_ok=True):
        self.batches = []
        self.foreground = foreground
        self.clipboard_ok = clipboard_ok
        self.opened = 0

    def SendInput(self, count, batch, size):
        self.batches.append([(int(batch[i].u.ki.wVk), int(batch[i].u.ki.dwFlags))
                             for i in range(count)])
        return count

    def GetForegroundWindow(self):
        return self.foreground

    def IsIconic(self, hwnd):
        return False

    def ShowWindow(self, hwnd, mode):
        return True

    def BringWindowToTop(self, hwnd):
        return True

    def SetForegroundWindow(self, hwnd):
        return True

    def GetWindowThreadProcessId(self, hwnd, _pid):
        return 77

    def AttachThreadInput(self, first, second, attach):
        return True

    def OpenClipboard(self, hwnd):
        self.opened += 1
        return bool(self.clipboard_ok)


class FakeThreads:
    def GetCurrentThreadId(self):
        return 42


def win_seams(whisper, monkeypatch, focus=True, keys=6, copied=True, hwnd=4242):
    """Swap the Windows seams of a send for stubs; returns the call log."""
    calls = []
    monkeypatch.setattr(whisper, '_WIN', True)     # send() refuses off Windows before any seam; the
    monkeypatch.setattr(whisper, 'find_game', lambda: hwnd)   # fakes below stand in for Windows
    monkeypatch.setattr(whisper, 'copy', lambda text: calls.append(('copy', text)) or copied)
    monkeypatch.setattr(whisper, 'focus',
                        lambda handle: calls.append(('focus', handle)) or focus)
    monkeypatch.setattr(whisper, 'press_paste_and_enter',
                        lambda: calls.append(('keys',)) or keys)
    return calls


def module_imports(src):
    names = set()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Import):
            names.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split('.')[0])
    return names


# ------------------------------------------------------------------------- the message

def test_the_buying_and_selling_lines_are_the_warframe_market_wording(whisper):
    assert whisper.message('Primed Continuity', 120, 'buy') == BUY
    assert whisper.message('Neo D3 Relic', 7, 'sell') == SELL
    assert whisper.message('Primed Continuity', 120, 'buy').count('"') == 2   # quotes kept
    assert whisper.message('Primed Continuity', 120, 'buy').endswith('(warframe.market)')


@pytest.mark.parametrize('rank', [1, 10, '10', 10.0])
def test_the_rank_rides_inside_the_quotes_like_the_site(whisper, rank):
    """warframe.market's own copy button spells a ranked order '"<item> (rank N)"' and its Terms
    ask for that line used as-is, so the rank belongs inside the quoted name, before ' for'."""
    text = whisper.message('Primed Continuity', 120, 'sell', rank)

    assert '(rank %d)' % int(rank) in text
    assert text.index('(rank') < text.index(' for ')
    assert text.count('"') == 2 and text.endswith('(warframe.market)')   # untouched around it


def test_a_rank_10_line_is_exactly_the_sites_wording(whisper):
    assert whisper.message('Primed Continuity', 120, 'sell', 10) == (
        'Hi! I am selling: "Primed Continuity (rank 10)" for 120 platinum. (warframe.market)')


@pytest.mark.parametrize('rank', [0, '0', 0.0])
def test_rank_zero_shows_because_the_site_shows_it(whisper, rank):
    """'Necramech Flow (rank 0)' is what the site generates for an unranked mod - rank 0 is not
    the same as no rank, and the message has to match the generated one for the Terms cover."""
    assert whisper.message('Primed Continuity', 120, 'buy', rank) == BUY_R0


@pytest.mark.parametrize('rank', [None, '', 'x', -3, '  '])
def test_no_rank_at_all_means_no_suffix(whisper, rank):
    """A plain part is not ranked: the API sends rank null and the line stays bare."""
    assert whisper.message('Primed Continuity', 120, 'buy', rank) == BUY


def test_rank_10_and_rank_0_are_different_lines(whisper):
    assert (whisper.message('Primed Continuity', 120, 'buy', 10)
            != whisper.message('Primed Continuity', 120, 'buy', 0))
    assert whisper.message('Primed Continuity', 120, 'buy', 0) == BUY_R0


def test_line_carries_the_whisper_command_the_site_copies(whisper):
    assert whisper.line('Quersus_', 'Primed Continuity', 120, 'buy', 10) == (
        '/w Quersus_ Hi! I want to buy: "Primed Continuity (rank 10)" for 120 platinum. '
        '(warframe.market)')


@pytest.mark.parametrize('user', ['', '   ', None])
def test_line_refuses_a_missing_user(whisper, user):
    """Without a user the paste would land in whatever channel the chat box is on."""
    with pytest.raises(ValueError):
        whisper.line(user, 'Primed Continuity', 120, 'buy')


@pytest.mark.parametrize('kind,buying', [('buy', True), ('buying', True), ('WTB', True),
                                         ('sell', False), ('selling', False), ('wts', False)])
def test_kind_accepts_the_trade_shorthand(whisper, kind, buying):
    line = whisper.message('X', 5, kind)

    assert line == whisper.message('X', 5, 'buy' if buying else 'sell')
    assert ('I want to buy' in line) is buying


@pytest.mark.parametrize('kind', ['trade', 'both', '', None, 'wtt'])
def test_an_unknown_kind_raises_instead_of_guessing(whisper, kind):
    with pytest.raises(ValueError):
        whisper.message('X', 5, kind)


@pytest.mark.parametrize('price,expected', [(120, '120'), (120.0, '120'), ('120', '120'),
                                            (' 7 ', '7'), (7.5, '7.5'), ('0', '0')])
def test_price_shapes_land_in_the_line_verbatim(whisper, price, expected):
    assert '" for %s platinum. (warframe.market)' % expected in whisper.message('X', price, 'buy')


def test_the_item_name_is_trimmed_but_never_rewritten(whisper):
    assert whisper.message('  Primed Continuity ', 120, 'buy') == BUY
    assert whisper.message('MK1-Braton', 5, 'buy').count('MK1-Braton') == 1


@pytest.mark.parametrize('kind,rank', [('buy', None), ('sell', 0), ('buy', 10), ('sell', 3)])
def test_parse_round_trips_a_message(whisper, kind, rank):
    text = whisper.message('Primed Continuity', 120, kind, rank)

    parsed = whisper.parse(text)

    assert parsed == {'kind': kind, 'item': 'Primed Continuity', 'price': '120', 'rank': rank}


def test_parse_also_reads_the_w_line_the_site_copies(whisper):
    assert whisper.parse(whisper.line('Quersus_', 'Primed Continuity', 120, 'buy', 10)) == {
        'kind': 'buy', 'item': 'Primed Continuity', 'price': '120', 'rank': 10,
        'user': 'Quersus_'}


def test_parse_takes_the_old_outside_the_quotes_spelling_too(whisper):
    assert whisper.parse('Hi! I am selling: "Prime Continuity" rank 3 for 9 platinum. '
                         '(warframe.market)') == {
        'kind': 'sell', 'item': 'Prime Continuity', 'price': '9', 'rank': 3}


def test_parse_accepts_the_rank_inside_the_quotes_spelling_too(whisper):
    assert whisper.parse('Hi! I want to buy: "X rank 3" for 9 platinum. (warframe.market)') == {
        'kind': 'buy', 'item': 'X', 'price': '9', 'rank': 3}


@pytest.mark.parametrize('text', ['', '   ', 'hi', 'Hi! I want to buy: "X" for 9 platinum.',
                                  None, 42])
def test_parse_returns_an_empty_dict_for_anything_else(whisper, text):
    assert whisper.parse(text) == {}


def test_title_for_turns_a_slug_into_a_display_name(whisper):
    assert whisper.title_for('primed_continuity') == 'Primed Continuity'
    assert whisper.title_for('hildryn-prime-chassis-blueprint') == \
        'Hildryn Prime Chassis Blueprint'
    assert whisper.title_for('') == ''


# ------------------------------------------------------------------------ window picking

def test_find_game_matches_the_title_and_prefers_the_games_own_process(whisper, monkeypatch):
    monkeypatch.setattr(whisper, '_WIN', True)
    monkeypatch.setattr(whisper, 'windows', lambda: [
        (11, 'Warframe Market - Buy, Sell and Trade - Google Chrome', 900),
        (22, 'Warframe', 1000)])
    monkeypatch.setattr(whisper, 'process_name',
                        lambda pid: {900: 'chrome.exe', 1000: 'warframe.x64.exe'}[pid])

    assert whisper.find_game() == 22


def test_find_game_skips_browsers_and_the_launcher_even_on_a_title_match(whisper, monkeypatch):
    monkeypatch.setattr(whisper, '_WIN', True)
    monkeypatch.setattr(whisper, 'windows', lambda: [
        (11, 'warframe.market - Firefox', 900),
        (22, 'Warframe Launcher', 901),
        (33, 'Overwolf Warframe App', 902)])
    monkeypatch.setattr(whisper, 'process_name',
                        lambda pid: {900: 'firefox.exe', 901: 'warframelauncher.exe',
                                     902: 'overwolfbrowser.exe'}[pid])

    assert whisper.find_game() is None            # pasting into any of these would be worse


def test_find_game_falls_back_to_the_title_when_the_process_is_unreadable(whisper, monkeypatch):
    monkeypatch.setattr(whisper, '_WIN', True)
    monkeypatch.setattr(whisper, 'windows', lambda: [(22, 'Warframe', 1000)])
    monkeypatch.setattr(whisper, 'process_name', lambda pid: '')

    assert whisper.find_game() == 22


def test_find_game_ignores_windows_that_do_not_mention_warframe(whisper, monkeypatch):
    monkeypatch.setattr(whisper, '_WIN', True)
    monkeypatch.setattr(whisper, 'windows', lambda: [(1, 'Notepad', 5), (2, 'Discord', 6)])
    monkeypatch.setattr(whisper, 'process_name', lambda pid: 'notepad.exe')

    assert whisper.find_game() is None


def test_probe_reports_the_game_and_the_reason(whisper, monkeypatch):
    monkeypatch.setattr(whisper, '_WIN', True)
    monkeypatch.setattr(whisper, 'find_game', lambda: None)

    assert whisper.probe() == {'game': False, 'reason': 'game window not found'}

    monkeypatch.setattr(whisper, 'find_game', lambda: 7)
    assert whisper.probe() == {'game': True, 'reason': ''}
    assert set(whisper.probe()) == {'game', 'reason'}


@WIN_ONLY
def test_find_game_reports_none_on_a_machine_without_the_game_running(whisper):
    if whisper.find_game() is not None:
        pytest.skip('the game is running on this machine - nothing to prove here')

    assert whisper.probe() == {'game': False, 'reason': 'game window not found'}


@WIN_ONLY
def test_windows_lists_real_top_level_windows_with_a_title(whisper):
    rows = whisper.windows()

    assert isinstance(rows, list)
    assert all(isinstance(hwnd, int) and title for hwnd, title, _pid in rows)


# ----------------------------------------------------------------------------- clipboard

@WIN_ONLY
def test_the_clipboard_round_trips_through_ctypes(whisper):
    before = whisper.read()
    marker = 'wfm whisper pytest %d' % os.getpid()
    if not whisper.copy(marker):
        pytest.skip('OpenClipboard refused - another process holds the clipboard')

    try:
        assert whisper.read() == marker
        assert whisper.copy('unicode \u2014 "\u00e9"') and whisper.read() == \
            'unicode \u2014 "\u00e9"'
    finally:
        if before is not None:
            whisper.copy(before)
            assert whisper.read() == before


@WIN_ONLY
def test_only_user32_and_kernel32_are_loaded(whisper):
    whisper.copy('x')

    assert whisper.loaded_libs() == ['kernel32', 'user32']     # no shell32, no new package


def test_copy_gives_up_when_the_clipboard_never_opens(whisper, monkeypatch):
    monkeypatch.setattr(whisper, '_WIN', True)
    monkeypatch.setattr(whisper, 'CLIP_TRIES', 2)
    fake = FakeUser32(clipboard_ok=False)
    monkeypatch.setattr(whisper, '_win32', lambda: (fake, FakeThreads()))

    assert whisper.copy('x') is False and fake.opened == 2      # tried, then told the truth


@NOT_WIN
def test_off_windows_the_clipboard_answers_false_and_none(whisper):
    assert whisper.copy('x') is False and whisper.read() is None


# -------------------------------------------------------------------------- keystrokes

def test_press_paste_and_enter_types_ctrl_v_then_return(whisper, monkeypatch):
    """The whole point of the module: Ctrl down, V down, V up, Ctrl up, then Return."""
    monkeypatch.setattr(whisper, '_WIN', True)
    fake = FakeUser32()
    monkeypatch.setattr(whisper, '_win32', lambda: (fake, FakeThreads()))

    assert whisper.press_paste_and_enter() == 6

    ctrl, v, return_ = whisper.VK_CONTROL, whisper.VK_V, whisper.VK_RETURN
    up = whisper.KEYEVENTF_KEYUP
    assert fake.batches == [[(ctrl, 0), (v, 0), (v, up), (ctrl, up)], [(return_, 0), (return_, up)]]


def test_a_refused_send_input_reports_zero_events(whisper, monkeypatch):
    monkeypatch.setattr(whisper, '_WIN', True)

    class Blocked(FakeUser32):
        def SendInput(self, count, batch, size):
            return 0

    monkeypatch.setattr(whisper, '_win32', lambda: (Blocked(), FakeThreads()))

    assert whisper.press_paste_and_enter() == 0


def test_focus_only_reports_true_when_the_game_really_is_foreground(whisper, monkeypatch):
    monkeypatch.setattr(whisper, '_WIN', True)
    monkeypatch.setattr(whisper, 'FOCUS_TRIES', 2)

    never = FakeUser32(foreground=99)
    monkeypatch.setattr(whisper, '_win32', lambda: (never, FakeThreads()))
    assert whisper.focus(4242) is False

    reached = FakeUser32(foreground=4242)
    monkeypatch.setattr(whisper, '_win32', lambda: (reached, FakeThreads()))
    assert whisper.focus(4242) is True

    wrapped = FakeUser32(foreground=None)
    wrapped.GetForegroundWindow = lambda: whisper.HWND(4242)     # c_void_p, not an int
    monkeypatch.setattr(whisper, '_win32', lambda: (wrapped, FakeThreads()))
    assert whisper.focus(4242) is True

    assert whisper.focus(None) is False and whisper.focus(0) is False


def test_window_handles_are_compared_by_value(whisper):
    """Regression: GetForegroundWindow() is an int and HWND(x) is a c_void_p - never equal."""
    assert whisper.handle_value(whisper.HWND(4242)) == 4242
    assert whisper.handle_value(4242) == 4242
    assert whisper.handle_value(None) == 0 and whisper.handle_value(whisper.HWND(0)) == 0
    assert whisper.handle_value('nonsense') == 0
    assert whisper.HWND(4242) != 4242                        # why the helper exists


def test_focus_never_raises_when_the_foreground_thread_cannot_be_attached(whisper, monkeypatch):
    monkeypatch.setattr(whisper, '_WIN', True)

    class Broken(FakeUser32):
        def GetWindowThreadProcessId(self, hwnd, _pid):
            raise OSError('input queue is gone')

    monkeypatch.setattr(whisper, '_win32', lambda: (Broken(), FakeThreads()))

    assert whisper.focus(4242) is False


@NOT_WIN
def test_off_windows_the_win32_half_answers_zero_and_false(whisper):
    assert whisper.press_paste_and_enter() == 0
    assert whisper.focus(1) is False and whisper.find_game() is None
    assert whisper.windows() == []


# --------------------------------------------------------------------------------- send

def test_send_without_the_game_copies_the_text_and_says_so(whisper, monkeypatch):
    monkeypatch.setattr(whisper, '_WIN', True)   # send() refuses off Windows
    monkeypatch.setattr(whisper, 'find_game', lambda: None)
    copied = []
    monkeypatch.setattr(whisper, 'copy', lambda text: copied.append(text) or True)
    monkeypatch.setattr(whisper, 'focus',
                        lambda hwnd: pytest.fail('nothing may be focused without a game'))
    monkeypatch.setattr(whisper, 'press_paste_and_enter',
                        lambda: pytest.fail('no key may be typed without a game'))

    assert whisper.send(BUY) == (False, 'game window not found')

    assert copied == [BUY]                                  # the user can still paste it by hand
    row = read_json(whisper.LOG_PATH)[-1]
    assert row['mode'] == 'copy' and row['copied'] is True and row['sent'] is False
    assert row['reason'] == 'game window not found'


def test_send_without_the_game_reports_a_failed_copy_too(whisper, monkeypatch):
    monkeypatch.setattr(whisper, '_WIN', True)   # send() refuses off Windows
    monkeypatch.setattr(whisper, 'find_game', lambda: None)
    monkeypatch.setattr(whisper, 'copy', lambda text: False)

    assert whisper.send(BUY) == (False, 'game window not found')
    row = read_json(whisper.LOG_PATH)[-1]
    assert row['copied'] is False and row['mode'] == 'blocked'


def test_send_copies_focuses_and_reports_success(whisper, monkeypatch):
    calls = win_seams(whisper, monkeypatch)

    assert whisper.send(BUY) == (True, '')

    assert calls == [('copy', BUY), ('focus', 4242), ('keys',)]
    row = read_json(whisper.LOG_PATH)[-1]
    assert row['mode'] == 'sent' and row['copied'] is True and row['sent'] is True
    assert row['reason'] == '' and row['ts'].endswith('Z')
    assert whisper.sent_count() == 1


@pytest.mark.parametrize('seam,value,reason,copied', [
    ('copied', False, 'clipboard busy', False),
    ('focus', False, 'game window not focused', True),
    ('keys', 0, 'input blocked', True),
    ('keys', 4, 'input blocked', True),
])
def test_send_reports_every_refusal_honestly(whisper, monkeypatch, seam, value, reason, copied):
    kwargs = {seam: value}
    win_seams(whisper, monkeypatch, **kwargs)

    assert whisper.send(BUY) == (False, reason)

    row = read_json(whisper.LOG_PATH)[-1]
    assert row['copied'] is copied and row['sent'] is False and row['reason'] == reason
    assert whisper.sent_count() == 0                        # a refusal is never a send


def test_send_never_types_when_focus_was_refused(whisper, monkeypatch):
    win_seams(whisper, monkeypatch, focus=False)
    typed = []
    monkeypatch.setattr(whisper, 'press_paste_and_enter', lambda: typed.append(True) or 6)

    whisper.send(BUY)

    assert typed == []                                      # Ctrl+V must never land blind


def test_send_fills_the_ledger_row_from_the_text_when_no_fields_are_given(whisper, monkeypatch):
    win_seams(whisper, monkeypatch)

    whisper.send('%s' % whisper.message('Primed Continuity', 120, 'sell', 10))

    row = read_json(whisper.LOG_PATH)[-1]
    assert row['item'] == 'Primed Continuity' and row['price'] == '120' and row['kind'] == 'sell'


def test_send_prefers_the_explicit_fields_over_the_parsed_text(whisper, monkeypatch):
    win_seams(whisper, monkeypatch)

    whisper.send(BUY, item='Riven Mod', price='999', kind='sell', user='TestTenno')

    row = read_json(whisper.LOG_PATH)[-1]
    assert (row['item'], row['price'], row['kind']) == ('Riven Mod', '999', 'sell')
    assert row['user'] == 'TestTenno' and row['sent'] is True


@pytest.mark.parametrize('text', ['', '   ', None])
def test_send_refuses_an_empty_message_and_still_logs_it(whisper, text):
    assert whisper.send(text) == (False, 'empty message')

    row = read_json(whisper.LOG_PATH)[-1]
    assert row['mode'] == 'blocked' and row['copied'] is False and row['reason'] == 'empty message'


@NOT_WIN
def test_off_windows_send_answers_with_a_reason_and_never_raises(whisper, monkeypatch):
    monkeypatch.setattr(whisper, 'press_paste_and_enter',
                        lambda: pytest.fail('no keystroke off Windows'))

    assert whisper.send(BUY) == (False, 'windows only')
    assert whisper.probe() == {'game': False, 'reason': 'windows only'}

    row = read_json(whisper.LOG_PATH)[-1]
    assert row['mode'] == 'unsupported' and row['copied'] is False and row['sent'] is False


def test_send_survives_an_unwritable_ledger(whisper, monkeypatch):
    blocked = whisper.DATA + os.sep + 'not-a-dir'
    (whisper.ROOT and open(blocked, 'w', encoding='utf-8').close())     # a FILE where a dir goes
    monkeypatch.setattr(whisper, 'LOG_PATH', os.path.join(blocked, 'whisper_log.json'))
    win_seams(whisper, monkeypatch)

    assert whisper.send(BUY) == (True, '')                  # the send counts, the log complains


def test_send_asks_the_gates_and_refuses_rather_than_queueing(whisper, monkeypatch):
    calls = win_seams(whisper, monkeypatch)
    monkeypatch.setattr(whisper, 'clock', FakeClock())

    assert whisper.send(BUY)[0] is True
    calls.clear()

    assert whisper.send(BUY) == (False, 'cooldown 2s')
    assert calls == []                                      # nothing copied, nothing typed
    row = read_json(whisper.LOG_PATH)[-1]
    assert row['mode'] == 'blocked' and row['reason'] == 'cooldown 2s'


# --------------------------------------------------------------------------------- gates

def test_the_gate_names_and_numbers_are_the_documented_ones(whisper):
    assert (whisper.R_SENT, whisper.R_NO_GAME) == ('', 'game window not found')
    assert whisper.R_COOLDOWN == 'cooldown 2s' and whisper.COOLDOWN == 2.0
    assert whisper.R_RATE == 'rate limit 10 per minute' and whisper.RATE_MAX == 10
    assert whisper.RATE_WINDOW == 60.0 and whisper.LOG_KEEP == 500


def test_the_first_send_is_allowed_and_the_second_is_on_cooldown(whisper, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(whisper, 'clock', clock)

    assert whisper.gate() == ''
    whisper._mark_sent()
    assert whisper.gate() == 'cooldown 2s'
    clock.advance(1.99)
    assert whisper.gate() == 'cooldown 2s'                  # the boundary is strict
    clock.advance(0.01)
    assert whisper.gate() == ''


def test_ten_sends_leave_and_the_eleventh_is_rate_limited(whisper, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(whisper, 'clock', clock)

    for _ in range(whisper.RATE_MAX):
        assert whisper.gate() == ''
        whisper._mark_sent()
        clock.advance(whisper.COOLDOWN)                     # 2s apart: inside one minute

    assert whisper.sent_count() == whisper.RATE_MAX
    assert whisper.gate() == 'rate limit 10 per minute'


def test_the_minute_window_rolls_over(whisper, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(whisper, 'clock', clock)
    for _ in range(whisper.RATE_MAX):
        whisper._mark_sent()
        clock.advance(whisper.COOLDOWN)

    clock.advance(whisper.RATE_WINDOW)
    assert whisper.sent_count() == 0 and whisper.gate() == ''


def test_only_sends_that_really_left_count_against_the_cap(whisper, monkeypatch):
    monkeypatch.setattr(whisper, '_WIN', True)   # send() refuses off Windows
    clock = FakeClock()
    monkeypatch.setattr(whisper, 'clock', clock)
    monkeypatch.setattr(whisper, 'find_game', lambda: None)
    monkeypatch.setattr(whisper, 'copy', lambda text: True)

    for _ in range(whisper.RATE_MAX + 3):                   # every one refused: no game
        assert whisper.send(BUY) == (False, 'game window not found')
        clock.advance(whisper.COOLDOWN)

    assert whisper.sent_count() == 0 and whisper.gate() == ''


def test_reset_forgets_the_send_history(whisper, monkeypatch):
    monkeypatch.setattr(whisper, 'clock', FakeClock())
    whisper._mark_sent()

    assert whisper.sent_count() == 1

    whisper.reset()

    assert whisper.sent_count() == 0 and whisper.gate() == ''


def test_the_clock_is_read_through_the_module_name(whisper, monkeypatch):
    """The gates must be provable by monkeypatching whisper.clock (documented contract)."""
    monkeypatch.setattr(whisper, 'clock', lambda: 1_000_000.0)
    whisper._mark_sent()
    monkeypatch.setattr(whisper, 'clock', lambda: 1_000_000.0 + whisper.RATE_WINDOW)

    assert whisper.sent_count() == 0                        # read at call time, not captured


# ------------------------------------------------------------------------------- ledger

def test_a_row_carries_the_documented_fields(whisper):
    row = whisper.row_for(whisper.MODE_SENT, True, True, '', item='X', price='5', kind='buy',
                          user='TestTenno')

    assert list(row) == ['ts', 'user', 'item', 'price', 'kind', 'mode', 'copied', 'sent', 'reason']
    assert row['ts'].endswith('Z') and 'T' in row['ts']
    assert row['copied'] is True and row['sent'] is True and row['reason'] == ''


def test_the_user_field_is_optional_and_comes_from_the_trader_state(whisper):
    assert 'user' not in whisper.row_for(whisper.MODE_SENT, True, True, '')
    assert whisper.account() == ''

    write_json(whisper.STATE_PATH, {'account': 'RoyalSpartanIIX', 'orders': {}})
    assert whisper.account() == 'RoyalSpartanIIX'
    assert whisper.row_for(whisper.MODE_SENT, True, True, '')['user'] == 'RoyalSpartanIIX'

    with open(whisper.STATE_PATH, 'w', encoding='utf-8') as fh:
        fh.write('{ not json')
    assert whisper.account() == ''                          # unreadable: no invented name


def test_the_ledger_keeps_the_newest_rows_only(whisper, monkeypatch):
    monkeypatch.setattr(whisper, 'LOG_KEEP', 3)

    for index in range(5):
        whisper.append(whisper.row_for(whisper.MODE_SENT, True, True, '', item='row %d' % index))

    rows = read_json(whisper.LOG_PATH)
    assert [r['item'] for r in rows] == ['row 2', 'row 3', 'row 4']


def test_the_ledger_is_written_atomically_and_leaves_no_tmp_file(whisper):
    whisper.record(whisper.MODE_SENT, True, True, '', item='X')

    assert 'whisper_log.json.tmp' not in os.listdir(whisper.DATA)
    assert len(read_json(whisper.LOG_PATH)) == 1


def test_log_last_is_newest_first_and_honours_n(whisper):
    for index in range(4):
        whisper.record(whisper.MODE_SENT, True, True, '', item='row %d' % index)

    assert [r['item'] for r in whisper.log_last(2)] == ['row 3', 'row 2']
    assert len(whisper.log_last()) == 4 and whisper.log_last(0) == []
    assert whisper.log_last('2')[0]['item'] == 'row 3'      # a string count is not a crash
    assert whisper.log_last(None)[0]['item'] == 'row 3'


def test_log_last_is_empty_rather_than_an_error_without_a_ledger(whisper):
    assert whisper.log_last(5) == [] and whisper.load() == []


def test_a_corrupt_ledger_is_moved_aside_not_dropped(whisper):
    with open(whisper.LOG_PATH, 'w', encoding='utf-8') as fh:
        fh.write('{{broken')

    assert whisper.load() == []
    spare = [name for name in os.listdir(whisper.DATA) if 'corrupt' in name]
    assert spare and open(os.path.join(whisper.DATA, spare[0]),
                          encoding='utf-8').read() == '{{broken'

    assert whisper.append(whisper.row_for(whisper.MODE_SENT, True, True, ''))[-1]['sent'] is True


def test_a_non_list_ledger_starts_fresh_instead_of_raising(whisper):
    write_json(whisper.LOG_PATH, {'not': 'a list'})

    assert whisper.load() == []


# ---------------------------------------------------------------------------- CLI + import

def test_selftest_passes_in_process_and_touches_nothing_in_data(whisper, capsys):
    assert whisper.main(['--selftest']) == 0

    out = capsys.readouterr().out
    assert 'selftest OK' in out and 'FAIL' not in out and 'PASS' in out
    assert 'no keystrokes, no game, no network' in out
    assert not os.path.exists(whisper.LOG_PATH)              # the real ledger is left alone


def test_selftest_runs_clean_from_the_command_line(whisper):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    proc = subprocess.run([sys.executable, WHISPER_SRC, '--selftest'], cwd=os.path.dirname(SCRIPTS),
                          capture_output=True, text=True, timeout=180, env=env,
                          encoding='utf-8', errors='replace')

    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    assert 'selftest OK' in proc.stdout and 'FAIL' not in proc.stdout


def test_the_message_cli_prints_the_exact_line(whisper, capsys):
    assert whisper.main(['--message', 'primed_continuity', '120', 'buy']) == 0

    assert capsys.readouterr().out == BUY + '\n'

    assert whisper.main(['--message', 'primed_continuity', '120', 'buy', '--rank', '10']) == 0
    assert capsys.readouterr().out == ('Hi! I want to buy: "Primed Continuity (rank 10)" for 120 '
                                       'platinum. (warframe.market)\n')

    assert whisper.main(['--message', 'primed_continuity', '120', 'buy', '--rank', '0']) == 0
    assert capsys.readouterr().out == BUY_R0 + '\n'           # rank 0 is spelled out

    assert whisper.main(['--message', 'primed_continuity', '120', 'buy', '--rank', '10',
                         '--user', 'Quersus_']) == 0
    assert capsys.readouterr().out == ('/w Quersus_ Hi! I want to buy: "Primed Continuity '
                                       '(rank 10)" for 120 platinum. (warframe.market)\n')


def test_the_probe_and_log_cli_answer_without_a_game(whisper, capsys):
    assert whisper.main(['--probe']) == 0
    out = capsys.readouterr().out
    assert 'game window' in out and 'sends in the last' in out

    whisper.record(whisper.MODE_COPY, True, False, 'game window not found', item='Primed Continuity')
    assert whisper.main(['--log', '5']) == 0
    out = capsys.readouterr().out
    assert 'whisper ledger' in out and 'Primed Continuity' in out
    assert 'refused: game window not found' in out


def test_cli_guards(whisper, capsys):
    assert whisper.main(['--selftest', '--probe']) == 2
    assert whisper.main(['--rank', '3']) == 2                # --rank needs --message
    assert whisper.main(['--message', 'x', '1', 'trade']) == 2   # unknown kind
    assert 'kind must be buy or sell' in capsys.readouterr().out
    assert whisper.main([]) == 2
    with pytest.raises(SystemExit) as exc:
        whisper.main(['--log', '0'])
    assert exc.value.code == 2


def test_the_selftest_reports_a_zero_failure_run_as_ok(whisper, capsys):
    assert whisper.main(['--selftest']) == 0
    assert '0 failed' in capsys.readouterr().out


# ------------------------------------------------------------------------- import contract

def test_module_level_imports_are_stdlib_only():
    names = module_imports(open(WHISPER_SRC, encoding='utf-8').read())

    assert names <= MODULE_IMPORTS
    assert 'ctypes' in names                                # the whole Windows half is ctypes


def test_the_private_trader_scripts_are_never_imported():
    src = open(WHISPER_SRC, encoding='utf-8').read()

    assert not module_imports(src) & PRIVATE_TRADER


def test_whisper_stays_offline_and_shell_free():
    src = open(WHISPER_SRC, encoding='utf-8').read().lower()

    for banned in ('urllib', 'requests.', 'socket', 'http://', 'https://', 'pip install'):
        assert banned not in src, 'whisper.py must stay local - found %r' % banned
    assert 'os.replace' in src                              # atomic write (house style)
    for api in ('openclipboard', 'setclipboarddata', 'enumwindows', 'getwindowtextw',
                'setforegroundwindow', 'sendinput'):
        assert api in src, 'whisper.py must use %s' % api


def test_importing_the_module_is_inert(whisper):
    assert whisper.loaded_libs() == []                      # no DLL at import time
    assert whisper._SENT == []                              # no send history
    assert whisper._WIN is (os.name == 'nt')
    assert (whisper.WNDENUMPROC is None) is (os.name != 'nt')


def test_import_opens_no_dll_in_a_fresh_interpreter(whisper):
    probe = (
        'import ctypes, importlib.util, sys\n'
        'def _boom(*a, **k):\n'
        '    raise AssertionError("a Win32 library was loaded at import time")\n'
        'ctypes.WinDLL = _boom\n'
        'spec = importlib.util.spec_from_file_location("whisper_probe", sys.argv[1])\n'
        'mod = importlib.util.module_from_spec(spec)\n'
        'spec.loader.exec_module(mod)\n'
        'assert mod.loaded_libs() == []\n'
        'print("IMPORT_OK")\n'
    )
    proc = subprocess.run([sys.executable, '-c', probe, WHISPER_SRC],
                          capture_output=True, text=True, timeout=120,
                          encoding='utf-8', errors='replace')

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert 'IMPORT_OK' in proc.stdout
@WIN_ONLY
def test_the_selftest_is_clean_on_a_non_windows_host_too(whisper, tmp_path):
    """os.name is flipped inside the child, so this is what the Linux CI runner executes.

    The stdlib modules whisper imports are pre-imported in the child (several of them pick
    their implementation from os.name at import time), then os.name is set to 'posix'
    before whisper is loaded. Every function must answer False/None with a reason and
    --selftest must still exit 0 with the Windows-only checks skipped - the failure mode
    this guards against is a selftest that only passes on the developer's PC while CI (and
    any Linux/macOS checkout) goes red.
    """
    log = tmp_path / 'data' / 'whisper_log.json'
    log.parent.mkdir(exist_ok=True)                            # the fixture already made data/
    probe = (
        'import argparse, contextlib, ctypes, importlib.util, io, json, os, re\n'
        'import shutil, subprocess, sys, tempfile, time\n'
        'os.name = "posix"\n'
        'spec = importlib.util.spec_from_file_location("whisper_posix", sys.argv[1])\n'
        'mod = importlib.util.module_from_spec(spec)\n'
        'spec.loader.exec_module(mod)\n'
        'mod.LOG_PATH = sys.argv[2]\n'                 # never the repo's data/ directory
        'assert mod._WIN is False and mod.loaded_libs() == []\n'
        'assert mod.WNDENUMPROC is None and mod.windows() == []\n'
        'assert mod.find_game() is None and mod.read() is None\n'
        'assert mod.copy("x") is False\n'
        'assert mod.probe() == {"game": False, "reason": "windows only"}\n'
        'assert mod.send("hi") == (False, "windows only")\n'
        'assert mod.message("Primed Continuity", 120, "buy").endswith("(warframe.market)")\n'
        'print("POSIX_OK")\n'
        'sys.exit(mod.main(["--selftest"]))\n'
    )
    proc = subprocess.run([sys.executable, '-c', probe, WHISPER_SRC, str(log)],
                          cwd=os.path.dirname(SCRIPTS), capture_output=True, text=True,
                          timeout=180, encoding='utf-8', errors='replace')

    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    assert 'POSIX_OK' in proc.stdout and 'FAIL' not in proc.stdout
    assert 'selftest OK' in proc.stdout and 'skipped' in proc.stdout
    assert read_json(log)[-1]['mode'] == 'unsupported'          # logged, never faked as sent
