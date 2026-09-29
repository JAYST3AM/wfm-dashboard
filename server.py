"""WFM Trader dashboard — localhost server (stdlib only).
Serves static/ + JSON API over the project's data/ folder.
"""
import json, os, sys, subprocess, time, re, html as htmllib, threading
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

ROOT = os.path.abspath(os.environ.get('WFM_ROOT') or os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get('WFM_DATA') or os.path.join(ROOT, 'data')
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
    _dashcfg = None
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
    cards = {c.get('slug'): c for c in
             ((jload(os.path.join(DATA, 'mod_cards.json')) or {}).get('cards') or [])
             if c.get('slug')}
    lanes = (jload(os.path.join(DATA, 'price_lanes.json')) or {}).get('items') or {}
    equipped = {}
    for x in ((jload(os.path.join(DATA, 'inuse.json')) or {}).get('items') or []):
        if x.get('slug'):
            equipped[x['slug']] = equipped.get(x['slug'], 0) + 1
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
        # Rank lanes (same rule as scripts/report.build_rows): a ranked copy is priced from
        # the lane of the rank owned. The item-level wts is usually a rank-0 listing while
        # the item-level wtb can be a rank-10 bid - an any-rank pair misleads on mods.
        r['equipped'] = equipped.get(r['slug'], 0)
        rank = (cards.get(r['slug']) or {}).get('owned_rank')
        lane_doc = lanes.get(r['slug'])
        if isinstance(rank, int):
            r['own_rank'] = rank
            if isinstance(lane_doc, dict):
                cells = lane_doc.get('lanes') or {}
                if cells:
                    cell = cells.get(str(rank)) if isinstance(cells.get(str(rank)), dict) else {}
                    r['lane_rank'] = rank
                    r['lane_ask'] = cell.get('ask')
                    r['lane_bid'] = cell.get('bid')
                    r['lanes'] = cells
                    r['max_rank'] = lane_doc.get('max_rank')
        r['value'] = (r['wts'] or 0) * r['count']
        r['spread'] = (r['wts'] - r['wtb']) if (r['wts'] is not None and r['wtb'] is not None) else None
        r['sections'] = ','.join(sorted(x for x in r['sections'] if x))
    return out

_CATALOG = None

def catalog_payload():
    """Full WFM catalogue (slug/name/icon) behind the global item search - owned or not.
    Cached in memory; the source dump is ~1.6 MB and stable for the session."""
    global _CATALOG
    if _CATALOG is None:
        d = jload(os.path.join(DATA, 'wfm_items_v2.json')) or {}
        items = d.get('data') if isinstance(d, dict) else None
        out = []
        for it in (items or []):
            if not isinstance(it, dict):
                continue
            slug = str(it.get('slug') or '').strip()
            if not slug:
                continue
            en = (it.get('i18n') or {}).get('en') or {}
            out.append({'slug': slug, 'name': en.get('name') or slug, 'icon': en.get('icon') or ''})
        out.sort(key=lambda r: r['name'].lower())
        _CATALOG = out
    return _CATALOG

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

def _money_of(ev):
    """The platinum a stored event moved; trade_schema.money_of owns it (one reader, every total)."""
    return _session().money_of(ev)


def trades_payload():
    hist = jload(os.path.join(DATA, 'trade_log.json')) or []
    tot = dict(earned=0, spent=0, net=0, sales=0, purchases=0, items=0)
    # schema.money_of: `total` when the record has it, and `plat x qty` for a pre-canonical one, so
    # historical money cannot disappear from a total (outside review, round 3).
    for e in hist:
        k = e.get('kind')
        if k == 'sale':
            tot['earned'] += _money_of(e)
            tot['sales'] += 1
            tot['items'] += e.get('qty') or 0
        elif k == 'purchase':
            tot['spent'] += _money_of(e)
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
    'advisor': 'sell_advisor.json', 'itemhist': 'item_history.json',
    'materials': 'materials.json',
    'player': 'player.json',
    'relics_panel': 'relics_panel.json',     # Collection > Relics (where from + what's inside)
    'mastery': 'mastery.json',               # Mastery Helper (MR + what to master next)
    'progress': 'progress.json',             # Today / sessions tracker
    'session': 'trade_session.json',         # Trading Session loop (computed in session_payload)
}


def feature_payload(name, query=None):
    if name == 'session':
        # The loop's own payload, not the raw store: session + focus + pending + summary.
        return session_payload()
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
    elif name == 'itemhist':
        # Two shapes from one store. With ?slug=<slug> the item price page gets the full record:
        # [ts, ask, bid] points and your own sales at real timestamps. Without it the inventory
        # Trend column gets the ask series only, oldest -> newest, last 48 usable points, ints.
        # Either way a missing item_history.json answers empty, never a 500.
        wanted = None
        if query:
            wanted = (query.get('slug') or [None])[0]
        if wanted:
            rec = ((raw.get('items') or {}).get(wanted) or {})
            points, sales = [], []
            for pt in (rec.get('points') or []):
                if not (isinstance(pt, (list, tuple)) and len(pt) > 1) or pt[0] is None:
                    continue
                val = pt[1]
                try:
                    val = int(round(float(val))) if val is not None else None
                except (TypeError, ValueError):
                    val = None
                bid = pt[2] if len(pt) > 2 else None
                try:
                    bid = int(round(float(bid))) if bid is not None else None
                except (TypeError, ValueError):
                    bid = None
                if val is None and bid is None:
                    continue
                points.append([int(pt[0]), val, bid])
            for sale in (rec.get('sales') or []):
                if isinstance(sale, (list, tuple)) and len(sale) > 1 and sale[0] is not None:
                    try:
                        sales.append([int(sale[0]), int(round(float(sale[1]))), int(sale[2]) if len(sale) > 2 and sale[2] is not None else 1])
                    except (TypeError, ValueError):
                        continue
            return {
                'slug': wanted, 'name': rec.get('name') or wanted,
                'points': points, 'sales': sales,
                'first': rec.get('first'), 'last': rec.get('last'),
                'src': rec.get('src') or {}, 'count': len(points),
            }
        src = raw.get('items') if isinstance(raw, dict) else None
        items = {}
        for slug, rec in (src or {}).items():
            if not isinstance(rec, dict):
                continue
            vals = []
            for pt in (rec.get('points') or [])[-48:]:
                ask = pt[1] if isinstance(pt, (list, tuple)) and len(pt) > 1 else None
                if ask is None:
                    continue
                try:
                    vals.append(int(round(float(ask))))
                except (TypeError, ValueError):
                    continue
            if len(vals) >= 2:
                items[slug] = vals
        return {'count': len(items), 'items': items}
    elif name == 'materials':
        # Materials + Clan Dojo panels. Two files, joined by slug (never shipped raw):
        #   data/materials.json  -> what you own per slug (count, cat, dojo_hint)
        #   data/dojo_costs.json -> per-room costs + per-material needed totals
        # Both are owned by other scripts, so either one missing or corrupt degrades to an
        # empty panel (count 0, no rows, dojo null) with HTTP 200 - the route never 500s,
        # never writes, and never touches the network.
        dcosts = jload(os.path.join(DATA, 'dojo_costs.json'))
        have_dojo = isinstance(dcosts, dict)
        dcosts = dcosts if have_dojo else {}

        def to_int(v):
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        needed = {}
        for slug, rec in (dcosts.get('materials') or {}).items():
            if not isinstance(rec, dict):
                continue
            n = to_int(rec.get('needed'))
            if n is None:
                continue
            needed[str(slug)] = (rec.get('name') or str(slug), n)
        owned, rows = {}, []
        for r in (raw.get('materials') or []):
            if not isinstance(r, dict) or not r.get('slug'):
                continue
            slug = str(r['slug'])
            if slug in owned:
                continue
            count = to_int(r.get('count')) or 0
            owned[slug] = count
            n = needed.get(slug, (None, None))[1]
            rows.append({'slug': slug, 'name': r.get('name') or slug, 'count': count,
                         'cat': r.get('cat') or '',
                         'dojo': slug in needed or bool(r.get('dojo_hint')),
                         'needed': n, 'short': max(0, n - count) if n is not None else None})
        dojo = None
        if have_dojo:
            rooms, credits = [], 0
            for rm in (dcosts.get('rooms') or []):
                if not isinstance(rm, dict) or not rm.get('slug'):
                    continue
                cr = to_int(rm.get('credits')) or 0
                credits += cr
                costs = []
                for cslug, qty in (rm.get('costs') or {}).items():
                    q = to_int(qty)
                    if q is None:
                        continue
                    cslug = str(cslug)
                    costs.append({'slug': cslug,
                                  'name': (needed.get(cslug) or (None,))[0] or next(
                                      (r2['name'] for r2 in rows if r2['slug'] == cslug), cslug),
                                  'qty': q, 'owned': owned.get(cslug, 0),
                                  'short': max(0, q - owned.get(cslug, 0))})
                costs.sort(key=lambda c: (-c['qty'], c['name'].lower()))
                rooms.append({'slug': str(rm['slug']), 'name': rm.get('name') or str(rm['slug']),
                              'url': rm.get('url') or '', 'credits': cr,
                              'built': to_int(rm.get('built')) or 0,
                              'note': str(rm.get('note') or ''), 'costs': costs})
            mats = []
            for slug, (mname, n) in needed.items():
                have = owned.get(slug, 0)
                mats.append({'slug': slug, 'name': mname, 'needed': n, 'owned': have,
                             'short': max(0, n - have)})
            mats.sort(key=lambda m: (-m['needed'], m['name'].lower()))

            # Clan tiers: the wiki lists every room's cost at all five clan sizes. Needed/Owned/
            # Short are rebuilt per tier from data/dojo_costs.json 'tier_totals' (verbatim source
            # values, nothing scaled here) so the panel's tier switch matches the player's clan.
            mat_names = {r['slug']: r['name'] for r in rows}
            name_of = lambda s: (needed.get(s) or (None,))[0] or mat_names.get(s) or s
            tiers_list = [t for t in (dcosts.get('tiers') or []) if isinstance(t, str)]
            tier_totals = {}
            for tier in tiers_list:
                blk = (dcosts.get('tier_totals') or {}).get(tier)
                if not isinstance(blk, dict):
                    continue
                trows = []
                for slug, rec in (blk.get('materials') or {}).items():
                    if not isinstance(rec, dict):
                        continue
                    n = to_int(rec.get('needed'))
                    if n is None:
                        continue
                    slug = str(slug)
                    have = owned.get(slug, 0)
                    mat_names.setdefault(slug, str(rec.get('name') or slug))
                    trows.append({'slug': slug, 'name': str(rec.get('name') or slug), 'needed': n,
                                  'owned': have, 'short': max(0, n - have)})
                trows.sort(key=lambda m: (-m['needed'], m['name'].lower()))
                tier_credits = to_int(blk.get('credits')) or 0
                if trows or tier_credits:        # a tier with no usable number is not a tier
                    tier_totals[tier] = {'credits': tier_credits, 'materials': trows}
            room_tiers = {}
            for rm in rooms:
                per = (dcosts.get('room_tiers') or {}).get(rm['slug'])
                if not isinstance(per, dict):
                    continue
                tmap = {}
                for tier, blk in per.items():
                    if not isinstance(blk, dict):
                        continue
                    costs = []
                    for cslug, qty in (blk.get('costs') or {}).items():
                        q = to_int(qty)
                        if q is None:
                            continue
                        cslug = str(cslug)
                        costs.append({'slug': cslug, 'name': name_of(cslug), 'qty': q,
                                      'owned': owned.get(cslug, 0),
                                      'short': max(0, q - owned.get(cslug, 0))})
                    costs.sort(key=lambda c: (-c['qty'], c['name'].lower()))
                    if costs:                       # a tier with no usable cost is not a tier
                        tmap[str(tier)] = {'credits': to_int(blk.get('credits')) or 0, 'costs': costs}
                if tmap:
                    room_tiers[rm['slug']] = tmap
            dojo = {'source': str(dcosts.get('source') or ''),
                    'fetched_iso': str(dcosts.get('fetched_iso') or ''),
                    'scope': str(dcosts.get('scope') or ''), 'credits': credits,
                    'rooms': rooms, 'materials': mats,
                    'tiers': tiers_list, 'tier_totals': tier_totals, 'room_tiers': room_tiers,
                    'skipped': [s for s in (dcosts.get('skipped') or []) if isinstance(s, dict)]}
        return {'count': len(rows), 'updated_iso': str(raw.get('updated_iso') or ''),
                'categories': raw.get('categories') if isinstance(raw.get('categories'), dict) else {},
                'materials': rows, 'dojo': dojo}
    elif name == 'player':
        # data/player.json (profile snapshot: mastery, clan, syndicates, intrinsics, focus).
        # Shipped as-is to the Player page. A missing, corrupt or non-object file answers {}
        # with HTTP 200, so the page renders dashes instead of the route raising.
        if not isinstance(raw, dict):
            raw = {}
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

def profiles_payload():
    """Account profiles (scripts/profiles.py --list --json): marker state + every profile.

    The dashboard's Settings > Accounts card reads this; the switch itself is a POST that
    shells out to profiles.py, so the engine keeps owning every safety check.
    """
    spath = os.path.join(ROOT, 'scripts', 'profiles.py')
    try:
        r = subprocess.run([sys.executable, spath, '--list', '--json'],
                           capture_output=True, text=True, timeout=30, cwd=ROOT)
        if r.returncode != 0:
            return {'ok': False, 'error': ((r.stdout or '') + (r.stderr or '')).strip()[-300:]}
        doc = json.loads(r.stdout or '{}')
        doc['ok'] = True
        return doc
    except Exception as e:
        return {'ok': False, 'error': str(e)[:200]}

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

# ---------------------------------------------------------------- orders (Trade page)
# Jay (2026-09-28): *"is there a list on trade that shows real buy orders and sell orders?
# with usernames"* + *"the app needs to understand values of different ranks for a mod"*.
# scripts/orders.py owns the network discipline and the 45s raw cache; these routes only shape
# its answer for the tab. /api/rank_values keeps the ladder rendering even when wfm is
# unreachable (data/price_lanes.json is the last snapshot), and /api/whisper owns the local
# rate limit so the dashboard can never spam the same seller twice in a row.
ORDERS_TIMEOUT = 6.0     # wall-clock budget for one orderbook read; the route cannot hang past it
ORDERS_MAX = 40          # rows a side the tab shows

try:
    import orders as orderbook               # scripts/ is on sys.path (the config import above)
except Exception:
    orderbook = None


def _qs(query, key, default=''):
    """First value of a GET query key (parse_qs shape)."""
    try:
        vals = (query or {}).get(key)
        return str(vals[0]) if vals else default
    except (TypeError, ValueError, IndexError):
        return default


def _rank_arg(raw):
    """rank=<n|all> -> (rank|None, error|None)."""
    s = str(raw or '').strip().lower()
    if s in ('', 'all'):
        return None, None
    try:
        r = int(s)
    except ValueError:
        return None, 'rank must be a number or all'
    if r < 0:
        return None, 'rank must be 0 or more'
    return r, None


def _limit_arg(raw, cap=ORDERS_MAX):
    """limit=<n<=40> -> (1..cap, error|None); numbers are clamped, junk is refused."""
    s = str(raw or '').strip()
    if not s:
        return cap, None
    try:
        n = int(s)
    except ValueError:
        return cap, 'limit must be a number'
    return max(1, min(cap, n)), None


def orders_payload(query=None):
    """GET /api/orders - one item's live book, reduced for the Trade > Orders tab.

    {'ok', 'item', 'age_s', 'counts': {'sell','buy'}, 'ranks': [...], 'sell': [...],
     'buy': [...], 'values': {...}, 'source': 'live'|'cache'} - plus 'error' when the book
    could not be read, in which case the lists stay empty and ok stays true: the tab shows
    the reason instead of the route raising or hanging (ORDERS_TIMEOUT is the ceiling).
    rows are {platinum, quantity, rank, user, reputation, status, updated_ts} and 'values'
    is the per-rank ladder, so the tab can price the rank the copy actually is.
    """
    if orderbook is None:
        return {'ok': False, 'error': 'orders not installed'}
    item = _qs(query, 'item').strip().lower()
    if not item:
        return {'ok': False, 'error': 'item required'}
    if not orderbook.valid_slug(item):
        return {'ok': False, 'item': item, 'error': 'bad item slug'}
    rank, err = _rank_arg(_qs(query, 'rank'))
    if err:
        return {'ok': False, 'item': item, 'error': err}
    limit, err = _limit_arg(_qs(query, 'limit'))
    if err:
        return {'ok': False, 'item': item, 'error': err}
    snap = orderbook.snapshot(item, budget=ORDERS_TIMEOUT)
    if snap['source'] is None:                        # nothing to serve: no cache and no answer
        if '404' in str(snap['error'] or ''):         # a wrong slug is a wrong slug, not an outage
            return {'ok': False, 'item': item, 'error': 'unknown item'}
        return {'ok': True, 'item': item, 'age_s': None, 'source': None,
                'counts': {'sell': 0, 'buy': 0}, 'ranks': [], 'sell': [], 'buy': [],
                'values': {}, 'error': str(snap['error'] or 'orderbook unavailable')}
    rows = orderbook.book(snap['orders'], rank=rank, limit=limit)
    out = {'ok': True, 'item': item, 'name': item_display_name(item), 'age_s': snap['age_s'],
           'source': snap['source'],
           'counts': orderbook.counts(snap['orders'], rank=rank),
           'ranks': orderbook.ranks(snap['orders']),
           'sell': rows['sell'], 'buy': rows['buy'],
           'values': orderbook.values(snap['orders'])}
    if snap['error']:
        out['error'] = snap['error']
    return out


def rank_values_payload(query=None):
    """GET /api/rank_values - the per-rank ladder for one item.

    Live/cached orders first (source 'orders'); when there is no book the ladder falls back
    to data/price_lanes.json (source 'price_lanes', scripts/fetch_lanes.py's snapshot) so a
    rank ladder renders even with wfm unreachable. Only an item in neither store is an error.
    """
    if orderbook is None:
        return {'ok': False, 'error': 'orders not installed'}
    item = _qs(query, 'item').strip().lower()
    if not item:
        return {'ok': False, 'error': 'item required'}
    if not orderbook.valid_slug(item):
        return {'ok': False, 'item': item, 'error': 'bad item slug'}
    snap = orderbook.snapshot(item, budget=ORDERS_TIMEOUT)
    vals = orderbook.values(snap['orders']) if snap['orders'] else {}
    if vals:
        return {'ok': True, 'item': item, 'values': vals, 'source': 'orders'}
    lane_doc = jload(os.path.join(DATA, 'price_lanes.json')) or {}
    lanes = lane_doc.get('items') if isinstance(lane_doc, dict) else None
    rec = (lanes or {}).get(item) if isinstance(lanes, dict) else None
    if isinstance(rec, dict):
        return {'ok': True, 'item': item, 'values': rec.get('lanes') or {}, 'source': 'price_lanes'}
    return {'ok': False, 'item': item, 'values': {},
            'error': str(snap['error'] or ('no rank values for %s' % item))}


WHISPER_GAP = 2.0        # one whisper every 2 seconds...
WHISPER_PER_MIN = 10     # ...and ten a minute: wfm chat is not a firehose
_whisper_last = [0.0]
_whisper_minute = []


def _load_whisper():
    """scripts/whisper.py, imported on first use. -> (module|None, error|None)."""
    scripts = os.path.join(ROOT, 'scripts')
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        import whisper
        return whisper, None
    except Exception as e:
        return None, str(e)[:120]


_NAME_BY_SLUG = None


def item_display_name(item):
    """The name the paste carries: the catalogue's display name for a slug, else the text as given.

    The Orders tab sends the slug ('primed_continuity'); warframe.market's own message names the
    item ('Primed Continuity'), and the paste should read the same way.
    """
    global _NAME_BY_SLUG
    text = str(item or '').strip()
    if not text:
        return text
    if _NAME_BY_SLUG is None:
        try:
            _NAME_BY_SLUG = {r['slug']: r['name'] for r in catalog_payload()}
        except Exception:                                          # a missing dump must not 500
            _NAME_BY_SLUG = {}
    return _NAME_BY_SLUG.get(text.lower(), text)


def whisper_post(body):
    """POST /api/whisper -> (http_status, payload).

    body: {'item', 'user', 'price', 'kind': 'buy'|'sell', 'rank'?, 'lane'?, 'mode': 'copy'|'send'}.
    Builds the message through scripts/whisper.py (whisper.message(item, price, kind, rank)),
    copies it (whisper.copy) and, in send mode, sends it and reports the module's own reason.
    503 when whisper.py is not installed, 429 when the local cooldown trips, 400 on bad input -
    bad input never 500s.
    """
    body = body if isinstance(body, dict) else {}
    item = str(body.get('item') or '').strip().lower()
    # the paste names the item the way the site does; the slug stays for the ledger and lookups
    name = item_display_name(item)
    user = str(body.get('user') or '').strip()
    kind = str(body.get('kind') or '').strip().lower()
    mode = str(body.get('mode') or 'copy').strip().lower()
    if not item or not user:
        return 400, {'ok': False, 'error': 'item and user required'}
    if kind not in ('buy', 'sell'):
        return 400, {'ok': False, 'error': "kind must be 'buy' or 'sell'"}
    if mode not in ('copy', 'send'):
        return 400, {'ok': False, 'error': "mode must be 'copy' or 'send'"}
    price = body.get('price')
    if isinstance(price, bool) or isinstance(price, (dict, list)):
        return 400, {'ok': False, 'error': 'price must be a number'}
    try:
        price = int(price)
    except (TypeError, ValueError):
        return 400, {'ok': False, 'error': 'price must be a number'}
    if price < 1:
        return 400, {'ok': False, 'error': 'price must be at least 1'}
    rank = body.get('rank')
    if rank in (None, ''):
        rank = None
    else:
        try:
            rank = int(rank)
        except (TypeError, ValueError):
            return 400, {'ok': False, 'error': 'rank must be a number'}
        if rank < 0:
            return 400, {'ok': False, 'error': 'rank must be 0 or more'}
    now = time.time()
    if now - _whisper_last[0] < WHISPER_GAP:
        reason = 'one whisper every %.0fs' % WHISPER_GAP
        return 429, {'ok': False, 'error': reason, 'reason': reason}
    while _whisper_minute and now - _whisper_minute[0] > 60:
        _whisper_minute.pop(0)
    if len(_whisper_minute) >= WHISPER_PER_MIN:
        reason = 'whisper limit reached (%d a minute)' % WHISPER_PER_MIN
        return 429, {'ok': False, 'error': reason, 'reason': reason}
    whisper, err = _load_whisper()
    if whisper is None:
        return 503, {'ok': False, 'error': 'whisper not installed'}
    try:
        msg = whisper.message(name, price, kind, rank)
        # warframe.market's copy button includes the whisper command and its Terms ask for that
        # text used as-is: the clipboard and the keystrokes carry the whole line, not just the body
        ln = whisper.line(user, name, price, kind, rank) if hasattr(whisper, 'line') else msg
        copied = bool(whisper.copy(ln))
        sent, reason = False, ''
        if mode == 'send':
            res = whisper.send(ln, item=name, price=price, kind=kind, user=user)
            sent = bool(res[0])
            reason = str(res[1] or '') if len(res) > 1 else ''
    except Exception as e:                                     # a broken module must not 500 the UI
        return 500, {'ok': False, 'error': 'whisper: ' + str(e)[:160]}
    _whisper_last[0] = now
    _whisper_minute.append(now)
    out = {'ok': True, 'message': msg, 'line': ln, 'copied': copied,
           'sent': sent, 'reason': reason}
    # Trading Session (docs/trading-session-workflow.md §3): a whisper that actually reached the
    # game while a session is open becomes that session's CONTACTED trade - with the inventory and
    # platinum it went out at, which is the one snapshot reconciliation needs. Copied-but-not-sent
    # is deliberately not a contact: nothing left the clipboard. A failure here must never fail
    # the whisper, so it is contained.
    if sent:
        try:
            ts = _session()
            doc = ts.load(DATA)
            if doc.get('session'):
                # Which lane this whisper is for: the button names it when it knows it (the session
                # rows do), and otherwise it is derived from the rank. Two refinements of one relic
                # share a slug and have no rank, so the lane is what picks the right queue row.
                lane = str(body.get('lane') or '').strip()
                want = ts.key_of({'slug': item, 'lane': lane}) if lane else None
                row_qty, row_lane = 1, ''
                for r in (doc['session'].get('queue') or []):
                    if r.get('slug') != item:
                        continue
                    if want is not None and ts.key_of(r) != want:
                        continue
                    if want is None and (rank is None or r.get('rank') == rank):
                        row_qty, row_lane = r.get('qty') or 1, ts.lane_of(r)
                        break
                    row_qty, row_lane = r.get('qty') or 1, ts.lane_of(r)
                    break
                if not lane:
                    lane = row_lane or (('rank %d' % rank) if rank is not None else '')
                inv, plat, _basis = _session_before(item, rank, lane)
                out['contact'] = ts.contact(doc, item, rank=rank, qty=row_qty, price=price,
                                           buyer=user, inv_before=inv, plat_before=plat,
                                           kind=kind, lane=lane)
                ts.save(DATA, doc)
        except Exception as e:
            out['contact'] = None
            out['contact_error'] = str(e)[:120]
    return 200, out


# ------------------------------------------------------------------ build state (first run)
# docs/trading-session-workflow.md §9: the first build can take a while, so the app must not look
# dead while it happens. The states are the honest ones - Waiting / Running / Complete / Failed -
# because the scripts cannot report a percentage: Running means the local pipeline is running right
# now, Failed means the last run failed and says why, Complete carries how long ago it landed.
# Usable parts of the app are already visible: every screen reads its own file and renders empty
# when it is missing, and this list is what tells the user which ones are still coming.
BUILD_ARTIFACTS = [
    ('player', 'Player data', 'lastData.dec.json'),
    ('inventory', 'Inventory', 'owned.json'),
    ('prices', 'Market prices', 'prices.json'),
    ('lanes', 'Rank lanes', 'price_lanes.json'),
    ('collection', 'Collection', 'collection_log.json'),
    ('advisor', 'Trading advice', 'sell_advisor.json'),
    ('report', 'Sell report', 'report.json'),
    ('relics', 'Relic analysis', 'relic_ev.json'),
]


def build_payload():
    """GET /api/build -> the setup's real state. Read-only; it never starts a build."""
    now = time.time()
    running = bool(SYNC.get('running'))
    failed = SYNC.get('last_ok') is False
    rows = []
    for key, label, name in BUILD_ARTIFACTS:
        path = os.path.join(DATA, name)
        age = int(now - os.path.getmtime(path)) if os.path.exists(path) else None
        if age is not None:
            state, detail = 'complete', None
        elif running:
            state, detail = 'running', 'building now'
        elif failed:
            state, detail = 'failed', (SYNC.get('error') or 'the last run failed')[:120]
        else:
            state, detail = 'waiting', 'not built yet'
        rows.append({'key': key, 'label': label, 'file': name, 'state': state,
                     'age_s': age, 'detail': detail})
    done = sum(1 for r in rows if r['state'] == 'complete')
    return {'ok': True, 'rows': rows, 'complete': done, 'total': len(rows),
            'running': running, 'last_sync': SYNC.get('last_sync'), 'last_ok': SYNC.get('last_ok'),
            'error': SYNC.get('error'), 'seconds': sync_config_seconds()}


# ---------------------------------------------------------------- auto sync
# Jay (2026-09-27): "can we get an auto sync with settings ie 5m 10m 15m 30m 1hr".
# The cadence is the dashboard knob auto_refresh_seconds (0 = manual only, default 900). While the
# server runs, sync_tick() runs the LOCAL pipeline steps below on that cadence so the numbers the
# UI polls are actually refreshed, not just re-rendered. Prices (fetch_prices.py) stay out: it is
# a ~2 minute network job, not a 5-minute one - the Refresh button still runs the full pass.
SYNC_STEPS = [('refresh.py', []), ('invdiff.py', []), ('progress.py', ['--once'])]
SYNC = {'seconds': 0, 'last_sync': None, 'last_ok': None, 'last_ms': None,
        'next_at': None, 'for_secs': None, 'running': False, 'error': None}


def sync_config_seconds(default=900):
    """auto_refresh_seconds from data/config.json (read via scripts/config.py). Never raises."""
    try:
        if _dashcfg is None:
            return default
        v = _dashcfg.read().get('auto_refresh_seconds')
    except Exception:
        return default
    try:
        return max(0, min(3600, int(v)))
    except (TypeError, ValueError):
        return default


def sync_run(steps=None):
    """Run the local pipeline steps in order. -> (ok, ms, notes). One failure never stops the rest."""
    t0 = time.time()
    ok, notes = True, []
    for script, args in (SYNC_STEPS if steps is None else steps):
        try:
            r = subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', script)] + list(args),
                               capture_output=True, text=True, timeout=600, cwd=ROOT)
            if r.returncode != 0:
                ok = False
                notes.append('%s rc=%d' % (script, r.returncode))
        except Exception as e:
            ok = False
            notes.append('%s %s' % (script, str(e)[:80]))
    return ok, int((time.time() - t0) * 1000), notes


def sync_tick(now=None):
    """One decision, and one run when it is due. -> 'off' | 'waiting' | 'ran' | 'failed'."""
    now = time.time() if now is None else now
    secs = SYNC['seconds'] = sync_config_seconds()
    if not secs:
        SYNC['next_at'], SYNC['for_secs'] = None, None
        return 'off'
    if SYNC['next_at'] is None:
        SYNC['next_at'], SYNC['for_secs'] = now + secs, secs
        return 'waiting'
    if SYNC['for_secs'] != secs:
        # the knob moved: re-time from the last run instead of waiting out the old cadence, so
        # switching 1 hour -> 5 minutes takes effect now rather than in an hour
        base = SYNC['last_sync'] or now
        SYNC['next_at'], SYNC['for_secs'] = base + secs, secs
    if now < SYNC['next_at']:
        return 'waiting'
    SYNC['running'], SYNC['error'] = True, None
    try:
        ok, ms, notes = sync_run()
    except Exception as e:                                   # never kill the loop
        ok, ms, notes = False, 0, [str(e)[:120]]
    SYNC.update(last_sync=int(time.time()), last_ok=ok, last_ms=ms, running=False,
                error=('; '.join(notes) or None))
    SYNC['next_at'] = time.time() + secs
    print('auto sync: %s %dms%s' % ('ok' if ok else 'FAILED', ms,
                                    (' ' + '; '.join(notes)) if notes else ''), flush=True)
    sync_log_write()
    return 'ran' if ok else 'failed'


def sync_log_write(keep=50):
    """Append this run to data/sync_log.json (last `keep` rows). Never raises.

    The loop's own print has nowhere to land when the supervisor starts the server with
    pythonw, so the history lives next to the other data files instead.
    """
    try:
        path = os.path.join(DATA, 'sync_log.json')
        rows = jload(path) or []
        if not isinstance(rows, list):
            rows = []
        rows.append({'ts': SYNC['last_sync'], 'ok': SYNC['last_ok'], 'ms': SYNC['last_ms'],
                     'error': SYNC['error']})
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(rows[-keep:], f, indent=1)
        os.replace(tmp, path)
    except Exception:
        pass


# ------------------------------------------------------------------ trading session (the loop)
# docs/trading-session-workflow.md, stages 2-5. The state lives in data/trade_session.json and is
# owned by scripts/trade_session.py - these are thin adapters: read the payloads the app already
# produces, hand them in, save the result. No price, rank or buyer is recomputed here.
def _scripts_path():
    scripts = os.path.join(ROOT, 'scripts')
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return scripts


def _session():
    _scripts_path()
    import trade_session as ts
    return ts


def _session_inputs():
    """The recommendation payloads the session queue is built from (same files Home reads)."""
    return {'plan': jload(os.path.join(DATA, 'trader_plan.json')) or {},
            'advisor': jload(os.path.join(DATA, 'sell_advisor.json')) or {},
            'report': jload(os.path.join(DATA, 'report.json')) or {},
            'runqueue': jload(os.path.join(DATA, 'run_queue.json')) or {}}


def _session_plat_now():
    """The newest platinum reading: plat_history's last entry, or trader_limits, whichever is newer.

    Both come from the same game save; plat_history carries the timeline, trader_limits the live
    read. Reconciliation must compare against the same 'now' the contact snapshot was taken with,
    or a sale looks like it never arrived.
    """
    hist = jload(os.path.join(DATA, 'plat_history.json'))
    limits = jload(os.path.join(DATA, 'trader_limits.json')) or {}
    best, best_ts = None, -1
    if isinstance(hist, list) and hist and isinstance(hist[-1], dict):
        v = hist[-1].get('plat')
        if isinstance(v, (int, float)):
            best, best_ts = int(v), int(hist[-1].get('ts') or 0)
    v = limits.get('plat')
    if isinstance(v, (int, float)) and int(limits.get('ts') or 0) >= best_ts:
        best = int(v)
    return best


def _session_before(slug, rank=None, lane=None):
    """(sellable copies of that lane, platinum) right now - the 'before' side of reconciliation.

    Read from the same payloads the app renders: report.json for the stack, the newest platinum
    reading. Both may be None when the data is not there yet; None is stored as None and never
    guessed at later. `lane` identifies which lane of the item (a mod rank, a relic refinement):
    a slug alone cannot tell two lanes apart.
    """
    report = jload(os.path.join(DATA, 'report.json')) or {}
    ts = _session()
    inv, basis = ts.inv_of(report, slug, rank, lane=lane)
    return inv, _session_plat_now(), basis


def session_payload():
    """GET /api/session - the live session, its focus row, the pending trades and the summary."""
    ts = _session()
    limits = dict(jload(os.path.join(DATA, 'trader_limits.json')) or {})
    plat = _session_plat_now()
    if plat is not None:
        limits['plat'] = plat                   # the same 'now' the contact snapshots use
    return ts.payload(DATA, limits=limits, **_session_inputs())


def _kick_sync(reason='trade confirmed'):
    """Recompute the derived stores in the background after a confirmation (spec §5).

    Today's strip, the session history, the inventory diff and the ledger all read what the local
    pipeline writes, so one confirmation has to set that pipeline going - without making the user
    wait ~30s on the POST. It records into the same SYNC block the UI already polls, so the header's
    sync pill tells the truth while it runs.
    """
    def run():
        SYNC['running'] = True
        try:
            ok, ms, notes = sync_run()
            SYNC.update(last_sync=int(time.time()), last_ok=ok, last_ms=ms, error=('; '.join(notes) or None))
            sync_log_write()
            print('session %s: sync %s %dms' % (reason, 'ok' if ok else 'FAILED', ms), flush=True)
        except Exception as e:                               # never kill the caller
            SYNC.update(last_sync=int(time.time()), last_ok=False, error=str(e)[:200])
        finally:
            SYNC['running'] = False
    threading.Thread(target=run, daemon=True).start()


def session_post(action, body):
    """POST /api/session/<action> -> (code, body). start | focus | state | end."""
    ts = _session()
    limits = jload(os.path.join(DATA, 'trader_limits.json')) or {}
    if action == 'start':
        limit = body.get('limit')
        try:
            limit = max(1, min(40, int(limit))) if limit is not None else ts.QUEUE_LIMIT
        except (TypeError, ValueError):
            limit = ts.QUEUE_LIMIT
        out = ts.start_payload(DATA, limits=limits, limit=limit, **_session_inputs())
        return (200 if out.get('ok') else 409), out
    doc = ts.load(DATA)
    if action == 'reconcile':
        # Read-only: what the game save says now vs what each contact was sent at. Nothing is
        # written and no trade is inferred - the proposal is what the user confirms (§4).
        inv_now, inv_basis, cache, plat_now = {}, {}, {}, None
        for p in (doc.get('pending') or []):
            if p.get('state') not in (ts.CONTACTED, ts.POSSIBLE):
                continue
            key = ts.key_of(p)                    # (slug, lane): never a slug on its own
            if key not in cache:
                cache[key] = _session_before(p.get('slug'), p.get('rank'), ts.lane_of(p))
            inv, plat, basis = cache[key]
            if inv is not None:
                inv_now[key] = inv
            if basis:
                inv_basis[key] = basis
            if plat is not None:
                plat_now = plat
        out = ts.propose(doc.get('pending') or [], inv_now, plat_now, inv_basis=inv_basis)
        out['ok'] = True
        out['session_payload'] = session_payload()
        return 200, out
    if action == 'confirm':
        rec = body.get('trade') if isinstance(body.get('trade'), dict) else body
        out = ts.confirm_payload(DATA, rec)
        if out.get('ok') and out.get('created'):
            _kick_sync()                     # derived stores catch up in the background
            out['session_payload'] = session_payload()
        return (200 if out.get('ok') else 400), out
    if action == 'contact':
        slug = str(body.get('slug') or body.get('item') or '').strip().lower()
        if not slug:
            return 400, {'ok': False, 'error': 'slug required'}
        rank = body.get('rank')
        try:
            rank = int(rank) if rank not in (None, '') else None
        except (TypeError, ValueError):
            return 400, {'ok': False, 'error': 'rank must be a number'}
        lane = str(body.get('lane') or '').strip()
        if not lane and rank is not None:
            lane = 'rank %d' % rank
        inv, plat, basis = _session_before(slug, rank, lane)
        pend = ts.contact(doc, slug, rank=rank, qty=body.get('qty') or 1, price=body.get('price'),
                          buyer=body.get('user') or body.get('buyer'), inv_before=inv,
                          plat_before=plat, note=body.get('note') or '', inv_basis=basis, lane=lane)
        ts.save(DATA, doc)
        return 200, {'ok': True, 'pending': pend, 'session_payload': session_payload()}
    if action == 'focus':
        row = ts.focus(doc, index=body.get('index'), slug=body.get('slug'))
        if row is None:
            return 404, {'ok': False, 'error': 'the session has no queue to point at'}
        ts.save(DATA, doc)
        return 200, {'ok': True, 'focus': row, 'session_payload': session_payload()}
    if action == 'state':
        state = str(body.get('state') or '').upper()
        if state not in ts.STATES:
            return 400, {'ok': False, 'error': 'bad state', 'states': list(ts.STATES)}
        row = ts.set_state(doc, body.get('slug'), rank=body.get('rank'), state=state,
                           note=body.get('note') or '', lane=body.get('lane'))
        if row is None:
            return 404, {'ok': False, 'error': 'no such queue row'}
        ts.save(DATA, doc)
        return 200, {'ok': True, 'row': row, 'session_payload': session_payload()}
    if action == 'end':
        if ts.end(doc) is None:
            return 404, {'ok': False, 'error': 'no session is open'}
        ts.save(DATA, doc)
        return 200, {'ok': True, 'session_payload': session_payload()}
    return 404, {'ok': False, 'error': 'unknown session action'}


# ------------------------------------------------------------------ chat (home dock)
# Jay (2026-09-27): *"add a chat that snaps to the right of the home page. look into getting it so
# other people can chat with their profiles active."* The store is local and always works with no
# relay and no keys; when `chat_relay_url` is set the client also posts to that relay, which is what
# lets other people's dashboards share the room. The profile stamp comes from the local save -
# what is displayed is what gets sent, nothing invented.
CHAT_CAP = 300
CHAT_POST_GAP = 1.5
_chat_last = [0.0]


def chat_rows():
    rows = jload(os.path.join(DATA, 'chat.json')) or []
    return rows if isinstance(rows, list) else []


def chat_me():
    """Name + rank shown on your own messages (local save; '' when unknown)."""
    pl = jload(os.path.join(DATA, 'player.json')) or {}
    mr = jload(os.path.join(DATA, 'mastery.json')) or {}
    rank = None
    if isinstance(mr.get('mr'), dict):
        rank = mr['mr'].get('rank')
    elif isinstance(mr.get('mr'), int):
        rank = mr['mr']
    name = str(pl.get('alias') or '')
    if name.startswith('signin'):                      # the save reader's error text, never a name
        name = ''
    return {'name': name[:24], 'mr': rank if isinstance(rank, int) else None,
            'platform': str(pl.get('platform') or '')[:12]}


def chat_relay_url():
    try:
        return str((_dashcfg.read() if _dashcfg else {}).get('chat_relay_url') or '').strip()
    except Exception:
        return ''


def chat_payload():
    rows = chat_rows()
    return {'rows': rows[-120:], 'count': len(rows), 'cap': CHAT_CAP,
            'relay': chat_relay_url(), 'me': chat_me()}


def chat_post(who, text):
    """Append one message. -> (http_status, payload). Local store first, always."""
    text = ' '.join(str(text or '').split())
    if not text:
        return 400, {'ok': False, 'error': 'empty message'}
    now = time.time()
    if now - _chat_last[0] < CHAT_POST_GAP:
        return 429, {'ok': False, 'error': 'one message at a time'}
    _chat_last[0] = now
    stamp = {}
    if isinstance(who, dict):
        for k, cap in (('name', 24), ('platform', 12), ('clan', 24)):
            v = who.get(k)
            if v is not None and str(v).strip():
                stamp[k] = ' '.join(str(v).split())[:cap]
        mr = who.get('mr')
        if isinstance(mr, bool):
            mr = None
        if isinstance(mr, int) or (isinstance(mr, str) and mr.strip().isdigit()):
            stamp['mr'] = int(mr)
    rid = None
    if isinstance(who, dict):                          # the relay's own id, so a relayed message has
        rid = who.get('id')                            # one identity locally and in the room
    if isinstance(rid, int) and rid > 0:
        row = {'id': rid, 'ts': int(now), 'who': stamp, 'text': text[:500]}
    else:
        row = {'id': int(now * 1000), 'ts': int(now), 'who': stamp, 'text': text[:500]}
    rows = chat_rows() + [row]
    try:
        tmp = os.path.join(DATA, 'chat.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(rows[-CHAT_CAP:], f, indent=1, ensure_ascii=False)
        os.replace(tmp, os.path.join(DATA, 'chat.json'))
    except Exception as e:                             # never 500 the UI over a log write
        return 500, {'ok': False, 'error': 'store: ' + str(e)[:60]}
    return 200, {'ok': True, 'row': row, 'count': min(len(rows), CHAT_CAP)}


def sync_payload():
    """GET /api/sync - the loop's own state (the UI reads this, it never guesses)."""
    s = SYNC
    next_in = None
    if s['seconds'] and s['next_at']:
        next_in = max(0, int(round(s['next_at'] - time.time())))
    return {'enabled': bool(s['seconds']), 'seconds': int(s['seconds'] or 0),
            'last_sync': s['last_sync'], 'last_ok': s['last_ok'], 'last_ms': s['last_ms'],
            'next_in': next_in, 'running': bool(s['running']), 'error': s['error'],
            'steps': [name for name, _ in SYNC_STEPS]}


def autosync_loop():
    """Daemon body: tick, then sleep a slice short enough to notice a cadence change."""
    slice_s = float(os.environ.get('WFM_SYNC_SLICE') or 5)
    while True:
        try:
            sync_tick()
        except Exception as e:
            SYNC['error'] = str(e)[:120]
        time.sleep(max(0.2, min(slice_s, max(1.0, (SYNC['seconds'] or 60) / 4.0))))


# ================================================================ build planner (Phase 2)
# The Phase 1 engine under builds/ owns every Warframe number; these endpoints only join the
# ingested database to it and trim the payloads to what the planner UI draws. The database is
# loaded once per process (WFM_BUILD_DB overrides the repo default) and the mod library is
# cached per (kind, content hash).
_PLANNER = {}

PLANNER_KIND_LABELS = {'warframe': 'Warframe', 'primary': 'Primary', 'secondary': 'Secondary',
                       'melee': 'Melee', 'sentinel': 'Sentinel',
                       'sentinel_weapon': 'Sentinel Weapon'}
PLANNER_MOD_LINES = 3            # effect lines the library row carries (the rest live in detail)
PLANNER_SUPPORT_ITEMS = 4        # refusal texts the library row carries, per class


def _builds():
    """The Phase 1 engine modules, imported once (None when the package is missing)."""
    if 'mod' not in _PLANNER:
        try:
            if ROOT not in sys.path:
                sys.path.insert(0, ROOT)
            from builds import api as b_api
            from builds import capacity as b_capacity
            from builds import data as b_data
            from builds import effects as b_effects
            from builds import schema as b_schema
            from builds import unsupported as b_unsupported
            _PLANNER['mod'] = {'api': b_api, 'capacity': b_capacity, 'data': b_data,
                               'effects': b_effects, 'schema': b_schema,
                               'unsupported': b_unsupported}
        except Exception as e:            # engine missing: the rest of the app still works
            _PLANNER['mod'] = None
            _PLANNER['import_error'] = str(e)[:200]
    return _PLANNER['mod']


def _planner_db():
    """(db, error) - the build database, or the one message that fixes it."""
    mods = _builds()
    if not mods:
        return None, ('the build engine is not importable (%s)'
                      % _PLANNER.get('import_error') or 'builds/ missing')
    path = os.environ.get('WFM_BUILD_DB') or None
    if _PLANNER.get('db') is not None and _PLANNER.get('db_path') == path:
        return _PLANNER['db'], None
    try:
        db = mods['data'].load(path=path, allow_missing=True) if path else \
            mods['data'].load(allow_missing=True)
    except Exception as e:
        return None, 'the build database could not be read: %s' % str(e)[:200]
    if not db:
        return None, 'no build database - run: python builds/ingest.py'
    _PLANNER['db'], _PLANNER['db_path'] = db, path
    _PLANNER.pop('library', None)
    return db, None


def planner_meta():
    """What the planner needs before its first frame: kinds, slot layouts, database identity."""
    db, err = _planner_db()
    if err:
        return {'ok': False, 'error': err}
    mods = _builds()
    info = mods['data'].summary(db)
    kinds = []
    for kind in mods['schema'].EQUIP_KINDS:
        count = info['equipment_by_kind'].get(kind) or 0
        if not count:
            continue
        kinds.append({'kind': kind, 'label': PLANNER_KIND_LABELS.get(kind, kind.title()),
                      'count': count, 'slots': list(mods['schema'].EQUIP_SLOT_KINDS.get(kind, ())),
                      'normal_slots': mods['schema'].NORMAL_SLOTS,
                      'max_rank': (mods['schema'].MAX_RANK_FRAME
                                   if kind == mods['schema'].EQUIP_WARFRAME
                                   else mods['schema'].MAX_RANK_WEAPON)})
    return {'ok': True, 'schema_version': db.get('schema_version'),
            'content_hash': db.get('content_hash'),
            'generated': db.get('generated_iso'),
            'game_version': (db.get('game_data') or {}).get('source_version'),
            'engine': {'schema_version': db.get('schema_version'),
                       'content_hash': db.get('content_hash'),
                       'generated': db.get('generated_iso')},
            'categories': [k['kind'] for k in kinds],
            'kinds': kinds,
            'equipment_total': info.get('equipment'), 'mods_total': info.get('mods'),
            'unsupported': len(mods['unsupported'].list_all()),
            'storage_version': PLANNER_STORAGE_VERSION}


def _planner_equip_row(row):
    """One equipment row, trimmed to what a picker row and the planner's header need."""
    return {'id': row.get('id'), 'uniqueName': row.get('id'), 'name': row.get('name'),
            'slug': row.get('slug'),
            'kind': row.get('kind'), 'subtype': row.get('subtype'),
            'mastery_req': row.get('mastery_req'), 'max_rank': row.get('max_rank'),
            'variant': row.get('variant'), 'is_prime': row.get('is_prime'),
            'incarnon': row.get('incarnon'),
            'damage_total': row.get('damage_total'), 'crit_chance': row.get('crit_chance'),
            'crit_multiplier': row.get('crit_multiplier'),
            'status_chance': row.get('status_chance'), 'fire_rate': row.get('fire_rate'),
            'magazine': row.get('magazine'), 'reload': row.get('reload'),
            'stats': row.get('stats') or None}


def planner_equipment(query):
    """Search the ingested equipment rows: ?q=&kind=&limit= (name or slug, ranked)."""
    db, err = _planner_db()
    if err:
        return {'ok': False, 'error': err}
    mods = _builds()
    q = _qs(query, 'q').lower()
    kind = _qs(query, 'kind')
    try:
        limit = int(_qs(query, 'limit') or 80)
    except (TypeError, ValueError):
        limit = 80
    limit = max(1, min(200, limit))
    rows = []
    for row in mods['data'].index(db, 'equipment').values():
        if kind and row.get('kind') != kind:
            continue
        name = str(row.get('name') or '')
        if q and q not in name.lower() and q not in str(row.get('slug') or ''):
            continue
        rows.append(row)
    rows.sort(key=lambda r: _planner_equip_sort(r, q))
    return {'ok': True, 'total': len(rows),
            'rows': [_planner_equip_row(r) for r in rows[:limit]]}


def _planner_equip_sort(row, q):
    """Exact name, then prefix, then earliest hit; ties by name (variant rows sink)."""
    name = str(row.get('name') or '').lower()
    if not q:
        rank = 1
    elif name == q:
        rank = -2
    elif name.startswith(q):
        rank = -1
    else:
        rank = name.find(q)
    return (rank, row.get('variant') and 1 or 0, name)


def planner_equipment_detail(key):
    """One equipment row + the slot layout the planner draws, straight from the engine's schema."""
    db, err = _planner_db()
    if err:
        return {'ok': False, 'error': err}
    mods = _builds()
    row = mods['data'].find_equipment(db, key)
    if not row:
        return {'ok': False, 'error': "no equipment with id or slug '%s'" % key}
    layout = _planner_slot_layout(mods, row)
    return {'ok': True, 'equipment': row, 'slots': layout,
            # The DE export carries `polarities` for some items and not others (Braton Prime
            # ships none, Kuva Bramma ships one). When it is absent the grid opens vacant and
            # the UI says so rather than inventing the item's foundry polarities.
            'polarities_from_export': bool(row.get('polarities'))}


def _planner_slot_layout(mods, row):
    """The slots this item has, their default polarity, and what is locked.

    The order is the engine's (normal slots first, then aura / stance / exilus) and the
    polarity the item ships with comes from its own row, so the grid opens the way the item
    comes out of the foundry - not the way a build guide would polarize it.
    """
    schema = mods['schema']
    polarities = list(row.get('polarities') or [])
    layout = []
    for index in range(int(schema.NORMAL_SLOTS)):
        layout.append({'kind': schema.SLOT_NORMAL, 'index': index,
                       'polarity': polarities[index] if index < len(polarities) else None,
                       'unlocked': True, 'default_polarity': None})
    for kind in schema.EQUIP_SLOT_KINDS.get(row.get('kind'), ()):
        if kind == schema.SLOT_NORMAL:
            continue
        entry = {'kind': kind, 'index': None, 'unlocked': True, 'default_polarity': None,
                 'polarity': None}
        if kind == schema.SLOT_AURA:
            entry['polarity'] = row.get('aura_polarity')
        elif kind == schema.SLOT_STANCE:
            entry['polarity'] = row.get('stance_polarity')
        elif kind == schema.SLOT_EXILUS:
            entry['unlocked'] = False        # needs an Exilus Adapter before anything fits
            entry['polarity'] = row.get('exilus_polarity')
        layout.append(entry)
    for entry in layout:
        entry['default_polarity'] = entry['polarity']
    return layout


def _planner_mod_line(row):
    """One display line, trimmed to something a library row can hold."""
    text = ' '.join(str((row or {}).get('text') or '').split())
    return text if len(text) <= 120 else text[:117] + '\u2026'


def _planner_line_norm(text):
    """Whitespace- and case-insensitive form, for matching a card line against a refusal.

    The card text carries both real newlines and the export's literal '\\n' escape
    ('On Kill:\\n+2.7% ...'), and the engine's refusal list holds the cleaned form, so both
    spellings fold to a single space before the comparison.
    """
    text = str(text or '').replace('\\n', ' ')
    return ' '.join(text.split()).lower()


def _planner_mod_lines(mods, effects, max_rank):
    """The mod card's own lines at its max rank ('+165% Damage'), minus the refused riders.

    effects['per_rank'] is the engine's cleaned copy of the card text, so this is the line a
    player reads on the card - and a rider the engine refused stays out of it, appearing in
    support.conditional / support.unmodelled_examples instead.
    """
    per_rank = effects.get('per_rank') or []
    if max_rank is None or max_rank >= len(per_rank):
        rank_lines = per_rank[-1] if per_rank else []
    else:
        rank_lines = per_rank[max(0, max_rank)]
    refused = {_planner_line_norm(t) for t in (effects.get('conditional') or [])}
    lines = []
    for line in rank_lines:
        text = ' '.join(str(line or '').split())
        if not text or _planner_line_norm(text) in refused:
            continue
        lines.append(_planner_mod_line({'text': text}))
        if len(lines) >= PLANNER_MOD_LINES:
            break
    if not lines:                       # no card text: fall back to the numeric table
        for row in mods['effects'].effect_rows(effects, max_rank):
            if row.get('conditional'):
                continue
            value = row.get('value')
            unit = '%' if row.get('unit') == 'percent' else ''
            if value is None:
                continue
            lines.append('%+g%s %s' % (value, unit, row.get('stat')))
            if len(lines) >= PLANNER_MOD_LINES:
                break
    return lines


def _planner_mod_summary(mods, row):
    """The library-row payload for one mod: identity, the numbers a decision needs, support state."""
    effects = row.get('effects') or {}
    max_rank = row.get('max_rank')
    lines = _planner_mod_lines(mods, effects, max_rank)
    refusals, conditionals = [], []
    for stat, ranks in sorted((effects.get('unmodelled') or {}).items()):
        example = (effects.get('unmodelled_examples') or {}).get(stat, stat)
        if len(refusals) < PLANNER_SUPPORT_ITEMS:
            refusals.append(_planner_mod_line({'text': example}))
    for text in (effects.get('conditional') or [])[:PLANNER_SUPPORT_ITEMS]:
        conditionals.append(_planner_mod_line({'text': text}))
    drain_max = None
    if row.get('base_drain') is not None and max_rank is not None:
        drain_max = mods['capacity'].mod_drain(row['base_drain'], max_rank)
    flags = row.get('flags') or {}
    return {
        'id': row.get('id'), 'name': row.get('name'), 'slug': row.get('slug'),
        'base_name': row.get('base_name'),
        'shadowed': bool(row.get('shadowed')), 'shadowed_by': row.get('shadowed_by'),
        'polarity': row.get('polarity'), 'base_drain': row.get('base_drain'),
        'drain_max': drain_max, 'max_rank': max_rank, 'rarity': row.get('rarity'),
        'type': row.get('type'), 'compat': row.get('compat'), 'slot': row.get('slot'),
        'exilus_ok': row.get('exilus_ok'), 'variant': row.get('variant'),
        'class': row.get('class'), 'targets': row.get('targets') or [],
        'flags': [k for k in ('primed', 'umbral', 'galvanized', 'archon', 'amalgam',
                              'sacrificial', 'augment', 'stance', 'aura', 'set', 'exilus',
                              'flawed', 'riven') if flags.get(k)],
        'is_prime': bool(flags.get('prime')),
        'conclave': bool(row.get('conclave')),
        'lines': lines,
        'support': {'unmodelled': len(effects.get('unmodelled') or {}),
                    'conditional': len(effects.get('conditional') or []),
                    'unmodelled_examples': refusals, 'conditional_examples': conditionals},
    }


def planner_library(query):
    """Every mod installable on one item (the library list): ?equipment=<id|slug>."""
    db, err = _planner_db()
    if err:
        return {'ok': False, 'error': err}
    mods = _builds()
    key = _qs(query, 'equipment')
    row = mods['data'].find_equipment(db, key) if key else None
    if not row:
        return {'ok': False, 'error': "no equipment with id or slug '%s'" % key}
    cache = _PLANNER.setdefault('library', {})
    cache_key = (row.get('kind'), db.get('content_hash'))
    if cache_key not in cache:
        visible, shadowed = [], []
        for m in mods['data'].mods_for_kind(db, row.get('kind')):
            (shadowed if m.get('shadowed') else visible).append(_planner_mod_summary(mods, m))
        # The real card sorts first; a Flawed starter copy keeps its own name (the wiki's) and
        # sorts by it, so the library reads the way the game's mod station does.
        order = {'': 0, 'beginner': 1, 'intermediate': 2, 'expert': 3}
        visible.sort(key=lambda r: (str(r.get('name') or '').lower(),
                                    order.get(r.get('variant') or '', 4),
                                    -(r.get('max_rank') or 0)))
        shadowed.sort(key=lambda r: (str(r.get('name') or '').lower(), -(r.get('max_rank') or 0)))
        cache[cache_key] = {'rows': visible, 'shadowed': shadowed}
    packed = cache[cache_key]
    include_hidden = _qs(query, 'shadowed') == '1'
    rows = list(packed['rows']) + (list(packed['shadowed']) if include_hidden else [])
    return {'ok': True, 'total': len(rows),
            'equipment': {'id': row.get('id'), 'name': row.get('name'),
                          'kind': row.get('kind')},
            'hidden': {'shadowed': len(packed['shadowed']),
                       'reason': 'obsolete internal rows wearing a real mod\'s name'},
            'rows': rows}


def planner_unsupported():
    """The refusal registry (brief section 14: the UI shows what is not calculated)."""
    mods = _builds()
    if not mods:
        return {'ok': False, 'error': 'the build engine is not importable'}
    return {'ok': True, 'rows': mods['unsupported'].list_all(),
            'marker_keys': mods['unsupported'].MARKER_TO_KEY}


def planner_compute(build):
    """One build -> the engine's full answer (validation, capacity, stats, baseline, refusals)."""
    db, err = _planner_db()
    if err:
        return {'ok': False, 'error': err}
    if not isinstance(build, dict):
        return {'ok': False, 'error': 'build must be a JSON object'}
    mods = _builds()
    out = mods['api'].compute(build, db)
    out['engine'] = {'schema_version': db.get('schema_version'),
                     'content_hash': db.get('content_hash')}
    return out


def _planner_payload(raw):
    """The POST body as an object: anything else (a list, a string, null) is an empty one, so a
    caller's malformed body becomes a structured answer instead of a raised AttributeError."""
    return raw if isinstance(raw, dict) else {}


def planner_preview(payload):
    """A hypothetical edit: what changes (brief section 11), from two real engine runs.

    Both sides are complete builds: `build` is what the page holds, `next` is that build with
    the edit applied. The engine's compare does the arithmetic."""
    db, err = _planner_db()
    if err:
        return {'ok': False, 'error': err}
    mods = _builds()
    payload = _planner_payload(payload)
    a = payload.get('build') or {}
    b = payload.get('next') or {}
    if not isinstance(a, dict) or not isinstance(b, dict):
        return {'ok': False, 'error': 'build and next must be JSON objects'}
    out = mods['api'].compare(a, b, db)
    return out


def planner_explain(payload):
    """The rendered trace for one stat of a computed build (brief section 12)."""
    db, err = _planner_db()
    if err:
        return {'ok': False, 'error': err}
    mods = _builds()
    payload = _planner_payload(payload)
    build = payload.get('build') or {}
    stat = str(payload.get('stat') or '')
    if not isinstance(build, dict):
        return {'ok': False, 'error': 'build must be a JSON object', 'stat': stat,
                'text': None, 'available': [], 'result': {'stats': {}, 'damage': {}}}
    computed = mods['api'].compute(build, db)
    text = mods['api'].explain(computed, stat) if stat else None
    traces = ((computed or {}).get('result') or {}).get('traces') or {}
    return {'ok': text is not None, 'stat': stat, 'text': text,
            'available': sorted(traces),
            'result': {'stats': ((computed or {}).get('result') or {}).get('stats') or {},
                       'damage': ((computed or {}).get('result') or {}).get('damage') or {}}}


PLANNER_STORAGE_VERSION = 1       # the localStorage schema the page writes (planner storage v1)


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
        if p == '/api/catalog': return self._send(200, catalog_payload())
        if p == '/api/plat_history': return self._send(200, plat_history_payload())
        if p == '/api/trades': return self._send(200, trades_payload())
        if p == '/api/trader': return self._send(200, trader_payload())
        if p == '/api/session': return self._send(200, session_payload())
        if p == '/api/build': return self._send(200, build_payload())
        if p == '/api/gamenews': return self._send(200, gamenews_payload())
        if p == '/api/config': return self._send(200, dashcfg_payload())
        if p == '/api/sync': return self._send(200, sync_payload())
        if p == '/api/chat': return self._send(200, chat_payload())
        if p == '/api/trader/cfg': return self._send(200, cfg_payload())
        if p == '/api/profiles': return self._send(200, profiles_payload())
        if p == '/api/orders': return self._send(200, orders_payload(parse_qs(urlparse(self.path).query)))
        if p == '/api/rank_values': return self._send(200, rank_values_payload(parse_qs(urlparse(self.path).query)))
        if p.startswith('/api/feature/'):
            name = p.rsplit('/', 1)[-1]
            if name in FEATURES:
                try:
                    return self._send(200, feature_payload(name, parse_qs(urlparse(self.path).query)))
                except Exception as e:
                    return self._send(500, {'error': str(e)[:200]})
            return self._send(404, {'error': 'unknown feature'})
        if p == '/api/report': return self._send(200, jload(os.path.join(DATA, 'report.json')) or {})
        if p == '/api/planner/meta': return self._send(200, planner_meta())
        if p == '/api/planner/equipment':
            return self._send(200, planner_equipment(parse_qs(urlparse(self.path).query)))
        if p.startswith('/api/planner/equipment/'):
            return self._send(200, planner_equipment_detail(
                unquote(p[len('/api/planner/equipment/'):])))
        if p == '/api/planner/mods':
            return self._send(200, planner_library(parse_qs(urlparse(self.path).query)))
        if p == '/api/planner/unsupported': return self._send(200, planner_unsupported())
        if p.startswith('/api/planner/'):
            return self._send(404, {'ok': False, 'error': 'unknown planner route'})
        return self._serve_file(p.lstrip('/'))

    def do_POST(self):
        p = urlparse(self.path).path
        if p == '/api/chat':
            ln = int(self.headers.get('Content-Length') or 0)
            b = json.loads(self.rfile.read(ln).decode('utf-8', 'replace') or '{}')
            code, out = chat_post(b.get('who'), b.get('text'))
            return self._send(code, out)
        if p == '/api/whisper':
            try:
                ln = int(self.headers.get('Content-Length') or 0)
                b = json.loads(self.rfile.read(ln).decode('utf-8', 'replace') or '{}')
            except Exception:
                return self._send(400, {'ok': False, 'error': 'bad json body'})
            try:
                code, out = whisper_post(b)
            except Exception as e:
                return self._send(500, {'ok': False, 'error': str(e)[:200]})
            return self._send(code, out)
        if p.startswith('/api/session/'):
            try:
                ln = int(self.headers.get('Content-Length') or 0)
                b = json.loads(self.rfile.read(ln).decode('utf-8', 'replace') or '{}')
            except Exception:
                b = {}
            if not isinstance(b, dict):
                b = {}
            try:
                code, out = session_post(p.rsplit('/', 1)[-1], b)
            except Exception as e:
                return self._send(500, {'ok': False, 'error': str(e)[:200]})
            return self._send(code, out)
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
                # one writer for trade_log (stage 5): atomic, and every new event carries an id so
                # a retry cannot double-log it. This route logs an event; a *completion* goes
                # through POST /api/session/confirm, which is the one path that moves the session.
                ts = _session()
                rec, created = ts.append_event(DATA, ev)
                hist = jload(os.path.join(DATA, 'trade_log.json')) or []
                return self._send(200, {'ok': True, 'n': len(hist), 'id': rec.get('id'),
                                        'created': created, 'totals': trades_payload()['totals']})
            except ValueError as e:
                # the record cannot be canonicalised (a sale with no price): the caller's mistake,
                # not a server fault, and nothing was written
                return self._send(400, {'ok': False, 'error': str(e)})
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
        if p == '/api/profiles':
            try:
                ln = int(self.headers.get('Content-Length') or 0)
                b = json.loads(self.rfile.read(ln).decode('utf-8', 'replace') or '{}')
                action = str(b.get('action') or '')
                name = str(b.get('name') or '').strip()
                if action not in ('create', 'switch') or len(name) > 40:
                    return self._send(400, {'ok': False, 'error': 'action must be create|switch (name max 40 chars)'})
                if action == 'switch' and not name:
                    return self._send(400, {'ok': False, 'error': 'switch needs a profile name'})
                cmd = [sys.executable, os.path.join(ROOT, 'scripts', 'profiles.py'),
                       '--create' if action == 'create' else '--switch']
                if name:
                    cmd.append(name)   # create without a name = auto-name from the AlecaFrame account
                if action == 'switch' and b.get('apply'):
                    cmd.append('--apply')
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=ROOT)
                return self._send(200, {'ok': r.returncode == 0, 'rc': r.returncode,
                                        'stdout': (r.stdout or '')[-4000:], 'stderr': (r.stderr or '')[-2000:],
                                        'profiles': profiles_payload()})
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
        if p.startswith('/api/planner/'):
            try:
                ln = int(self.headers.get('Content-Length') or 0)
                b = json.loads(self.rfile.read(ln).decode('utf-8', 'replace') or '{}')
            except Exception as e:
                return self._send(400, {'ok': False, 'error': 'bad JSON body: %s' % str(e)[:120]})
            try:
                if p == '/api/planner/compute':
                    return self._send(200, planner_compute(b))
                if p == '/api/planner/preview':
                    return self._send(200, planner_preview(b))
                if p == '/api/planner/explain':
                    return self._send(200, planner_explain(b))
            except Exception as e:                     # a bad body is an answer, never a 500
                return self._send(200, {'ok': False, 'error': 'the engine refused this body: %s'
                                        % str(e)[:160]})
            return self._send(404, {'ok': False, 'error': 'unknown planner route'})
        return self._send(404, {'error': 'not found'})

    def log_message(self, fmt, *args):
        pass

if __name__ == '__main__':
    srv = ThreadingHTTPServer((HOST, PORT), H)
    threading.Thread(target=autosync_loop, daemon=True).start()
    print(f'WFM Trader serving on http://{HOST}:{PORT}/ (ctrl-c to stop)', flush=True)
    srv.serve_forever()
