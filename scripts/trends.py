"""Demand-trend badges per tracked slug (vol30 vs the 90-day volume baseline).

Source: GET https://api.warframe.market/v1/items/{slug}/statistics
  payload.statistics_closed.90days  -> day rows, ONE ROW PER (day, mod_rank); mod_rank is
  null for unranked items (relics/parts) and there are several lanes for mods/arcanes.
  Zero-volume days are omitted, so series can be sparse (18 rows over 80 days for a dead
  relic). 48hours -> hourly rows with the same lane scheme.
Tracking set (bounded): every slug in data/deals.json (deduped; wealthiest vol48 first) then
data/owned.json entries with count>=1 and a floor WTS price >=10p (prices.json), capped at
MAX_SLUGS -- anything past the cap is skipped this run.
Metrics (all rank lanes summed for volume, matching the stats.json volday90 convention):
  vol30 = day-row volume in the last 30 days | vol90total = every returned day row
  ratio = vol30 / (vol90total/3); badge: SPIKE >=1.6, STEADY >=0.75, FADE <0.75,
  insufficient_data when vol90total < 5 (ratio still reported, excluded from top lists).
  price_trend_pct: medians across rank lanes are not comparable, so it uses the busiest lane
  only -- last day median vs the day row nearest the 30-day cutoff (+-7 days, else null).
  vol48 prefers data/stats.json (canonical dashboard value), then the deal row, then the
  summed 48 hour endpoint window.
Cache: data/trends_cache.json -- raw day/hour rows trimmed to (datetime, volume, median,
mod_rank), resumable, TTL 12h; --refresh refetches everything. Reads
data/{deals,owned,prices,stats}.json; writes data/trends.json + cache. Stdlib only.
Usage: python scripts/trends.py [--refresh] [--limit N] [--sleep S]
"""
import argparse, datetime as dt, json, os, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
TRENDS_P = os.path.join(DATA, 'trends.json')
CACHE_P = os.path.join(DATA, 'trends_cache.json')
UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'
API = 'https://api.warframe.market/v1/items/{}/statistics'
CACHE_TTL = 12 * 3600      # reuse cached rows for 12h
MAX_SLUGS = 250            # bounded tracking set (caps the run ~6 min at 0.4s spacing)
SPIKE_R, STEADY_R = 1.6, 0.75
MIN_VOL90 = 5              # below this the 30d/90d split is noise
PRICE_TOL_DAYS = 7         # how far from the 30-day cutoff a price baseline may sit
PERMANENT_HTTP = (400, 404, 410, 422)   # cached as permanent misses so reruns stay fast


def jload(path, default):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return default


def jdump(path, obj):
    with open(path + '.tmp', 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, indent=1)
    os.replace(path + '.tmp', path)


def iso(epoch):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(epoch))


def pdt(raw):
    return dt.datetime.fromisoformat(str(raw).replace('Z', '+00:00'))


def trim(rows):
    """Raw API rows -> the fields every metric here needs."""
    return [{'datetime': r.get('datetime'), 'volume': int(r.get('volume') or 0),
             'median': r.get('median'), 'mod_rank': r.get('mod_rank')} for r in rows]


def fetch(slug, tries=3):
    """(days, h48, error) for one slug; backs off on 429/5xx."""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(API.format(slug),
                                         headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                j = json.loads(resp.read().decode())
            sc = (j.get('payload') or {}).get('statistics_closed')
            if sc is None:
                return None, None, 'no statistics_closed'
            return trim(sc.get('90days') or []), trim(sc.get('48hours') or []), None
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504):
                return None, None, 'http %s%s' % (exc.code, ' perm' if exc.code in PERMANENT_HTTP else '')
            time.sleep(3 + 2 * attempt)
        except Exception:
            time.sleep(2 + 2 * attempt)
    return None, None, 'fetch failed'


def select_slugs(deals_rows, owned, prices):
    """Ordered tracking slugs + slug->name. Deals first, then liquid owned fill the cap."""
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
        if len(ordered) >= MAX_SLUGS:
            break
        seen.add(s)
        ordered.append(s)
    return ordered[:MAX_SLUGS], names


def price_trend(days, cut30):
    """(median now - median 30d ago)/median*100 on the busiest rank lane, else None."""
    lanes = {}
    for r in days:
        lanes.setdefault(r.get('mod_rank'), []).append(r)
    if not lanes:
        return None
    rows = sorted(max(lanes.values(), key=lambda rs: sum(x['volume'] for x in rs)),
                  key=lambda r: pdt(r['datetime']))
    cur = next((r['median'] for r in reversed(rows) if r['median'] is not None), None)
    best = None
    for r in rows:
        if r['median'] is None:
            continue
        off = abs((pdt(r['datetime']) - cut30).total_seconds())
        if best is None or off < best[0]:
            best = (off, r['median'])
    if not cur or best is None or best[0] > PRICE_TOL_DAYS * 86400:
        return None
    past = best[1]
    if not past:
        return None
    return round((cur - past) * 100.0 / past, 1)


def demand_row(slug, name, days, h48, vol48_local, now):
    vol90 = sum(r['volume'] for r in days)
    cut30 = now - dt.timedelta(days=30)
    vol30 = sum(r['volume'] for r in days if pdt(r['datetime']) >= cut30)
    ratio = round(vol30 / (vol90 / 3.0), 2) if vol90 else None
    if vol90 < MIN_VOL90:
        badge = 'insufficient_data'
    elif ratio >= SPIKE_R:
        badge = 'spike'
    elif ratio >= STEADY_R:
        badge = 'steady'
    else:
        badge = 'fade'
    vol48 = vol48_local
    if vol48 is None:
        vol48 = sum(r['volume'] for r in h48 if pdt(r['datetime']) >= now - dt.timedelta(hours=48))
    return {'slug': slug, 'name': name or slug, 'vol48': int(vol48 or 0), 'vol30': vol30,
            'vol90': vol90, 'ratio': ratio, 'badge': badge,
            'price_trend_pct': price_trend(days, cut30)}


def fresh(entry, now_epoch):
    return bool(entry) and isinstance(entry.get('fetched'), int) and now_epoch - entry['fetched'] <= CACHE_TTL


def main():
    ap = argparse.ArgumentParser(description='Demand-trend badges (vol30 vs 90-day volume) for tracked slugs')
    ap.add_argument('--refresh', action='store_true', help='ignore the cache and refetch every slug')
    ap.add_argument('--limit', type=int, default=0, help='debug: only the first N slugs (0 = all)')
    ap.add_argument('--sleep', type=float, default=0.4, help='seconds between API calls (floor 0.4)')
    args = ap.parse_args()
    sleep = max(0.4, args.sleep)

    deals = jload(os.path.join(DATA, 'deals.json'), {}) or {}
    deals_rows = deals.get('deals') or []
    owned = jload(os.path.join(DATA, 'owned.json'), []) or []
    prices = jload(os.path.join(DATA, 'prices.json'), {}) or {}
    stats = jload(os.path.join(DATA, 'stats.json'), {}) or {}
    slugs, names = select_slugs(deals_rows, owned, prices)
    if args.limit > 0:
        slugs = slugs[:args.limit]
    deal_vol48 = {}
    for d in deals_rows:
        s = d.get('slug')
        if s:
            deal_vol48[s] = max(int(deal_vol48.get(s) or 0), int(d.get('vol48') or 0))

    cache = jload(CACHE_P, {}) or {}
    entries = cache.get('entries') or {}
    now_epoch = int(time.time())
    now = dt.datetime.now(dt.timezone.utc)
    todo = [s for s in slugs if args.refresh or not fresh(entries.get(s), now_epoch)]
    hits = len(slugs) - len(todo)
    print('[trends] tracked %d slugs (%d deals + owned fill, cap %d) | cache hits %d | to fetch %d | sleep %.1fs'
          % (len(slugs), len({d.get('slug') for d in deals_rows}), MAX_SLUGS, hits, len(todo), sleep), flush=True)

    t0, prev_req, errors = time.time(), 0.0, []
    for i, slug in enumerate(todo, 1):
        if prev_req:
            gap = sleep - (time.time() - prev_req)
            if gap > 0:
                time.sleep(gap)
        prev_req = time.time()
        days, h48, err = fetch(slug)
        if err:
            errors.append((slug, err))
            if 'perm' in err:
                entries[slug] = {'fetched': now_epoch, 'days': None, 'h48': None, 'error': err}
        else:
            entries[slug] = {'fetched': now_epoch, 'days': days, 'h48': h48}
        if i % 20 == 0 or i == len(todo):
            el = time.time() - t0
            eta = (el / i) * (len(todo) - i) if i else 0
            el_all = (el / i) * len(todo)
            print('[trends] %d/%d fetched in %.0fs (eta %.0fs, full-run est %.0fs) | errors %d'
                  % (i, len(todo), el, eta, el_all, len(errors)), flush=True)
            jdump(CACHE_P, {'version': 1, 'updated': now_epoch, 'updated_iso': iso(now_epoch),
                            'ttl_seconds': CACHE_TTL, 'slugs': slugs, 'entries': entries})

    rows, skip = [], 0
    for slug in slugs:
        e = entries.get(slug) or {}
        if not fresh(e, now_epoch):
            skip += 1
            continue
        if e.get('days') is None:
            skip += 1
            continue
        v48 = (stats.get(slug) or {}).get('vol48')
        if v48 is None:
            v48 = deal_vol48.get(slug)
        rows.append(demand_row(slug, names.get(slug), e['days'], e.get('h48') or [], v48, now))
    rows.sort(key=lambda r: r['slug'])

    counts = {'tracked': len(rows), 'spike': 0, 'steady': 0, 'fade': 0, 'insufficient': 0}
    for r in rows:
        counts['insufficient' if r['badge'] == 'insufficient_data' else r['badge']] += 1
    ranked = [r for r in rows if r['badge'] != 'insufficient_data' and r['ratio'] is not None]
    top_spikes = sorted(ranked, key=lambda r: -r['ratio'])[:10]
    top_fades = sorted(ranked, key=lambda r: r['ratio'])[:10]
    jdump(TRENDS_P, {'version': 1, 'generated': now_epoch, 'generated_iso': iso(now_epoch),
                     'counts': counts, 'rows': rows, 'top_spikes': top_spikes, 'top_fades': top_fades})

    # drop out-of-rotation cache entries after a week so the file stays bounded
    stale_cut = now_epoch - 7 * 86400
    dropped = [s for s, e in entries.items()
               if s not in set(slugs) and isinstance(e.get('fetched'), int) and e['fetched'] < stale_cut]
    for s in dropped:
        del entries[s]
    cache.update({'updated': now_epoch, 'updated_iso': iso(now_epoch), 'slugs': slugs, 'entries': entries})
    jdump(CACHE_P, cache)

    print('[trends] counts: tracked %d | spike %d | steady %d | fade %d | insufficient %d'
          % (counts['tracked'], counts['spike'], counts['steady'], counts['fade'], counts['insufficient']), flush=True)
    if skip:
        print('[trends] skipped %d slugs with no cached data' % skip, flush=True)
    if errors:
        print('[trends] errors (%d): %s' % (len(errors), ', '.join('%s:%s' % e for e in errors[:10])), flush=True)
    for tag, lst in (('SPIKE', top_spikes), ('FADE', top_fades)):
        for r in lst[:3]:
            print('  %s %-32s vol48 %-4s vol30 %-5d vol90 %-6d ratio %-5s trend %s%%'
                  % (tag, r['slug'][:32], r['vol48'], r['vol30'], r['vol90'], r['ratio'], r['price_trend_pct']), flush=True)
    print('[out] %s | %s | %.0fs' % (TRENDS_P, CACHE_P, time.time() - t0), flush=True)


if __name__ == '__main__':
    main()
