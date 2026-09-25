"""Keep the dashboard server alive.

Starts server.py, restarts it when it exits, and restarts it when the health
check fails a few times in a row (a hung process that stopped answering).

    python tools/supervise.py             # run in the foreground (supervise.bat)
    python tools/supervise.py --selftest  # offline checks, starts no server

Logs: data/supervisor.log (this file's events) and data/server.log (server output).

Windows tip: put a shortcut to supervise.bat in your Startup folder
(Win+R -> shell:startup) if you want the dashboard running on every login.
If something is already serving the port (another server or supervisor), this
one just watches it instead of starting a second copy.
"""
import argparse, http.client, json, os, socket, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
LOG = os.path.join(DATA, 'supervisor.log')
SERVER_LOG = os.path.join(DATA, 'server.log')
POLL = 20            # seconds between health probes
FAILS_TO_RESTART = 2


def log(msg):
    os.makedirs(DATA, exist_ok=True)
    line = '%s %s' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg)
    print(line, flush=True)
    try:
        with open(LOG, 'a', encoding='utf-8') as fh:
            fh.write(line + '\n')
    except OSError:
        pass


def ping(host, port, timeout=5.0):
    """True when the dashboard answers on / (any HTTP status counts as alive)."""
    try:
        c = http.client.HTTPConnection(host, port, timeout=timeout)
        c.request('GET', '/')
        c.getresponse().read()
        c.close()
        return True
    except (OSError, socket.error):
        return False


def cfg_port(path=None):
    """Port from data/config.json when the user changed it there, else None."""
    try:
        with open(path or os.path.join(DATA, 'config.json'), encoding='utf-8') as fh:
            return int(json.load(fh).get('port') or 0) or None
    except (OSError, ValueError, TypeError):
        return None


def spawn(host, port):
    os.makedirs(DATA, exist_ok=True)
    env = dict(os.environ, WFM_PORT=str(port), WFM_HOST=host)
    out = open(SERVER_LOG, 'a', encoding='utf-8')
    return subprocess.Popen([sys.executable, os.path.join(ROOT, 'server.py')],
                            cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT)


def stop(child):
    if child is None:
        return
    child.kill()
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def supervise(host, port, poll=POLL):
    log('supervisor up - watching http://%s:%s/ every %ss' % (host, port, poll))
    child = None
    fails = 0
    if ping(host, port):
        log('something is already serving the port - watching it, not starting a second copy')
    else:
        child = spawn(host, port)
        log('server started (pid %s)' % child.pid)
    try:
        while True:
            time.sleep(poll)
            if child is not None and child.poll() is not None:
                log('server exited (code %s) -> restarting' % child.returncode)
                child = spawn(host, port)
                log('server started (pid %s)' % child.pid)
                fails = 0
                continue
            if ping(host, port):
                fails = 0
                continue
            fails += 1
            log('health check failed (%s/%s)' % (fails, FAILS_TO_RESTART))
            if fails >= FAILS_TO_RESTART:
                log('not answering -> restarting the server')
                stop(child)
                child = spawn(host, port)
                log('server started (pid %s)' % child.pid)
                fails = 0
    except KeyboardInterrupt:
        log('stopping (Ctrl+C)')
        stop(child)
        return 0


def selftest():
    """Offline checks: a real HTTP answer pings True, a dead port pings False."""
    import http.server
    import threading

    ok = True
    srv = http.server.HTTPServer(('127.0.0.1', 0), http.server.SimpleHTTPRequestHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    live = ping('127.0.0.1', port, timeout=3)
    print('live server pings: %s (want True)' % live)
    ok = ok and live
    srv.shutdown()
    dead = ping('127.0.0.1', port, timeout=2)
    print('closed port pings: %s (want False)' % dead)
    ok = ok and not dead

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'config.json')
        with open(p, 'w', encoding='utf-8') as fh:
            json.dump({'port': 9999}, fh)
        got = cfg_port(p)
        print('cfg_port reads config.json: %s (want 9999)' % got)
        ok = ok and got == 9999
        print('cfg_port tolerates junk: %s (want None)' % cfg_port(os.path.join(d, 'nope.json')))
        ok = ok and cfg_port(os.path.join(d, 'nope.json')) is None

    print('selftest:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description='Keep the dashboard server alive.')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=None, help='default: config.json port, else 8787')
    ap.add_argument('--poll', type=int, default=POLL, help='seconds between health probes')
    ap.add_argument('--selftest', action='store_true', help='offline checks, starts no server')
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    port = args.port or cfg_port() or 8787
    return supervise(args.host, port, poll=args.poll)


if __name__ == '__main__':
    sys.exit(main() or 0)
