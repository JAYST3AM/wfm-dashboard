"""WFM Trader dashboard — localhost server (stdlib only).
Serves static/ + JSON API over the project's data/ folder.
"""
import json, os, sys, subprocess, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, 'data')
STATIC = os.path.join(ROOT, 'static')
PORT = int(os.environ.get('WFM_PORT', '8787'))

def jload(p, default=None):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default

BUILTIN = {'set', 'prime', 'relic', 'mod', 'arcane_enhancement', 'component', 'blueprint'}

def items_payload():
    owned = jload(os.path.join(DATA, 'owned.json')) or []
    prices = jload(os.path.join(DATA, 'prices.json')) or {}
    stats = jload(os.path.join(DATA, 'stats.json')) or {}
    out, seen = [], {}
    for o in owned:
        tags = set(o.get('tags') or [])
        if 'set' in tags and 'prime' not in tags and o.get('section') in ('Suits', 'LongGuns', 'Pistols', 'Melee', 'Sentinels', 'SentinelWeapons'):
            continue
        key = o['slug']
        r = seen.get(key)
        if not r:
            if 'relic' in tags: cat = 'relic'
            elif 'mod' in tags: cat = 'mod'
            elif 'arcane_enhancement' in tags: cat = 'arcane'
            elif 'prime' in tags and 'component' in tags: cat = 'prime_part'
            elif 'prime' in tags and 'blueprint' in tags: cat = 'prime_bp'
            elif 'prime' in tags and 'set' in tags: cat = 'prime_set'
            else: cat = 'other'
            r = seen[key] = dict(slug=key, name=o['name'], cat=cat, count=0,
                                 ducats=o.get('ducats'), wts=None, wtb=None,
                                 vol48=None, median=None, avg48=None,
                                 sections=set())
            out.append(r)
        r['count'] += o.get('count') or 1
        r['sections'].add(o.get('section') or '')
    for r in out:
        p = prices.get(r['slug']) or {}
        r['wts'] = p.get('wts'); r['wtb'] = p.get('wtb')
        s = stats.get(r['slug']) or {}
        r['vol48'] = s.get('vol48'); r['median'] = s.get('median'); r['avg48'] = s.get('avg48')
        r['value'] = (r['wts'] or 0) * r['count']
        r['spread'] = (r['wts'] - r['wtb']) if (r['wts'] is not None and r['wtb'] is not None) else None
        r['sections'] = ','.join(sorted(x for x in r['sections'] if x))
    return out

def plat_history_payload():
    hist = jload(os.path.join(DATA, 'plat_history.json')) or []
    now = int(time.time())

    def before(t):
        v = None
        for p in hist:
            if p['ts'] <= t:
                v = p['plat']
        return v

    cur = hist[-1]['plat'] if hist else None
    d24 = d7 = None
    if hist:
        b24, b7 = before(now - 86400), before(now - 7 * 86400)
        if b24 is not None: d24 = cur - b24
        if b7 is not None: d7 = cur - b7
    return dict(points=hist, now=cur, d24=d24, d7=d7,
                first_ts=hist[0]['ts'] if hist else None,
                first_plat=hist[0]['plat'] if hist else None, n=len(hist))

def trades_payload():
    hist = jload(os.path.join(DATA, 'trade_log.json')) or []
    tot = dict(earned=0, spent=0, net=0, sales=0, purchases=0, items=0)
    for e in hist:
        k = e.get('kind')
        if k == 'sale':
            tot['earned'] += e.get('total') or 0
            tot['sales'] += 1
            tot['items'] += e.get('qty') or 0
        elif k == 'purchase':
            tot['spent'] += e.get('total') or 0
            tot['purchases'] += 1
            tot['items'] += e.get('qty') or 0
    tot['net'] = tot['earned'] - tot['spent']
    return dict(events=list(reversed(hist)), totals=tot, n=len(hist))

def summary_payload():
    save = jload(os.path.join(DATA, 'lastData.dec.json')) or {}
    items = items_payload()
    totals = {}
    for r in items:
        totals[r['cat']] = totals.get(r['cat'], 0) + (r['value'] or 0)
    def mtime(p):
        try: return int(os.path.getmtime(p))
        except OSError: return None
    return dict(
        mr=save.get('PlayerLevel'), trades=save.get('TradesRemaining'),
        gifts=save.get('GiftsRemaining'), credits=save.get('RegularCredits'),
        plat=save.get('PremiumCredits'),
        items=len(items), priced=sum(1 for r in items if r['wts'] is not None),
        total_value=sum(r['value'] or 0 for r in items), by_cat=totals,
        lastdata_mtime=mtime(os.path.join(DATA, 'lastData.dec.json')),
        prices_mtime=mtime(os.path.join(DATA, 'prices.json')),
        plat_hist=plat_history_payload(),
    )

class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype='application/json'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_file(self, rel):
        full = os.path.normpath(os.path.join(STATIC, rel))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            return self._send(404, {'error': 'missing'})
        ext = os.path.splitext(full)[1].lstrip('.')
        ct = {'html': 'text/html; charset=utf-8', 'js': 'text/javascript', 'css': 'text/css',
              'json': 'application/json', 'ico': 'image/x-icon'}.get(ext, 'application/octet-stream')
        with open(full, 'rb') as f:
            self._send(200, f.read(), ct)

    def do_GET(self):
        p = urlparse(self.path).path
        if p == '/': return self._serve_file('index.html')
        if p == '/api/summary': return self._send(200, summary_payload())
        if p == '/api/items': return self._send(200, items_payload())
        if p == '/api/plat_history': return self._send(200, plat_history_payload())
        if p == '/api/trades': return self._send(200, trades_payload())
        if p == '/api/report': return self._send(200, jload(os.path.join(DATA, 'report.json')) or {})
        return self._serve_file(p.lstrip('/'))

    def do_POST(self):
        p = urlparse(self.path).path
        if p == '/api/refresh':
            try:
                r = subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', 'refresh.py')],
                                   capture_output=True, text=True, timeout=180, cwd=ROOT)
                ok = r.returncode == 0
                snap = ''
                if ok:
                    s = subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', 'snapshot_plat.py')],
                                       capture_output=True, text=True, timeout=60, cwd=ROOT)
                    snap = (s.stdout or '').strip()
                return self._send(200 if ok else 500, {
                    'ok': ok, 'stdout': (r.stdout or '')[-2000:], 'stderr': (r.stderr or '')[-2000:],
                    'snapshot': snap, 'summary': summary_payload() if ok else None})
            except Exception as e:
                return self._send(500, {'ok': False, 'error': str(e)})
        if p == '/api/trades':
            try:
                ln = int(self.headers.get('Content-Length') or 0)
                ev = json.loads(self.rfile.read(ln).decode('utf-8', 'replace') or '{}')
                if ev.get('kind') not in ('sale', 'purchase', 'listing', 'unlist', 'reprice', 'note'):
                    return self._send(400, {'ok': False, 'error': 'bad kind'})
                ev.setdefault('ts', int(time.time()))
                path = os.path.join(DATA, 'trade_log.json')
                hist = jload(path) or []
                hist.append(ev)
                json.dump(hist, open(path, 'w', encoding='utf-8'), indent=1)
                return self._send(200, {'ok': True, 'n': len(hist), 'totals': trades_payload()['totals']})
            except Exception as e:
                return self._send(500, {'ok': False, 'error': str(e)})
        return self._send(404, {'error': 'not found'})

    def log_message(self, fmt, *args):
        pass

if __name__ == '__main__':
    srv = ThreadingHTTPServer(('127.0.0.1', PORT), H)
    print(f'WFM Trader serving on http://127.0.0.1:{PORT}/ (ctrl-c to stop)', flush=True)
    srv.serve_forever()
