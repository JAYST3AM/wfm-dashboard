#!/usr/bin/env python3
r"""One-click trade whisper for the Trade Orders tab (Windows, stdlib + ctypes only).

What one click does, for one order row:
  1. message(item, price, kind, rank) builds the standard warframe.market line, e.g.
     'Hi! I want to buy: "Primed Continuity" rank 10 for 120 platinum. (warframe.market)'
  2. copy(text) puts that line on the Windows clipboard as CF_UNICODETEXT.
  3. send(text) finds the Warframe window (EnumWindows + GetWindowTextW), brings it to
     the front, then types Ctrl+V followed by Enter with SendInput - the recipe
     AlecaFrame uses for its one-click whisper. One call, one message.

Discipline (why there is no queue in here)
  ONE click = ONE message. No loop, no batch mode, no retry, no 'send to everyone':
  a second click inside COOLDOWN seconds is refused with 'cooldown 2s', and no more than
  RATE_MAX sends leave inside RATE_WINDOW seconds ('rate limit 10 per minute'). Every
  call - refused ones included - appends one row to data/whisper_log.json (atomic write,
  newest LOG_KEEP rows kept), so the tab can show exactly what was typed into the game.

Honesty rules
  * A missing game window is not an error and not a silent success: the text is still
    copied to the clipboard and send() answers (False, 'game window not found'), so the
    UI can say 'copied - paste it yourself'. Nothing is ever typed into a window we could
    not confirm is the game (pasting on faith is how whispers land in Discord).
  * Off Windows every function answers False/None with a reason ('windows only') instead
    of raising; no send is faked to look like it worked.
  * The keystroke half is Ctrl+V and Enter and nothing else: no movement, no combat
    input, no trade automation. The user's own click is the trigger, one at a time.

The sent line is the warframe.market copy/paste message, which the site's own terms ask
to be sent unmodified - so the quotes and the '(warframe.market)' tail are kept exactly,
and a rank > 0 is added as ' rank <n>' right before ' for'.

Interface the dashboard imports
  message(item, price, kind, rank=None) -> str
  copy(text) -> bool                    # clipboard only; logs nothing
  read() -> str|None                    # clipboard read-back (tests, UI preview)
  find_game() -> int|None
  send(text, item=..., price=..., kind=..., user=None) -> (sent: bool, reason: str)
  probe() -> {'game': bool, 'reason': str}
  log_last(n=20) -> list                # newest first

Usage
  python scripts/whisper.py --selftest
  python scripts/whisper.py --message primed_continuity 120 buy --rank 10
  python scripts/whisper.py --send 'Hi! I want to buy: "Primed Continuity" for 120 platinum. (warframe.market)'
  python scripts/whisper.py --probe
  python scripts/whisper.py --log 10

Importing this module is inert: no DLL is loaded, no window is enumerated, no key is sent.

Exit codes: 0 = ok / selftest passed, 1 = refused or failed, 2 = bad args.
"""
import argparse
import contextlib
import ctypes
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
LOG_PATH = os.path.join(DATA, 'whisper_log.json')
STATE_PATH = os.path.join(DATA, 'trader_state.json')     # read-only source of the account

GAME_TITLE = 'warframe'          # window title must contain this (case-insensitive)
GAME_EXES = ('warframe.x64.exe', 'warframe.exe')         # the game's own process
SKIP_HINTS = ('launcher', 'chrome', 'msedge', 'firefox', 'brave', 'opera', 'vivaldi',
              'chromium', 'iexplore', 'overwolf', 'webview')   # never typed into

COOLDOWN = 2.0                   # seconds two real sends must be apart
RATE_MAX = 10                    # sends ...
RATE_WINDOW = 60.0               # ... allowed inside this many seconds
LOG_KEEP = 500                   # ledger keeps the newest N rows
LOG_LIMIT = 20                   # log_last() default rows

FOCUS_SETTLE = 0.12              # seconds between focusing the game and the paste
FOCUS_TRIES = 3                  # foreground attempts before giving up honestly
PASTE_GAP = 0.06                 # seconds between the paste and Enter
PASTE_EVENTS = 6                 # Ctrl down/up + V down/up + Return down/up
CLIP_TRIES = 6                   # OpenClipboard attempts (another app may hold it)
CLIP_WAIT = 0.02                 # seconds between those attempts

# reason strings - '' means sent, the two gates and the no-game case are the documented ones
R_SENT = ''
R_NO_GAME = 'game window not found'
R_COOLDOWN = 'cooldown %ds' % int(COOLDOWN)
R_RATE = 'rate limit %d per minute' % int(RATE_MAX)
R_WINDOWS = 'windows only'                       # every function off Windows
R_EMPTY = 'empty message'
R_CLIP = 'clipboard busy'                        # another app held the clipboard
R_FOCUS = 'game window not focused'              # copied, but not typed anywhere
R_INPUT = 'input blocked'                        # SendInput was refused (UIPI)

MODE_SENT = 'sent'               # copied AND typed into the game
MODE_COPY = 'copy'               # copied only - the user pastes it by hand
MODE_BLOCKED = 'blocked'         # refused by a gate; nothing copied
MODE_UNSUPPORTED = 'unsupported'  # not Windows; nothing copied

_VERBS = {'buy': 'I want to buy', 'buying': 'I want to buy', 'wtb': 'I want to buy',
          'sell': 'I am selling', 'selling': 'I am selling', 'wts': 'I am selling'}

_W_PREFIX = re.compile(r'^/w (?P<user>\S+) ')

WHISPER_RE = re.compile(
    r'^Hi! I (?P<verb>want to buy|am selling): "(?P<item>.+?)'
    r'(?: \(?rank (?P<rank_in>\d+)\)?)?"(?: \(?rank (?P<rank_out>\d+)\)?)?'
    r' for (?P<price>[^ ]+) platinum\. \(warframe\.market\)$')

_WIN = os.name == 'nt'
_LIBS = {}                       # ctypes DLLs; empty until a Win32 function is used
_SENT = []                       # monotonic stamps of the sends that really left


# ----------------------------------------------------------------------- win32 types
DWORD = ctypes.c_uint32
WORD = ctypes.c_uint16
UINT = ctypes.c_uint32
INT = ctypes.c_int32
BOOL = ctypes.c_int32
LONG = ctypes.c_int32
ULONG_PTR = ctypes.c_size_t
HWND = HANDLE = LPVOID = ctypes.c_void_p

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_V = 0x56
VK_RETURN = 0x0D
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
SW_RESTORE = 9
GW_OWNER = 4
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', LONG), ('dy', LONG), ('mouseData', DWORD), ('dwFlags', DWORD),
                ('time', DWORD), ('dwExtraInfo', ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', WORD), ('wScan', WORD), ('dwFlags', DWORD), ('time', DWORD),
                ('dwExtraInfo', ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [('uMsg', DWORD), ('wParamL', WORD), ('wParamH', WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    """The real SendInput record: MOUSEINPUT must be in the union or cbSize is wrong."""
    _fields_ = [('type', DWORD), ('u', _INPUTUNION)]


def size_of_input():
    """sizeof(INPUT) - 40 on 64-bit Windows, 28 on 32-bit; SendInput rejects anything else."""
    return ctypes.sizeof(INPUT)


def loaded_libs():
    """Names of the Win32 DLLs loaded so far - empty until a Win32 function is called."""
    return sorted(_LIBS)


if _WIN:
    WNDENUMPROC = ctypes.WINFUNCTYPE(BOOL, HWND, LPVOID)

    def _win32():
        """user32 + kernel32 with full signatures, loaded once, on first use."""
        if 'user32' in _LIBS:
            return _LIBS['user32'], _LIBS['kernel32']
        u32 = ctypes.WinDLL('user32', use_last_error=True)
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        u32.EnumWindows.argtypes = [WNDENUMPROC, LPVOID]
        u32.EnumWindows.restype = BOOL
        u32.GetWindowTextW.argtypes = [HWND, ctypes.c_wchar_p, INT]
        u32.GetWindowTextW.restype = INT
        u32.GetWindowTextLengthW.argtypes = [HWND]
        u32.GetWindowTextLengthW.restype = INT
        u32.IsWindowVisible.argtypes = [HWND]
        u32.IsWindowVisible.restype = BOOL
        u32.GetWindow.argtypes = [HWND, UINT]
        u32.GetWindow.restype = HWND
        u32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(DWORD)]
        u32.GetWindowThreadProcessId.restype = DWORD
        u32.IsIconic.argtypes = [HWND]
        u32.IsIconic.restype = BOOL
        u32.ShowWindow.argtypes = [HWND, INT]
        u32.ShowWindow.restype = BOOL
        u32.BringWindowToTop.argtypes = [HWND]
        u32.BringWindowToTop.restype = BOOL
        u32.SetForegroundWindow.argtypes = [HWND]
        u32.SetForegroundWindow.restype = BOOL
        u32.GetForegroundWindow.argtypes = []
        u32.GetForegroundWindow.restype = HWND
        u32.AttachThreadInput.argtypes = [DWORD, DWORD, BOOL]
        u32.AttachThreadInput.restype = BOOL
        u32.SendInput.argtypes = [UINT, ctypes.POINTER(INPUT), INT]
        u32.SendInput.restype = UINT
        u32.OpenClipboard.argtypes = [HWND]
        u32.OpenClipboard.restype = BOOL
        u32.EmptyClipboard.argtypes = []
        u32.EmptyClipboard.restype = BOOL
        u32.SetClipboardData.argtypes = [UINT, HANDLE]
        u32.SetClipboardData.restype = HANDLE
        u32.GetClipboardData.argtypes = [UINT]
        u32.GetClipboardData.restype = HANDLE
        u32.IsClipboardFormatAvailable.argtypes = [UINT]
        u32.IsClipboardFormatAvailable.restype = BOOL
        u32.CloseClipboard.argtypes = []
        u32.CloseClipboard.restype = BOOL
        k32.GlobalAlloc.argtypes = [UINT, ctypes.c_size_t]
        k32.GlobalAlloc.restype = HANDLE
        k32.GlobalLock.argtypes = [HANDLE]
        k32.GlobalLock.restype = LPVOID
        k32.GlobalUnlock.argtypes = [HANDLE]
        k32.GlobalUnlock.restype = BOOL
        k32.GlobalFree.argtypes = [HANDLE]
        k32.GlobalFree.restype = HANDLE
        k32.OpenProcess.argtypes = [DWORD, BOOL, DWORD]
        k32.OpenProcess.restype = HANDLE
        k32.QueryFullProcessImageNameW.argtypes = [HANDLE, DWORD, ctypes.c_wchar_p,
                                                   ctypes.POINTER(DWORD)]
        k32.QueryFullProcessImageNameW.restype = BOOL
        k32.CloseHandle.argtypes = [HANDLE]
        k32.CloseHandle.restype = BOOL
        k32.GetCurrentThreadId.argtypes = []
        k32.GetCurrentThreadId.restype = DWORD
        _LIBS['user32'], _LIBS['kernel32'] = u32, k32
        return u32, k32
else:                                                          # non-Windows: keep the shape
    WNDENUMPROC = None

    def _win32():
        raise OSError('the whisper sender needs Windows (user32/kernel32 via ctypes)')


# --------------------------------------------------------------------------- util
def warn(message):
    """One-line diagnostic on stdout. Never raises: the send must still answer."""
    try:
        print('WARN whisper: %s' % message)
    except Exception:                                      # noqa: BLE001 - pythonw has no stdout
        pass


# --------------------------------------------------------------------------- message
def fmt_price(price):
    """'120' for 120 and 120.0 - a JSON float must not print as '120.0' in a whisper."""
    if isinstance(price, str):
        return price.strip()
    if isinstance(price, float) and price.is_integer():
        return str(int(price))
    return str(price)


def rank_suffix(rank):
    """' (rank 10)' for any rank the order states, '' when there is none (parts are not ranked).

    warframe.market's own copy/paste line carries the rank inside the quoted name and its Terms
    ask for that line used as-is: 'Hi! I want to buy: \"Necramech Flow (rank 0)\" for 10
    platinum. (warframe.market)'. So rank 0 shows too - a plain part (rank None) shows nothing.
    """
    try:
        value = int(rank)
    except (TypeError, ValueError):
        return ''
    return ' (rank %d)' % value if value >= 0 else ''


def message(item, price, kind, rank=None):
    """The warframe.market whisper line for one order row.

    buying : Hi! I want to buy: \"<item> (rank 0)\" for <price> platinum. (warframe.market)
    selling: Hi! I am selling: \"<item> (rank 0)\" for <price> platinum. (warframe.market)
    The rank rides inside the quotes, exactly like the site's own copy button (its Terms require
    the generated message used as-is); rank None adds nothing.
    kind takes buy/buying/wtb and sell/selling/wts; anything else raises ValueError.
    """
    verb = _VERBS.get(str(kind or '').strip().lower())
    if verb is None:
        raise ValueError('kind must be buy or sell, got %r' % (kind,))
    return 'Hi! %s: \"%s%s\" for %s platinum. (warframe.market)' % (
        verb, str(item).strip(), rank_suffix(rank), fmt_price(price))


def line(user, item, price, kind, rank=None):
    """The whole paste: '/w <user> ' + message(...) - what actually goes into the game.

    The site's copy button includes the whisper command (all three) and the Terms ask for that
    text as-is, so the tab sends one line: command, name, price, site. A user is required: a
    message without one would land in whatever channel the chat box is on.
    """
    who = ' '.join(str(user or '').split())
    if not who:
        raise ValueError('user required')
    return '/w %s %s' % (who, message(item, price, kind, rank))


def parse(text):
    """Reverse of line()/message() -> {'kind', 'item', 'price', 'rank'[, 'user']}; {} otherwise.

    Used by send() so a caller that only has the finished line still gets a useful ledger
    row. The '/w <user> ' prefix is stripped and returned as 'user' when present (warframe.market's
    copy button includes it). Both rank spellings are accepted ('"X (rank 10)"' and '"X" rank 10').
    Never raises.
    """
    text = str(text or '').strip()
    who = None
    try:
        pre = _W_PREFIX.match(text)
        if pre:
            who = pre.group('user')
            text = text[pre.end():]
        found = WHISPER_RE.match(text)
    except (TypeError, ValueError):
        return {}
    if not found:
        return {}
    rank = found.group('rank_in') or found.group('rank_out')
    out = {'kind': 'buy' if found.group('verb') == 'want to buy' else 'sell',
           'item': found.group('item'), 'price': found.group('price'),
           'rank': int(rank) if rank else None}
    if who:
        out['user'] = who
    return out


def title_for(slug):
    """Best-effort display name from a slug ('primed_continuity' -> 'Primed Continuity').

    The tab passes the real item name to message(); this exists for the CLI, where the
    caller types a slug.
    """
    words = re.split(r'[_\-\s]+', str(slug).strip())
    return ' '.join(word[:1].upper() + word[1:] for word in words if word)


# ------------------------------------------------------------------------- clipboard
def _clip_open(u32):
    """OpenClipboard with retries; another app may hold the clipboard for a moment."""
    for _ in range(max(1, int(CLIP_TRIES))):
        if u32.OpenClipboard(None):
            return True
        time.sleep(CLIP_WAIT)
    return False


def copy(text):
    """Put text on the Windows clipboard as CF_UNICODETEXT. -> True on success.

    Never raises and never touches the game: this is the half that always works, which is
    why send() still calls it when the game window is missing.
    """
    if not _WIN:
        return False
    try:
        u32, k32 = _win32()
    except OSError as exc:                                 # no user32 here: answer, never raise
        warn('clipboard unavailable: %s' % exc)
        return False
    body = '' if text is None else str(text)
    data = body.encode('utf-16-le') + b'\x00\x00'          # NUL-terminated UTF-16
    if not _clip_open(u32):
        return False
    handle = None
    try:
        if not u32.EmptyClipboard():
            return False
        handle = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        ptr = k32.GlobalLock(handle)
        if not ptr:
            k32.GlobalFree(handle)
            return False
        ctypes.memmove(ptr, data, len(data))
        k32.GlobalUnlock(handle)
        if not u32.SetClipboardData(CF_UNICODETEXT, handle):
            k32.GlobalFree(handle)
            return False
        handle = None                                      # the system owns it now
        return True
    except Exception as exc:                               # noqa: BLE001 - answer, never raise
        warn('clipboard write failed: %r' % (exc,))
        return False
    finally:
        if handle:
            k32.GlobalFree(handle)
        u32.CloseClipboard()


def read():
    """The clipboard's text right now, or None (empty clipboard, or not text). Never raises."""
    if not _WIN:
        return None
    try:
        u32, k32 = _win32()
    except OSError as exc:                                 # no user32 here: answer, never raise
        warn('clipboard unavailable: %s' % exc)
        return None
    if not _clip_open(u32):
        return None
    try:
        if not u32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        handle = u32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = k32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            k32.GlobalUnlock(handle)
    except Exception as exc:                               # noqa: BLE001 - answer, never raise
        warn('clipboard read failed: %r' % (exc,))
        return None
    finally:
        u32.CloseClipboard()


# ---------------------------------------------------------------------------- window
def windows():
    """[(hwnd, title, pid)] for visible, owner-less top-level windows that have a title.

    Empty off Windows. Never raises: a window that disappears mid-enumeration is skipped.
    """
    if not _WIN:
        return []
    try:
        u32, _k32 = _win32()
    except OSError as exc:                                 # no user32 here: answer, never raise
        warn('window enumeration unavailable: %s' % exc)
        return []
    rows = []

    def collect(hwnd, _lparam):
        try:
            if not u32.IsWindowVisible(hwnd) or u32.GetWindow(hwnd, GW_OWNER):
                return True                                # hidden, or a tool window
            length = u32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            u32.GetWindowTextW(hwnd, buf, length + 1)
            pid = DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if buf.value:
                rows.append((int(hwnd), buf.value, int(pid.value)))
        except Exception:                                  # noqa: BLE001 - skip and carry on
            pass
        return True

    callback = WNDENUMPROC(collect)                        # must outlive the call
    try:
        u32.EnumWindows(callback, None)
    except Exception as exc:                               # noqa: BLE001 - answer, never raise
        warn('EnumWindows failed: %r' % (exc,))
    return rows


def process_name(pid):
    """The executable's file name for a pid (lower case), or '' when it cannot be read."""
    if not _WIN or not pid:
        return ''
    try:
        _u32, k32 = _win32()
    except OSError:
        return ''
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ''
    try:
        size = DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if not k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ''
        return os.path.basename(buf.value).lower()
    except Exception:                                      # noqa: BLE001 - name it or say nothing
        return ''
    finally:
        k32.CloseHandle(handle)


def game_titles():
    """Titles of the windows that look like the game (diagnostics for --probe)."""
    return [title for _hwnd, title, _pid in windows() if GAME_TITLE in title.lower()]


def find_game():
    """The Warframe window handle, or None when the game is not running. Never raises.

    A title containing 'warframe' (case-insensitive) is the filter; the game's own process
    (Warframe.x64.exe) wins over a look-alike, and launcher/browser/webview windows are
    skipped outright - pasting a whisper into Chrome or into the launcher (whose Enter
    button is 'Play') would be worse than not sending at all. When the process name cannot
    be read (protection, permissions) the title match stands alone.
    """
    if not _WIN:
        return None
    best = None
    for hwnd, title, pid in windows():
        if GAME_TITLE not in title.lower():
            continue
        exe = process_name(pid)
        if any(hint in exe for hint in SKIP_HINTS):
            continue
        if exe in GAME_EXES:
            return hwnd
        if best is None:
            best = hwnd
    return best


def handle_value(handle):
    """The integer behind a window handle (ctypes c_void_p, a plain int, or None).

    Comparing GetForegroundWindow() (an int) with HWND(x) (a c_void_p) is always False, so
    every handle comparison goes through here - focus() would otherwise never confirm.
    """
    if handle is None:
        return 0
    value = handle.value if hasattr(handle, 'value') else handle
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def focus(hwnd):
    """Bring the game window to the front. -> True only when it IS the foreground window.

    SetForegroundWindow is refused for a background process (the click landed in the
    browser, not in this process), so the foreground thread is attached first - the
    standard workaround. The return value is checked by send(): typing Ctrl+V into
    whatever happened to be focused instead of the game is not an acceptable fallback.
    """
    if not _WIN or not hwnd:
        return False
    try:
        u32, k32 = _win32()
    except OSError as exc:                                 # no user32 here: answer, never raise
        warn('focusing unavailable: %s' % exc)
        return False
    target = HWND(hwnd)
    for _ in range(max(1, int(FOCUS_TRIES))):
        try:
            if u32.IsIconic(target):
                u32.ShowWindow(target, SW_RESTORE)
            foreground = u32.GetForegroundWindow()
            fg_tid = int(u32.GetWindowThreadProcessId(foreground, None)) if foreground else 0
            my_tid = int(k32.GetCurrentThreadId())
            attached = False
            if fg_tid and fg_tid != my_tid:
                attached = bool(u32.AttachThreadInput(fg_tid, my_tid, True))
            try:
                u32.BringWindowToTop(target)
                u32.SetForegroundWindow(target)
            finally:
                if attached:
                    u32.AttachThreadInput(fg_tid, my_tid, False)
        except Exception as exc:                           # noqa: BLE001 - try again, then say no
            warn('focus attempt failed: %r' % (exc,))
        time.sleep(FOCUS_SETTLE)
        if handle_value(u32.GetForegroundWindow()) == handle_value(hwnd):
            return True
    return False


def press_paste_and_enter():
    """Type Ctrl+V, wait, then Enter into the focused window. -> key events accepted.

    Six events in two SendInput calls: Ctrl down, V down, V up, Ctrl up, then Return down
    and Return up. Off Windows (or with a partially accepted batch) it returns fewer than
    six and send() reports 'input blocked' rather than claiming a message went out.
    """
    if not _WIN:
        return 0
    try:
        u32, _k32 = _win32()
    except OSError as exc:                                 # no user32 here: answer, never raise
        warn('keyboard input unavailable: %s' % exc)
        return 0
    paste = _key_batch([(VK_CONTROL, 0), (VK_V, 0), (VK_V, KEYEVENTF_KEYUP),
                        (VK_CONTROL, KEYEVENTF_KEYUP)])
    entered = _key_batch([(VK_RETURN, 0), (VK_RETURN, KEYEVENTF_KEYUP)])
    try:
        sent = int(u32.SendInput(len(paste), paste, ctypes.sizeof(INPUT)))
    except Exception as exc:                               # noqa: BLE001 - answer, never raise
        warn('SendInput failed: %r' % (exc,))
        return 0
    if sent < len(paste):
        return sent
    time.sleep(PASTE_GAP)                                  # let the chat box take the paste
    try:
        return sent + int(u32.SendInput(len(entered), entered, ctypes.sizeof(INPUT)))
    except Exception as exc:                               # noqa: BLE001 - the paste still landed
        warn('SendInput (Enter) failed: %r' % (exc,))
        return sent


def _key_batch(events):
    """A ctypes INPUT array for [(virtual key, flags)] key-down/key-up events."""
    batch = (INPUT * len(events))()
    for index, (vkey, flags) in enumerate(events):
        batch[index].type = INPUT_KEYBOARD
        batch[index].u.ki.wVk = vkey
        batch[index].u.ki.wScan = 0
        batch[index].u.ki.dwFlags = flags
        batch[index].u.ki.time = 0
        batch[index].u.ki.dwExtraInfo = 0
    return batch


# ------------------------------------------------------------------------ rate gates
def clock():
    """Monotonic seconds. Tests and the selftest monkeypatch this name to fake time."""
    return time.monotonic()


def reset():
    """Forget the send history (tests and the selftest only; the dashboard never calls it)."""
    del _SENT[:]
    return _SENT


def recent_sends(now=None):
    """Stamps of the sends still inside the rate window; older stamps are dropped."""
    now = clock() if now is None else now
    inside = [stamp for stamp in _SENT if now - stamp < RATE_WINDOW]
    if len(inside) != len(_SENT):
        _SENT[:] = inside
    return inside


def gate(now=None):
    """'' when one message may go out, else the reason it may not. Never raises."""
    now = clock() if now is None else now
    stamps = recent_sends(now)
    if stamps and now - stamps[-1] < COOLDOWN:
        return R_COOLDOWN
    if len(stamps) >= RATE_MAX:
        return R_RATE
    return ''


def _mark_sent(now=None):
    """Record one message that really left (this is what the gates count)."""
    _SENT.append(clock() if now is None else now)


def sent_count():
    """Messages that really left inside the current rate window."""
    return len(recent_sends())


# ------------------------------------------------------------------------------ log
def utc_stamp():
    """'2026-09-28T11:25:31Z' - the same stamp shape notify.py's ledger uses."""
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def account():
    """The signed-in warframe.market account from data/trader_state.json, '' when unknown."""
    try:
        with open(STATE_PATH, encoding='utf-8') as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return ''
    if isinstance(doc, dict):
        return str(doc.get('account') or '').strip()
    return ''


def atomic_write(path, doc):
    """tmp file + os.replace, so a half-written ledger never lands (house style)."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, indent=1)
    os.replace(tmp, path)


def load(path=None):
    """Every ledger row (list of dicts); unreadable content is moved aside, never dropped."""
    path = path or LOG_PATH
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding='utf-8') as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        spare = '%s.corrupt-%s' % (path, time.strftime('%Y%m%d-%H%M%S', time.gmtime()))
        try:
            os.replace(path, spare)
            print('WARN %s unreadable (%s) - moved aside to %s, starting a fresh ledger'
                  % (rel(path), exc, rel(spare)))
        except OSError:
            print('WARN %s unreadable (%s) - starting a fresh ledger' % (rel(path), exc))
        return []
    if not isinstance(doc, list):
        print('WARN %s is not a JSON list - starting a fresh ledger' % rel(path))
        return []
    return [row for row in doc if isinstance(row, dict)]


def append(row, path=None):
    """Append one row to the ledger (newest LOG_KEEP kept); returns the whole ledger."""
    path = path or LOG_PATH
    rows = load(path)
    rows.append(row)
    if LOG_KEEP > 0 and len(rows) > LOG_KEEP:
        rows = rows[-LOG_KEEP:]
    atomic_write(path, rows)
    return rows


def row_for(mode, copied, sent, reason, item='', price='', kind='', user=None, ts=None):
    """One ledger row: {ts, user?, item, price, kind, mode, copied, sent, reason}."""
    row = {'ts': ts or utc_stamp()}
    who = account() if user is None else str(user or '')
    if who:
        row['user'] = who
    row.update({'item': str(item or ''), 'price': str(price or ''), 'kind': str(kind or ''),
                'mode': mode, 'copied': bool(copied), 'sent': bool(sent),
                'reason': str(reason or '')})
    return row


def record(mode, copied, sent, reason, **fields):
    """Append an attempt to the ledger. Never raises: a bad disk must not break the send."""
    try:
        return append(row_for(mode, copied, sent, reason, **fields))
    except (OSError, ValueError) as exc:
        print('WARN could not write %s: %s' % (rel(LOG_PATH), exc))
        return []


def log_last(n=LOG_LIMIT, path=None):
    """The newest `n` ledger rows, newest first. [] when there is no ledger yet."""
    try:
        count = max(0, int(n))
    except (TypeError, ValueError):
        count = LOG_LIMIT
    rows = load(path)
    return rows[-count:][::-1] if count else []


def rel(path):
    """Path relative to the repo root, forward slashes (falls back to the raw path)."""
    try:
        return os.path.relpath(path, ROOT).replace('\\', '/')
    except ValueError:
        return str(path).replace('\\', '/')


# ------------------------------------------------------------------------------ send
def probe():
    """{'game': bool, 'reason': str} - is the game window there right now?"""
    if not _WIN:
        return {'game': False, 'reason': R_WINDOWS}
    hwnd = find_game()
    return {'game': bool(hwnd), 'reason': R_SENT if hwnd else R_NO_GAME}


def send(text, item=None, price=None, kind=None, user=None):
    """Send ONE whisper into the running game. -> (sent: bool, reason: str)

    reason: '' when it really went out; 'game window not found' (the text IS copied, so the
    UI can offer a manual paste); 'cooldown 2s' / 'rate limit 10 per minute' (a gate
    refused, nothing copied); plus 'windows only', 'empty message', 'clipboard busy',
    'game window not focused' and 'input blocked' for the honest failure cases.

    item/price/kind enrich the ledger row only; without them the row is filled from the
    text itself via parse(). Every call appends exactly one row, refusals included.
    """
    body = '' if text is None else str(text)
    found = parse(body)
    fields = {'item': found.get('item', '') if item is None else item,
              'price': found.get('price', '') if price is None else price,
              'kind': found.get('kind', '') if kind is None else kind,
              'user': user}
    if not body.strip():
        record(MODE_BLOCKED, False, False, R_EMPTY, **fields)
        return False, R_EMPTY
    if not _WIN:
        record(MODE_UNSUPPORTED, False, False, R_WINDOWS, **fields)
        return False, R_WINDOWS

    hwnd = find_game()
    if not hwnd:                                           # copy anyway: click, paste, done
        copied = copy(body)
        reason = R_NO_GAME
        record(MODE_COPY if copied else MODE_BLOCKED, copied, False, reason, **fields)
        return False, reason

    blocked = gate()
    if blocked:
        record(MODE_BLOCKED, False, False, blocked, **fields)
        return False, blocked
    if not copy(body):
        record(MODE_BLOCKED, False, False, R_CLIP, **fields)
        return False, R_CLIP
    if not focus(hwnd):
        record(MODE_COPY, True, False, R_FOCUS, **fields)
        return False, R_FOCUS
    if press_paste_and_enter() < PASTE_EVENTS:
        record(MODE_COPY, True, False, R_INPUT, **fields)
        return False, R_INPUT
    _mark_sent()
    record(MODE_SENT, True, True, R_SENT, **fields)
    return True, R_SENT


# ------------------------------------------------------------------------------- CLI
def count_int(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError('expected an integer, got %r' % text)
    if value <= 0:
        raise argparse.ArgumentTypeError('expected a positive integer, got %r' % text)
    return value


def build_parser():
    parser = argparse.ArgumentParser(
        prog='whisper.py',
        description='One-click warframe.market whisper: copy the line, focus the game, '
                    'type Ctrl+V then Enter. One message per call, never a batch.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='examples:\n'
               '  whisper.py --selftest\n'
               '  whisper.py --message primed_continuity 120 buy --rank 10\n'
               '  whisper.py --send "Hi! I want to buy: \\"Primed Continuity\\" for 120 '
               'platinum. (warframe.market)"\n'
               '  whisper.py --probe\n')
    parser.add_argument('--selftest', action='store_true',
                        help='offline checks: no keystrokes, no game, no network, no real '
                             'ledger writes')
    parser.add_argument('--message', nargs=3, metavar=('ITEM', 'PRICE', 'KIND'), default=None,
                        help='print the whisper line for a slug and price (buy|sell)')
    parser.add_argument('--rank', type=int, default=None,
                        help='item rank, shown inside the quotes as (rank N); rankable orders '
                             'carry 0-10, an unranked part is omitted or None')
    parser.add_argument('--user', metavar='IGN', default=None,
                        help='with --message: print the whole paste, /w <user> included')
    parser.add_argument('--send', metavar='TEXT', default=None,
                        help='send one message for real (copies + types into the game)')
    parser.add_argument('--probe', action='store_true',
                        help='is the game window there right now?')
    parser.add_argument('--log', type=count_int, default=0, metavar='N',
                        help='print the newest N ledger rows and exit')
    return parser


def cmd_probe():
    state = probe()
    print('game window: %s%s' % ('found' if state['game'] else 'not found',
                                 '' if state['game'] else ' (%s)' % state['reason']))
    if _WIN:
        for title in game_titles():
            print('  title match: %s' % title)
    print('sends in the last %ds: %d of %d' % (int(RATE_WINDOW), sent_count(), int(RATE_MAX)))
    latest = log_last(1)
    print('latest row: %s' % (latest[0] if latest else 'none yet'))
    return 0


def cmd_log(count):
    rows = log_last(count)
    if not rows:
        print('no whisper ledger rows yet in %s' % rel(LOG_PATH))
        return 0
    print('whisper ledger: %s (newest first, showing %d)' % (rel(LOG_PATH), len(rows)))
    for row in rows:
        print('%-20s %-4s %-11s %-9s %s' % (row.get('ts'), row.get('kind') or '-',
                                            'copied' if row.get('copied') else 'not copied',
                                            'SENT' if row.get('sent') else 'not sent',
                                            row.get('item') or '(no item)'))
        if row.get('reason'):
            print('    refused: %s' % row['reason'])
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    modes = [bool(args.selftest), args.message is not None, args.send is not None,
             bool(args.probe), bool(args.log)]
    if sum(modes) > 1:
        print('use one of --selftest / --message / --send / --probe / --log at a time')
        return 2
    if args.rank is not None and args.message is None:
        print('--rank needs --message (a raw --send text is used verbatim)')
        return 2
    if args.user is not None and args.message is None:
        print('--user needs --message (a raw --send text already carries its own /w user)')
        return 2
    if args.selftest:
        return selftest()
    if args.probe:
        return cmd_probe()
    if args.log:
        return cmd_log(args.log)
    if args.message is not None:
        slug, price, kind = args.message
        try:
            if args.user:                    # the whole paste, whisper command included
                print(line(args.user, title_for(slug), price, kind, args.rank))
            else:
                print(message(title_for(slug), price, kind, args.rank))
        except ValueError as exc:
            print(str(exc))
            return 2
        return 0
    if args.send is not None:
        sent, reason = send(args.send)
        print('sent' if sent else 'not sent (%s)' % reason)
        return 0 if sent else 1
    build_parser().print_help()
    return 2


# -------------------------------------------------------------------------- selftest
class _FakeClock:
    """A controllable stand-in for whisper.clock() (the gates must be provable offline)."""

    def __init__(self, start=1000.0):
        self.t = float(start)

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += float(seconds)
        return self.t


def selftest():
    """Offline checks. Never types a key, never needs the game, never writes the real ledger.

    The keystroke half is exercised through the module's own seams (find_game / copy /
    focus / press_paste_and_enter are swapped for stubs), so running this with the game
    OPEN is safe: nothing is sent into it, and the clipboard text is put back.
    """
    results = []
    skipped = 0

    def check(label, ok, detail=''):
        ok = bool(ok)
        results.append(ok)
        print('%s  %s%s' % ('PASS' if ok else 'FAIL', label, (' - %s' % detail) if detail else ''))
        return ok

    def skip(label, why):
        nonlocal skipped
        skipped += 1
        print('SKIP  %s - %s' % (label, why))

    tmp = tempfile.mkdtemp(prefix='whisper_selftest_')
    real_ledger = LOG_PATH
    ledger_existed = os.path.exists(real_ledger)
    saved = {'LOG_PATH': LOG_PATH, 'STATE_PATH': STATE_PATH, 'clock': clock, 'find_game': find_game,
             'copy': copy, 'focus': focus, 'press_paste_and_enter': press_paste_and_enter,
             '_WIN': _WIN, 'sent': list(_SENT)}
    globals()['LOG_PATH'] = os.path.join(tmp, 'whisper_log.json')
    globals()['STATE_PATH'] = os.path.join(tmp, 'trader_state.json')
    try:
        # --- message ---------------------------------------------------------------
        check('message: buying line is exact',
              message('Primed Continuity', 120, 'buy')
              == 'Hi! I want to buy: "Primed Continuity" for 120 platinum. (warframe.market)',
              message('Primed Continuity', 120, 'buy'))
        check('message: selling line is exact',
              message('Neo D3 Relic', 7, 'sell')
              == 'Hi! I am selling: "Neo D3 Relic" for 7 platinum. (warframe.market)',
              message('Neo D3 Relic', 7, 'sell'))
        check('message: the rank rides inside the quotes, like the site',
              message('Primed Continuity', 120, 'sell', 10)
              == 'Hi! I am selling: "Primed Continuity (rank 10)" for 120 platinum. '
                 '(warframe.market)',
              message('Primed Continuity', 120, 'sell', 10))
        check('message: rank 0 shows too (Necramech Flow (rank 0)), None shows nothing',
              message('Primed Continuity', 120, 'buy', 0)
              == 'Hi! I want to buy: "Primed Continuity (rank 0)" for 120 platinum. '
                 '(warframe.market)'
              and message('Primed Continuity', 120, 'buy')
              == message('Primed Continuity', 120, 'buy', None)
              == 'Hi! I want to buy: "Primed Continuity" for 120 platinum. (warframe.market)')
        check('message: rank 10 and rank 0 differ',
              '(rank 10)' in message('X', 1, 'buy', 10)
              and '(rank 0)' in message('X', 1, 'buy', 0)
              and message('X', 1, 'buy', 10) != message('X', 1, 'buy', 0))
        check('line: the whisper command is part of the paste',
              line('Quersus_', 'Primed Continuity', 120, 'buy', 10)
              == '/w Quersus_ Hi! I want to buy: "Primed Continuity (rank 10)" for 120 '
                 'platinum. (warframe.market)'
              and parse(line('Quersus_', 'Primed Continuity', 120, 'buy', 10))
              == {'kind': 'buy', 'item': 'Primed Continuity', 'price': '120',
                  'rank': 10, 'user': 'Quersus_'})
        check('line: a missing user is refused, never sent to the open channel',
              _raises(ValueError, line, '', 'X', 1, 'buy')
              and _raises(ValueError, line, '   ', 'X', 1, 'buy'))
        check('message: kind aliases (buying/selling/wtb/wts) agree',
              message('X', 5, 'buying') == message('X', 5, 'buy') == message('X', 5, 'WTB')
              and message('X', 5, 'selling') == message('X', 5, 'sell')
              == message('X', 5, 'wts'))
        check('message: a junk kind raises ValueError',
              _raises(ValueError, message, 'X', 5, 'trade'))
        check('message: a JSON float price prints as an integer',
              message('X', 120.0, 'buy') == message('X', 120, 'buy')
              and message('X', 7.5, 'buy').count('7.5') == 1)
        check('message: a rank string and a rank float both work',
              message('X', 5, 'buy', '10') == message('X', 5, 'buy', 10.0)
              == message('X', 5, 'buy', 10))
        check('parse: message() round-trips item/price/kind/rank',
              parse(message('Primed Continuity', 120, 'sell', 10))
              == {'kind': 'sell', 'item': 'Primed Continuity', 'price': '120', 'rank': 10}
              and parse(message('Neo D3 Relic', 7, 'buy')) == {
                  'kind': 'buy', 'item': 'Neo D3 Relic', 'price': '7', 'rank': None})
        check('parse: junk and empty text give {}',
              parse('not a whisper') == {} and parse('') == {} and parse(None) == {})
        check('parse: the rank-inside-quotes spelling is accepted too',
              parse('Hi! I want to buy: "X rank 3" for 9 platinum. (warframe.market)')
              == {'kind': 'buy', 'item': 'X', 'price': '9', 'rank': 3})
        check('title_for: a slug becomes a display name',
              title_for('primed_continuity') == 'Primed Continuity'
              and title_for('hildryn-prime-chassis-blueprint')
              == 'Hildryn Prime Chassis Blueprint')

        # --- clipboard round-trip --------------------------------------------------
        if not _WIN:
            skip('clipboard round-trip', 'needs Windows')
        else:
            keep = read()
            try:
                marker = 'wfm whisper selftest %d' % os.getpid()
                wrote, back = copy(marker), read()
                check('clipboard: copy() then read() returns the same text',
                      wrote is True and back == marker, repr(back))
                check('clipboard: unicode survives the round-trip',
                      copy('WTS "Hildryn Prime Chassis Blueprint" 9p \u2014 ok')
                      and read() == 'WTS "Hildryn Prime Chassis Blueprint" 9p \u2014 ok')
            finally:
                if keep is not None:
                    copy(keep)
                    check('clipboard: the previous clipboard text was put back', read() == keep)
                else:
                    skip('clipboard restore', 'the clipboard held no text to restore')

        # --- send without the game, then with stubbed Win32 -------------------------
        # The platform flag is forced True for this block so the whole pipeline runs on any
        # host (the Linux CI runner included): every Win32 seam below is a stub, so this
        # touches no DLL, no clipboard and no keyboard.
        text = message('Primed Continuity', 120, 'buy')
        fake = _FakeClock()
        globals()['clock'] = fake
        globals()['_WIN'] = True
        reset()
        try:
            globals()['find_game'] = lambda: None           # provable, and safe with the game ON
            globals()['copy'] = lambda text: True           # ... and no real clipboard either
            sent, reason = send(text)
            check('send: no game window -> (False, "game window not found")',
                  (sent, reason) == (False, R_NO_GAME))
            rows = load()
            check('send: that attempt is logged as a copy-only row',
                  len(rows) == 1 and rows[0]['mode'] == MODE_COPY and rows[0]['copied'] is True
                  and rows[0]['sent'] is False and rows[0]['reason'] == R_NO_GAME
                  and rows[0]['item'] == 'Primed Continuity' and rows[0]['price'] == '120'
                  and rows[0]['kind'] == 'buy')
            check('send: an empty message is refused and logged',
                  send('  ') == (False, R_EMPTY) and load()[-1]['reason'] == R_EMPTY
                  and load()[-1]['mode'] == MODE_BLOCKED)
            check('probe: exactly {game, reason}, and honest with no game',
                  set(probe()) == {'game', 'reason'} and probe()['game'] is False
                  and probe()['reason'] == R_NO_GAME)

            calls = []
            globals()['find_game'] = lambda: 4242
            globals()['copy'] = lambda text: calls.append(('copy', text)) or True
            globals()['focus'] = lambda hwnd: calls.append(('focus', hwnd)) or True
            globals()['press_paste_and_enter'] = lambda: calls.append(('keys',)) or 6
            fake.advance(COOLDOWN)
            check('send: a full run copies, focuses, types, and says it went out',
                  send(text) == (True, R_SENT)
                  and calls == [('copy', text), ('focus', 4242), ('keys',)])
            check('send: the sent row is mode "sent" with copied+sent true and no reason',
                  load()[-1]['mode'] == MODE_SENT and load()[-1]['copied'] is True
                  and load()[-1]['sent'] is True and load()[-1]['reason'] == '')
            fake.advance(COOLDOWN)
            check('send: a refused focus is reported, never typed blind',
                  _swapped({'focus': lambda hwnd: False}, lambda: send(text) == (False, R_FOCUS))
                  and load()[-1]['copied'] is True and load()[-1]['mode'] == MODE_COPY)
            fake.advance(COOLDOWN)
            check('send: a refused SendInput is reported too',
                  _swapped({'press_paste_and_enter': lambda: 0},
                           lambda: send(text) == (False, R_INPUT)))
            fake.advance(COOLDOWN)
            check('send: a partially accepted batch is not counted as sent',
                  _swapped({'press_paste_and_enter': lambda: 4},
                           lambda: send(text) == (False, R_INPUT)))
            fake.advance(COOLDOWN)
            check('send: a busy clipboard is reported (nothing copied)',
                  _swapped({'copy': lambda text: False}, lambda: send(text) == (False, R_CLIP))
                  and load()[-1]['copied'] is False)

            # --- the gates, on the fake clock ---------------------------------------
            reset()
            check('gate: the first message is allowed', gate() == '')
            send(text)
            check('gate: a second message inside 2s -> "cooldown 2s"',
                  send(text) == (False, R_COOLDOWN) and gate() == R_COOLDOWN
                  and R_COOLDOWN == 'cooldown 2s')
            check('gate: a refused message is logged with nothing copied',
                  load()[-1]['mode'] == MODE_BLOCKED and load()[-1]['copied'] is False
                  and load()[-1]['sent'] is False)
            fake.advance(COOLDOWN)
            check('gate: exactly 2s later the cooldown is over', gate() == '')
            reset()
            bursts = []
            for _ in range(RATE_MAX + 1):                   # 10 sends, 2s apart, inside a minute
                fake.advance(COOLDOWN)
                bursts.append(send(text)[1])
            check('gate: 10 sends leave, the 11th is "rate limit 10 per minute"',
                  bursts == [R_SENT] * RATE_MAX + [R_RATE] and sent_count() == RATE_MAX
                  and R_RATE == 'rate limit 10 per minute',
                  '%d sent, then %r' % (bursts.count(R_SENT), bursts[-1]))
            fake.advance(RATE_WINDOW + 0.1)
            check('gate: a minute later the window has rolled over',
                  gate() == '' and sent_count() == 0 and send(text) == (True, R_SENT))
        finally:
            for name in ('find_game', 'copy', 'focus', 'press_paste_and_enter', 'clock', '_WIN'):
                globals()[name] = saved[name]

        # --- non-Windows behaviour (real seams, only the platform flag flipped) -----
        reset()
        try:
            globals()['_WIN'] = False
            check('off Windows: copy/find_game/read/probe/send answer with a reason, no raise',
                  copy('x') is False and find_game() is None and read() is None
                  and probe() == {'game': False, 'reason': R_WINDOWS}
                  and send(text) == (False, R_WINDOWS)
                  and load()[-1]['mode'] == MODE_UNSUPPORTED
                  and load()[-1]['reason'] == R_WINDOWS)
            check('off Windows: windows() is empty and message() still works',
                  windows() == [] and message('X', 1, 'buy').endswith('(warframe.market)'))
        finally:
            globals()['_WIN'] = saved['_WIN']

        # --- ledger ----------------------------------------------------------------
        globals()['LOG_PATH'] = os.path.join(tmp, 'capped.json')
        for index in range(LOG_KEEP + 5):
            append(row_for(MODE_SENT, True, True, '', item='row %d' % index))
        on_disk = load()
        check('ledger: the newest %d rows are kept, the older ones dropped' % LOG_KEEP,
              len(on_disk) == LOG_KEEP and on_disk[0]['item'] == 'row 5'
              and on_disk[-1]['item'] == 'row %d' % (LOG_KEEP + 4))
        check('ledger: no .tmp file is left behind (atomic write)',
              'capped.json' in os.listdir(tmp) and 'capped.json.tmp' not in os.listdir(tmp))
        check('ledger: log_last() is newest first and honours n',
              [r['item'] for r in log_last(3)] == ['row %d' % (LOG_KEEP + 4),
                                                   'row %d' % (LOG_KEEP + 3),
                                                   'row %d' % (LOG_KEEP + 2)]
              and log_last(0) == [] and len(log_last()) == LOG_LIMIT)
        shaped = row_for(MODE_SENT, True, True, '', item='u', user='RoyalSpartanIIX')
        check('ledger: row shape is {ts, user?, item, price, kind, mode, copied, sent, reason}',
              list(shaped) == ['ts', 'user', 'item', 'price', 'kind', 'mode', 'copied', 'sent',
                               'reason'] and shaped['ts'].endswith('Z')
              and list(row_for(MODE_SENT, True, True, '')) == ['ts', 'item', 'price', 'kind',
                                                               'mode', 'copied', 'sent',
                                                               'reason'])
        check('ledger: account() is "" when the state file is missing',
              account() == '' and not os.path.exists(STATE_PATH))
        _write_json(STATE_PATH, {'account': ' TestAcct ', 'orders': {}})
        check('ledger: account() fills the user field from data/trader_state.json',
              account() == 'TestAcct' and row_for(MODE_SENT, True, True, '')['user'] == 'TestAcct')
        with open(LOG_PATH, 'w', encoding='utf-8') as fh:
            fh.write('{ not json')
        check('ledger: a corrupt ledger is moved aside, not dropped',
              load() == [] and any('corrupt' in name for name in os.listdir(tmp)))
        check('ledger: log_last() on an absent file is an empty list, not an error',
              log_last(5, path=os.path.join(tmp, 'nope.json')) == [])
        _write_json(os.path.join(tmp, 'obj.json'), {'a': 1})
        check('ledger: a non-list ledger does not raise',
              load(os.path.join(tmp, 'obj.json')) == [])

        # --- the Win32 pieces -------------------------------------------------------
        if _WIN:
            size = size_of_input()
            check('input: sizeof(INPUT) is what SendInput expects (40 bytes on x64)',
                  size in (40, 28), '%d bytes' % size)
            check('input: KEYBDINPUT offsets are wVk=0, wScan=2, dwFlags=4; union aligned',
                  (KEYBDINPUT.wVk.offset, KEYBDINPUT.wScan.offset,
                   KEYBDINPUT.dwFlags.offset) == (0, 2, 4)
                  and INPUT.u.offset == (8 if size == 40 else 4))
            check('input: the Ctrl+V batch is four events, key-up flagged where it should be',
                  _batch_shape() == [(VK_CONTROL, 0), (VK_V, 0), (VK_V, KEYEVENTF_KEYUP),
                                     (VK_CONTROL, KEYEVENTF_KEYUP)])
            check('windows: EnumWindows really runs (no game here, nothing matched)',
                  isinstance(windows(), list) and find_game() is None)
            ok, detail = _import_is_inert()
            check('import: a fresh interpreter loads this file with ctypes.WinDLL disarmed'
                  ' (no DLL, no clipboard, no key)', ok, detail)
        else:
            skip('input: sizeof(INPUT) probe', 'needs Windows')
            skip('import: import-inertness probe', 'needs Windows')

        # --- CLI wiring -------------------------------------------------------------
        parser = build_parser()
        check('cli: the flags are wired up',
              parser.parse_args(['--selftest']).selftest is True
              and parser.parse_args(['--message', 'a', '1', 'buy', '--rank', '10']).rank == 10
              and parser.parse_args(['--probe']).probe is True
              and parser.parse_args(['--send', 'x']).send == 'x')
        check('cli: an unknown kind is a clean error, not a traceback',
              _quiet(main, ['--message', 'x', '1', 'trade']) == 2)
        check('cli: --message prints the exact line',
              _capture(main, ['--message', 'primed_continuity', '120', 'buy', '--rank', '10'])
              == 'Hi! I want to buy: "Primed Continuity (rank 10)" for 120 platinum. '
                 '(warframe.market)\n'
              and _capture(main, ['--message', 'primed_continuity', '120', 'buy',
                                  '--rank', '10', '--user', 'Quersus_'])
              == '/w Quersus_ Hi! I want to buy: "Primed Continuity (rank 10)" for 120 '
                 'platinum. (warframe.market)\n')
        check('cli: one mode at a time, and --rank needs --message',
              _quiet(main, ['--selftest', '--probe']) == 2
              and _quiet(main, ['--rank', '3']) == 2 and _quiet(main, []) == 2
              and _raises(SystemExit, _quiet, main, ['--log', '0']))
    finally:
        for name, value in saved.items():
            if name != 'sent':
                globals()[name] = value
        _SENT[:] = saved['sent']
        shutil.rmtree(tmp, ignore_errors=True)

    check('the real data/whisper_log.json was not written by the selftest',
          os.path.exists(real_ledger) == ledger_existed)
    failed = results.count(False)
    print('selftest %s (%d checks, %d failed%s) - no keystrokes, no game, no network'
          % ('OK' if not failed else 'FAILED', len(results), failed,
             ', %d skipped' % skipped if skipped else ''))
    return 0 if not failed else 1


def _swapped(seams, call):
    """Call() with module globals swapped for stand-ins, restored afterwards."""
    saved = {name: globals()[name] for name in seams}
    globals().update(seams)
    try:
        return call()
    finally:
        globals().update(saved)


def _batch_shape():
    """[(vk, flags)] read back off a built INPUT batch - proves the array really is wired."""
    events = [(VK_CONTROL, 0), (VK_V, 0), (VK_V, KEYEVENTF_KEYUP), (VK_CONTROL, KEYEVENTF_KEYUP)]
    built = _key_batch(events)
    return [(int(row.u.ki.wVk), int(row.u.ki.dwFlags)) for row in built]


def _import_is_inert():
    """Import this file in a fresh interpreter whose ctypes.WinDLL raises. -> (ok, detail).

    Proves the import path opens nothing: if a DLL were loaded while the module was exec'd
    the probe would die instead of printing IMPORT_OK.
    """
    probe = (
        'import ctypes, importlib.util, sys\n'
        'def _boom(*a, **k):\n'
        '    raise AssertionError("a Win32 library was loaded at import time")\n'
        'ctypes.WinDLL = _boom\n'
        'spec = importlib.util.spec_from_file_location("whisper_import_probe", sys.argv[1])\n'
        'mod = importlib.util.module_from_spec(spec)\n'
        'spec.loader.exec_module(mod)\n'
        'assert mod.loaded_libs() == [], "loaded_libs() is not empty after import"\n'
        'print("IMPORT_OK")\n'
    )
    try:
        proc = subprocess.run([sys.executable, '-c', probe, os.path.abspath(__file__)],
                              cwd=ROOT, capture_output=True, text=True, timeout=60,
                              encoding='utf-8', errors='replace',
                              creationflags=0x08000000 if _WIN else 0)
    except Exception as exc:                               # noqa: BLE001
        return False, repr(exc)[:120]
    out = ((proc.stdout or '') + (proc.stderr or '')).strip()
    return ('IMPORT_OK' in out and proc.returncode == 0), (out.splitlines() or [''])[-1][:120]


def _raises(exc, fn, *args):
    try:
        fn(*args)
    except exc:
        return True
    except Exception:                                      # noqa: BLE001
        return False
    return False


def _capture(fn, argv):
    """Stdout of fn(argv) as a string (the selftest prints a lot; keep it out of the way)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        fn(argv)
    return buf.getvalue()


def _quiet(fn, argv):
    """fn(argv)'s return value, with its stdout/stderr swallowed."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        return fn(argv)


def _write_json(path, obj):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
