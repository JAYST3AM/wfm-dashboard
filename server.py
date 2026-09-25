"""WFM Trader dashboard — localhost server (stdlib only).
Serves static/ + JSON API over the project's data/ folder.
"""
import json, os, sys, subprocess, time, re, html as htmllib
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, 'data')
STATIC = os.path.join(ROOT, 'static')
PORT = int(os.environ.get('WFM_PORT', '8787'))
HOST = '127.0.0.1'
# Optional dashboard config (scripts/config.py → data/config.json). Read-only, never creates;
# env (WFM_PORT/WFM_HOST) still wins over the file. Values validated by config.py itself.
try:
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    import config as _dashcfg
    _cfg = _dashcfg.read()
    if not os.environ.get('WFM_PORT'):
        PORT = int(_cfg.get('port') or PORT)
    HOST = os.environ.get('WFM_HOST') or _cfg.get('host') or HOST
except Exception:
    _cfg = {}

# When launched via pythonw (no console) sys.stdout/stderr are None — log to data/server.log.
if sys.stdout is None or sys.stderr is None:
    try:
        _lf = open(os.path.join(DATA, 'server.log'), 'a', encoding='utf-8', buffering=1)
        sys.stdout = sys.stderr = _lf
    except Exception:
        pass

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

NEWS_UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'

FEATURES = {
    'deals': 'deals.json', 'ducats': 'ducats.json', 'sets': 'sets.json', 'relics': 'relic_ev.json',
    'limits': 'trader_limits.json', 'sessions': 'session_stats.json', 'invdiff': 'invdiff.json',
    'movers': 'price_movers.json', 'flips': 'flip_digest.json', 'trends': 'trends.json',
    'baro': 'baro.json', 'wishlist': 'wishlist.json', 'nudges': 'nudges.json', 'killswitch': 'kill_switch.json',
    'flipper': 'flipper_plan.json', 'hygiene': 'hygiene_plan.json', 'runqueue': 'run_queue.json',
    'timing': 'sell_timing.json', 'watchlist': 'watchlist.json', 'rivens': 'rivens.json',
    'meta': 'meta_watch.json', 'craft': 'craft.json',
    'notify': 'notify_outbox.json',
    'collection': 'collection_log.json', 'cards': 'mod_cards.json', 'ledger': 'plat_ledger.json',
    'advisor': 'sell_advisor.json',
}


def feature_payload(name):
    raw = jload(os.path.join(DATA, FEATURES[name])) or {}
    if name == 'deals':
        raw['deals'] = (raw.get('deals') or [])[:_cfg.get('deals_shown') or 60]
    elif name == 'ducats':
        rows = raw.get('rows') or []
        burn = sorted([r for r in rows if r.get('verdict') == 'BURN'], key=lambda r: -(r.get('ducats_per_plat') or 0))[:25]
        sell = sorted([r for r in rows if r.get('verdict') == 'SELL'], key=lambda r: -(r.get('sell_total') or 0))[:25]
        raw['rows'] = burn + sell
        raw.pop('buckets', None)
    elif name == 'sets':
        raw.pop('sets', None)  # full rows are ~350KB; UI uses summary/top_targets/cash_out_parts
    elif name == 'sessions':
        raw['sessions'] = (raw.get('sessions') or [])[:_cfg.get('sessions_shown') or 12]
    elif name == 'craft':
        raw['rows'] = [r for r in (raw.get('rows') or []) if r.get('verdict') != 'SKIP'][:40]
        raw.pop('live_prices', None)
        raw.pop('ignored_ingredients', None)
    elif name == 'meta':
        raw['rows'] = (raw.get('rows') or [])[:60]
    elif name == 'advisor':
        raw.pop('ranked', None)  # UI reads items/ranked order from 'top' + per-slug lookups
        for rec in (raw.get('items') or {}).values():
            rec.pop('notes', None)
    return raw

def cfg_payload():
    """Trader guardrail settings: current values + slider schema (from settings.py)."""
    spath = os.path.join(ROOT, 'scripts', 'trader', 'settings.py')
    out = {'settings': {}, 'schema': [], 'error': None}
    try:
        r = subprocess.run([sys.executable, spath, '--show'], capture_output=True, text=True, timeout=30, cwd=ROOT)
        out['settings'] = json.loads(r.stdout or '{}')
    except Exception as e:
        out['error'] = str(e)[:200]
    try:
        r = subprocess.run([sys.executable, spath, '--schema'], capture_output=True, text=True, timeout=30, cwd=ROOT)
        out['schema'] = json.loads(r.stdout or '[]')
    except Exception:
        pass
    return out

def dashcfg_payload():
    """Dashboard config (scripts/config.py → data/config.json): current values + knob schema.

    Same shape/pattern as cfg_payload(): one shell-out per key per request (no caching, so a
    Save is visible on the next GET), 30s timeout each, and any failure degrades to
    {'values': {}, 'schema': []} with the error kept in 'error'.
    """
    spath = os.path.join(ROOT, 'scripts', 'config.py')
    out = {'values': {}, 'schema': [], 'error': None}
    try:
        r = subprocess.run([sys.executable, spath, '--show'], capture_output=True, text=True, timeout=30, cwd=ROOT)
        out['values'] = json.loads(r.stdout or '{}')
    except Exception as e:
        out['error'] = str(e)[:200]
    try:
        r = subprocess.run([sys.executable, spath, '--schema'], capture_output=True, text=True, timeout=30, cwd=ROOT)
        out['schema'] = json.loads(r.stdout or '[]')
    except Exception:
        pass
    return out

def dashcfg_set(pairs):
    """Write {knob: value} through `config.py --set key=value`, one pair at a time.

    Returns (http_status, body) where body is {'ok', 'results', 'cfg'} — plus 'rc' and
    config.py's own message in 'error' when a value is refused (rc 2). Later pairs are not
    attempted after a refusal, and a refused pair leaves data/config.json byte-identical.
    """
    spath = os.path.join(ROOT, 'scripts', 'config.py')
    results = []
    for key, value in (pairs or {}).items():
        try:
            r = subprocess.run([sys.executable, spath, '--set', '%s=%s' % (key, value)],
                               capture_output=True, text=True, timeout=30, cwd=ROOT)
            rc = r.returncode
            msg = ((r.stdout or '') + (r.stderr or '')).strip()[-300:]
        except Exception as e:
            rc, msg = 1, str(e)[:200]
        results.append({'key': key, 'value': value, 'ok': rc == 0, 'message': msg})
        if rc != 0:
            return 200, {'ok': False, 'rc': rc, 'error': msg, 'results': results,
                         'cfg': dashcfg_payload()}
    return 200, {'ok': True, 'results': results, 'cfg': dashcfg_payload()}

def _fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={'User-Agent': NEWS_UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def _plain(s, cap=240):
    s = htmllib.unescape(re.sub('<[^>]+>', ' ', s or ''))
    s = re.sub(r'\[/?[^\]]+\]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()[:cap]

def refresh_gamenews():
    items = []
    try:
        root = ET.fromstring(_fetch('https://forums.warframe.com/forum/3-pc-update-notes.xml'))
        for it in root.iter('item'):
            title = (it.findtext('title') or '').strip()
            link = (it.findtext('link') or '').strip()
            try:
                ts = int(parsedate_to_datetime(it.findtext('pubDate') or '').timestamp())
            except Exception:
                ts = None
            if title and link:
                items.append(dict(title=title, url=link, date=ts, source='updates',
                                  excerpt=_plain(it.findtext('description') or '')))
    except Exception:
        pass
    try:
        sj = json.loads(_fetch('https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=230410&count=12&maxlength=300').decode('utf-8'))
        for it in sj['appnews']['newsitems']:
            if (it.get('feedlabel') or '') != 'Community Announcements':
                continue
            if it.get('title') and it.get('url'):
                items.append(dict(title=it['title'].strip(), url=it['url'], date=it.get('date'),
                                  source='news', excerpt=_plain(it.get('contents') or '')))
    except Exception:
        pass
    seen, merged = set(), []
    for it in sorted(items, key=lambda x: x.get('date') or 0, reverse=True):
        k = it['title'].lower()
        if k in seen:
            continue
        seen.add(k)
        merged.append(it)
    version = None
    for it in merged:
        if it.get('source') == 'updates':
            m = re.search(r'(\d+\.\d+(?:\.\d+)?)', it.get('title') or '')
            if m:
                version = m.group(1)
            break
    out = dict(fetched=int(time.time()), version=version, items=merged[:10])
    try:
        with open(os.path.join(DATA, 'gamenews.json'), 'w', encoding='utf-8') as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
    except Exception:
        pass
    return out

def gamenews_payload():
    news = jload(os.path.join(DATA, 'gamenews.json'))
    if not news or (time.time() - (news.get('fetched') or 0)) > (_cfg.get('gamenews_cache_seconds') or 1800):
        try:
            news = refresh_gamenews()
        except Exception:
            pass
    return news or dict(fetched=None, version=None, items=[])

def trader_payload():
    return dict(
        plan=jload(os.path.join(DATA, 'trader_plan.json')) or {},
        state=jload(os.path.join(DATA, 'trader_state.json')) or {},
        settings=jload(os.path.join(ROOT, 'scripts', 'trader', 'settings.json')) or {},
        queue=jload(os.path.join(DATA, 'trader_relist_queue.json')) or [],
        undercuts=jload(os.path.join(DATA, 'trader_undercuts.json')) or {},
    )


def summary_payload():
    save = jload(os.path.join(DATA, 'lastData.dec.json')) or {}
    items = items_payload()
    totals = {}
    for r in items:
        totals[r['cat']] = totals.get(r['cat'], 0) + (r['value'] or 0)
    # report.json prices sellable copies only (equipped copies excluded);
    # fall back to the owned-basis sum when the report is missing/stale.
    rpt_t = (jload(os.path.join(DATA, 'report.json')) or {}).get('totals') or {}
    owned_value = sum(r['value'] or 0 for r in items)
    def mtime(p):
        try: return int(os.path.getmtime(p))
        except OSError: return None
    return dict(
        mr=save.get('PlayerLevel'), trades=save.get('TradesRemaining'),
        gifts=save.get('GiftsRemaining'), credits=save.get('RegularCredits'),
        plat=save.get('PremiumCredits'),
        items=len(items), priced=sum(1 for r in items if r['wts'] is not None),
        total_value=rpt_t.get('value', owned_value), total_value_owned=owned_value,
        by_cat=(rpt_t.get('by_cat') or totals),
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
        if p == '/api/trader': return self._send(200, trader_payload())
        if p == '/api/gamenews': return self._send(200, gamenews_payload())
        if p == '/api/config': return self._send(200, dashcfg_payload())
        if p == '/api/trader/cfg': return self._send(200, cfg_payload())
        if p.startswith('/api/feature/'):
            name = p.rsplit('/', 1)[-1]
            if name in FEATURES:
                try:
                    return self._send(200, feature_payload(name))
                except Exception as e:
                    return self._send(500, {'error': str(e)[:200]})
            return self._send(404, {'error': 'unknown feature'})
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
        if p in ('/api/trader/plan', '/api/trader/cycle', '/api/trader/watch'):
            try:
                if p.endswith('plan'):
                    cmd = [sys.executable, os.path.join(ROOT, 'scripts', 'trader', 'lister.py')]
                    tmo = 300
                elif p.endswith('watch'):
                    cmd = [sys.executable, os.path.join(ROOT, 'scripts', 'trader', 'watcher.py'), '--once']
                    tmo = 240
                else:
                    cmd = [sys.executable, os.path.join(ROOT, 'scripts', 'trader', 'detector.py'), '--once']
                    tmo = 120
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=tmo, cwd=ROOT)
                return self._send(200 if r.returncode == 0 else 500, {
                    'ok': r.returncode == 0, 'stdout': (r.stdout or '')[-3000:],
                    'stderr': (r.stderr or '')[-2000:], 'trader': trader_payload()})
            except Exception as e:
                return self._send(500, {'ok': False, 'error': str(e)})
        if p in ('/api/trader/hygiene', '/api/trader/flip', '/api/trader/runqueue'):
            try:
                if p.endswith('hygiene'):
                    cmd = [sys.executable, os.path.join(ROOT, 'scripts', 'trader', 'hygiene.py'), '--once']
                    tmo = 120
                elif p.endswith('flip'):
                    cmd = [sys.executable, os.path.join(ROOT, 'scripts', 'trader', 'flipper.py'), '--live']
                    tmo = 300
                else:
                    cmd = [sys.executable, os.path.join(ROOT, 'scripts', 'trader', 'runqueue.py')]
                    tmo = 240
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=tmo, cwd=ROOT)
                return self._send(200 if r.returncode == 0 else 500, {
                    'ok': r.returncode == 0, 'stdout': (r.stdout or '')[-3000:], 'stderr': (r.stderr or '')[-2000:]})
            except Exception as e:
                return self._send(500, {'ok': False, 'error': str(e)})
        if p == '/api/trader/notify':
            try:
                cmd = [sys.executable, os.path.join(ROOT, 'scripts', 'notify.py'), '--send', 'Dashboard test ping',
                       '--body', 'test ping from the dashboard button', '--to', 'my-channel']
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=ROOT)
                return self._send(200, {'ok': r.returncode == 0, 'stdout': (r.stdout or '')[-1500:], 'stderr': (r.stderr or '')[-800:]})
            except Exception as e:
                return self._send(500, {'ok': False, 'error': str(e)})
        if p == '/api/trader/settings':
            try:
                ln = int(self.headers.get('Content-Length') or 0)
                b = json.loads(self.rfile.read(ln).decode('utf-8', 'replace') or '{}')
                pairs = b.get('pairs') or {}
                spath = os.path.join(ROOT, 'scripts', 'trader', 'settings.py')
                for k, v in pairs.items():
                    r = subprocess.run([sys.executable, spath, '--set', '%s=%s' % (k, v)],
                                       capture_output=True, text=True, timeout=60, cwd=ROOT)
                    if r.returncode != 0:
                        return self._send(200, {'ok': False, 'rc': r.returncode,
                                                'error': ((r.stdout or '') + (r.stderr or '')).strip()[-300:],
                                                'cfg': cfg_payload()})
                return self._send(200, {'ok': True, 'cfg': cfg_payload()})
            except Exception as e:
                return self._send(500, {'ok': False, 'error': str(e)})
        if p == '/api/config':
            try:
                ln = int(self.headers.get('Content-Length') or 0)
                b = json.loads(self.rfile.read(ln).decode('utf-8', 'replace') or '{}')
                code, body = dashcfg_set(b.get('pairs') or {})
                return self._send(code, body)
            except Exception as e:
                return self._send(500, {'ok': False, 'error': str(e)})
        if p == '/api/trader/killswitch':
            try:
                ln = int(self.headers.get('Content-Length') or 0)
                b = json.loads(self.rfile.read(ln).decode('utf-8', 'replace') or '{}')
                ks = {'active': bool(b.get('active')), 'note': str(b.get('note') or '')[:200], 'ts': int(time.time())}
                path = os.path.join(DATA, 'kill_switch.json')
                tmp = path + '.tmp'
                json.dump(ks, open(tmp, 'w', encoding='utf-8'))
                os.replace(tmp, path)
                return self._send(200, ks)
            except Exception as e:
                return self._send(500, {'ok': False, 'error': str(e)})
        return self._send(404, {'error': 'not found'})

    def log_message(self, fmt, *args):
        pass

if __name__ == '__main__':
    srv = ThreadingHTTPServer((HOST, PORT), H)
    print(f'WFM Trader serving on http://{HOST}:{PORT}/ (ctrl-c to stop)', flush=True)
    srv.serve_forever()
