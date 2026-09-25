#!/usr/bin/env python3
r"""System-tray widget for the WFM dashboard (stdlib only, Windows, ctypes).

Menu (right-click; left-click opens the dashboard):
    Open dashboard        http://127.0.0.1:8787/ in the default browser
    Rebuild plan (lister) detached `pythonw scripts/trader/lister.py`
    Run detector          detached `pythonw scripts/trader/detector.py`
    Kill switch: arm|disarm
                          `python scripts/trader/killswitch.py --on|--off` in a worker
                          thread; the menu label, tooltip, balloon and icon colour follow
                          the state that is actually on disk afterwards
    Quit tray

The icon is a 32x32 RGBA PNG built here pixel by pixel (accent diamond on a dark disc -
orange while the kill switch is off, red while it is armed), wrapped in a one-image .ico
and handed to the shell with CreateIconFromResourceEx. No image library, no icon file on
disk; a temp .ico is only written if that call fails, and LoadIconW(IDI_APPLICATION) is the
last resort.

The shell side is a hidden message window: RegisterClassW + CreateWindowExW +
Shell_NotifyIconW(NIM_ADD / NIM_MODIFY / NIM_DELETE) + a GetMessageW pump, all through
ctypes. The window is re-added if Explorer restarts ("TaskbarCreated").

State: read-only observer of data/kill_switch.json. The semantics mirror
scripts/trader/killswitch.py - absent file reads as off, an unreadable or unparsable file
reads as fail-closed ARMED - and killswitch.py stays the only writer (arming goes through
its CLI as a subprocess, never through this file).

Usage:
  pythonw scripts/tray.py                the widget (no console window)
  python  scripts/tray.py --smoke        really create the tray, then quit after 3s
  python  scripts/tray.py --log PATH     also append messages to PATH (useful under pythonw)
  python  scripts/tray.py --selftest     offline checks: no tray, no window, no DLL load,
                                         no subprocess, no network, no writes

Importing this module has no side effects: no window class, no DLL, no thread, no process.
Everything Win32 lives behind `os.name == 'nt'`, so the file also imports on Linux (the byte,
menu and state helpers are cross-platform and are what tests/test_tray.py exercises in CI).

Exit codes: 0 = ok / selftest passed, 1 = failed, 2 = bad args.
"""
import argparse
import ctypes
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
TRADER_DIR = os.path.join(ROOT, 'scripts', 'trader')
KILL_SWITCH_PATH = os.path.join(DATA, 'kill_switch.json')      # same file killswitch.py owns
KILL_SWITCH_NOTE = 'set from the tray'
DASHBOARD_PORT = 8787                                          # server.py's WFM_PORT default
SMOKE_MS = 3000                                                # --smoke self-quit delay
KILLSWITCH_TIMEOUT = 60                                        # its preflight reads the save
ICON_SIZE = 32
ICON_UID = 1
LOG_PATH = ''                                                  # set by --log
_WIN = os.name == 'nt'
_TRAY_CREATED = False                                          # flips in Tray.create only


# --------------------------------------------------------------------------- messages
def say(*parts):
    """print() that survives pythonw (where sys.stdout is None) and never raises."""
    text = ' '.join(str(p) for p in parts)
    try:
        if sys.stdout is not None:
            print(text)
    except Exception:
        pass
    if LOG_PATH:
        try:
            with open(LOG_PATH, 'a', encoding='utf-8') as fh:
                fh.write('%s %s\n' % (time.strftime('%Y-%m-%dT%H:%M:%S'), text))
        except OSError:
            pass


# ------------------------------------------------------------------------------- icon
ACCENT_OFF = (240, 158, 56)        # orange diamond: kill switch off
ACCENT_ARMED = (232, 72, 60)       # red diamond: kill switch armed
DISC = (18, 22, 30)                # dark slate disc
PNG_MAGIC = b'\x89PNG\r\n\x1a\n'
PNG_COLOR_RGBA = 6
PNG_BITDEPTH = 8
ICO_TYPE_ICON = 1
ICON_DIR_SIZE = 6
ICON_ENTRY_SIZE = 16
ICO_HEADER_SIZE = ICON_DIR_SIZE + ICON_ENTRY_SIZE              # 22


def icon_pixels(size=ICON_SIZE, accent=ACCENT_OFF):
    """RGBA rows (top-down) for the tray icon: an accent diamond on a dark disc.

    Hand-rasterised: every pixel is sampled on a 2x2 sub-grid, so the disc edge fades from
    alpha 0 to 255 and the diamond edge is smooth. The rim just inside the disc edge is the
    accent dimmed to 55%, which keeps both the off and the armed icon readable at 32px.
    """
    rim = tuple(int(c * 0.55) for c in accent)
    centre = size / 2.0
    r_out = size * 0.46
    r_rim2 = (r_out - max(1.0, size / 16.0)) ** 2
    r_out2 = r_out * r_out
    half = size * 0.30                                        # diamond radius, |dx|+|dy|
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            tot_r = tot_g = tot_b = cov = 0
            for sy in (0.25, 0.75):
                for sx in (0.25, 0.75):
                    dx = x + sx - centre
                    dy = y + sy - centre
                    dist2 = dx * dx + dy * dy
                    if dist2 > r_out2:
                        continue                                  # outside the disc
                    cov += 1
                    if abs(dx) + abs(dy) <= half:
                        rgb = accent
                    elif dist2 > r_rim2:
                        rgb = rim
                    else:
                        rgb = DISC
                    tot_r += rgb[0]
                    tot_g += rgb[1]
                    tot_b += rgb[2]
            if not cov:
                row += b'\x00\x00\x00\x00'
            else:
                row += bytes((tot_r // cov, tot_g // cov, tot_b // cov, cov * 255 // 4))
        rows.append(bytes(row))
    return rows


def _png_chunk(tag, data):
    return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)


def png_bytes(size=ICON_SIZE, accent=ACCENT_OFF):
    """A valid 8-bit RGBA PNG (colour type 6, no interlace) built with struct + zlib only."""
    raw = b''.join(b'\x00' + row for row in icon_pixels(size, accent))
    ihdr = struct.pack('>IIBBBBB', size, size, PNG_BITDEPTH, PNG_COLOR_RGBA, 0, 0, 0)
    return (PNG_MAGIC + _png_chunk(b'IHDR', ihdr) + _png_chunk(b'IDAT', zlib.compress(raw, 9))
            + _png_chunk(b'IEND', b''))


def ico_bytes(size=ICON_SIZE, accent=ACCENT_OFF):
    """A one-image .ico wrapping the PNG payload (PNG-in-ICO works on Windows Vista+).

    Layout: ICONDIR (reserved=0, type=1, count=1) + ICONDIRENTRY (width, height, colourCount
    0, reserved 0, planes 1, bitCount 32, bytesInRes = len(png), imageOffset = 22) + png.
    bytesInRes must be the PNG length - the shell uses it to find the image data, so a zero
    there would describe an empty image. A 256px image is recorded as 0 per the .ico spec.
    """
    png = png_bytes(size, accent)
    dim = size & 0xFF
    entry = struct.pack('<BBBBHHII', dim, dim, 0, 0, 1, 32, len(png), ICO_HEADER_SIZE)
    return struct.pack('<HHH', 0, ICO_TYPE_ICON, 1) + entry + png


def parse_ico(data):
    """Parse a one-image PNG-in-ICO. -> {'width', 'height', 'bpp', 'png', 'offset', ...}

    Used by --selftest and tests/test_tray.py to prove the writer's byte layout round-trips.
    Raises ValueError on anything malformed.
    """
    if len(data) < ICO_HEADER_SIZE or data[:4] != b'\x00\x00\x01\x00':
        raise ValueError('not a one-image icon file')
    reserved, kind, count = struct.unpack('<HHH', data[:ICON_DIR_SIZE])
    if kind != ICO_TYPE_ICON:
        raise ValueError('type is not 1 (icon): %d' % kind)
    if count != 1:
        raise ValueError('expected exactly 1 image, got %d' % count)
    dim_w, dim_h, colors, _res, planes, bpp, nbytes, offset = struct.unpack(
        '<BBBBHHII', data[ICON_DIR_SIZE:ICO_HEADER_SIZE])
    if offset + nbytes > len(data):
        raise ValueError('image data runs past the end of the file')
    return {'reserved': reserved, 'type': kind, 'count': count, 'width': dim_w or 256,
            'height': dim_h or 256, 'colors': colors, 'planes': planes, 'bpp': bpp,
            'bytes_in_res': nbytes, 'offset': offset, 'png': data[offset:offset + nbytes]}


def parse_png(data):
    """Parse our PNG: IHDR + IDAT + IEND with every CRC verified. -> dict (incl. 'raw').

    'raw' is the inflated filtered scanline stream, so length is height * (1 + width * 4)
    for 8-bit RGBA. Raises ValueError on anything malformed.
    """
    if data[:8] != PNG_MAGIC:
        raise ValueError('bad PNG signature')
    pos, chunks, ihdr, idat = 8, [], None, b''
    while pos + 8 <= len(data):
        length = struct.unpack('>I', data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        crc = struct.unpack('>I', data[pos + 8 + length:pos + 12 + length])[0]
        if zlib.crc32(tag + body) & 0xFFFFFFFF != crc:
            raise ValueError('CRC mismatch on %r' % tag)
        chunks.append(tag)
        if tag == b'IHDR':
            ihdr = body
        elif tag == b'IDAT':
            idat += body
        pos += 12 + length
    if ihdr is None or not chunks or chunks[0] != b'IHDR' or chunks[-1] != b'IEND':
        raise ValueError('chunk order is not IHDR..IEND: %r' % chunks)
    width, height, depth, color, comp, filt, interlace = struct.unpack('>IIBBBBB', ihdr)
    return {'width': width, 'height': height, 'bitdepth': depth, 'colortype': color,
            'compression': comp, 'filter': filt, 'interlace': interlace, 'chunks': chunks,
            'raw': zlib.decompress(idat)}


# --------------------------------------------------------------------------- commands
def python_path(exe=None):
    """A console python.exe next to the running interpreter (the killswitch CLI wants one)."""
    return _sibling_exe('python.exe', exe)


def pythonw_path(exe=None):
    """pythonw.exe next to the running interpreter - how the engines are launched."""
    return _sibling_exe('pythonw.exe', exe)


def _sibling_exe(name, exe=None):
    exe = exe or sys.executable or ''
    if os.path.basename(exe).lower() == name:
        return exe
    cand = os.path.join(os.path.dirname(exe), name)
    return cand if os.path.exists(cand) else exe


def engine_command(engine):
    """argv for one trader engine, launched under pythonw (no console window)."""
    return [pythonw_path(), os.path.join(TRADER_DIR, str(engine) + '.py')]


def killswitch_command(active, note=KILL_SWITCH_NOTE):
    """argv for the killswitch CLI - the only writer of data/kill_switch.json."""
    return [python_path(), os.path.join(TRADER_DIR, 'killswitch.py'),
            '--on' if active else '--off', '--note', str(note)]


def dashboard_url():
    """Dashboard root; WFM_PORT (the env var server.py reads) overrides the 8787 default."""
    try:
        port = int(os.environ.get('WFM_PORT') or 0)
    except ValueError:
        port = 0
    return 'http://127.0.0.1:%d/' % (port if port > 0 else DASHBOARD_PORT)


def spawn_engine(engine):
    """Start an engine detached (pythonw, no console, survives the tray). -> result dict."""
    cmd = engine_command(engine)
    if not os.path.exists(cmd[1]):
        return {'ok': False, 'pid': None, 'cmd': cmd, 'error': 'missing %s' % cmd[1]}
    try:
        proc = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                close_fds=True,
                                creationflags=0x00000008 | 0x08000000 if _WIN else 0)
    except Exception as e:                                     # noqa: BLE001 - report, never raise
        return {'ok': False, 'pid': None, 'cmd': cmd, 'error': repr(e)[:200]}
    return {'ok': True, 'pid': proc.pid, 'cmd': cmd, 'error': None}


def run_killswitch(active, timeout=KILLSWITCH_TIMEOUT):
    """Arm/disarm through the killswitch CLI. -> {'ok', 'code', 'cmd', 'tail', 'error'}.

    Never raises and never touches the state file itself; the caller re-reads the state to
    confirm what actually landed.
    """
    cmd = killswitch_command(active)
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                              encoding='utf-8', errors='replace',
                              creationflags=0x08000000 if _WIN else 0)
    except Exception as e:                                     # noqa: BLE001
        return {'ok': False, 'code': None, 'cmd': cmd, 'tail': '', 'error': repr(e)[:200]}
    lines = [ln.strip() for ln in (proc.stdout or '').splitlines() if ln.strip()]
    return {'ok': proc.returncode == 0, 'code': proc.returncode, 'cmd': cmd,
            'tail': lines[0] if lines else '', 'error': None if proc.returncode == 0 else
            'exit %s' % proc.returncode}


# ------------------------------------------------------------------------ kill switch
def _kill_path():
    """State-file path; KILL_SWITCH_PATH (env, same var killswitch.py reads) overrides."""
    return os.environ.get('KILL_SWITCH_PATH') or KILL_SWITCH_PATH


def read_kill_switch(path=None):
    """{'active', 'note', 'ts', 'source', 'error'} for data/kill_switch.json. Never raises.

    Read-only: this file is never created or written here, killswitch.py owns it.
    Mirrors killswitch.state(): 'absent' reads as off, anything unreadable or unparsable
    reads as fail-closed ARMED so a broken safety switch can never look disarmed.
    """
    p = path or _kill_path()
    try:
        with open(p, encoding='utf-8') as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        return {'active': False, 'note': '', 'ts': 0, 'source': 'absent', 'error': None}
    except Exception as e:                                     # noqa: BLE001
        return {'active': True, 'note': 'state file unreadable - fail-closed', 'ts': 0,
                'source': 'fail_closed', 'error': repr(e)[:160]}
    if not isinstance(doc, dict) or not isinstance(doc.get('active'), bool):
        return {'active': True, 'note': 'state file corrupt - fail-closed', 'ts': 0,
                'source': 'fail_closed', 'error': 'active is not a bool'}
    try:
        ts = int(doc.get('ts') or 0)
    except (TypeError, ValueError):
        ts = 0
    return {'active': doc['active'], 'note': str(doc.get('note') or ''), 'ts': ts,
            'source': 'file', 'error': None}


class KillSwitchGate:
    """Runs one kill-switch command at a time; a click during a run wins as the next target.

    The CLI takes a moment (its preflight reads the game save), so clicks must not block the
    message loop and must not be silently dropped: the newest target requested while a run is
    in flight replaces any older pending one and starts as soon as the current run lands.
    Win32-free and runner-injectable, so tests exercise the whole dance with a stub.
    """

    def __init__(self, runner, on_done):
        self._runner = runner                                  # callable(target) -> result
        self._on_done = on_done                                # callable(target, result)
        self._lock = threading.Lock()
        self._busy = False
        self._pending = None

    @property
    def busy(self):
        """True while a command is running (a queued target counts as running)."""
        return self._busy

    @property
    def pending(self):
        """The target waiting for the current run to finish (None when idle)."""
        return self._pending

    def request(self, target):
        """Queue `target`. -> True when it started now, False when it was queued behind one."""
        target = bool(target)
        with self._lock:
            if self._busy:
                self._pending = target
                return False
            self._busy = True
        self._start(target)
        return True

    def _start(self, target):
        threading.Thread(target=self._run, args=(target,), name='tray-killswitch',
                         daemon=True).start()

    def _run(self, target):
        result = self._runner(target)
        with self._lock:
            pending, self._pending = self._pending, None
            self._busy = pending is not None
        try:
            self._on_done(target, result)
        finally:
            if pending is not None:
                self._start(pending)


# ------------------------------------------------------------------------------- menu
MENU_SEPARATOR = 0
MENU_OPEN, MENU_REBUILD, MENU_DETECT, MENU_KILL, MENU_QUIT = 1, 2, 3, 4, 5
ACTIONS = {MENU_OPEN: 'open_dashboard', MENU_REBUILD: 'rebuild_plan',
           MENU_DETECT: 'run_detector', MENU_KILL: 'kill_switch_toggle', MENU_QUIT: 'quit'}


def menu_items(kill_active):
    """[(cmd_id, label, enabled)] for the popup menu; cmd_id 0 is a separator.

    Pure and Win32-free, so --selftest and tests/test_tray.py can assert the exact menu
    (labels included) without a desktop, a window or a running tray.
    """
    return [
        (MENU_OPEN, 'Open dashboard', True),
        (MENU_REBUILD, 'Rebuild plan (lister)', True),
        (MENU_DETECT, 'Run detector', True),
        (MENU_SEPARATOR, None, True),
        (MENU_KILL, 'Kill switch: disarm (ARMED)' if kill_active else 'Kill switch: arm', True),
        (MENU_SEPARATOR, None, True),
        (MENU_QUIT, 'Quit tray', True),
    ]


def action_for(cmd):
    """Menu command id -> action name (None for separators and unknown ids)."""
    try:
        return ACTIONS.get(int(cmd))
    except (TypeError, ValueError):
        return None


def tip_text(kill_active):
    """Tray tooltip (szTip is 128 wide chars; stay under it)."""
    state = 'KILL SWITCH ARMED' if kill_active else 'kill switch off'
    return ('WFM dashboard - %s' % state)[:127]


def tray_event(lparam):
    """Mouse/action id from a NOTIFYICON_VERSION_4/3 tray callback.

    Versions 3 and 4 pack the message into the LOWORD of lParam (HIGHORD = icon id); the
    original version 0 callback passed the message itself, so that shape is accepted too.
    """
    low = lparam & 0xFFFF
    if low in TRAY_EVENTS:
        return low
    return lparam if lparam in TRAY_EVENTS else low


# ------------------------------------------------------------------ Win32 (Windows only)
WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_TIMER = 0x0113
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
WM_APP = 0x8000
WM_TRAYICON = WM_APP + 20
WM_KS_DONE = WM_APP + 21
TRAY_EVENTS = (WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP, WM_CONTEXTMENU)
TIMER_QUIT = 1

NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO, NIF_SHOWTIP = 0x01, 0x02, 0x04, 0x10, 0x80
NOTIFYICON_VERSION_4 = 4
NIIF_INFO = 0x00000001
IDI_APPLICATION = 32512
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
ERROR_CLASS_ALREADY_EXISTS = 1410
MF_STRING, MF_SEPARATOR = 0x0000, 0x0800
TPM_RIGHTBUTTON, TPM_NONOTIFY, TPM_RETURNCMD = 0x0002, 0x0080, 0x0100

_LIBS = {}                                    # ctypes DLLs; empty until the tray starts

DWORD = ctypes.c_uint32
WORD = ctypes.c_uint16
UINT = ctypes.c_uint32
INT = ctypes.c_int32
BOOL = ctypes.c_int32
BYTE = ctypes.c_ubyte
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
LRESULT = ctypes.c_ssize_t
LPCWSTR = ctypes.c_wchar_p
LPVOID = ctypes.c_void_p
HANDLE = HINSTANCE = HWND = HICON = HMENU = ctypes.c_void_p


def loaded_libs():
    """Names of the Win32 DLLs loaded so far - empty until a Tray is actually created."""
    return sorted(_LIBS)


if _WIN:
    class GUID(ctypes.Structure):
        _fields_ = [('Data1', DWORD), ('Data2', WORD), ('Data3', WORD), ('Data4', BYTE * 8)]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [('cbSize', DWORD), ('hWnd', HWND), ('uID', UINT), ('uFlags', UINT),
                    ('uCallbackMessage', UINT), ('hIcon', HICON), ('szTip', ctypes.c_wchar * 128),
                    ('dwState', DWORD), ('dwStateMask', DWORD),
                    ('szInfo', ctypes.c_wchar * 256), ('uVersion', UINT),
                    ('szInfoTitle', ctypes.c_wchar * 64), ('dwInfoFlags', DWORD),
                    ('guidItem', GUID), ('hBalloonIcon', HICON)]

    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [('style', UINT), ('lpfnWndProc', WNDPROC), ('cbClsExtra', INT),
                    ('cbWndExtra', INT), ('hInstance', HINSTANCE), ('hIcon', HICON),
                    ('hCursor', HANDLE), ('hbrBackground', HANDLE), ('lpszMenuName', LPCWSTR),
                    ('lpszClassName', LPCWSTR)]

    class MSG(ctypes.Structure):
        _fields_ = [('hwnd', HWND), ('message', UINT), ('wParam', WPARAM), ('lParam', LPARAM),
                    ('time', DWORD), ('pt', ctypes.c_int32 * 2)]

    class POINT(ctypes.Structure):
        _fields_ = [('x', INT), ('y', INT)]

    class RECT(ctypes.Structure):
        _fields_ = [('left', INT), ('top', INT), ('right', INT), ('bottom', INT)]

    class NOTIFYICONIDENTIFIER(ctypes.Structure):
        _fields_ = [('cbSize', DWORD), ('hWnd', HWND), ('uID', UINT), ('guidItem', GUID)]

    def _win32():
        """user32 + kernel32 + shell32 with full signatures, loaded once, on first use."""
        if 'user32' in _LIBS:
            return _LIBS['user32'], _LIBS['kernel32'], _LIBS['shell32']
        u32 = ctypes.WinDLL('user32', use_last_error=True)
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        s32 = ctypes.WinDLL('shell32', use_last_error=True)     # Shell_NotifyIconW lives here
        u32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        u32.RegisterClassW.restype = WORD
        u32.UnregisterClassW.argtypes = [LPCWSTR, HINSTANCE]
        u32.CreateWindowExW.argtypes = [DWORD, LPCWSTR, LPCWSTR, DWORD, INT, INT, INT, INT,
                                        HWND, HMENU, HINSTANCE, LPVOID]
        u32.CreateWindowExW.restype = HWND
        u32.DefWindowProcW.argtypes = [HWND, UINT, WPARAM, LPARAM]
        u32.DefWindowProcW.restype = LRESULT
        u32.DestroyWindow.argtypes = [HWND]
        u32.PostMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]
        u32.PostQuitMessage.argtypes = [INT]
        u32.GetMessageW.argtypes = [ctypes.POINTER(MSG), HWND, UINT, UINT]
        u32.GetMessageW.restype = INT
        u32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
        u32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
        u32.RegisterWindowMessageW.argtypes = [LPCWSTR]
        u32.RegisterWindowMessageW.restype = UINT
        s32.Shell_NotifyIconW.argtypes = [DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
        s32.Shell_NotifyIconW.restype = BOOL
        s32.Shell_NotifyIconGetRect.argtypes = [ctypes.POINTER(NOTIFYICONIDENTIFIER),
                                                ctypes.POINTER(RECT)]
        s32.Shell_NotifyIconGetRect.restype = INT              # HRESULT: 0 = S_OK
        u32.CreateIconFromResourceEx.argtypes = [ctypes.POINTER(BYTE), DWORD, BOOL, DWORD,
                                                 INT, INT, UINT]
        u32.CreateIconFromResourceEx.restype = HICON
        u32.LoadImageW.argtypes = [HINSTANCE, LPCWSTR, UINT, INT, INT, UINT]
        u32.LoadImageW.restype = HANDLE
        u32.LoadIconW.argtypes = [HINSTANCE, LPVOID]
        u32.LoadIconW.restype = HICON
        u32.DestroyIcon.argtypes = [HICON]
        u32.CreatePopupMenu.restype = HMENU
        u32.AppendMenuW.argtypes = [HMENU, UINT, ctypes.c_size_t, LPCWSTR]
        u32.DestroyMenu.argtypes = [HMENU]
        u32.TrackPopupMenu.argtypes = [HMENU, UINT, INT, INT, INT, HWND, LPVOID]
        u32.TrackPopupMenu.restype = INT                       # with TPM_RETURNCMD: the id
        u32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
        u32.SetForegroundWindow.argtypes = [HWND]
        u32.SetTimer.argtypes = [HWND, ctypes.c_size_t, UINT, LPVOID]   # no W/A suffix
        u32.SetTimer.restype = ctypes.c_size_t
        u32.KillTimer.argtypes = [HWND, ctypes.c_size_t]
        k32.GetModuleHandleW.argtypes = [LPCWSTR]
        k32.GetModuleHandleW.restype = HINSTANCE
        _LIBS['user32'], _LIBS['kernel32'], _LIBS['shell32'] = u32, k32, s32
        return u32, k32, s32

    class Tray:
        """Hidden message window + Shell_NotifyIconW icon + popup menu for one process.

        Created only by main(): constructing it opens a window and puts an icon in the
        notification area, so --selftest never gets here.
        """

        def __init__(self, autoclose_ms=0):
            self.u32, self.k32, self.s32 = _win32()
            self.hinst = self.k32.GetModuleHandleW(None)
            self.class_name = 'WFM_Dashboard_Tray_%d' % os.getpid()
            self.hwnd = None
            self._added = False
            self._icons = {}                                   # 'off'/'armed' -> (HICON, owned)
            self._icon_sources = {}
            self._tmp_ico = None
            self.autoclose_ms = int(autoclose_ms or 0)
            self.kill = read_kill_switch()
            self._ks_result = None
            self._ks_target = False
            self._ks = KillSwitchGate(run_killswitch, self._ks_finished)
            self._cb = WNDPROC(self._on_message)               # keep alive: C owns the pointer
            self._wm_taskbar_created = self.u32.RegisterWindowMessageW('TaskbarCreated')

        # ------------------------------------------------------------------ lifetime
        def create(self):
            """Register the class, create the hidden window, add the icon. -> self"""
            global _TRAY_CREATED
            wc = WNDCLASSW()
            wc.style = 0
            wc.lpfnWndProc = self._cb
            wc.cbClsExtra = wc.cbWndExtra = 0
            wc.hInstance = self.hinst
            wc.lpszClassName = self.class_name
            if not self.u32.RegisterClassW(ctypes.byref(wc)):
                err = ctypes.get_last_error()
                if err != ERROR_CLASS_ALREADY_EXISTS:
                    raise OSError('RegisterClassW failed (error %d)' % err)
            self.hwnd = self.u32.CreateWindowExW(0, self.class_name, 'WFM dashboard tray',
                                                 0, 0, 0, 0, 0, None, None, self.hinst, None)
            if not self.hwnd:
                raise OSError('CreateWindowExW failed (error %d)' % ctypes.get_last_error())
            if self.autoclose_ms:
                self.u32.SetTimer(self.hwnd, TIMER_QUIT, max(200, self.autoclose_ms), None)
            if not self._add_icon():
                raise OSError('Shell_NotifyIconW(NIM_ADD) failed (error %d)'
                              % ctypes.get_last_error())
            _TRAY_CREATED = True
            return self

        def pump(self):
            """Run the message loop until the window closes (blocks). -> True on WM_QUIT."""
            msg = MSG()
            while True:
                res = self.u32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if res == 0:
                    return True
                if res < 0:
                    return False
                self.u32.TranslateMessage(ctypes.byref(msg))
                self.u32.DispatchMessageW(ctypes.byref(msg))

        def quit(self):
            """Ask the window to close; the WM_DESTROY handler tears the icon down."""
            if self.hwnd:
                self.u32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

        # -------------------------------------------------------------------- icon
        def _make_icon(self, accent):
            """(HICON, source, owned): PNG payload first, temp .ico next, built-in last."""
            png = png_bytes(ICON_SIZE, accent)
            buf = ctypes.create_string_buffer(png, len(png))
            hicon = self.u32.CreateIconFromResourceEx(ctypes.cast(buf, ctypes.POINTER(BYTE)),
                                                      len(png), 1, 0x00030000, ICON_SIZE,
                                                      ICON_SIZE, 0)
            if hicon:
                return hicon, 'CreateIconFromResourceEx(png)', True
            try:
                path = os.path.join(tempfile.gettempdir(), 'wfm_tray_%d.ico' % os.getpid())
                with open(path, 'wb') as fh:
                    fh.write(ico_bytes(ICON_SIZE, accent))
                self._tmp_ico = path
                hicon = self.u32.LoadImageW(None, path, IMAGE_ICON, ICON_SIZE, ICON_SIZE,
                                            LR_LOADFROMFILE)
                if hicon:
                    return hicon, 'LoadImageW(%s)' % path, True
            except OSError as e:
                say('tray: temp .ico fallback failed: %r' % (e,))
            return self.u32.LoadIconW(None, IDI_APPLICATION), 'IDI_APPLICATION (built-in)', False

        def _icon(self, armed):
            key = 'armed' if armed else 'off'
            if key not in self._icons:
                hicon, source, owned = self._make_icon(ACCENT_ARMED if armed else ACCENT_OFF)
                self._icons[key] = (hicon, owned)
                self._icon_sources[key] = source
                say('tray: %s icon -> %s' % (key, source))
            return self._icons[key][0]

        @property
        def icon_source(self):
            """How the icon for the current kill-switch state was built."""
            return self._icon_sources.get('armed' if self.kill['active'] else 'off', 'none')

        def _nid(self):
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = self.hwnd
            nid.uID = ICON_UID
            return nid

        def _add_icon(self):
            nid = self._nid()
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
            nid.uCallbackMessage = WM_TRAYICON
            nid.hIcon = self._icon(bool(self.kill['active']))
            nid.szTip = tip_text(bool(self.kill['active']))
            if not self.s32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
                return False
            self._added = True
            ver = self._nid()                                  # version 4 = LOWORD(lParam) msgs
            ver.uVersion = NOTIFYICON_VERSION_4
            self.s32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(ver))
            return True

        def _apply_state(self):
            """Re-read the state file and push it into the icon, tooltip and menu label."""
            self.kill = read_kill_switch()
            armed = bool(self.kill['active'])
            nid = self._nid()
            nid.uFlags = NIF_ICON | NIF_TIP | NIF_SHOWTIP
            nid.hIcon = self._icon(armed)
            nid.szTip = tip_text(armed)
            return bool(self.s32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid)))

        def balloon(self, title, text):
            """Show a notification balloon next to the icon."""
            nid = self._nid()
            nid.uFlags = NIF_INFO
            nid.dwInfoFlags = NIIF_INFO
            nid.szInfoTitle = str(title)[:63]
            nid.szInfo = str(text)[:255]
            return bool(self.s32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid)))

        def icon_rect(self):
            """Ask the shell where our icon is (Shell_NotifyIconGetRect). -> (ok, text)

            S_OK with a non-empty rectangle means the notification area really holds this
            icon - the strongest check available without a human looking at the taskbar.
            """
            ident = NOTIFYICONIDENTIFIER()
            ident.cbSize = ctypes.sizeof(NOTIFYICONIDENTIFIER)
            ident.hWnd = self.hwnd
            ident.uID = ICON_UID
            rect = RECT()
            try:
                hr = self.s32.Shell_NotifyIconGetRect(ctypes.byref(ident), ctypes.byref(rect))
            except AttributeError:
                return False, 'Shell_NotifyIconGetRect is unavailable here'
            if hr != 0:
                return False, 'HRESULT 0x%08X' % (hr & 0xFFFFFFFF)
            return True, 'x=%d y=%d w=%d h=%d' % (rect.left, rect.top, rect.right - rect.left,
                                                  rect.bottom - rect.top)

        # -------------------------------------------------------------------- menu
        def show_menu(self):
            """Pop up the menu at the cursor; TPM_RETURNCMD gives the chosen id back."""
            if not self.hwnd:
                return None
            self.kill = read_kill_switch()                     # a stale label would lie
            menu = self.u32.CreatePopupMenu()
            if not menu:
                return None
            cmd = 0
            try:
                for cid, label, enabled in menu_items(bool(self.kill['active'])):
                    if cid == MENU_SEPARATOR:
                        self.u32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                    else:
                        self.u32.AppendMenuW(menu, MF_STRING, cid, label)
                pt = POINT()
                self.u32.GetCursorPos(ctypes.byref(pt))
                self.u32.SetForegroundWindow(self.hwnd)        # else the menu never dismisses
                cmd = self.u32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_NONOTIFY | TPM_RETURNCMD,
                                              pt.x, pt.y, 0, self.hwnd, None)
                self.u32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
            finally:
                self.u32.DestroyMenu(menu)
            if cmd:
                self.dispatch(cmd)
            return cmd

        def dispatch(self, cmd):
            """Run the action mapped to a menu command id."""
            action = action_for(cmd)
            if action == 'open_dashboard':
                self.open_dashboard()
            elif action == 'rebuild_plan':
                self.spawn_engine('lister')
            elif action == 'run_detector':
                self.spawn_engine('detector')
            elif action == 'kill_switch_toggle':
                self.toggle_kill_switch()
            elif action == 'quit':
                self.quit()
            else:
                say('tray: unknown menu command %r' % (cmd,))

        # ------------------------------------------------------------------ actions
        def open_dashboard(self):
            url = dashboard_url()
            try:
                webbrowser.open(url)
                say('tray: opened %s' % url)
            except Exception as e:                             # noqa: BLE001
                self.balloon('WFM dashboard', 'could not open %s (%r)' % (url, e))

        def spawn_engine(self, engine):
            """Start an engine detached; under pythonw a balloon is the only feedback channel."""
            res = spawn_engine(engine)
            if res['ok']:
                self.balloon('WFM dashboard', '%s started (pid %s)' % (engine, res['pid']))
                say('tray: started %s (pid %s)' % (engine, res['pid']))
            else:
                self.balloon('WFM dashboard', 'could not start %s: %s' % (engine, res['error']))
                say('tray: could not start %s: %s' % (engine, res['error']))
            return res

        def toggle_kill_switch(self):
            """Flip the switch through the killswitch CLI (off the message thread).

            The target comes from a FRESH read of the state file, not from the cached copy -
            a click that lands while the previous command is still settling would otherwise
            flip the state the tray last saw instead of the state that is on disk.
            """
            self.kill = read_kill_switch()
            return self._ks.request(not bool(self.kill['active']))

        def _ks_finished(self, target, result):
            """Worker thread: land the new state on disk, then ask the window to show it."""
            self._ks_result = result
            self._ks_target = target
            self.kill = read_kill_switch()                     # what actually landed on disk
            say('tray: kill switch -> %s (killswitch CLI)' % ('arm' if target else 'disarm'))
            if self.hwnd:
                self.u32.PostMessageW(self.hwnd, WM_KS_DONE, 1 if self.kill['active'] else 0, 0)

        def _after_kill_switch(self):
            """Main thread (WM_KS_DONE): refresh the icon, tooltip and the balloon text."""
            armed = bool(self.kill['active'])
            res = self._ks_result or {}
            if not res.get('ok'):
                msg = 'kill switch command failed: %s' % (res.get('error') or res.get('tail') or '?')
            elif armed != bool(self._ks_target):
                msg = 'state did not change - still %s' % ('ARMED' if armed else 'off')
            else:
                msg = ('KILL SWITCH ARMED - lister/detector will refuse to run' if armed
                       else 'kill switch off - lister/detector may run')
            self._apply_state()
            self.balloon('WFM kill switch', msg)
            say('tray: kill switch now %s (%s)' % ('ARMED' if armed else 'off', msg))

        # ----------------------------------------------------------------- plumbing
        def _on_message(self, hwnd, msg, wparam, lparam):
            try:
                if msg == WM_TRAYICON:
                    event = tray_event(lparam)
                    if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                        self.open_dashboard()                  # left click = open dashboard
                    elif event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                        self.show_menu()
                    return 0
                if msg == WM_KS_DONE:
                    self._after_kill_switch()
                    return 0
                if msg == self._wm_taskbar_created:            # Explorer restarted
                    self._add_icon()
                    return 0
                if msg == WM_TIMER:
                    if wparam == TIMER_QUIT:
                        say('tray: smoke timer fired, quitting')
                        self.quit()
                    return 0
                if msg == WM_CLOSE:
                    self.u32.DestroyWindow(hwnd)
                    return 0
                if msg == WM_DESTROY:
                    self._teardown()
                    self.u32.PostQuitMessage(0)
                    return 0
            except Exception as e:                             # noqa: BLE001 - never break the pump
                say('tray: window procedure error: %r' % (e,))
            return self.u32.DefWindowProcW(hwnd, msg, wparam, lparam)

        def _teardown(self):
            try:
                if self._added:
                    self.s32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid()))
                    self._added = False
                if self.hwnd:
                    self.u32.KillTimer(self.hwnd, TIMER_QUIT)
                for hicon, owned in self._icons.values():
                    if owned and hicon:                        # shared icons must not be destroyed
                        self.u32.DestroyIcon(hicon)
                self._icons.clear()
                if self._tmp_ico:
                    try:
                        os.unlink(self._tmp_ico)
                    except OSError:
                        pass
                    self._tmp_ico = None
                if self.class_name:
                    self.u32.UnregisterClassW(self.class_name, self.hinst)
            except Exception as e:                             # noqa: BLE001
                say('tray: teardown error: %r' % (e,))
            self.hwnd = None
else:                                                          # non-Windows: keep the API shape
    Tray = None

    def _win32():
        raise OSError('the tray widget needs Windows')


# ------------------------------------------------------------------------------- CLI
def build_parser():
    ap = argparse.ArgumentParser(description='WFM dashboard tray widget (Windows, stdlib only).')
    ap.add_argument('--selftest', action='store_true',
                    help='offline checks: no tray, no window, no DLL load, no network, no writes')
    ap.add_argument('--smoke', action='store_true',
                    help='really create the tray, then quit after %d ms' % SMOKE_MS)
    ap.add_argument('--smoke-ms', type=int, default=SMOKE_MS, help=argparse.SUPPRESS)
    ap.add_argument('--log', default='', help='also append messages to this file (pythonw has no stdout)')
    return ap


def main(argv=None):
    global LOG_PATH
    a = build_parser().parse_args(argv)
    if a.log:
        LOG_PATH = a.log
    if a.selftest:
        return 0 if selftest() else 1
    if not _WIN:
        say('tray: this widget needs Windows (ctypes Shell_NotifyIconW); nothing to do here')
        return 1
    ms = max(200, min(int(a.smoke_ms or SMOKE_MS), 600000)) if a.smoke else 0
    try:
        tray = Tray(autoclose_ms=ms).create()
    except Exception as e:                                     # noqa: BLE001
        say('tray: could not start: %r' % (e,))
        return 1
    kill = tray.kill
    say('tray: running (icon: %s%s) - dashboard %s | kill switch %s%s' % (
        tray.icon_source, ', smoke: quits in %.1fs' % (ms / 1000.0) if ms else '',
        dashboard_url(), 'ARMED' if kill['active'] else 'off',
        ' (%s)' % kill['source'] if kill['source'] != 'file' else ''))
    if ms:
        ok_rect, detail = tray.icon_rect()
        say('tray: smoke - Shell_NotifyIconGetRect reports %s (%s)'
            % ('the icon is in the notification area' if ok_rect else 'no icon', detail))
    ok = tray.pump()
    say('tray: stopped (%s)' % ('clean' if ok else 'message loop error'))
    return 0 if ok else 1


# -------------------------------------------------------------------------- selftest
def selftest():
    """Fully offline, side-effect-free checks. -> True when everything passed.

    No tray, no window, no DLL load, no subprocess, no network, no writes outside a temp
    directory (the real data/kill_switch.json is only hashed, never opened for writing).
    """
    results = []

    def check(label, ok, detail=''):
        ok = bool(ok)
        results.append(ok)
        print('%s  %s%s' % ('PASS' if ok else 'FAIL', label, (' - %s' % detail) if detail else ''))
        return ok

    checks_before = len(results)
    skipped = 0
    tmp = tempfile.mkdtemp(prefix='tray_selftest_')
    real_hash = _file_hash(_kill_path())
    port_before = os.environ.get('WFM_PORT')
    try:
        # --- .ico container -------------------------------------------------------
        ico = ico_bytes()
        check('ico: ICONDIR magic is reserved 0, type 1, count 1',
              ico[:6] == b'\x00\x00\x01\x00\x01\x00')
        dim_w, dim_h, colors, res, planes, bpp, nbytes, offset = struct.unpack(
            '<BBBBHHII', ico[ICON_DIR_SIZE:ICO_HEADER_SIZE])
        check('ico: ICONDIRENTRY says 32x32, colourCount 0, planes 1, bpp 32',
              (dim_w, dim_h, colors, res, planes, bpp) == (32, 32, 0, 0, 1, 32))
        check('ico: bytesInRes = PNG length and imageOffset = 22',
              nbytes == len(ico) - ICO_HEADER_SIZE and offset == ICO_HEADER_SIZE
              and nbytes > 0)
        check('ico: PNG payload starts right after the header', ico[22:30] == PNG_MAGIC)
        parsed = parse_ico(ico)
        check('ico: parse_ico round-trips every header field',
              parsed['reserved'] == 0 and parsed['type'] == 1 and parsed['count'] == 1
              and (parsed['width'], parsed['height'], parsed['bpp']) == (32, 32, 32)
              and parsed['bytes_in_res'] == nbytes and parsed['png'] == ico[22:])
        check('ico: 256px images would be recorded as 0 (spec)', ico_bytes(256)[6] == 0
              and parse_ico(ico_bytes(256))['width'] == 256)

        # --- PNG payload ----------------------------------------------------------
        png = parsed['png']
        check('png: signature + IHDR is the first chunk',
              png[:8] == PNG_MAGIC and png[12:16] == b'IHDR')
        info = parse_png(png)
        check('png: IHDR 32x32, bit depth 8, colour type 6 (RGBA), no interlace',
              (info['width'], info['height'], info['bitdepth'], info['colortype'],
               info['interlace']) == (32, 32, 8, 6, 0))
        check('png: chunk order IHDR..IDAT..IEND with valid CRCs',
              info['chunks'][0] == b'IHDR' and info['chunks'][-1] == b'IEND'
              and b'IDAT' in info['chunks'])
        check('png: IDAT inflates to 32 filter-0 RGBA scanlines (32*(1+128) bytes)',
              len(info['raw']) == 32 * (1 + 32 * 4)
              and all(info['raw'][i * (1 + 32 * 4)] == 0 for i in range(32)))
        check('png: a corrupt payload is rejected (CRC guard is live)',
              _raises(ValueError, parse_png, png[:50] + bytes([png[50] ^ 0xFF]) + png[51:]))

        # --- pixels ---------------------------------------------------------------
        rows = icon_pixels()
        px = lambda x, y: tuple(rows[y][x * 4:x * 4 + 4])       # noqa: E731
        check('icon: 32 RGBA rows of 32 pixels', len(rows) == 32 and all(len(r) == 128 for r in rows))
        check('icon: centre is the opaque orange diamond',
              px(16, 16) == ACCENT_OFF + (255,))
        check('icon: corners are fully transparent',
              px(0, 0)[3] == 0 and px(31, 0)[3] == 0 and px(0, 31)[3] == 0 and px(31, 31)[3] == 0)
        check('icon: disc between the diamond tip and the rim is dark and opaque',
              px(16, 5) == DISC + (255,) and px(5, 16) == DISC + (255,)
              and px(16, 26) == DISC + (255,))
        check('icon: the rim just inside the edge is the accent dimmed to 55%',
              px(16, 2) == tuple(int(c * 0.55) for c in ACCENT_OFF) + (255,))
        check('icon: diamond spans the disc at the centre row',
              px(6, 16)[:3] != ACCENT_OFF and px(10, 16)[:3] == ACCENT_OFF
              and px(22, 16)[:3] == ACCENT_OFF)
        armed_rows = icon_pixels(ICON_SIZE, ACCENT_ARMED)
        armed_px = tuple(armed_rows[16][16 * 4:16 * 4 + 3])
        check('icon: armed accent repaints the diamond red', armed_px == ACCENT_ARMED
              and armed_px != ACCENT_OFF)
        armed_ico = ico_bytes(ICON_SIZE, ACCENT_ARMED)
        armed_info = parse_png(parse_ico(armed_ico)['png'])
        check('icon: the armed .ico is well formed and paints different pixels',
              struct.unpack('<HHH', armed_ico[:6]) == (0, 1, 1)
              and (armed_info['width'], armed_info['height'], armed_info['colortype'])
              == (32, 32, 6) and armed_info['raw'] != info['raw'])

        # --- menu -----------------------------------------------------------------
        off_menu, armed_menu = menu_items(False), menu_items(True)
        labels = [lbl for _cid, lbl, _en in off_menu if lbl]
        check('menu: the five commands in order',
              labels == ['Open dashboard', 'Rebuild plan (lister)', 'Run detector',
                         'Kill switch: arm', 'Quit tray'])
        check('menu: two separators carry id 0 and no label',
              sum(1 for cid, lbl, _en in off_menu if cid == MENU_SEPARATOR and lbl is None) == 2)
        kill_row = next(r for r in armed_menu if r[0] == MENU_KILL)
        check('menu: kill-switch label flips with the state',
              kill_row[1] == 'Kill switch: disarm (ARMED)'
              and next(r for r in off_menu if r[0] == MENU_KILL)[1] == 'Kill switch: arm')
        ids = [cid for cid, _l, _e in off_menu if cid]
        check('menu: command ids are unique and all enabled',
              len(set(ids)) == len(ids) and sorted(ids) == sorted(ACTIONS))
        check('menu: every command id resolves to an action, junk ids do not',
              sorted(action_for(i) for i in ids) == sorted(set(ACTIONS.values()))
              and action_for(MENU_SEPARATOR) is None and action_for(99) is None
              and action_for(None) is None)
        check('menu: tooltip tracks the state and stays under 128 chars',
              'ARMED' in tip_text(True) and 'off' in tip_text(False)
              and len(tip_text(True)) < 128)
        check('menu: v4 callback lParam decodes to the mouse event',
              tray_event((ICON_UID << 16) | WM_RBUTTONUP) == WM_RBUTTONUP
              and tray_event(WM_LBUTTONUP) == WM_LBUTTONUP
              and tray_event(0x1234) == 0x1234)

        # --- kill-switch read (temp file only) -------------------------------------
        ks = os.path.join(tmp, 'kill_switch.json')
        r = read_kill_switch(ks)
        check('kill switch: absent file reads as off and is NOT created',
              r['active'] is False and r['source'] == 'absent' and not os.path.exists(ks))
        _write_json(ks, {'active': True, 'note': 'selftest', 'ts': 1790000000})
        r = read_kill_switch(ks)
        check('kill switch: armed file reads as ARMED with note + ts',
              r['active'] is True and r['note'] == 'selftest' and r['ts'] == 1790000000
              and r['source'] == 'file' and r['error'] is None)
        _write_json(ks, {'active': False})
        check('kill switch: disarmed file reads as off', read_kill_switch(ks)['active'] is False
              and read_kill_switch(ks)['source'] == 'file')
        with open(ks, 'w', encoding='utf-8') as fh:
            fh.write('{ not json')
        r = read_kill_switch(ks)
        check('kill switch: corrupt file is fail-closed ARMED (killswitch.py policy)',
              r['active'] is True and r['source'] == 'fail_closed' and bool(r['error']))
        with open(ks, 'w', encoding='utf-8') as fh:
            fh.write('{"active": "yes"}')
        check('kill switch: non-bool active is fail-closed ARMED',
              read_kill_switch(ks)['active'] is True)
        _write_json(ks, ['nope'])
        check('kill switch: a non-object file is fail-closed ARMED',
              read_kill_switch(ks)['active'] is True)

        # --- kill-switch gate (threads only: no process, no window) ----------------
        seen, done, release = [], [], threading.Event()

        def _stub_runner(target):
            seen.append(target)
            release.wait(10)
            return {'ok': True, 'code': 0, 'cmd': [], 'tail': '', 'error': None}

        gate = KillSwitchGate(_stub_runner, lambda t, r: done.append(t))
        check('gate: an idle request starts straight away', gate.request(True) is True)
        _wait_until(lambda: bool(seen), 5)
        check('gate: the stub runner received the target', seen == [True] and gate.busy is True)
        check('gate: a click during a run is queued, not dropped',
              gate.request(False) is False and gate.pending is False)
        check('gate: the newest click replaces the pending target',
              gate.request(True) is False and gate.pending is True)
        release.set()
        _wait_until(lambda: len(done) == 2, 10)
        check('gate: the queued target ran after the first one', seen == [True, True]
              and done == [True, True])
        check('gate: idle again once the queue drained',
              gate.busy is False and gate.pending is None)

        # --- commands -------------------------------------------------------------
        lst, det = engine_command('lister'), engine_command('detector')
        check('cmd: engines run through scripts/trader/*.py',
              all(c[1].replace('\\', '/').endswith(p) for c, p in
                  ((lst, 'scripts/trader/lister.py'), (det, 'scripts/trader/detector.py'))))
        check('cmd: engines are launched with pythonw.exe (no console window)',
              (not _WIN) or os.path.basename(lst[0]).lower() == 'pythonw.exe')
        ks_on, ks_off = killswitch_command(True), killswitch_command(False)
        check('cmd: killswitch CLI argv is --on / --off with a note',
              '--on' in ks_on and '--off' in ks_off and ks_on[-2] == '--note'
              and ks_on[1].replace('\\', '/').endswith('scripts/trader/killswitch.py'))
        check('cmd: killswitch CLI uses a console python.exe',
              (not _WIN) or os.path.basename(ks_on[0]).lower() == 'python.exe')
        check('cmd: python_path/pythonw_path fall back to sys.executable',
              python_path('/nonexistent/py/python.exe') == '/nonexistent/py/python.exe'
              and pythonw_path('/nonexistent/py/python.exe') == '/nonexistent/py/python.exe')
        check('cmd: a pythonw interpreter is preferred as-is',
              pythonw_path('C:/x/pythonw.exe').replace('\\', '/').endswith('pythonw.exe'))
        os.environ.pop('WFM_PORT', None)
        check('cmd: dashboard url defaults to the supervisor port',
              dashboard_url() == 'http://127.0.0.1:8787/')
        os.environ['WFM_PORT'] = '8899'
        check('cmd: WFM_PORT overrides the dashboard url',
              dashboard_url() == 'http://127.0.0.1:8899/')
        os.environ['WFM_PORT'] = 'garbage'
        check('cmd: a junk WFM_PORT falls back to 8787',
              dashboard_url() == 'http://127.0.0.1:8787/')

        # --- import is inert ------------------------------------------------------
        check('import: no Win32 library loaded (import touched no DLL)', loaded_libs() == [])
        check('import: no tray was created anywhere in this run (Tray.create never called)',
              _TRAY_CREATED is False)
        ns = build_parser().parse_args(['--smoke', '--log', 'x.log'])
        check('cli: --selftest / --smoke / --log / --smoke-ms are wired up',
              build_parser().parse_args(['--selftest']).selftest is True and ns.smoke is True
              and ns.log == 'x.log' and ns.smoke_ms == SMOKE_MS)
        saved_stdout, saved_log = sys.stdout, LOG_PATH
        try:
            sys.stdout = None                                   # exactly what pythonw hands us
            say('this must not raise')
            ok_say = True
        except Exception:                                       # noqa: BLE001
            ok_say = False
        finally:
            sys.stdout, globals()['LOG_PATH'] = saved_stdout, saved_log
        check('say(): survives a pythonw-style sys.stdout = None', ok_say)
        if _WIN:
            ok_probe, detail = _import_is_inert()
            check('import: a fresh interpreter loads the file with ctypes.WinDLL disarmed'
                  ' (no window class, no DLL, no tray)', ok_probe, detail)
        else:
            skipped += 1
            print('SKIP  import-inertness probe needs Windows')
    finally:
        if port_before is None:
            os.environ.pop('WFM_PORT', None)
        else:
            os.environ['WFM_PORT'] = port_before
        shutil.rmtree(tmp, ignore_errors=True)

    check('the real kill_switch.json was only hashed, never written',
          _file_hash(_kill_path()) == real_hash)
    failed = results[checks_before:].count(False)
    print('selftest: %d checks, %d passed, %d failed%s - no tray, no DLL, no subprocess, no network'
          % (len(results), len(results) - failed, failed,
             ', %d skipped' % skipped if skipped else ''))
    return failed == 0


def _import_is_inert():
    """Import this file in a fresh interpreter whose ctypes.WinDLL raises. -> (ok, detail)

    Proves the import path opens nothing: if a DLL were loaded while the module was exec'd
    the probe would die instead of printing IMPORT_OK.
    """
    probe = (
        'import ctypes, importlib.util, sys\n'
        'def _boom(*a, **k):\n'
        '    raise AssertionError("a Win32 library was loaded at import time")\n'
        'ctypes.WinDLL = _boom\n'
        'spec = importlib.util.spec_from_file_location("tray_import_probe", sys.argv[1])\n'
        'mod = importlib.util.module_from_spec(spec)\n'
        'spec.loader.exec_module(mod)\n'
        'assert mod.loaded_libs() == [], "loaded_libs() is not empty after import"\n'
        'print("IMPORT_OK")\n'
    )
    try:
        proc = subprocess.run([python_path(), '-c', probe, os.path.abspath(__file__)],
                              cwd=ROOT, capture_output=True, text=True, timeout=60,
                              encoding='utf-8', errors='replace',
                              creationflags=0x08000000 if _WIN else 0)
    except Exception as e:                                     # noqa: BLE001
        return False, repr(e)[:120]
    out = ((proc.stdout or '') + (proc.stderr or '')).strip()
    return ('IMPORT_OK' in out and proc.returncode == 0), (out.splitlines() or [''])[-1][:120]


def _raises(exc, fn, *args):
    try:
        fn(*args)
    except exc:
        return True
    except Exception:                                          # noqa: BLE001
        return False
    return False


def _wait_until(pred, timeout=5.0, step=0.01):
    """Poll pred() until it is true or the timeout expires (threads, not sleeps-in-series)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return bool(pred())


def _write_json(path, obj):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh)


def _file_hash(path):
    try:
        with open(path, 'rb') as fh:
            return zlib.crc32(fh.read())
    except OSError:
        return None


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
