"""Baro Ki'Teer (Void Trader) planner -- what to buy on the current or next visit.

Baro's cycle is fixed: arrives Fri 13:00 UTC, leaves Sun 13:00 UTC, every 14 days.
This planner pulls the live worldstate, matches his inventory against what the
account already owns, and ranks the rest against the ducat/credit balance on hand.

Per inventory row:
    SKIP_OWNED -- already owned (owned count included in the row)
    BUY        -- not owned and affordable right now  -> wishlist_buys (ducats desc)
    SAVE_UP    -- not owned but the balance will not cover it yet

The worldstate response is cached raw to data/baro_worldstate.json (TTL 30 min).
If the network fails the cache is used and every surface is flagged stale=true.
While Baro is away the API publishes an EMPTY inventory (stock only exists during
the visit window) -- in that case the wishlist is empty and the reason is recorded
in notes[] instead of being invented.

Inputs:  worldstate API https://api.warframestat.us/pc -> data/baro_worldstate.json
         data/owned.json, data/wfm_items_v2.json, data/lastData.dec.json, data/ducats.json
Output:  data/baro.json
Run:     python scripts/baro.py [--offline] [--worldstate-file P] [--out P]
                               [--ttl 30] [--ducats N] [--credits N] [--plat N]
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
WS_URL = 'https://api.warframestat.us/pc'
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'
CACHE = os.path.join(DATA, 'baro_worldstate.json')
TTL_MIN = 30
DUCATS_FALLBACK = 6250          # no ducat balance in the save export; override with --ducats
CREDITS_FALLBACK = 3900000
PLAT_FALLBACK = 1247
WEEKDAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')


def load(name, default=None):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return default
    try:
        return json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return default


def now_utc():
    return datetime.now(timezone.utc)


def parse_iso(s):
    """ISO-8601 (API returns '...T13:00:00.000Z') -> aware UTC datetime, else None."""
    if not s or not isinstance(s, str):
        return None
    t = s.strip().replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    return '%s %04d-%02d-%02d %02d:%02d UTC' % (WEEKDAYS[dt.weekday()], dt.year, dt.month,
                                                dt.day, dt.hour, dt.minute)


def human_delta(seconds):
    sec = int(max(0, seconds))
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    return '%dd %dh %dm' % (d, h, r // 60)


def write_json_atomic(path, obj):
    d = os.path.dirname(path) or '.'
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.tmp-baro-', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(obj, f, indent=1)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_bytes_atomic(path, blob):
    d = os.path.dirname(path) or '.'
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.tmp-baro-', suffix='.json')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(blob)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------- worldstate

def get_worldstate(ttl_min, offline=False, source_file=None):
    """Return (raw_dict, info). Order: file override > fresh cache > network > stale cache."""
    if source_file:
        blob = open(source_file, 'rb').read()
        raw = json.loads(blob.decode('utf-8'))
        info = dict(source='file', stale=False, cache_file=source_file, offline=offline,
                    fetched_utc=fmt_dt(datetime.fromtimestamp(os.path.getmtime(source_file),
                                                              timezone.utc)),
                    cache_age_min=None, url=None)
        return raw, info

    have_cache = os.path.exists(CACHE)
    age_min = None
    if have_cache:
        age_min = (time.time() - os.path.getmtime(CACHE)) / 60.0
    fresh = have_cache and age_min is not None and age_min <= ttl_min

    if fresh and not offline:
        raw = json.load(open(CACHE, encoding='utf-8'))
        return raw, dict(source='cache', stale=False, cache_file=CACHE, url=WS_URL,
                         offline=offline, cache_age_min=round(age_min, 1),
                         fetched_utc=fmt_dt(datetime.fromtimestamp(os.path.getmtime(CACHE),
                                                                   timezone.utc)))

    err = None
    if not offline:
        try:
            req = urllib.request.Request(WS_URL, headers={'User-Agent': UA,
                                                          'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                blob = resp.read()
            raw = json.loads(blob.decode('utf-8'))          # validate before caching
            write_bytes_atomic(CACHE, blob)                  # cache raw bytes verbatim
            return raw, dict(source='live', stale=False, cache_file=CACHE, url=WS_URL,
                             offline=False, cache_age_min=0.0, fetched_utc=fmt_dt(now_utc()))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            err = '%s: %s' % (type(exc).__name__, exc)

    if have_cache:
        raw = json.load(open(CACHE, encoding='utf-8'))
        info = dict(source='stale-cache', stale=True, cache_file=CACHE, url=WS_URL,
                    offline=offline, cache_age_min=round(age_min, 1) if age_min is not None else None,
                    cached_fetch_error=err,
                    fetched_utc=fmt_dt(datetime.fromtimestamp(os.path.getmtime(CACHE),
                                                              timezone.utc)))
        return raw, info

    raise SystemExit('baro.py: no worldstate (network error: %s) and no cache at %s'
                     % (err or 'offline', CACHE))


def extract_trader(ws):
    """voidTrader object (fall back to voidTraders[0]); {} when the API omits it."""
    vt = ws.get('voidTrader')
    if not isinstance(vt, dict) or not vt:
        arr = ws.get('voidTraders')
        if isinstance(arr, list) and arr:
            vt = arr[0] if isinstance(arr[0], dict) else {}
        else:
            vt = {}
    return vt


def trader_state(vt, now):
    """active / activation / expiry / countdown text. Handles both API shapes:
    some builds send {:active, :startString}, this one only activation+expiry."""
    act, exp = parse_iso(vt.get('activation')), parse_iso(vt.get('expiry'))
    active = vt.get('active')
    if active is None:
        if act and exp:
            active = act <= now < exp
        elif act:
            active = now >= act
        elif exp:
            active = now < exp
        else:
            active = None
    active = bool(active) if active is not None else None

    loc = vt.get('location') or 'unknown relay'
    out = dict(id=vt.get('id'), character=vt.get('character') or "Baro Ki'Teer",
               location=loc, active=active,
               activation_iso=act.isoformat().replace('+00:00', 'Z') if act else None,
               expiry_iso=exp.isoformat().replace('+00:00', 'Z') if exp else None,
               start_string=vt.get('startString'), schedule=vt.get('schedule') or [],
               starts_in_days=None, starts_in_hours=None, starts_in=None,
               closes_in=None, activation_text=None, expiry_text=None)

    if act:
        out['activation_text'] = fmt_dt(act)
    if exp:
        out['expiry_text'] = fmt_dt(exp)

    if active:
        left = (exp - now).total_seconds() if exp else None
        out['closes_in'] = human_delta(left) if left is not None else None
        out['status_text'] = ("ACTIVE at %s -- closes %s%s"
                              % (loc, out['expiry_text'] or '?',
                                 ' (in %s)' % out['closes_in'] if out['closes_in'] else ''))
    elif act and act > now:
        secs = (act - now).total_seconds()
        out['starts_in_days'] = round(secs / 86400.0, 2)
        out['starts_in_hours'] = round(secs / 3600.0, 2)
        out['starts_in'] = human_delta(secs)
        out['status_text'] = ("NOT active -- next visit %s at %s (in %s)"
                              % (out['activation_text'], loc, out['starts_in']))
    else:
        out['status_text'] = ("NOT active -- API reports no upcoming activation%s"
                              % (' (last window ended %s)' % out['expiry_text']
                                 if exp and exp <= now else ''))
    return out


# ------------------------------------------------------------------- matching

def norm_key(name):
    """Canonical match key: case/punctuation-insensitive, 'Blueprint' dropped,
    primed->prime. 'Prisma Grakata Blueprint' == 'Prisma Grakata'; Ki'Teer == KiTeer."""
    s = (name or '').lower().replace('\u2019', "'").replace('\u2018', "'")
    s = s.replace("'", '')
    words = [w for w in re.sub(r'[^a-z0-9]+', ' ', s).split() if w != 'blueprint']
    words = ['prime' if w == 'primed' else w for w in words]
    return ' '.join(words)


def norm_path(p):
    return re.sub(r'[^a-z0-9]+', '', (p or '').lower())


def strip_bp_path(p):
    return p.replace('blueprint', '')


def slugify(name):
    return re.sub(r'[^a-z0-9]+', '_', norm_key(name)).strip('_') or 'unknown'


def rel_or_abs(p):
    try:
        return os.path.relpath(p, ROOT)
    except ValueError:              # different drive on Windows
        return p


def build_indexes(owned, catalog):
    o_key, o_path = {}, {}
    for o in owned or []:
        k, n = norm_key(o.get('name')), int(o.get('count') or 1)
        if k:
            o_key[k] = o_key.get(k, 0) + n
        p = norm_path(o.get('path'))
        if p:
            o_path[p] = o_path.get(p, 0) + n
    c_key, c_path = {}, {}
    for it in (catalog or {}).get('data') or []:
        name = ((it.get('i18n') or {}).get('en') or {}).get('name')
        if name and it.get('slug'):
            c_key.setdefault(norm_key(name), it['slug'])
        g = norm_path(it.get('gameRef'))
        if g and it.get('slug'):
            c_path.setdefault(g, it['slug'])
    return dict(owned_key=o_key, owned_path=o_path, cat_key=c_key, cat_path=c_path)


def match_item(it, idx):
    """(owned_count, matched_by, slug) for one Baro inventory entry."""
    name = it.get('item') or it.get('name') or ''
    uniq = it.get('uniqueName') or it.get('unique_name') or ''
    key = norm_key(name)
    pk = norm_path(uniq)
    pk_s = strip_bp_path(pk)

    count, how = 0, None
    for cand, label in ((pk, 'uniqueName'), (pk_s, 'uniqueName-noBluePrint'), (key, 'name')):
        if not cand:
            continue
        if label.startswith('name'):
            if key and key in idx['owned_key']:
                count, how = idx['owned_key'][key], label
                break
        elif cand in idx['owned_path']:
            count, how = idx['owned_path'][cand], label
            break

    slug = idx['cat_path'].get(pk) or idx['cat_path'].get(pk_s) or idx['cat_key'].get(key)
    slug_src = 'catalog' if slug else 'derived'
    if not slug:
        slug = slugify(name)
    return count, how, slug, slug_src


# --------------------------------------------------------------------- report

def build_rows(vt, idx, ducats, credits):
    rows = []
    for it in vt.get('inventory') or []:
        if not isinstance(it, dict):
            continue
        name = it.get('item') or it.get('name') or 'unknown'
        duc = int(it.get('ducats') or 0)
        cr = int(it.get('credits') or 0)
        count, how, slug, slug_src = match_item(it, idx)
        owned = count > 0
        have_d = ducats >= duc
        have_c = credits >= cr
        afford = have_d and have_c
        if owned:
            verdict = 'SKIP_OWNED'
            reason = 'already owned (x%d)' % count
        elif afford:
            verdict = 'BUY'
            reason = 'affordable: %d/%d ducats, %d/%d credits' % (ducats, duc, credits, cr)
        else:
            verdict = 'SAVE_UP'
            miss = []
            if not have_d:
                miss.append('%d ducats short' % (duc - ducats))
            if not have_c:
                miss.append('%d credits short' % (cr - credits))
            reason = 'not owned, ' + (' and '.join(miss) if miss else 'inventory cost missing')
        rows.append(dict(item=name, slug=slug, slug_source=slug_src, unique_name=it.get('uniqueName'),
                         ducats=duc, credits=cr, owned=owned, owned_count=count,
                         matched_by=how, have_ducats=have_d, have_credits=have_c,
                         affordable=afford, verdict=verdict, reason=reason))
    rows.sort(key=lambda r: (r['verdict'] != 'BUY', -r['ducats'], -r['credits'], r['item']))
    return rows


def build_wishlist(rows):
    buys = [r for r in rows if r['verdict'] == 'BUY']
    buys.sort(key=lambda r: (-r['ducats'], -r['credits'], r['item']))
    run_d = run_c = 0
    out = []
    for i, r in enumerate(buys, 1):
        run_d += r['ducats']
        run_c += r['credits']
        w = dict(r)
        w.update(rank=i, running_ducats=run_d, running_credits=run_c)
        out.append(w)
    return out


def main():
    ap = argparse.ArgumentParser(description="Baro Ki'Teer planner: what to buy this visit")
    ap.add_argument('--offline', action='store_true', help='never hit the network; use cache')
    ap.add_argument('--worldstate-file', help='read worldstate JSON from a file (testing)')
    ap.add_argument('--out', default=os.path.join(DATA, 'baro.json'), help='output JSON path')
    ap.add_argument('--ttl', type=int, default=TTL_MIN, help='cache TTL minutes (default 30)')
    ap.add_argument('--ducats', type=int, help='ducat balance override')
    ap.add_argument('--credits', type=int, help='credit balance override')
    ap.add_argument('--plat', type=int, help='platinum balance override')
    args = ap.parse_args()

    ws, winfo = get_worldstate(args.ttl, offline=args.offline,
                               source_file=args.worldstate_file)
    now = now_utc()
    vt = extract_trader(ws)
    trader = trader_state(vt, now)

    owned = load('owned.json', []) or []
    catalog = load('wfm_items_v2.json', {}) or {}
    dec = load('lastData.dec.json', {}) or {}
    duc = load('ducats.json', {}) or {}
    idx = build_indexes(owned, catalog)

    # balances: CLI > save export > default constant (labelled so it is never silent)
    src = {}
    if args.credits is not None:
        credits, src['credits'] = args.credits, 'cli'
    elif dec.get('RegularCredits'):
        credits, src['credits'] = int(dec['RegularCredits']), 'lastData.dec.json:RegularCredits'
    else:
        credits, src['credits'] = CREDITS_FALLBACK, 'assumed default'
    if args.plat is not None:
        plat, src['platinum'] = args.plat, 'cli'
    elif dec.get('PremiumCredits') is not None:
        plat, src['platinum'] = int(dec['PremiumCredits']), 'lastData.dec.json:PremiumCredits'
    else:
        plat, src['platinum'] = PLAT_FALLBACK, 'assumed default'
    bal = load('player_balance.json', {}) or {}
    if args.ducats is not None:
        ducats, src['ducats'] = args.ducats, 'cli'
    elif dec.get('Ducats') is not None:
        ducats, src['ducats'] = int(dec['Ducats']), 'lastData.dec.json:Ducats'
    elif bal.get('ducats') is not None:
        ducats, src['ducats'] = int(bal['ducats']), 'player_balance.json'
    else:
        ducats, src['ducats'] = DUCATS_FALLBACK, 'assumed default (no ducat balance in save export)'

    rows = build_rows(vt, idx, ducats, credits)
    wishlist = build_wishlist(rows)

    burn_rows = [r for r in (duc.get('rows') or []) if r.get('verdict') == 'BURN']
    burn_d = sum(int(r.get('ducats_total') or 0) for r in burn_rows)
    not_owned = [r for r in rows if not r['owned']]
    needed_d = sum(r['ducats'] for r in not_owned)
    needed_c = sum(r['credits'] for r in not_owned)
    buy = [r for r in rows if r['verdict'] == 'BUY']
    save = [r for r in rows if r['verdict'] == 'SAVE_UP']
    skip = [r for r in rows if r['verdict'] == 'SKIP_OWNED']

    summary = dict(
        inventory_items=len(rows),
        inventory_available=bool(rows),
        owned_count=len(skip), not_owned_count=len(not_owned),
        buy_count=len(buy), skip_owned_count=len(skip), save_up_count=len(save),
        needed_ducats=needed_d, needed_credits=needed_c,
        player_ducats=ducats, player_credits=credits, player_platinum=plat,
        affordable_now=len(buy),
        affordable_now_ducats=sum(r['ducats'] for r in buy),
        affordable_now_credits=sum(r['credits'] for r in buy),
        ducats_shortfall=max(0, needed_d - ducats),
        credits_shortfall=max(0, needed_c - credits),
        buy_everything_affordable=(None if not rows else not save),
        burnable_parts=len(burn_rows), ducats_from_burnable_parts=burn_d,
        ducats_if_burnable_burned=ducats + burn_d,
        can_afford_all_if_burned=(None if not rows else
                                  (needed_d <= ducats + burn_d and needed_c <= credits)),
    )

    notes = []
    if not trader['active'] and not rows:
        notes.append("voidTrader.active is false and the worldstate API returned an EMPTY "
                     "inventory -- stock is only published while Baro is present, so there is "
                     "no preview to score. Re-run during the visit window (%s -> %s)."
                     % (trader.get('activation_iso'), trader.get('expiry_iso')))
    elif not rows:
        notes.append('voidTrader is active but the API returned an empty inventory.')
    if trader['active'] is None:
        notes.append('API gave no active flag and no usable activation/expiry; state unknown.')
    if winfo.get('stale'):
        why = ('offline mode -- no fetch attempted' if winfo.get('offline')
               else 'network fetch failed: %s' % winfo.get('cached_fetch_error'))
        notes.append('worldstate cache is STALE (%s) -- figures may be out of date.' % why)
    if src.get('ducats') == 'assumed default (no ducat balance in save export)':
        notes.append('ducat balance is an ASSUMED default (%d) -- the save export carries no '
                     'ducat total; pass --ducats N to override.' % ducats)
    if summary['save_up_count']:
        notes.append('%d item(s) not owned but not affordable now; burning the %d BURN-earmarked '
                     'stacks in data/ducats.json yields %d ducats (balance would become %d).'
                     % (summary['save_up_count'], len(burn_rows), burn_d,
                        summary['ducats_if_burnable_burned']))

    out = dict(
        generated=time.strftime('%Y-%m-%d %H:%M'),
        generated_utc=fmt_dt(now),
        params=dict(ttl_min=args.ttl, offline=args.offline,
                    worldstate_file=args.worldstate_file, url=WS_URL),
        worldstate=winfo,
        trader=trader,
        player=dict(ducats=ducats, credits=credits, platinum=plat, sources=src),
        summary=summary,
        wishlist_buys=wishlist,
        rows=rows,
        notes=notes,
    )
    write_json_atomic(os.path.abspath(args.out), out)

    # ------------------------------------------------------------- stdout
    print("BARO KI'TEER PLANNER")
    print('  ' + trader['status_text'])
    print('  worldstate: %s%s  cache=%s  age=%s min'
          % (winfo.get('source'), ' (STALE)' if winfo.get('stale') else '',
             rel_or_abs(winfo.get('cache_file') or CACHE),
             winfo.get('cache_age_min')))
    print('  balance: %d ducats, %d credits, %d plat  (ducats source: %s)'
          % (ducats, credits, plat, src.get('ducats')))
    print('  inventory: %d items | owned %d | not owned %d | BUY %d | SKIP_OWNED %d | SAVE_UP %d'
          % (summary['inventory_items'], summary['owned_count'], summary['not_owned_count'],
             summary['buy_count'], summary['skip_owned_count'], summary['save_up_count']))
    print('  everything not owned costs %d ducats + %d credits | affordable now: %d (%d d + %d cr)'
          % (needed_d, needed_c, summary['affordable_now'], summary['affordable_now_ducats'],
             summary['affordable_now_credits']))
    if rows:
        print('  sample rows:')
        for r in rows[:5]:
            print('    %-34s %5dd %12dcr own=%-3d %-10s %s'
                  % (r['item'][:34], r['ducats'], r['credits'], r['owned_count'],
                     r['verdict'], r['reason']))
    else:
        print('  no inventory rows (see notes in baro.json)')
    for n in notes:
        print('  note: ' + n)
    print('  wrote %s' % os.path.abspath(args.out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
