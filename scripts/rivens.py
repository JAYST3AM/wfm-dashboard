#!/usr/bin/env python3
"""Veiled-riven price bands + owned-riven valuation (dashboard feature #16).

The market only quotes VEILED riven mods per weapon family (rifle / shotgun / pistol / melee /
zaw / kitgun / archgun / companion weapon), so that per-family band is the honest baseline for
an owned riven whose exact roll is unknown.  A revealed, well-rolled riven is worth far more
than its veiled band and is deliberately NOT modelled here.

Sources (live, unless a fresh cache already covers them)
  api.warframe.market/v2/items                    catalog -> veiled riven families
  api.warframe.market/v1/items/{slug}/statistics  closed 48h buckets -> median + volume
  api.warframe.market/v2/orders/item/{slug}/top   live visible orders -> sell floor / buy top

Band per family: floor = cheapest visible sell order (fallback: lowest 48h trade), median =
volume-weighted 48h median, vol48 = trades closed in the last 48h.  Only 'unrevealed' rows
count -- the same items also trade 'revealed' at wildly different prices, and mixing them
would invent a band nobody quotes.  An owned riven is valued floor..median (a fast sale
reaches the floor, a patient one the median), scaled by +RANK_UPLIFT per rank it is already
ranked to.  Riven entries whose weapon family cannot be derived from slug or name get
est_low/est_high = null and basis 'veiled_band_type_unknown' instead of a guessed number.

Caches (reruns reuse them; plain JSON, atomically replaced)
  data/riven_items_cache.json    catalog slice, ITEMS_TTL = 12h
  data/riven_prices_cache.json   per-slug quotes, MAX_AGE = 6h (--max-age H / --refresh)
Output
  data/rivens.json               {generated, veiled_bands[], owned_rivens[], summary}

CLI:  python scripts/rivens.py [--refresh | --max-age H] [--selftest] [--json]
      --selftest runs the band/valuation math on embedded fixtures, fully offline.
      --json prints data/rivens.json to stdout afterwards (handy for piping).
Env:  RIVENS_OUT_PATH / RIVEN_ITEMS_CACHE / RIVEN_PRICES_CACHE / RIVENS_OWNED_PATH override
      the four file paths (tests and throwaway runs).
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'

OUTP = os.environ.get('RIVENS_OUT_PATH') or os.path.join(DATA, 'rivens.json')
ITEMSC = os.environ.get('RIVEN_ITEMS_CACHE') or os.path.join(DATA, 'riven_items_cache.json')
PRICEC = os.environ.get('RIVEN_PRICES_CACHE') or os.path.join(DATA, 'riven_prices_cache.json')
OWNEDP = os.environ.get('RIVENS_OWNED_PATH') or os.path.join(DATA, 'owned.json')

ITEMS_URL = 'https://api.warframe.market/v2/items'
STATS_URL = 'https://api.warframe.market/v1/items/{}/statistics'
TOP_URL = 'https://api.warframe.market/v2/orders/item/{}/top'

SLEEP = 0.35           # api.warframe.market politeness between live calls
MAX_CALLS = 80         # live HTTP calls per run (8 families x 2 + catalog is ~17)
ITEMS_TTL = 12.0       # hours; the catalog barely moves, 12h is plenty
MAX_AGE = 6.0          # hours; quote cache TTL (--max-age H / --refresh overrides)
UNREVEALED = 'unrevealed'
UNKNOWN_BASIS = 'veiled_band_type_unknown'   # owned entry, family not derivable (contract string)
MISSING_BASIS = 'veiled_band_missing'        # family known, but no band was priced this run
TYPE_ORDER = ('rifle', 'shotgun', 'pistol', 'melee', 'zaw', 'kitgun', 'archgun', 'companion_weapon')
MAX_RIVEN_RANK = 8
RANK_UPLIFT = 0.05     # +5% of the band per rank already invested in the mod
RIVEN_TAGS = {'riven_mod', 'veiled_riven'}
TYPE_WORDS = (('companion_weapon', r'companion'), ('archgun', r'arch-?gun'), ('kitgun', r'kitgun'),
              ('zaw', r'zaw'), ('shotgun', r'shotgun'), ('rifle', r'rifle'), ('pistol', r'pistol'),
              ('melee', r'melee'))

_live = {'calls': 0}


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- io helpers
def http_json(url, tries=4):
    """GET json with the shared UA + backoff on throttling. Never raises: errors are dicts."""
    last = None
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            last = f'http {e.code}'
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(3 + 3 * a)
                continue
            return {'__error': last}
        except Exception as e:  # timeouts, dns, truncated body
            last = str(e)
            time.sleep(2 + 2 * a)
    return {'__error': last}


def live_json(url):
    """http_json under the per-run call budget (MAX_CALLS). Over budget -> no request at all."""
    if _live['calls'] >= MAX_CALLS:
        return {'__error': 'call cap reached (%d)' % MAX_CALLS}
    time.sleep(SLEEP)
    _live['calls'] += 1
    return http_json(url)


def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            log(f'warn: {os.path.basename(path)} unreadable ({e}); ignoring it')
    return default


def save_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def now_iso():
    return datetime.datetime.now().isoformat(timespec='seconds')


def age_hours(ts):
    """Hours since an ISO stamp; None when the stamp is missing or unparseable."""
    if not ts:
        return None
    try:
        return (datetime.datetime.now() - datetime.datetime.fromisoformat(str(ts))).total_seconds() / 3600.0
    except (ValueError, TypeError):
        return None


def fresh(ts, max_age):
    """True when a cached quote is younger than max_age hours."""
    age = age_hours(ts)
    return age is not None and age <= max_age


def quote_slug(slug):
    """URL-quote a slug; veiled riven slugs carry parentheses ('rifle_riven_mod_(veiled)')."""
    return urllib.parse.quote(slug or '', safe='')


# ---------------------------------------------------------------- parsing helpers
def riven_type_from_slug(slug):
    """'melee_riven_mod_(veiled)' -> 'melee'; weapon-specific slugs ('braton_riven_mod') -> None."""
    m = re.match(r'^([a-z0-9_]+?)_riven_mod(?:_\(veiled\))?$', (slug or '').strip().lower())
    if not m:
        return None
    t = m.group(1)
    return t if t in TYPE_ORDER else None


def riven_type_from_name(name):
    """Family keyword in a display name; 'Braton Riven Mod' (a specific weapon) -> None."""
    n = (name or '').lower()
    for t, pat in TYPE_WORDS:
        if re.search(r'\b' + pat + r'\b', n):
            return t
    return None


def veiled_from_catalog(payload):
    """Filter a /v2/items payload (or a cached item list) down to the veiled riven families."""
    data = payload.get('data') if isinstance(payload, dict) else payload
    out, seen = [], set()
    for it in data or []:
        if not isinstance(it, dict):
            continue
        slug = it.get('slug') or ''
        name = it.get('name') or (((it.get('i18n') or {}).get('en') or {}).get('name')) or ''
        if not slug or slug in seen:
            continue
        if not (slug.endswith('_riven_mod_(veiled)') or '(veiled)' in name.lower()):
            continue          # riven-adjacent catalog rows (revealed mods, slivers) are not bands
        fam = riven_type_from_slug(slug) or riven_type_from_name(name)
        seen.add(slug)
        out.append({'slug': slug, 'name': name or slug, 'type': fam})
    out.sort(key=lambda r: (TYPE_ORDER.index(r['type']) if r['type'] in TYPE_ORDER else len(TYPE_ORDER),
                            r['slug']))
    return out


def stats_48h(payload):
    """(median, vol48, min48, max48, buckets) from a v1 statistics payload, unrevealed rows only.

    median is volume-weighted over the per-bucket medians (same recipe as data/stats.json);
    a plain middle-value is used only when no bucket carries volume.
    """
    rows = (((payload.get('payload') or {}).get('statistics_closed') or {}).get('48hours')) or []
    tagged = [b for b in rows if (b.get('subtype') or '')]
    if tagged:                                   # items that never carry a subtype keep every bucket
        rows = [b for b in tagged if (b.get('subtype') or '').lower() == UNREVEALED]
    meds = [(float(b['median']), int(b.get('volume') or 0)) for b in rows if b.get('median') is not None]
    wsum = sum(w for _, w in meds)
    if meds and wsum:
        median = sum(m * w for m, w in meds) / wsum
    elif meds:
        vals = sorted(m for m, _ in meds)
        median = vals[len(vals) // 2]
    else:
        median = None
    mins = [float(b['min_price']) for b in rows if b.get('min_price') is not None]
    maxs = [float(b['max_price']) for b in rows if b.get('max_price') is not None]
    return (round(median, 2) if median is not None else None,
            sum(int(b.get('volume') or 0) for b in rows) if rows else None,
            min(mins) if mins else None, max(maxs) if maxs else None, len(rows))


def top_orders(payload):
    """(cheapest visible sell, highest visible buy, visible sell orders) from a /top payload.

    Riven orders carry subtype 'unrevealed'; when any visible order is tagged, only the
    unrevealed ones count so revealed-mod listings cannot fake a floor.
    """
    data = payload.get('data') if isinstance(payload, dict) else None
    data = data if isinstance(data, dict) else {}

    def side(kind):
        rows = [o for o in (data.get(kind) or []) if o.get('visible')]
        tagged = [o for o in rows if (o.get('subtype') or '')]
        if tagged:
            rows = [o for o in tagged if (o.get('subtype') or '').lower() == UNREVEALED]
        return rows

    sells, buys = side('sell'), side('buy')
    return (min((o.get('platinum') for o in sells if o.get('platinum') is not None), default=None),
            max((o.get('platinum') for o in buys if o.get('platinum') is not None), default=None),
            len(sells))


def band_for(item, q):
    """One veiled band row, or None when this family has no quote at all."""
    if not q:
        return None
    floor, median = q.get('sell_floor'), q.get('median')
    if floor is None:
        floor = q.get('min48')                   # /top failed: the 48h trade low is the floor
    if floor is None and median is None:
        return None                              # nothing priced: no invented band
    if floor is None:
        floor = median
    if median is None:
        median = floor
    return {'slug': item['slug'], 'name': item['name'], 'type': item['type'],
            'floor': round(float(floor), 2), 'median': round(float(median), 2),
            'vol48': q.get('vol48')}


def is_riven_entry(entry):
    """Owned riven MOD (tags riven_mod/veiled_riven, or a '... Riven Mod' name).

    Matched on 'riven mod' rather than 'riven' so a Riven Sliver resource is not valued.
    """
    if not isinstance(entry, dict):
        return False
    tags = {str(t).lower() for t in (entry.get('tags') or [])}
    if tags & RIVEN_TAGS:
        return True
    return bool(re.search(r'riven\s+mod\b', entry.get('name') or '', re.I))


def owned_rows(owned, bands_by_type):
    """Owned riven stacks summed per (name, family, rank), each valued from its family band."""
    groups = {}
    for e in owned or []:
        if not is_riven_entry(e):
            continue
        name = e.get('name') or e.get('slug') or 'Riven Mod'
        fam = riven_type_from_slug(e.get('slug')) or riven_type_from_name(name)
        try:
            rank = max(0, min(int(e.get('rank') or 0), MAX_RIVEN_RANK))
        except (TypeError, ValueError):
            rank = 0
        try:
            qty = max(1, int(e.get('count') or 1))
        except (TypeError, ValueError):
            qty = 1
        g = groups.setdefault((name, fam, rank), {'name': name, 'qty': 0})
        g['qty'] += qty

    rows = []
    for (name, fam, rank), g in groups.items():
        band = bands_by_type.get(fam) if fam else None
        up = 1.0 + RANK_UPLIFT * rank
        low = high = None
        basis = UNKNOWN_BASIS if fam is None else MISSING_BASIS
        if band and (band['floor'] is not None or band['median'] is not None):
            a, b = sorted((band['floor'] if band['floor'] is not None else band['median'],
                           band['median'] if band['median'] is not None else band['floor']))
            low, high = round(a * up, 2), round(b * up, 2)
            basis = 'veiled_band:%s%s' % (fam, ';rank:%d' % rank if rank else '')
        rows.append({'name': g['name'], 'qty': g['qty'], 'est_low': low, 'est_high': high,
                     'basis': basis})
    rows.sort(key=lambda r: (-(r['est_high'] or 0), r['name']))
    return rows


def build_doc(bands, rows, generated):
    """data/rivens.json contract: generated + bands + valued rivens + a human summary."""
    unknown = sum(1 for r in rows if r['basis'] == UNKNOWN_BASIS)
    missing = sum(1 for r in rows if r['basis'] == MISSING_BASIS)
    copies = sum(r['qty'] for r in rows)
    note = ('%d owned riven stack(s) / %d cop(ies); %d without a determinable weapon family '
            '(basis=%s)%s. Bands cover veiled (unrevealed) trades only: est range spans the live '
            'sell floor to the 48h volume-weighted median, +%d%%/rank for already-ranked mods. '
            'A revealed, well-rolled riven is worth more than its veiled band.'
            % (len(rows), copies, unknown, UNKNOWN_BASIS,
               '; %d family/families without a price band' % missing if missing else '',
               int(RANK_UPLIFT * 100)))
    return {'generated': generated, 'veiled_bands': bands, 'owned_rivens': rows,
            'summary': {'band_count': len(bands), 'owned_count': len(rows), 'note': note}}


# ---------------------------------------------------------------- fetch + cache
def load_catalog(force=False):
    """([{slug,name,type}], source) for the veiled riven families.

    Cache is good for ITEMS_TTL hours; --refresh forces the API pass.  An empty catalog with no
    fallback cache is fatal upstream, so a failed fetch prefers the stale cache over nothing.
    """
    cache = load_json(ITEMSC, {}) or {}
    cached = cache.get('items') or []
    age = age_hours(cache.get('fetched'))
    if cached and not force and age is not None and age <= ITEMS_TTL:
        log('item catalog: cache hit (%d veiled families, %.1fh old)' % (len(cached), age))
        return cached, 'cache'
    payload = live_json(ITEMS_URL)
    items = veiled_from_catalog(payload) if '__error' not in payload else []
    if items:
        save_json(ITEMSC, {'schema': 1, 'fetched': now_iso(), 'source': ITEMS_URL,
                           'count': len(items), 'items': items})
        log('item catalog: live (%d veiled families)' % len(items))
        return items, 'live'
    if cached:
        log('item catalog: API unavailable (%s) - falling back to the %.1fh-old cache'
            % (payload.get('__error'), age if age is not None else -1))
        return cached, 'stale-cache'
    return [], 'none'


def quote_for(slug, max_age, cache):
    """Band inputs for one slug: fresh cache entry, else a live statistics + /top pass.

    A transient failure keeps whatever the previous entry had (flagged 'partial'/'unavailable')
    instead of blanking the band; a brand-new slug with nothing to show returns None so the
    next run retries it.
    """
    store = cache.setdefault('items', {})
    hit = store.get(slug) or {}
    if hit and fresh(hit.get('ts'), max_age):
        return dict(hit, source='cache')
    stats = live_json(STATS_URL.format(quote_slug(slug)))
    top = live_json(TOP_URL.format(quote_slug(slug)))
    errs = [n for n, p in (('statistics', stats), ('top', top)) if '__error' in p]
    if len(errs) == 2:
        if not hit:
            return None                          # nothing live and nothing cached: skip this family
        return dict(hit, source='unavailable', failed=errs)
    ent = dict(hit)
    if '__error' not in stats:
        med, vol, low, high, buckets = stats_48h(stats)
        ent.update(median=med, vol48=vol, min48=low, max48=high, buckets=buckets)
    if '__error' not in top:
        sell, buy, vis = top_orders(top)
        ent.update(sell_floor=sell, buy_top=buy, sells=vis)
    ent.update(ts=now_iso(), src='live' if not errs else 'partial', failed=errs or None)
    store[slug] = dict(ent)
    return dict(ent, source='live' if not errs else 'partial')


def run(max_age=None, print_json=False):
    t0 = time.time()
    max_age = MAX_AGE if max_age is None else max_age
    refresh = max_age <= 0
    _live['calls'] = 0

    items, isrc = load_catalog(force=refresh)
    if not items:
        log('ERROR: no veiled riven items available (catalog fetch failed and no cache) - '
            'nothing to band')
        return 1

    owned = load_json(OWNEDP, []) or []
    pcache = load_json(PRICEC, {}) or {}
    pcache.setdefault('items', {})
    if refresh:                                  # drop live quotes so every family is re-priced
        pcache['items'] = {k: v for k, v in pcache['items'].items() if not v.get('ts')}

    bands, quotes, unavailable = [], [], []
    for it in items:
        q = quote_for(it['slug'], max_age, pcache)
        b = band_for(it, q)
        if b:
            bands.append(b)
            quotes.append((it, q))
        else:
            unavailable.append(it['slug'])
    pcache['schema'] = 1
    pcache['updated'] = now_iso()
    save_json(PRICEC, pcache)

    doc = build_doc(bands, owned_rows(owned, {b['type']: b for b in bands}), now_iso())
    save_json(OUTP, doc)
    rows = doc['owned_rivens']

    # ---------------------------------------------------------------- report
    cached = sum(1 for _, q in quotes if (q or {}).get('source') == 'cache')
    log('')
    log('RIVEN BANDS  %s' % doc['generated'])
    log('  veiled families : %d/%d priced (%d cached, %d live; catalog: %s; %d live call(s), cap %d)'
        % (len(bands), len(items), cached, len(quotes) - cached, isrc, _live['calls'], MAX_CALLS))
    log('  owned rivens    : %d stack(s), %d cop(ies); %d without a family, %d without a band'
        % (len(rows), sum(r['qty'] for r in rows),
           sum(1 for r in rows if r['basis'] == UNKNOWN_BASIS),
           sum(1 for r in rows if r['basis'] == MISSING_BASIS)))
    if unavailable:
        log('  no band for     : %s' % ', '.join(unavailable))
    log('')
    hdr = '%-34s %-17s %7s %8s %7s' % ('veiled family', 'type', 'floor', 'median', 'vol48')
    log(hdr)
    log('-' * len(hdr))
    for b in bands:
        log('%-34s %-17s %7s %8s %7s'
            % (b['name'][:34], b['type'] or '?', fmt(b['floor']), fmt(b['median']), fmt(b['vol48'])))
    if rows:
        log('')
        hdr = '%-34s %5s %8s %9s  %s' % ('owned riven', 'qty', 'est_low', 'est_high', 'basis')
        log(hdr)
        log('-' * len(hdr))
        for r in rows:
            log('%-34s %5d %8s %9s  %s'
                % (r['name'][:34], r['qty'], fmt(r['est_low']), fmt(r['est_high']), r['basis']))
    log('')
    log('wrote %s + %s + %s  (%.1fs)'
        % (rel(OUTP), rel(ITEMSC), rel(PRICEC), time.time() - t0))
    if print_json:
        log(json.dumps(doc, indent=1))
    return 0


def fmt(v):
    return '-' if v is None else ('%g' % v)


def rel(p):
    """Repo-relative display path; absolute when a path env override lives outside the repo."""
    try:
        return os.path.relpath(p, ROOT).replace('\\', '/')
    except ValueError:
        return p.replace('\\', '/')


# ---------------------------------------------------------------- selftest (offline)
def selftest():
    """Band + valuation math on embedded fixtures. No network, no files touched."""
    checks, fails = [], []

    def chk(name, got, want):
        checks.append(name)
        if got != want:
            fails.append('%s: got %r, want %r' % (name, got, want))

    # 1. weapon family from slug / name
    chk('slug->rifle', riven_type_from_slug('rifle_riven_mod_(veiled)'), 'rifle')
    chk('slug->companion', riven_type_from_slug('companion_weapon_riven_mod_(veiled)'),
        'companion_weapon')
    chk('weapon slug has no family', riven_type_from_slug('braton_riven_mod'), None)
    chk('name->melee', riven_type_from_name('Melee Riven Mod (Veiled)'), 'melee')
    chk('name->archgun', riven_type_from_name('Archgun Riven Mod (Veiled)'), 'archgun')
    chk('weapon name has no family', riven_type_from_name('Braton Riven Mod'), None)

    # 2. 48h statistics: revealed rows dropped, median weighted by volume
    stats = {'payload': {'statistics_closed': {'48hours': [
        {'volume': 10, 'median': 10.0, 'min_price': 8.0, 'max_price': 12.0, 'subtype': UNREVEALED},
        {'volume': 30, 'median': 20.0, 'min_price': 15.0, 'max_price': 25.0, 'subtype': UNREVEALED},
        {'volume': 99, 'median': 500.0, 'min_price': 400.0, 'max_price': 600.0, 'subtype': 'revealed'},
    ]}}}
    med, vol, low, high, buckets = stats_48h(stats)
    chk('revealed buckets excluded', (med, vol, buckets), (17.5, 40, 2))
    chk('48h trade low/high', (low, high), (8.0, 25.0))
    chk('no buckets -> no median', stats_48h({'payload': {}}), (None, None, None, None, 0))
    plain = {'payload': {'statistics_closed': {'48hours': [
        {'volume': 0, 'median': 4.0}, {'volume': 0, 'median': 6.0}]}}}
    chk('volume-less buckets use the middle value', stats_48h(plain)[0], 6.0)

    # 3. /top: hidden + revealed orders cannot set the floor
    top = {'data': {'sell': [{'platinum': 9, 'visible': True, 'subtype': UNREVEALED},
                             {'platinum': 5, 'visible': False, 'subtype': UNREVEALED},
                             {'platinum': 300, 'visible': True, 'subtype': 'revealed'}],
                    'buy': [{'platinum': 6, 'visible': True, 'subtype': UNREVEALED},
                            {'platinum': 400, 'visible': True, 'subtype': 'revealed'}]}}
    chk('sell floor skips hidden + revealed', top_orders(top), (9, 6, 1))
    chk('empty top payload', top_orders({}), (None, None, 0))

    # 4. band row + catalog filter
    item = {'slug': 'melee_riven_mod_(veiled)', 'name': 'Melee Riven Mod (Veiled)', 'type': 'melee'}
    band = band_for(item, {'sell_floor': 9, 'median': 17.5, 'vol48': 40, 'min48': 8.0})
    chk('band row shape', band, {'slug': 'melee_riven_mod_(veiled)', 'name': 'Melee Riven Mod (Veiled)',
                                 'type': 'melee', 'floor': 9.0, 'median': 17.5, 'vol48': 40})
    chk('floor falls back to the 48h low', band_for(item, {'median': 12, 'min48': 7, 'vol48': 2})['floor'],
        7.0)
    chk('no quote -> no band', band_for(item, None), None)
    cat = veiled_from_catalog({'data': [
        {'slug': 'rifle_riven_mod_(veiled)', 'tags': ['mod', 'riven_mod'],
         'i18n': {'en': {'name': 'Rifle Riven Mod (Veiled)'}}},
        {'slug': 'companion_weapon_riven_mod_(veiled)', 'tags': ['mod', 'riven'],
         'i18n': {'en': {'name': 'Companion Weapon Riven Mod (Veiled)'}}},
        {'slug': 'braton_riven_mod', 'tags': ['mod', 'riven'],
         'i18n': {'en': {'name': 'Braton Riven Mod'}}},
        {'slug': 'braton_prime_receiver', 'tags': ['prime'],
         'i18n': {'en': {'name': 'Braton Prime Receiver'}}}]})
    chk('catalog keeps veiled families only, TYPE_ORDER sorted',
        [(i['type'], i['slug']) for i in cat],
        [('rifle', 'rifle_riven_mod_(veiled)'), ('companion_weapon', 'companion_weapon_riven_mod_(veiled)')])

    # 5. owned valuation: qty summing, rank uplift, unknown-family flag
    owned = [
        {'slug': 'melee_riven_mod_(veiled)', 'name': 'Melee Riven Mod (Veiled)', 'count': 2,
         'tags': ['mod', 'riven_mod']},
        {'slug': 'melee_riven_mod_(veiled)', 'name': 'Melee Riven Mod (Veiled)', 'count': 1,
         'tags': ['mod', 'veiled_riven']},
        {'slug': 'melee_riven_mod_(veiled)', 'name': 'Melee Riven Mod (Veiled)', 'count': 1, 'rank': 8,
         'tags': ['mod', 'riven_mod']},
        {'slug': 'braton_riven_mod', 'name': 'Braton Riven Mod', 'count': 1, 'tags': ['mod', 'riven_mod']},
        {'slug': 'rifle_riven_mod_(veiled)', 'name': 'Rifle Riven Mod (Veiled)', 'count': 4,
         'tags': ['mod', 'riven_mod']},
        {'slug': 'riven_sliver', 'name': 'Riven Sliver', 'count': 5, 'tags': ['resource']},
    ]
    rows = owned_rows(owned, {'melee': band})
    chk('stacks summed, sliver dropped, most valuable stack first',
        [(r['name'], r['qty'], r['est_low'], r['est_high'], r['basis']) for r in rows],
        [('Melee Riven Mod (Veiled)', 1, 12.6, 24.5, 'veiled_band:melee;rank:8'),
         ('Melee Riven Mod (Veiled)', 3, 9.0, 17.5, 'veiled_band:melee'),
         ('Braton Riven Mod', 1, None, None, UNKNOWN_BASIS),
         ('Rifle Riven Mod (Veiled)', 4, None, None, MISSING_BASIS)])
    chk('unknown family never guesses', rows[2]['basis'], UNKNOWN_BASIS)

    # 6. cache freshness + doc contract
    chk('fresh stamp', fresh(now_iso(), MAX_AGE), True)
    chk('2h old < 6h TTL', fresh((datetime.datetime.now() - datetime.timedelta(hours=2)).isoformat(), 6.0), True)
    chk('20h old > 6h TTL', fresh((datetime.datetime.now() - datetime.timedelta(hours=20)).isoformat(), 6.0), False)
    chk('missing stamp is stale', fresh(None, 6.0), False)
    doc = build_doc([band], rows, '2026-01-01T00:00:00')
    chk('doc keys', sorted(doc), ['generated', 'owned_rivens', 'summary', 'veiled_bands'])
    chk('summary counts', (doc['summary']['band_count'], doc['summary']['owned_count']), (1, 4))
    chk('band row keys', sorted(doc['veiled_bands'][0]),
        ['floor', 'median', 'name', 'slug', 'type', 'vol48'])
    chk('owned row keys', sorted(doc['owned_rivens'][0]),
        ['basis', 'est_high', 'est_low', 'name', 'qty'])
    chk('note names the unknown basis', UNKNOWN_BASIS in doc['summary']['note'], True)

    log('selftest: %s %d/%d' % ('FAIL' if fails else 'PASS', len(checks) - len(fails), len(checks)))
    for f in fails:
        log('  FAIL %s' % f)
    return 1 if fails else 0


def parse_args(argv):
    ap = argparse.ArgumentParser(description='Veiled riven price bands + owned-riven valuation.')
    ap.add_argument('--selftest', action='store_true', help='run the offline fixture checks and exit')
    ap.add_argument('--refresh', action='store_true', help='ignore cached quotes and re-price + re-read the catalog')
    ap.add_argument('--max-age', type=float, default=MAX_AGE, metavar='H',
                    help='quote cache TTL in hours (default %s)' % MAX_AGE)
    ap.add_argument('--json', action='store_true', help='print data/rivens.json after the report')
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    if a.selftest:
        return selftest()
    return run(max_age=0.0 if a.refresh else a.max_age, print_json=a.json)


if __name__ == '__main__':
    raise SystemExit(main())
