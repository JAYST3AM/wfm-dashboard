"""Wishlist + budget planner.

Reads : data/sets.json           (top_targets COMPLETE/COMPLETE_MAYBE + per-part estimates)
        data/prices.json         (cached sell floors)
        data/trader_limits.json  (plat + trades_left)
        data/wfm_items_v2.json   (catalog: names / ids)
        data/wishlist_config.json (user-editable rows; created once, NEVER overwritten)
Writes: data/wishlist.json       (computed wishlist rows + suggested rows + affordable plan)

Config rows win over auto-suggested rows for the same slug. Floors come from prices.json; a slug
with no cached quote is fetched live (v2 /orders/item/{slug}/top, >=0.4s spacing, WFMTrader UA)
unless the network is unreachable, in which case it is reported as UNKNOWN instead of guessed.

Status   : BUY_NOW  floor <= max_price
           CLOSE    floor <= max_price * 1.25
           WAIT     floor above that
           UNKNOWN  no floor available (offline / no quotes)
Budget   : needed = sum(qty * max_price) over BUY_NOW rows in the wishlist (config + suggested).
           The affordable plan is a greedy knapsack by max_price/floor ratio (biggest discount
           first), one unit per trade, limited by plat and by the trade allowance.
Flags    : --offline  skip every network call (pure cache mode)
"""
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
OUT_PATH = os.path.join(DATA, 'wishlist.json')
CONFIG_PATH = os.path.join(DATA, 'wishlist_config.json')

UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'
TOP_URL = 'https://api.warframe.market/v2/orders/item/%s/top'
CONFIG_COMMENT = 'edit me: add rows like {"slug":"primed_continuity","max_price":100,"qty":1}'
TARGET_ACTIONS = ('COMPLETE', 'COMPLETE_MAYBE')
CLOSE_FACTOR = 1.25
SPACING = 0.45           # seconds between network calls (spec floor: 0.4)
MAX_LIVE_FETCHES = 60    # safety cap per run
RETRY_CODES = (429, 502, 503)
STATUSES = ('BUY_NOW', 'CLOSE', 'WAIT', 'UNKNOWN')


def load(name, default=None):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return default
    try:
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return default


def atomic_write(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, indent=1)
    os.replace(tmp, path)


def as_num(x):
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return None


def ensure_config():
    """Create the user config once. Never overwrite it on later runs."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding='utf-8') as fh:
                cfg = json.load(fh)
            if isinstance(cfg, dict):
                return cfg, False
            return {'_comment': CONFIG_COMMENT, 'entries': []}, False
        except Exception:
            return {'_comment': CONFIG_COMMENT, 'entries': []}, False
    atomic_write(CONFIG_PATH, {'_comment': CONFIG_COMMENT, 'entries': []})
    return {'_comment': CONFIG_COMMENT, 'entries': []}, True


def part_estimate_index(sets_doc):
    """set slug -> {part slug: (unit_price, need_units, price_src)} from sets[] rows."""
    idx = {}
    for row in (sets_doc.get('sets') or []):
        if not isinstance(row, dict) or not row.get('slug'):
            continue
        parts = {}
        for m in (row.get('missing') or []):
            if isinstance(m, dict):
                slug = m.get('slug')
                if slug:
                    parts[slug] = (as_num(m.get('unit_price')), int(as_num(m.get('missing')) or 1),
                                   m.get('price_src'))
            elif isinstance(m, str):
                parts[m] = (None, 1, None)
        idx[row['slug']] = parts
    return idx


def missing_of(row):
    """(slug, need_units) for a target row: 'missing' or 'need', dicts or bare strings."""
    out = []
    for key in ('missing', 'need'):
        for m in (row.get(key) or []):
            if isinstance(m, dict):
                slug = m.get('slug')
                if slug:
                    out.append((slug, max(1, int(as_num(m.get('missing')) or as_num(m.get('need')) or 1)),
                                as_num(m.get('unit_price')), m.get('price_src')))
            elif isinstance(m, str):
                out.append((m, 1, None, None))
    # de-dup while keeping the first (richest) occurrence
    seen, uniq = set(), []
    for slug, qty, price, src in out:
        if slug not in seen:
            seen.add(slug)
            uniq.append((slug, qty, price, src))
    return uniq


def build_suggested(sets_doc):
    """Auto-derive wishlist rows from top_targets with action COMPLETE / COMPLETE_MAYBE."""
    idx = part_estimate_index(sets_doc)
    rows, merged = [], {}
    for t in (sets_doc.get('top_targets') or []):
        if not isinstance(t, dict) or t.get('action') not in TARGET_ACTIONS:
            continue
        slug = t.get('slug')
        if not slug:
            continue
        miss = missing_of(t)
        if not miss:
            continue
        cost_est = as_num(t.get('cost_est')) or 0.0
        split = cost_est / len(miss)
        per_set = idx.get(slug) or {}
        for part, qty, price, src in miss:
            got = per_set.get(part) or (None, None, None)
            est, units, psrc = (got[0], got[1], got[2])
            basis = 'part_est'
            if est is None:
                est, basis, psrc = (price, 'part_est', src) if price is not None else (split, 'set_split', None)
            mp = int(math.ceil(est)) if basis == 'part_est' else int(round(est))
            row = dict(slug=part, name=None, max_price=max(1, mp), qty=max(1, int(units or qty or 1)),
                       source='suggested', set=slug, set_name=t.get('name') or slug,
                       set_action=t.get('action'), set_cost_est=round(cost_est, 1),
                       max_price_basis=basis, est_price=round(est, 1) if est is not None else None,
                       est_src=psrc, set_split=round(split, 1), from_sets=[slug])
            if part in merged:                       # two sets wanting the same part: keep the richer cap
                cur = merged[part]
                cur['max_price'] = max(cur['max_price'], row['max_price'])
                cur['qty'] = max(cur['qty'], row['qty'])
                cur['from_sets'].append(slug)
                if row['est_price'] is not None:
                    cur['max_price_basis'] = row['max_price_basis']
                    cur['est_price'], cur['est_src'] = row['est_price'], row['est_src']
                continue
            merged[part] = row
            rows.append(row)
    return rows


def parse_config(cfg, catalog_names):
    """Validated config rows + warnings. Bad rows are reported, never silently dropped."""
    rows, warns = [], []
    entries = cfg.get('entries')
    if entries is None:
        warns.append('no "entries" list in config; treated as empty')
        return rows, warns
    if not isinstance(entries, list):
        warns.append('"entries" is %s, expected a list; ignored' % type(entries).__name__)
        return rows, warns
    seen = set()
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            warns.append('entry #%d is %s, expected an object' % (i, type(e).__name__))
            continue
        slug = e.get('slug')
        if not isinstance(slug, str) or not slug.strip():
            warns.append('entry #%d has no usable slug' % i)
            continue
        slug = slug.strip()
        mp = as_num(e.get('max_price'))
        if mp is None or mp <= 0:
            warns.append('%s: max_price missing or <= 0; row skipped' % slug)
            continue
        qty = as_num(e.get('qty'))
        qty = 1 if qty is None or qty < 1 else int(qty)
        if slug in seen:
            warns.append('%s: duplicate config row; first one kept' % slug)
            continue
        seen.add(slug)
        rows.append(dict(slug=slug, name=catalog_names.get(slug) or slug, max_price=int(math.ceil(mp)),
                         qty=qty, source='config', max_price_basis='user', set=None, from_sets=[],
                         user_max_price=mp))
    return rows, warns


class Fetcher(object):
    """Live sell-floor lookup with hard 0.4s+ spacing and offline trip-switch."""

    def __init__(self, offline, catalog):
        self.offline = bool(offline)
        self.catalog = catalog
        self.last = 0.0
        self.calls = 0
        self.errors = []
        self.cache = {}
        self.status = {}
        self.ids = {(i.get('slug')): i.get('id') for i in (catalog or []) if isinstance(i, dict)}

    def _sleep(self):
        gap = SPACING - (time.time() - self.last)
        if gap > 0:
            time.sleep(gap)
        self.last = time.time()

    def floor(self, slug):
        if slug in self.cache:
            return self.cache[slug]
        if self.offline:
            self.status[slug] = 'offline'
            return None
        if self.calls >= MAX_LIVE_FETCHES:
            self.status[slug] = 'fetch_cap'
            return None
        ref = self.ids.get(slug) or slug
        res = None
        for attempt in range(3):
            self._sleep()
            self.calls += 1
            try:
                req = urllib.request.Request(TOP_URL % ref,
                                             headers={'User-Agent': UA, 'Accept': 'application/json'})
                with urllib.request.urlopen(req, timeout=25) as r:
                    data = json.loads(r.read().decode())['data']
                sell = [o for o in (data.get('sell') or []) if o.get('visible')]
                buy = [o for o in (data.get('buy') or []) if o.get('visible')]
                res = dict(floor=min((o['platinum'] for o in sell), default=None),
                           wtb=max((o['platinum'] for o in buy), default=None),
                           n_sell=len(sell), n_buy=len(buy), live=True)
                self.status[slug] = 'ok' if res['floor'] is not None else 'empty'
                break
            except urllib.error.HTTPError as e:
                if e.code in RETRY_CODES and attempt < 2:
                    time.sleep(2.0 + 2.0 * attempt)
                    continue
                self.errors.append('%s: http %s' % (slug, e.code))
                self.status[slug] = 'http_%d' % e.code
                break
            except Exception as e:                      # DNS/timeout/refused -> stop probing
                self.errors.append('%s: %s' % (slug, type(e).__name__))
                self.status[slug] = 'error'
                self.offline = True
                break
        self.cache[slug] = res
        return res


def resolve_budget(limits, state, history):
    """plat + trades_left with fallbacks; never invent a number that no source supports.

    Prefers trader_limits.json; falls back to trader_state.json, then the last known plat in
    plat_history.json. Unusable values stay None and are reported as warnings.
    """
    warn, src = [], 'trader_limits'
    plat, tr = as_num(limits.get('plat')), as_num(limits.get('trades_left'))
    age = None
    if plat and plat > 0:
        age = time.time() - (as_num(limits.get('ts')) or time.time())
    else:
        sp, st = as_num(state.get('plat')), as_num(state.get('trades_left'))
        if sp and sp > 0:
            plat, src = sp, 'trader_state'
            if tr is None:
                tr = st
            age = time.time() - (as_num(state.get('ts')) or time.time())
            warn.append('trader_limits.json plat is %s (status %s); fell back to trader_state.json'
                        % (limits.get('plat'), limits.get('status')))
        else:
            hist = [h for h in (history or []) if isinstance(h, dict) and as_num(h.get('plat'))]
            if hist:
                last = max(hist, key=lambda h: as_num(h.get('ts')) or 0)
                plat, src = as_num(last.get('plat')), 'plat_history'
                age = time.time() - (as_num(last.get('ts')) or time.time())
                warn.append('no live plat in trader_limits/trader_state; using last plat_history '
                            'entry (ts %s)' % last.get('ts'))
            else:
                src = 'none'
                warn.append('no usable plat figure in trader_limits/trader_state/plat_history; '
                            'budget cannot be checked this run')
    if tr is None or tr < 0:
        warn.append('trades_left unknown; plan not capped by the trade allowance')
    return (int(plat) if plat and plat > 0 else None,
            (int(tr) if isinstance(tr, (int, float)) and tr >= 0 else None), src, age, warn)


def status_for(floor, max_price):
    if floor is None:
        return 'UNKNOWN'
    if floor <= max_price:
        return 'BUY_NOW'
    if floor <= max_price * CLOSE_FACTOR:
        return 'CLOSE'
    return 'WAIT'


def compute(rows, prices, fetcher):
    """Attach floor / wtb / status / ratio / budget cost to each row."""
    out = []
    for r in rows:
        slug = r['slug']
        q = prices.get(slug) or {}
        floor, src, note = as_num(q.get('wts')), 'prices_json', None
        wtb = as_num(q.get('wtb'))
        n_sell = q.get('n_sell')
        if floor is None:
            note = 'cached_floor_null' if q else 'not_cached'
            live = fetcher.floor(slug)
            st = fetcher.status.get(slug)
            if live and live.get('floor') is not None:
                floor, wtb, n_sell, src, note = live['floor'], live.get('wtb'), live.get('n_sell'), 'live', None
            elif st == 'offline':
                src, note = 'none', 'offline'
            elif st == 'fetch_cap':
                src, note = 'none', 'fetch_cap'
            elif st == 'empty':
                src, note = 'none', 'no_live_sell_orders'
            elif st and str(st).startswith('http_'):
                src, note = 'none', st
            else:
                src, note = 'none', 'fetch_failed'
        mp, qty = int(r['max_price']), int(r.get('qty') or 1)
        cost = qty * mp
        row = dict(r)
        row.update(floor=(int(floor) if floor is not None else None), floor_src=src, floor_note=note,
                   wtb=(int(wtb) if wtb is not None else None), n_sell=n_sell,
                   status=status_for(floor, mp), unit_cost=mp, budget_cost=cost,
                   ratio=(round(mp / float(floor), 3) if floor else None),
                   in_catalog=bool(r.get('name') and r['name'] != slug))
        out.append(row)
    return out


def greedy_plan(buy_now, plat, trades_left):
    """One unit per trade, biggest max_price/floor ratio first, capped by plat and trades."""
    units = []
    for r in buy_now:
        for _ in range(int(r.get('qty') or 1)):
            units.append(r)
    trades_cap = int(trades_left) if isinstance(trades_left, (int, float)) and trades_left > 0 else None
    if plat is None or plat <= 0:                     # budget unknown -> do not guess a plan
        return ([], [dict(slug=r['slug'], name=r['name'], qty=int(r.get('qty') or 1),
                          cost=r['budget_cost'], floor=r['floor'], max_price=r['max_price'],
                          reason='budget_unknown') for r in buy_now], 0, 0, trades_cap)
    units.sort(key=lambda r: (-(r['max_price'] / float(max(r['floor'], 0.01))), r['floor'], r['slug']))
    spent, taken, per_slug = 0, [], {}
    for u in units:
        if spent + u['unit_cost'] > plat:
            continue
        if trades_cap is not None and len(taken) >= trades_cap:
            break
        spent += u['unit_cost']
        taken.append(u)
        per_slug.setdefault(u['slug'], {'slug': u['slug'], 'name': u['name'], 'qty': 0, 'cost': 0,
                                        'max_price': u['max_price'], 'floor': u['floor'],
                                        'status': u['status'], 'ratio': u['ratio'],
                                        'source': u['source'], 'set': u.get('set')})
        per_slug[u['slug']]['qty'] += 1
        per_slug[u['slug']]['cost'] += u['unit_cost']
    plan = sorted(per_slug.values(), key=lambda p: (-p['ratio'], p['slug']))
    got = {}
    for u in taken:
        got[u['slug']] = got.get(u['slug'], 0) + 1
    unaff = []
    for r in buy_now:
        left = int(r.get('qty') or 1) - got.get(r['slug'], 0)
        if left > 0:
            reason = ('plat_exhausted' if spent + left * r['unit_cost'] > plat
                      else 'trades_exhausted' if trades_cap is not None else 'not_selected')
            unaff.append(dict(slug=r['slug'], name=r['name'], qty=left, cost=left * r['unit_cost'],
                              floor=r['floor'], max_price=r['max_price'], reason=reason))
    return plan, unaff, spent, len(taken), trades_cap


def main():
    started = time.time()
    offline = '--offline' in sys.argv
    sets_doc = load('sets.json') or {}
    prices = load('prices.json') or {}
    limits = load('trader_limits.json') or {}
    catalog = (load('wfm_items_v2.json') or {}).get('data') or []
    names = {i['slug']: (((i.get('i18n') or {}).get('en') or {}).get('name') or i['slug'])
             for i in catalog if isinstance(i, dict) and i.get('slug')}

    cfg, cfg_created = ensure_config()
    cfg_rows, cfg_warns = parse_config(cfg, names)
    suggested = build_suggested(sets_doc)
    for r in suggested:
        r['name'] = names.get(r['slug']) or r['slug']

    fetcher = Fetcher(offline, catalog)
    entries = compute(cfg_rows, prices, fetcher)
    suggested = compute(suggested, prices, fetcher)

    # union for budgeting: config rows win over suggested rows for the same slug
    cfg_slugs = {r['slug'] for r in entries}
    for r in suggested:
        r['overridden_by_config'] = r['slug'] in cfg_slugs
    wishlist = list(entries) + [r for r in suggested if r['slug'] not in cfg_slugs]

    plat, trades_left, plat_src, plat_age, budget_warns = resolve_budget(
        limits, load('trader_state.json') or {}, load('plat_history.json') or [])
    buy_now = [r for r in wishlist if r['status'] == 'BUY_NOW']
    budget_needed = sum(r['budget_cost'] for r in buy_now)
    plan, unaff, spent, units, trades_cap = greedy_plan(buy_now, plat, trades_left)

    counts = {s: len([r for r in wishlist if r['status'] == s]) for s in STATUSES}
    summary = dict(
        budget_needed=budget_needed,
        budget_available=(plat if plat is not None else None),
        buy_now_count=len(buy_now),
        affordable_subset_cost=spent,
        trades_needed=units,
        entries_total=len(entries), suggested_total=len(suggested), wishlist_total=len(wishlist),
        close_count=counts['CLOSE'], wait_count=counts['WAIT'], unknown_count=counts['UNKNOWN'],
        budget_leftover=(plat - spent if plat is not None else None),
        budget_source=plat_src, plat_age_min=(round(plat_age / 60.0, 1) if plat_age is not None else None),
        trades_left=trades_left, trades_used=units, budget_warnings=budget_warns,
        trades_capped=bool(trades_cap is not None and units >= trades_cap),
        affordable_units=units, unaffordable_count=sum(u['qty'] for u in unaff),
        plan_items=len(plan), overrides=len(cfg_slugs & {r['slug'] for r in suggested}),
        status=limits.get('status'))

    checks = dict(
        statuses_known=all(r['status'] in STATUSES for r in wishlist),
        config_entries_match=len(entries) == len(cfg_rows),
        suggested_match=len(suggested) == len(build_suggested(sets_doc)),
        unique_slugs=len({r['slug'] for r in wishlist}) == len(wishlist),
        budget_matches_buy_now=budget_needed == sum(r['qty'] * r['max_price']
                                                   for r in wishlist if r['status'] == 'BUY_NOW'),
        plan_within_budget=plat is None or spent <= plat,
        plan_empty_when_budget_unknown=(plat is not None or not plan),
        plan_qty_within_needed=all(p['qty'] <= max((r['qty'] for r in buy_now if r['slug'] == p['slug']),
                                                   default=0) for p in plan),
        plan_cost_matches=spent == sum(p['cost'] for p in plan),
        trades_within_limit=trades_cap is None or units <= trades_cap,
        no_negative_qty=all(r['qty'] >= 1 and r['max_price'] >= 1 for r in wishlist))

    out = dict(
        version=1,
        generated=time.strftime('%Y-%m-%d %H:%M'),
        generated_iso=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        source='sets.json top_targets + wishlist_config.json; floors from prices.json, live v2 top-order '
               'fallback (offline=%s, live_calls=%d)' % (offline or fetcher.offline, fetcher.calls),
        config_path='data/wishlist_config.json',
        config=dict(created=cfg_created, entries=len(cfg_rows), raw_entries=len(cfg.get('entries') or []),
                    warnings=cfg_warns),
        accounts=dict(plat=plat, plat_source=plat_src, trades_left=trades_left,
                      account=limits.get('account') or (load('trader_state.json') or {}).get('account'),
                      limits_status=limits.get('status'), warnings=budget_warns),
        entries=entries,
        suggested=suggested,
        wishlist=wishlist,
        affordable_plan=plan,
        unaffordable=unaff,
        summary=summary,
        network=dict(offline=bool(offline or fetcher.offline), live_calls=fetcher.calls,
                     errors=fetcher.errors[:8], fetched=len(fetcher.cache)),
        assumptions=['BUY_NOW = floor <= max_price; CLOSE = floor <= max_price * 1.25; else WAIT',
                     'max_price for a suggested part = ceil(per-part unit_price from sets.json); if the '
                     'part has no per-part estimate, round(set cost_est / missing parts), min 1',
                     'suggested rows come from top_targets with action COMPLETE or COMPLETE_MAYBE',
                     'config rows override suggested rows for the same slug',
                     'budget_needed sums qty * max_price over BUY_NOW rows only',
                     'affordable plan = greedy knapsack by max_price/floor ratio, one unit per trade, '
                     'inside the plat budget and the trade allowance',
                     'floors missing from prices.json are fetched live; if the network is down they are '
                     'reported as UNKNOWN rather than estimated',
                     'data/wishlist_config.json is created once and never rewritten'],
        self_check=checks)

    atomic_write(OUT_PATH, out)

    failed = [k for k, v in checks.items() if not v]
    sx = fetcher.cache
    print('wishlist.py -> data/wishlist.json   %s   (%.1fs)' % (out['generated'], time.time() - started))
    print('config: data/wishlist_config.json %s | rows %d (%d raw)%s'
          % ('CREATED (empty entries)' if cfg_created else 'existing, untouched', len(cfg_rows),
             out['config']['raw_entries'],
             ' | warnings: ' + '; '.join(cfg_warns[:3]) if cfg_warns else ''))
    print('rows: config %d | suggested %d | wishlist union %d (overrides %d)'
          % (summary['entries_total'], summary['suggested_total'], summary['wishlist_total'],
             summary['overrides']))
    print('floors: %d from prices.json | %d live | %d unavailable | %s'
          % (len([r for r in wishlist if r['floor_src'] == 'prices_json']),
             len([r for r in wishlist if r['floor_src'] == 'live']),
             len([r for r in wishlist if r['floor'] is None]),
             'OFFLINE' if offline or fetcher.offline else 'online'))
    print('status: BUY_NOW %d | CLOSE %d | WAIT %d | UNKNOWN %d'
          % (summary['buy_now_count'], summary['close_count'], summary['wait_count'],
             summary['unknown_count']))
    print('budget: needed %dp vs available %s (plat, src=%s) | trades_left %s | plan cost %dp / %d units'
          % (budget_needed, plat if plat is not None else 'UNKNOWN', plat_src,
             trades_left if trades_left is not None else 'UNKNOWN', spent, units))
    for w in budget_warns:
        print('   budget note: %s' % w)
    print('plan (%d items)%s:' % (len(plan), '  [trades capped]' if summary['trades_capped'] else ''))
    for p in plan:
        print('   %-38s x%d cost=%3dp floor=%-4s cap=%-4s ratio=%s from=%s'
              % (p['slug'], p['qty'], p['cost'], p['floor'], p['max_price'], p['ratio'], p['source']))
    if unaff:
        print('unaffordable/left over (%d units): %s'
              % (sum(u['qty'] for u in unaff),
                 ', '.join('%s x%d (%s)' % (u['slug'], u['qty'], u['reason']) for u in unaff[:6])))
    print('samples (5 wishlist rows):')
    sample = (entries + suggested)[:5] or wishlist[:5]
    for r in sample:
        print('   %-38s %-9s floor=%-5s cap=%-4s x%d cost=%-4d src=%-12s set=%s'
              % (r['slug'], r['status'], r['floor'], r['max_price'], r['qty'], r['budget_cost'],
                 r['floor_src'], r.get('set') or '-'))
    print('self-check: %s' % ('OK (%d checks)' % len(checks) if not failed else 'FAILED: ' + ', '.join(failed)))
    if fetcher.errors:
        print('network errors: %s' % ', '.join(fetcher.errors[:4]))
    return out


if __name__ == '__main__':
    main()
