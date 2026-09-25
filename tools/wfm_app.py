#!/usr/bin/env python3
r"""One-click app launcher and Python shim for the WFM Trader dashboard.

Built by tools/build_app.py into "WFM Trader.exe". Two jobs:

1. **Python shim** - the exe IS the Python runtime for the folder it sits in, so any call of
   the form

       "WFM Trader.exe" scripts/fetch_prices.py --limit 10

   runs that script with the bundled interpreter. Every existing
   subprocess([sys.executable, ...]) chain inside the app therefore keeps working on a
   machine that has no Python installed at all.

2. **The whole app** - started with no script it does everything a first-time user needs:

       double-click "WFM Trader.exe"
         1. checks AlecaFrame (the inventory source) and says exactly what to do if missing
         2. first run only: builds the data (scripts/setup.py - inventory, prices, statistics,
            rank lanes, report, advisor and every page's data; 20-40 min, resumable)
         3. starts the dashboard, keeps it alive (restart on crash/hang) and opens the browser

Options (app mode):
    --serve-only     skip the setup check (tests; or after a manual setup)
    --no-browser     do not open the browser
    --port N         dashboard port (default: data/config.json, else 8787)
    --where          print the folders this launcher uses and exit
    --selftest       offline checks, no network and no server, and exit
"""
import argparse
import http.client
import os
import runpy
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser


# ---------------------------------------------------------------------------- layout
def frozen():
    """True when running as the built exe (PyInstaller)."""
    return bool(getattr(sys, 'frozen', False))


def app_root():
    """The app folder: where the exe sits (frozen), or the repo root (plain script)."""
    if frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def scripts_dir():
    return os.path.join(app_root(), 'scripts')


def data_dir():
    return os.path.join(app_root(), 'data')


def _prepare_import_path(extra=None):
    for p in (extra, scripts_dir(), app_root()):
        if p and p not in sys.path:
            sys.path.insert(0, p)


# ---------------------------------------------------------------------------- shim
def run_script(path, args=()):
    """Run a .py file as __main__ with this interpreter (python.exe behaviour)."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        sys.stderr.write('WFM Trader: script not found: %s\n' % path)
        return 2
    _prepare_import_path(os.path.dirname(path))
    argv = [path] + [str(a) for a in args]
    old_argv, old_path0 = sys.argv, (sys.path[0] if sys.path else None)
    sys.argv = argv
    try:
        runpy.run_path(path, run_name='__main__')
        return 0
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        sys.stderr.write('%s\n' % code)
        return 1
    finally:
        sys.argv = old_argv
        if old_path0 is not None and sys.path and sys.path[0] != old_path0:
            sys.path.pop(0)


def dispatch(argv):
    """python.exe-style dispatch: <script.py> [args] / -c "<code>" / -m module."""
    head = argv[0]
    if head.lower().endswith('.py'):
        return run_script(head, argv[1:])
    if head == '-c':
        if len(argv) < 2:
            sys.stderr.write('WFM Trader: -c needs code\n')
            return 2
        try:
            exec(compile(argv[1], '<-c>', 'exec'), {'__name__': '__main__'})
            return 0
        except SystemExit as exc:
            return int(exc.code or 0)
    if head == '-m':
        if len(argv) < 2:
            sys.stderr.write('WFM Trader: -m needs a module\n')
            return 2
        _prepare_import_path()
        old_argv = sys.argv
        sys.argv = [argv[1]] + [str(a) for a in argv[2:]]
        try:
            runpy.run_module(argv[1], run_name='__main__', alter_sys=True)
            return 0
        except ImportError as exc:
            sys.stderr.write('WFM Trader: %s\n' % exc)
            return 1
        except SystemExit as exc:
            return int(exc.code or 0)
        finally:
            sys.argv = old_argv
    sys.stderr.write('WFM Trader: do not know how to run %r\n' % head)
    return 2


# ---------------------------------------------------------------------------- app mode
AF_DIR = lambda: os.environ.get('WFM_ALECA_DIR') or os.path.expandvars(r'%LOCALAPPDATA%\AlecaFrame')
SETUP_MARKERS = ('owned.json', 'prices.json')      # what scripts/setup.py leaves behind


def alecaframe_save():
    """Path of the AlecaFrame save when it exists, else None."""
    p = os.path.join(AF_DIR(), 'lastData.dat')
    return p if os.path.exists(p) else None


def data_ready():
    return all(os.path.exists(os.path.join(data_dir(), n)) for n in SETUP_MARKERS)


def ping(host, port, timeout=4.0):
    """True when something answers on the dashboard port."""
    try:
        c = http.client.HTTPConnection(host, port, timeout=timeout)
        c.request('GET', '/')
        c.getresponse().read()
        c.close()
        return True
    except OSError:
        return False


def msgbox(title, text):
    """Best-effort Windows popup, so a double-click user actually sees the problem.
    Never in tests/CI/pythonw: a modal box would block a headless run forever."""
    if os.environ.get('WFM_NO_MSGBOX'):
        return
    if not (sys.stdin and getattr(sys.stdin, 'isatty', lambda: False)()):
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
    except Exception:
        pass


def pause():
    """Keep a double-clicked console open long enough to read the error."""
    try:
        if sys.stdin and sys.stdin.isatty():
            input('Press Enter to close...')
    except (EOFError, OSError):
        pass


def load_supervise():
    """tools/supervise.py - the keep-alive. It spawns [sys.executable, server.py], and
    sys.executable is this exe, so the server runs through the same bundled interpreter."""
    _prepare_import_path(os.path.join(app_root(), 'tools'))
    import supervise
    return supervise


def serve(host='127.0.0.1', port=None, open_browser=True):
    sup = load_supervise()
    port = port or sup.cfg_port() or 8787
    if open_browser:
        def waiter():
            for _ in range(60):
                if ping(host, port):
                    webbrowser.open('http://%s:%d/' % (host, port))
                    return
                time.sleep(1)
        threading.Thread(target=waiter, daemon=True).start()
    return sup.supervise(host, port)


def app(args):
    root = app_root()
    try:
        os.chdir(root)
    except OSError:
        pass
    print('=' * 62)
    print(' WFM Trader - Warframe market dashboard')
    print('=' * 62)
    print('app folder : %s' % root)
    print('data folder: %s' % data_dir())
    print('python     : %s%s' % (sys.version.split()[0], '  (bundled)' if frozen() else ''))
    print('')

    if not args.serve_only:
        save = alecaframe_save()
        if not save:
            message = ('AlecaFrame was not found.\n\n'
                       'AlecaFrame is what reads your Warframe inventory.\n\n'
                       '  1. Install it from https://alecaframe.com\n'
                       '  2. Open Warframe once so it syncs your inventory\n'
                       '  3. Start "WFM Trader" again\n\n'
                       'Looked for: %s' % os.path.join(AF_DIR(), 'lastData.dat'))
            print(message)
            msgbox('WFM Trader - AlecaFrame not found', message)
            pause()
            return 1
        print('AlecaFrame : %s' % save)
        if not data_ready():
            print('\nFirst run: building the dashboard data now.')
            print('This takes 20-40 minutes (prices + statistics + rank lanes). It is resumable -')
            print('close this window any time and start the app again to continue where it stopped.\n')
            rc = run_script(os.path.join(scripts_dir(), 'setup.py'))
            if rc != 0:
                message = ('Setup did not finish (exit %s).\n\n'
                           'Nothing is broken - start "WFM Trader" again to continue where it stopped.\n'
                           'The window above has the details.' % rc)
                print('\n' + message)
                msgbox('WFM Trader - setup incomplete', message)
                pause()
                return rc
        else:
            print('Data       : ready (%s)' % data_dir())

    print('\nStarting the dashboard - close this window to stop it.')
    try:
        return serve(port=args.port, open_browser=not args.no_browser)
    except KeyboardInterrupt:
        print('\nstopped.')
        return 0


# ---------------------------------------------------------------------------- selftest
def selftest():
    ok = True

    def chk(what, got, want=True):
        nonlocal ok
        good = got == want
        ok = ok and good
        print('%-52s %s' % (what, 'ok' if good else 'FAIL (got %r, want %r)' % (got, want)))

    root = app_root()
    chk('app_root has server.py', os.path.isfile(os.path.join(root, 'server.py')))
    chk('app_root has scripts/', os.path.isdir(scripts_dir()))
    chk('app_root has static/', os.path.isdir(os.path.join(root, 'static')))
    chk('app_root has tools/supervise.py', os.path.isfile(os.path.join(root, 'tools', 'supervise.py')))

    with tempfile.TemporaryDirectory() as td:
        probe = os.path.join(td, 'probe.py')
        out = os.path.join(td, 'out.txt')
        with open(probe, 'w', encoding='utf-8') as fh:
            fh.write('import json, sys, os\n'
                     "open(os.environ['PROBE_OUT'], 'w', encoding='utf-8').write(json.dumps(sys.argv[1:]))\n")
        os.environ['PROBE_OUT'] = out
        rc = run_script(probe, ['--flag', '7'])
        chk('run_script: exit code', rc, 0)
        got = open(out, encoding='utf-8').read() if os.path.exists(out) else ''
        chk('run_script: argv handed over', got, '["--flag", "7"]')
        chk('run_script: missing script is 2', run_script(os.path.join(td, 'nope.py')), 2)
        chk('dispatch -c', dispatch(['-c', 'raise SystemExit(3)']), 3)

    chk('data_ready is a bool', isinstance(data_ready(), bool))
    chk('alecaframe_save is a path or None', alecaframe_save() is None or os.path.isfile(alecaframe_save()))
    sup = load_supervise()
    chk('supervise: cfg_port callable', callable(sup.cfg_port))
    chk('supervise: supervise callable', callable(sup.supervise))
    print('')
    print('selftest:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


# ---------------------------------------------------------------------------- main
def main(argv=None):
    argv = [str(a) for a in (sys.argv[1:] if argv is None else argv)]
    if argv and (argv[0].lower().endswith('.py') or argv[0] in ('-c', '-m')):
        return dispatch(argv)
    ap = argparse.ArgumentParser(prog='WFM Trader', description=__doc__.splitlines()[0])
    ap.add_argument('--serve-only', action='store_true', help='skip the first-run setup check')
    ap.add_argument('--no-browser', action='store_true', help='do not open the browser')
    ap.add_argument('--port', type=int, default=None, help='dashboard port (default 8787)')
    ap.add_argument('--where', action='store_true', help='print the folder layout and exit')
    ap.add_argument('--selftest', action='store_true', help='offline checks and exit')
    a = ap.parse_args(argv)
    if a.where:
        print('app folder : %s' % app_root())
        print('scripts    : %s' % scripts_dir())
        print('data       : %s' % data_dir())
        print('frozen     : %s' % frozen())
        print('python     : %s' % sys.executable)
        return 0
    if a.selftest:
        return selftest()
    return app(a)


if __name__ == '__main__':
    sys.exit(main() or 0)
