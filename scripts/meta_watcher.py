#!/usr/bin/env python3
"""Post-patch meta watcher: demand spikes/sinks that follow a game update.

Framing: scripts/trends.py publishes steady-state demand badges (vol30 vs the rest of the
90-day window). This script answers the narrower trading question "what changed since the
last patch?" and is meant to be read next to the update notes.

Inputs (all local, read-only):
  data/gamenews.json      {fetched, version, items:[{title,url,date,source,excerpt}]} built by
      the server warm job. Update posts = source 'updates' or an update/hotfix/patch title.
      patch.latest_version is the server-extracted version string (else regexed out of the
      newest update title); latest_date is its epoch. post_patch_active = an update post
      inside the last POST_PATCH_DAYS (10) days.
  data/stats.json         canonical vol48 + volday90 (90-day volume per day) per slug.
  data/trends.json        trends.py rows: vol30 (30-day volume), price_trend_pct.
  data/trends_cache.json  trends.py's raw day rows, used when a slug is not in trends.json.
  data/price_history.json daily [date, wts, wtb, median, vol48] points.
  data/{deals,owned,prices}.json  the bounded tracking set (same selector as trends.py: deal
      slugs by vol48 first, then liquid owned, cap MAX_SLUGS=120).

Metrics (per tracked slug):
  vol30_baseline = 30-day per-day average demand. Best available source wins:
      fresh endpoint cache (data/meta_stats_cache.json, TTL 12h, opt-in --fetch)
      -> trends.json vol30/30 -> trends_cache 30-day day-row sum/30
      -> stats.json volday90 (90-day window proxy, flagged in baseline_sources).
  ratio = (vol48 / 2) / vol30_baseline -- the 48h window normalised to a per-day rate over
      the 30-day average, so 1.0 = exactly average demand. verdict: spike >= 2.0,
      sink <= 0.5, else steady. Slugs with no vol48 or a baseline under MIN_BASELINE=1.0/day
      are skipped (too little signal to call a spike or a sink).
  price_trend_pct reuses trends.py's computation when present, else the newest price_history
      day against the most recent earlier day, else null.
  post_patch = an update post landed inside the 10-day window.

Output data/meta_watch.json:
  {version, generated, generated_iso, patch{...}, spike[], sink[], rows[], summary{spike,sink,
   tracked}, baseline_sources{}, skipped, method}. Rows carry
  {slug, name, vol48, vol48_per_day, vol30_baseline, ratio, price_trend_pct, post_patch}.
Read-only against the network (statistics endpoint only, honest UA, 0.35s spacing, <=50 calls
per run, caches reused). Writes only data/meta_watch.json + data/meta_stats_cache.json.
Stdlib only. Env hooks: META_DATA_DIR, META_WATCH_PATH, META_CACHE_PATH.

Usage:
  python scripts/meta_watcher.py                 # offline, local files only
  python scripts/meta_watcher.py --fetch         # + fill baseline gaps from the API
  python scripts/meta_watcher.py --fetch-limit 30  # + fresh read of the top 30 tracked slugs
  python scripts/meta_watcher.py --selftest      # fully offline fixtures, no data/ touched
"""
import argparse
import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'
API = 'https://api.warframe.market/v1/items/{}/statistics'
VERSION = 1
CACHE_TTL = 12 * 3600        # reuse endpoint rows for 12h
CACHE_KEEP = 7 * 86400       # drop untracked cache entries after a week
MAX_SLUGS = 120              # bounded tracking set
POST_PATCH_DAYS = 10         # "post patch" window
SPIKE_R, SINK_R = 2.0, 0.5   # ratio thresholds
MIN_BASELINE = 1.0           # per-day baseline floor: below this a spike/sink call is noise
SLEEP_FLOOR = 0.35           # minimum seconds between API calls
DEFAULT_MAX_CALLS = 50       # hard cap on API calls per run
CLOCK_SKEW = 3600            # tolerate a little future-dating on news timestamps
INPUTS = ('gamenews.json', 'stats.json', 'trends.json', 'trends_cache.json',
          'price_history.json', 'deals.json', 'owned.json', 'prices.json')
UPDATE_RE = re.compile(r'\b(?:update|hotfix|patch)\b', re.I)
VER_RE = re.compile(r'(\d+\.\d+(?:\.\d+)?)')
METHOD = ('ratio = (vol48/2) / vol30_baseline (48h window as a per-day rate over the 30-day '
          'per-day average); spike >= %s, sink <= %s, min baseline %s/day'
          % (SPIKE_R, SINK_R, MIN_BASELINE))


# ---------------------------------------------------------------- json / paths / time

def jload(path, default):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return default


def jdump(path, obj):
    """Atomic write (tmp + replace), like the rest of the house scripts."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def iso(epoch):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(epoch))


def pdt(raw):
    return dt.datetime.fromisoformat(str(raw).replace('Z', '+00:00'))


def resolve_paths():
    """Env-overridable paths, resolved per call so tests and --selftest can redirect all of them."""
    data = os.environ.get('META_DATA_DIR') or DATA
    paths = {'data': data,
             'out': os.environ.get('META_WATCH_PATH') or os.path.join(data, 'meta_watch.json'),
             'cache': os.environ.get('META_CACHE_PATH') or os.path.join(data, 'meta_stats_cache.json')}
    for name in INPUTS:
        paths[name[:-5]] = os.path.join(data, name)
    return paths


# ---------------------------------------------------------------- news / patch block

def update_posts(doc):
    """Normalised game-update posts from gamenews.json, newest first."""
    posts = []
    for it in ((doc or {}).get('items') or []):
        date = it.get('date')
        if not isinstance(date, int):
            continue
        title = str(it.get('title') or '')
        if it.get('source') != 'updates' and not UPDATE_RE.search(title):
            continue
        m = VER_RE.search(title)
        posts.append({'title': title, 'url': it.get('url'), 'date': date,
                      'version': m.group(1) if m else None})
    posts.sort(key=lambda r: -r['date'])
    return posts


def patch_block(doc, now_epoch):
    """patch.latest_version / latest_date / post_patch_active (+ context) from gamenews.json."""
    posts = update_posts(doc)
    latest = posts[0] if posts else None
    recent = [p for p in posts if -CLOCK_SKEW <= now_epoch - p['date'] <= POST_PATCH_DAYS * 86400]
    return {
        'latest_version': (doc or {}).get('version') or (latest or {}).get('version'),
        'latest_date': latest['date'] if latest else None,
        'latest_date_iso': iso(latest['date']) if latest else None,
        'latest_title': latest['title'] if latest else None,
        'post_patch_active': bool(recent),
        'post_count_window': len(recent),
        'days_since_latest': round((now_epoch - latest['date']) / 86400.0, 2) if latest else None,
        'window_days': POST_PATCH_DAYS,
        'source': 'data/gamenews.json',
        'news_fetched_iso': iso(doc['fetched']) if isinstance((doc or {}).get('fetched'), int) else None,
    }


# ---------------------------------------------------------------- metrics

def ratio_of(vol48, baseline):
    """(vol48/2) / baseline: the 48h window as a per-day rate over the daily baseline."""
    if not baseline or baseline <= 0:
        return None
    return round((int(vol48 or 0) / 2.0) / float(baseline), 2)


def verdict(ratio):
    if ratio is None:
        return None
    if ratio >= SPIKE_R:
        return 'spike'
    if ratio <= SINK_R:
        return 'sink'
    return 'steady'


def days30_total(days, now):
    """(volume, rows) of trends_cache-style day rows inside the trailing 30 days."""
    cut = now - dt.timedelta(days=30)
    total = rows = 0
    for r in days or []:
        try:
            if pdt(r.get('datetime')) >= cut:
                total += int(r.get('volume') or 0)
                rows += 1
        except Exception:
            continue
    return total, rows


def select_slugs(deals_rows, owned, prices, cap=MAX_SLUGS):
    """Ordered tracking slugs + slug->name: deal slugs by vol48 desc, then liquid owned."""
    names = {}
    for o in owned:
        if o.get('slug') and o.get('name'):
            names.setdefault(o['slug'], o['name'])
    for d in deals_rows:
        if d.get('slug'):
            names[d['slug']] = d.get('name') or names.get(d['slug'], d['slug'])
    ordered, seen = [], set()
    for d in sorted(deals_rows, key=lambda d: (-int(d.get('vol48') or 0), str(d.get('slug')))):
        s = d.get('slug')
        if s and s not in seen:
            seen.add(s)
            ordered.append(s)
    extras = []
    for o in owned:
        s = o.get('slug')
        if not s or s in seen or int(o.get('count') or 0) < 1:
            continue
        if ((prices.get(s) or {}).get('wts') or 0) < 10:
            continue
        extras.append(s)
    extras.sort(key=lambda s: (-((prices.get(s) or {}).get('wts') or 0), s))
    for s in extras:
        if len(ordered) >= cap:
            break
        if s in seen:
            continue
        seen.add(s)
        ordered.append(s)
    return ordered[:cap], names


def fetch_slug(slug, tries=3):
    """(vol30, vol48, error): 90days rows summed over the trailing 30 days + the 48h window."""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(API.format(slug),
                                         headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                j = json.loads(resp.read().decode())
            sc = (j.get('payload') or {}).get('statistics_closed')
            if sc is None:
                return None, None, 'no statistics_closed'
            cut = time.time() - 30 * 86400
            vol30 = 0
            for r in (sc.get('90days') or []):
                try:
                    if pdt(r.get('datetime')).timestamp() >= cut:
                        vol30 += int(r.get('volume') or 0)
                except Exception:
                    continue
            vol48 = sum(int(r.get('volume') or 0) for r in (sc.get('48hours') or []))
            return vol30, vol48, None
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504):
                return None, None, 'http %s' % exc.code
            time.sleep(3 + 2 * attempt)
        except Exception:
            time.sleep(2 + 2 * attempt)
    return None, None, 'fetch failed'


# ---------------------------------------------------------------- scoring

def price_trend(slug, tmap, phist):
    """trends.py's price_trend_pct when it has the slug, else price_history day-over-day."""
    row = tmap.get(slug) or {}
    if row.get('price_trend_pct') is not None:
        return row['price_trend_pct']
    pts = [p for p in (phist.get(slug) or []) if p and p[1] is not None]
    if len(pts) < 2:
        return None
    prev, cur = pts[-2][1], pts[-1][1]
    if not prev:
        return None
    return round((cur - prev) * 100.0 / prev, 1)


def score_rows(slugs, names, stats, phist, baselines, endp48, post_patch, tmap):
    """(rows, skipped). One row per slug with a vol48 and a usable baseline."""
    rows, skipped = [], 0
    for s in slugs:
        v48 = (stats.get(s) or {}).get('vol48')
        if v48 is None and (phist.get(s) or []):
            v48 = phist[s][-1][4]
        if v48 is None:
            v48 = endp48.get(s)
        base = baselines.get(s)
        if v48 is None or not base or base < MIN_BASELINE:
            skipped += 1
            continue
        v48 = int(v48)
        rows.append({'slug': s, 'name': names.get(s) or s, 'vol48': v48,
                     'vol48_per_day': round(v48 / 2.0, 2),
                     'vol30_baseline': round(float(base), 2), 'ratio': ratio_of(v48, base),
                     'price_trend_pct': price_trend(s, tmap, phist),
                     'post_patch': bool(post_patch)})
    return rows, skipped


def build_output(patch, rows, sources, skipped, now_epoch):
    """The meta_watch.json document (spike/sink lists + summary + source coverage)."""
    rows.sort(key=lambda r: (-(r['ratio'] if r['ratio'] is not None else 0), r['slug']))
    spike = [r for r in rows if verdict(r['ratio']) == 'spike']
    sink = sorted([r for r in rows if verdict(r['ratio']) == 'sink'], key=lambda r: r['ratio'])
    counts = {}
    for r in rows:                      # coverage of the scored rows only
        s = sources.get(r['slug'])
        counts[s] = counts.get(s, 0) + 1
    return {'version': VERSION, 'generated': now_epoch, 'generated_iso': iso(now_epoch),
            'patch': patch, 'spike': spike, 'sink': sink, 'rows': rows,
            'summary': {'spike': len(spike), 'sink': len(sink), 'tracked': len(rows)},
            'baseline_sources': counts, 'skipped': skipped, 'method': METHOD}


# ---------------------------------------------------------------- run

def run(args):
    t0 = time.time()
    p = resolve_paths()
    now_epoch = int(time.time())
    now = dt.datetime.now(dt.timezone.utc)
    sleep = max(SLEEP_FLOOR, args.sleep)
    max_calls = max(0, args.max_calls)

    news_doc = jload(p['gamenews'], {}) or {}
    patch = patch_block(news_doc, now_epoch)
    deals = jload(p['deals'], {}) or {}
    deals_rows = deals.get('deals') or []
    owned = jload(p['owned'], []) or []
    prices = jload(p['prices'], {}) or {}
    stats = jload(p['stats'], {}) or {}
    phist = (jload(p['price_history'], {}) or {}).get('items') or {}
    tmap = {r['slug']: r for r in ((jload(p['trends'], {}) or {}).get('rows') or []) if r.get('slug')}
    cache_doc = jload(p['cache'], {}) or {}
    cache = cache_doc.get('entries') or {}

    slugs, names = select_slugs(deals_rows, owned, prices)
    if args.limit > 0:
        slugs = slugs[:args.limit]

    def fresh_entry(s, now=now_epoch):
        e = cache.get(s) or {}
        return bool(isinstance(e.get('fetched'), int) and now - e['fetched'] <= CACHE_TTL
                    and e.get('vol30') is not None and not e.get('error'))

    # 1) endpoint cache (freshest measurement of the documented 30-day window), when enabled
    baselines, sources, endp48 = {}, {}, {}
    for s in slugs:
        if fresh_entry(s):
            baselines[s] = float(cache[s]['vol30']) / 30.0
            sources[s] = 'stats_endpoint'
            if cache[s].get('vol48') is not None:
                endp48[s] = int(cache[s]['vol48'])

    # 2) trends.json (vol30) -> trends_cache day rows -> stats.json 90-day proxy
    gaps = []
    tcache = None
    for s in slugs:
        if s in baselines:
            continue
        v30 = (tmap.get(s) or {}).get('vol30')
        if isinstance(v30, int) and v30 > 0:
            baselines[s], sources[s] = v30 / 30.0, 'trends.json'
            continue
        gaps.append(s)
    if gaps:
        tcache = ((jload(p['trends_cache'], {}) or {}).get('entries') or {})
        still = []
        for s in gaps:
            e = tcache.get(s) or {}
            if (isinstance(e.get('fetched'), int) and now_epoch - e['fetched'] <= CACHE_TTL
                    and e.get('days')):
                total, rows = days30_total(e['days'], now)
                if rows:
                    baselines[s], sources[s] = total / 30.0, 'trends_cache'
                    continue
            still.append(s)
        gaps = still

    # 3) opt-in endpoint fetch: baseline gaps first, then the first --fetch-limit tracked slugs
    want = list(gaps)
    if args.fetch_limit > 0:
        want.extend(slugs[:args.fetch_limit])
    todo, seen = [], set()
    for s in want:
        if s in seen:
            continue
        seen.add(s)
        if fresh_entry(s) and not args.refresh:
            continue
        todo.append(s)
    calls, errors = 0, []
    if (args.fetch or args.fetch_limit > 0) and todo:
        todo = todo[:max_calls]
        refresh_n = max(0, len(todo) - len(gaps))
        print('[meta_watcher] endpoint: %d slug(s) to fetch (%d baseline gaps, %d refresh), sleep %.2fs'
              % (len(todo), len(gaps), refresh_n, sleep), flush=True)
        prev_req = 0.0
        for i, s in enumerate(todo, 1):
            if prev_req:
                gap_s = sleep - (time.time() - prev_req)
                if gap_s > 0:
                    time.sleep(gap_s)
            prev_req = time.time()
            vol30, vol48, err = fetch_slug(s)
            calls += 1
            if err:
                errors.append((s, err))
                cache[s] = {'fetched': now_epoch, 'vol30': None, 'vol48': None, 'error': err}
                continue
            cache[s] = {'fetched': now_epoch, 'vol30': vol30, 'vol48': vol48, 'error': None}
            baselines[s], sources[s] = float(vol30) / 30.0, 'stats_endpoint'
            if vol48 is not None:
                endp48[s] = int(vol48)
            if i % 10 == 0:
                print('[meta_watcher] fetched %d/%d (%.0fs)' % (i, len(todo), time.time() - t0), flush=True)
    elif todo:
        print('[meta_watcher] %d slugs have no 30d baseline; rerun with --fetch to fill them '
              '(offline: stats.json 90-day proxy is used instead)' % len(todo), flush=True)

    # 4) slugs still without any baseline fall back to the stats.json 90-day per-day rate
    for s in slugs:
        if s in baselines:
            continue
        vd = (stats.get(s) or {}).get('volday90')
        if isinstance(vd, (int, float)) and vd > 0:
            baselines[s], sources[s] = float(vd), 'stats.json:90d'

    rows, skipped = score_rows(slugs, names, stats, phist, baselines, endp48,
                               patch['post_patch_active'], tmap)

    doc = build_output(patch, rows, sources, skipped, now_epoch)
    jdump(p['out'], doc)

    if cache or calls or os.path.exists(p['cache']):
        stale_cut = now_epoch - CACHE_KEEP
        for s in [s for s, e in cache.items()
                  if s not in set(slugs) and isinstance(e.get('fetched'), int) and e['fetched'] < stale_cut]:
            del cache[s]
        jdump(p['cache'], {'version': VERSION, 'updated': now_epoch, 'updated_iso': iso(now_epoch),
                           'ttl_seconds': CACHE_TTL, 'ua': UA, 'entries': cache})

    c = doc['summary']
    print('[meta_watcher] post-patch meta watch | %s' % iso(now_epoch), flush=True)
    print('[meta_watcher] patch %s (%s) | post-patch %s | %d update post(s) in %dd | gap %sd'
          % (patch['latest_version'], (patch['latest_date_iso'] or '-'),
             'ACTIVE' if patch['post_patch_active'] else 'inactive',
             patch['post_count_window'], patch['window_days'], patch['days_since_latest']), flush=True)
    print('[meta_watcher] tracked %d slugs (deals %d + owned fill, cap %d) | baselines %s | skipped %d'
          % (len(rows), len({d.get('slug') for d in deals_rows}), MAX_SLUGS,
             doc['baseline_sources'] or '-', skipped), flush=True)
    print('[meta_watcher] SPIKE %d | SINK %d | steady %d | api calls %d'
          % (c['spike'], c['sink'], c['tracked'] - c['spike'] - c['sink'], calls), flush=True)
    for tag, lst in (('SPIKE', doc['spike']), ('SINK', doc['sink'])):
        for r in lst[:5]:
            print('  %-5s %-30s 48h %-5d (%s/d) base %-6s ratio %-5s trend %s%%%s'
                  % (tag, r['slug'][:30], r['vol48'], r['vol48_per_day'], r['vol30_baseline'],
                     r['ratio'], r['price_trend_pct'], ' [post-patch]' if r['post_patch'] else ''),
                  flush=True)
    if errors:
        print('[meta_watcher] errors (%d): %s'
              % (len(errors), ', '.join('%s:%s' % e for e in errors[:8])), flush=True)
    print('[out] %s | %s | %.1fs' % (p['out'], p['cache'], time.time() - t0), flush=True)
    return 0


# ---------------------------------------------------------------- selftest

def selftest():
    """Fully offline: fixtures in a temp dir, no network, no repo file touched."""
    import tempfile
    day = 86400
    now = int(time.time())
    tmp = tempfile.mkdtemp(prefix='meta_watch_selftest_')
    saved = {k: os.environ.get(k) for k in ('META_DATA_DIR', 'META_WATCH_PATH', 'META_CACHE_PATH')}
    real_fetch = globals()['fetch_slug']
    checks = []

    def ok(label, cond, detail=''):
        checks.append(bool(cond))
        print('[meta_watcher.selftest] %s %s%s'
              % ('OK  ' if cond else 'FAIL', label, (' | ' + str(detail)) if detail else ''), flush=True)

    def fixture(name, obj):
        jdump(os.path.join(tmp, name), obj)

    def news(version, posts):
        return {'fetched': now - 600, 'version': version,
                'items': [dict(title=t, url='https://example.invalid/' + str(i), date=now - d * day,
                               source=src, excerpt='') for i, (t, d, src) in enumerate(posts)]}

    os.environ['META_DATA_DIR'] = tmp
    os.environ['META_WATCH_PATH'] = os.path.join(tmp, 'meta_watch.json')
    os.environ['META_CACHE_PATH'] = os.path.join(tmp, 'meta_stats_cache.json')

    def boom(*a, **k):
        raise AssertionError('selftest must stay offline: fetch_slug was called')

    try:
        # --- news parsing / post-patch window
        doc = news('44.0.1', [('Iceblade of Narin: Hotfix 44.0.1', 3, 'updates'),
                              ('Citrine Prime Access Available Now', 4, 'news'),
                              ('Update 44: Iceblade of Narin', 12, 'updates')])
        pb = patch_block(doc, now)
        ok('patch.latest_version comes from gamenews.version', pb['latest_version'] == '44.0.1', pb['latest_version'])
        ok('patch.latest_date = newest update post', pb['latest_date'] == now - 3 * day)
        ok('post_patch_active true for a 3-day-old update', pb['post_patch_active'] is True)
        ok('only in-window update posts counted (steam news ignored)', pb['post_count_window'] == 1,
           pb['post_count_window'])
        ok('days_since_latest ~3.0', 2.9 <= pb['days_since_latest'] <= 3.1, pb['days_since_latest'])
        ok('latest_title carried for the UI', pb['latest_title'].startswith('Iceblade of Narin: Hotfix'), pb['latest_title'])

        ok('no version field -> regexed from the newest update title',
           patch_block(news(None, [('Hotfix 44.0.2', 2, 'updates')]), now)['latest_version'] == '44.0.2')
        ok('window boundary: just inside 10 days is active',
           patch_block(news(None, [('Update 44', 10, 'updates')]), now)['post_patch_active'] is True)
        ok('window boundary: 11 days out is inactive',
           patch_block(news(None, [('Update 44', 11, 'updates')]), now)['post_patch_active'] is False)
        ok('news-only feed -> no patch, no active window',
           patch_block(news(None, [('Devstream 197 Overview', 1, 'news')]), now)['post_patch_active'] is False)
        ok('empty/missing gamenews.json is handled',
           patch_block({}, now)['latest_version'] is None
           and patch_block({}, now)['post_patch_active'] is False)
        ok('non-int news dates are skipped',
           patch_block({'items': [{'title': 'Hotfix 1.0', 'date': None, 'source': 'updates'}]}, now)['latest_date'] is None)

        # --- metric math
        ok('ratio = (vol48/2)/baseline', ratio_of(60, 10) == 3.0 and ratio_of(20, 10) == 1.0
           and ratio_of(4, 10) == 0.2, '%s/%s/%s' % (ratio_of(60, 10), ratio_of(20, 10), ratio_of(4, 10)))
        ok('spike threshold is inclusive at 2.0x', verdict(ratio_of(40, 10)) == 'spike')
        ok('sink threshold is inclusive at 0.5x', verdict(ratio_of(10, 10)) == 'sink')
        ok('between the thresholds is steady', verdict(ratio_of(15, 10)) == 'steady'
           and verdict(ratio_of(30, 10)) == 'steady')
        ok('no baseline -> no ratio, no verdict', ratio_of(50, 0) is None and verdict(None) is None)

        # --- select_slugs (bounded tracking set, deals first)
        deals_rows = [{'slug': 'd1', 'name': 'Deal One', 'vol48': 5}, {'slug': 'd2', 'vol48': 9},
                      {'slug': 'd2', 'vol48': 4}]
        owned = [{'slug': 'o1', 'name': 'Owned One', 'count': 3}, {'slug': 'o2', 'count': 1},
                 {'slug': 'o3', 'name': 'Owned Three', 'count': 0}]
        sel, nm = select_slugs(deals_rows, owned, {'o1': {'wts': 50}, 'o2': {'wts': 99}, 'o3': {'wts': 99}}, cap=2)
        ok('deal slugs rank by vol48 desc and dedupe', sel == ['d2', 'd1'] and len(sel) == 2, sel)
        ok('names map covers deals and owned', nm.get('d2') == 'd2' and nm.get('o1') == 'Owned One')

        # --- end-to-end offline run
        fixture('gamenews.json', doc)
        fixture('stats.json', {'alpha': {'vol48': 90, 'volday90': 20.0},
                               'beta': {'volday90': 12.0},
                               'epsilon': {'vol48': 40, 'volday90': 5.0},
                               'eta': {'vol48': 1, 'volday90': 0.4}})
        fixture('deals.json', {'deals': [{'slug': 'alpha', 'name': 'Alpha', 'vol48': 90},
                                         {'slug': 'beta', 'name': 'Beta', 'vol48': 4},
                                         {'slug': 'gamma', 'name': 'Gamma', 'vol48': 100},
                                         {'slug': 'epsilon', 'name': 'Epsilon', 'vol48': 40},
                                         {'slug': 'zeta', 'name': 'Zeta', 'vol48': 30},
                                         {'slug': 'eta', 'name': 'Eta', 'vol48': 1}]})
        fixture('trends.json', {'rows': [{'slug': 'alpha', 'name': 'Alpha', 'vol30': 900,
                                          'vol90': 3000, 'ratio': 0.9, 'badge': 'steady',
                                          'price_trend_pct': 12.5}]})
        fixture('trends_cache.json', {'entries': {
            'beta': {'fetched': now - 3600, 'days': [
                {'datetime': (dt.datetime.fromtimestamp(now - 5 * day, dt.timezone.utc)
                              ).isoformat(), 'volume': 200, 'median': 5.0, 'mod_rank': None},
                {'datetime': (dt.datetime.fromtimestamp(now - 40 * day, dt.timezone.utc)
                              ).isoformat(), 'volume': 999, 'median': 5.0, 'mod_rank': None}]}}})
        fixture('price_history.json', {'items': {
            'beta': [['2026-09-01', 10, 4, 9.0, 4], ['2026-09-25', 20, 4, 9.5, 4]],
            'alpha': [['2026-09-25', 40, 4, 39.0, 90]]}})
        fixture('meta_stats_cache.json', {'entries': {
            'gamma': {'fetched': now - 600, 'vol30': 600, 'vol48': 100, 'error': None}}})
        fixture('prices.json', {})

        globals()['fetch_slug'] = boom
        rc = run(argparse.Namespace(fetch=False, fetch_limit=0, refresh=False, limit=0,
                                    max_calls=DEFAULT_MAX_CALLS, sleep=0.35, selftest=False))
        ok('offline run returns 0 and never touches the network', rc == 0)
        doc_out = jload(os.path.join(tmp, 'meta_watch.json'), None)
        ok('meta_watch.json written with the documented keys',
           isinstance(doc_out, dict) and {'version', 'generated', 'generated_iso', 'patch', 'spike',
                                          'sink', 'rows', 'summary', 'baseline_sources', 'skipped'}
           <= set(doc_out), sorted(doc_out or {}))
        ok('patch block carries the live fixture values',
           doc_out['patch']['latest_version'] == '44.0.1'
           and doc_out['patch']['latest_date'] == now - 3 * day
           and doc_out['patch']['post_patch_active'] is True)
        rmap = {r['slug']: r for r in doc_out['rows']}
        ok('trends.json vol30/30 drives the baseline', rmap['alpha']['vol30_baseline'] == 30.0
           and rmap['alpha']['ratio'] == 1.5, rmap['alpha'])
        ok('stats.json vol48 is the canonical recent window', rmap['alpha']['vol48'] == 90)
        ok('trends_cache 30d rows beat nothing: beta baseline = 200/30 -> sink',
           rmap['beta']['vol30_baseline'] == 6.67 and rmap['beta']['ratio'] == 0.3, rmap['beta'])
        ok('price_history vol48 used when stats.json has none', rmap['beta']['vol48'] == 4)
        ok('endpoint cache is the freshest baseline source',
           rmap['gamma']['vol30_baseline'] == 20.0 and rmap['gamma']['ratio'] == 2.5
           and doc_out['baseline_sources'].get('stats_endpoint') == 1, rmap['gamma'])
        ok('stats.json 90d proxy covers slugs with no 30d source',
           rmap['epsilon']['vol30_baseline'] == 5.0 and rmap['epsilon']['ratio'] == 4.0, rmap['epsilon'])
        ok('rows carry the exact row contract',
           all(set(r) == {'slug', 'name', 'vol48', 'vol48_per_day', 'vol30_baseline', 'ratio',
                          'price_trend_pct', 'post_patch'} for r in doc_out['rows']))
        ok('spike list is sorted by ratio desc', [r['slug'] for r in doc_out['spike']] == ['epsilon', 'gamma'],
           [r['slug'] for r in doc_out['spike']])
        ok('sink list holds the collapsed items', [r['slug'] for r in doc_out['sink']] == ['beta'])
        ok('summary counts match the lists',
           doc_out['summary'] == {'spike': 2, 'sink': 1, 'tracked': 4}, doc_out['summary'])
        ok('unusable slugs are skipped, not guessed', doc_out['skipped'] == 2, doc_out['skipped'])
        ok('every row is annotated post_patch while a patch is in window',
           all(r['post_patch'] is True for r in doc_out['rows']))
        ok('price_trend_pct reused from trends.json', rmap['alpha']['price_trend_pct'] == 12.5)
        ok('price_trend_pct falls back to price_history day-over-day',
           rmap['beta']['price_trend_pct'] == 100.0, rmap['beta']['price_trend_pct'])
        ok('vol48_per_day mirrors vol48/2', rmap['alpha']['vol48_per_day'] == 45.0)
        ok('offline run did not invent an endpoint cache',
           jload(os.path.join(tmp, 'meta_stats_cache.json'), {}).get('entries', {}).get('zeta') is None)

        # --- fetch path (stubbed, still offline) with cache reuse
        stub_calls = []

        def stub_fetch(slug, tries=3):
            stub_calls.append(slug)
            return 300, 20, None

        globals()['fetch_slug'] = stub_fetch
        rc = run(argparse.Namespace(fetch=True, fetch_limit=0, refresh=False, limit=0,
                                    max_calls=DEFAULT_MAX_CALLS, sleep=0.35, selftest=False))
        doc2 = jload(os.path.join(tmp, 'meta_watch.json'), None)
        rmap2 = {r['slug']: r for r in doc2['rows']}
        ok('--fetch fills the baseline gap for zeta', rc == 0 and 'zeta' in rmap2
           and rmap2['zeta']['vol30_baseline'] == 10.0, rmap2.get('zeta'))
        ok('--fetch calls the endpoint once per baseline gap (epsilon, zeta, eta)',
           stub_calls == ['epsilon', 'zeta', 'eta'], stub_calls)
        ok('--fetch rescues slugs the local files could not score',
           doc2['summary']['tracked'] == 6 and doc2['skipped'] == 0, doc2['summary'])
        calls1 = list(stub_calls)
        cache2 = jload(os.path.join(tmp, 'meta_stats_cache.json'), {})
        ok('meta_stats_cache.json stores vol30/vol48 with a fetched stamp',
           cache2['entries']['zeta']['vol30'] == 300 and cache2['entries']['zeta']['vol48'] == 20
           and isinstance(cache2['entries']['zeta']['fetched'], int)
           and cache2['ttl_seconds'] == CACHE_TTL and cache2['ua'] == UA)

        def stub_boom(slug, tries=3):
            raise AssertionError('fresh cache entry must be reused, not refetched')

        globals()['fetch_slug'] = stub_boom
        run(argparse.Namespace(fetch=True, fetch_limit=0, refresh=False, limit=0,
                               max_calls=DEFAULT_MAX_CALLS, sleep=0.35, selftest=False))
        ok('fresh endpoint-cache entries keep the next run off the network',
           stub_calls == calls1, stub_calls)

        globals()['fetch_slug'] = stub_fetch
        stale = jload(os.path.join(tmp, 'meta_stats_cache.json'), {})
        stale['entries']['zeta']['fetched'] = now - CACHE_TTL - 60
        jdump(os.path.join(tmp, 'meta_stats_cache.json'), stale)
        before3 = len(stub_calls)
        run(argparse.Namespace(fetch=True, fetch_limit=0, refresh=False, limit=0,
                               max_calls=DEFAULT_MAX_CALLS, sleep=0.35, selftest=False))
        ok('a cache entry older than the TTL is refetched',
           stub_calls[before3:] == ['zeta'], stub_calls[before3:])

        globals()['fetch_slug'] = stub_fetch
        before4 = len(stub_calls)
        run(argparse.Namespace(fetch=False, fetch_limit=6, refresh=True, limit=0,
                               max_calls=DEFAULT_MAX_CALLS, sleep=0.35, selftest=False))
        refreshed = stub_calls[before4:]
        ok('--refresh + --fetch-limit refetches the top tracked slugs',
           sorted(refreshed) == ['alpha', 'beta', 'epsilon', 'eta', 'gamma', 'zeta'], refreshed)

        before2 = len(stub_calls)
        run(argparse.Namespace(fetch=True, fetch_limit=6, refresh=True, limit=0,
                               max_calls=2, sleep=0.35, selftest=False))
        capped = stub_calls[before2:]
        ok('--max-calls caps one run at N endpoint calls',
           len(capped) == 2 and set(capped) <= set(refreshed), capped)

        before = list(stub_calls)
        run(argparse.Namespace(fetch=True, fetch_limit=6, refresh=True, limit=0,
                               max_calls=0, sleep=0.35, selftest=False))
        ok('--max-calls 0 keeps the run offline even with --fetch/--refresh',
           stub_calls == before, stub_calls)
    finally:
        globals()['fetch_slug'] = real_fetch
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    bad = [c for c in checks if not c]
    print('[meta_watcher.selftest] %d/%d checks passed%s'
          % (len(checks) - len(bad), len(checks), '' if not bad else ' -- FAILURES PRESENT'), flush=True)
    return 1 if bad else 0


# ---------------------------------------------------------------- cli

def main(argv=None):
    ap = argparse.ArgumentParser(description='Post-patch demand watcher (spikes/sinks after a game update)')
    ap.add_argument('--fetch', action='store_true',
                    help='use the statistics endpoint to fill slugs with no 30d baseline')
    ap.add_argument('--fetch-limit', type=int, default=0, metavar='N',
                    help='also refetch the first N tracked slugs from the endpoint (implies --fetch)')
    ap.add_argument('--refresh', action='store_true', help='ignore the endpoint cache TTL')
    ap.add_argument('--max-calls', type=int, default=DEFAULT_MAX_CALLS,
                    help='hard cap on API calls this run (default %d)' % DEFAULT_MAX_CALLS)
    ap.add_argument('--sleep', type=float, default=SLEEP_FLOOR,
                    help='seconds between API calls (floor %.2f)' % SLEEP_FLOOR)
    ap.add_argument('--limit', type=int, default=0, help='debug: only the first N tracked slugs')
    ap.add_argument('--selftest', action='store_true', help='offline fixture checks, then exit')
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
