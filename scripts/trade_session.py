"""Trading Session — the persisted loop state (recommend → contact → confirm → next).

One module owns everything the Trading Session workflow keeps between requests:

    data/trade_session.json
      session   the live session: its queue, where the user is in it, what it has earned
      pending   trades that have been whispered (CONTACTED) and are waiting on reconciliation
      confirmed the trade ids already written, so a retry can never double-log a trade

The doc behind it is docs/trading-session-workflow.md; the map of where each piece plugs into the
existing app is design/_session/implementation-map.md.

Design rules this file follows (and the tests pin):

* stdlib only, no import-time side effects, no network. Every payload is **injected**, so tests can
  drive the whole workflow with fixtures and never need a data/ directory.
* Writes are atomic (tmp + os.replace) and a corrupt state file is moved aside, never overwritten -
  this store carries money and inventory history.
* The queue is built from the payloads the app already produces (trader_plan.json, sell_advisor.json,
  report.json, run_queue.json). Prices, ranks and buyers are never recomputed here, so Home, Trade >
  Orders and the Session screen cannot disagree.
* Rank-aware: a queue row carries the rank the recommendation was made for, and a live buyer is only
  attached when the ranks agree. A rank-10 stack is never paired with a rank-0 order.
* Nothing in here decides that the user sold something. Reconciliation only *proposes*; the user
  confirms; confirmation is one idempotent transaction (see confirm()).

Stage map (docs/trading-session-workflow.md §15): this module grows in stages 2, 4 and 5 -
the session + queue first, then the reconciliation proposal, then the canonical confirm.
"""
import hashlib
import json
import os
import time

FILE = 'trade_session.json'
VERSION = 1

# The six states the workflow uses. Deliberately small (spec §3: no enterprise state machine).
READY = 'READY'
CONTACTED = 'CONTACTED'
POSSIBLE = 'POSSIBLE MATCH'
COMPLETED = 'COMPLETED'
SKIPPED = 'SKIPPED'
HELD = 'HELD'
STATES = (READY, CONTACTED, POSSIBLE, COMPLETED, SKIPPED, HELD)

QUEUE_LIMIT = 12          # a session queue is a session's worth of work, not the whole plan
STALE_PENDING_S = 6 * 3600  # a CONTACTED trade older than this is flagged, never auto-resolved
PENDING_KEEP = 40         # finished/abandoned pending rows kept for recovery


# --------------------------------------------------------------------------- io
def jload(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _path(data_dir):
    return os.path.join(data_dir, FILE)


def _atomic_write(path, doc):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def load(data_dir):
    """The stored doc, or a fresh one. A corrupt/partial file is quarantined, not clobbered."""
    path = _path(data_dir)
    doc = jload(path)
    if isinstance(doc, dict):
        return normalise(doc)                       # partly shaped is fine; normalise() coerces it
    if doc is not None or os.path.exists(path):
        # unparseable, or from a shape we do not know (a list, a bare string): keep it, start clean
        try:
            stamp = time.strftime('%Y%m%d-%H%M%S')
            os.replace(path, path + '.corrupt-' + stamp)
        except Exception:
            pass
    return empty()


def save(data_dir, doc):
    """Atomic write. Returns the doc so callers can chain."""
    doc['version'] = VERSION
    doc['updated_ts'] = int(time.time())
    _atomic_write(_path(data_dir), normalise(doc))
    return doc


# --------------------------------------------------------------------------- doc shape
def empty(now=None):
    return {'version': VERSION, 'session': None, 'pending': [], 'confirmed': [],
            'updated_ts': int(now or time.time())}


def normalise(doc):
    """Coerce anything half-formed into the documented shape (never raises)."""
    if not isinstance(doc, dict):
        return empty()
    out = {'version': VERSION, 'session': None, 'pending': [], 'confirmed': [],
           'updated_ts': int(doc.get('updated_ts') or time.time())}
    s = doc.get('session')
    if isinstance(s, dict):
        s = dict(s)
        s.setdefault('id', new_session_id(s.get('started_ts') or time.time()))
        s['started_ts'] = int(s.get('started_ts') or time.time())
        s['ended_ts'] = int(s['ended_ts']) if s.get('ended_ts') else None
        s['cursor'] = max(0, int(s.get('cursor') or 0))
        q = [r for r in (s.get('queue') or []) if isinstance(r, dict) and r.get('slug')]
        for r in q:
            r['state'] = r.get('state') if r.get('state') in STATES else READY
            r['qty'] = max(1, int(r.get('qty') or 1))
            r['rank'] = int(r['rank']) if isinstance(r.get('rank'), int) else r.get('rank')
        s['queue'] = q
        if s['cursor'] >= len(q):
            s['cursor'] = max(0, len(q) - 1)
        t = s.get('totals') if isinstance(s.get('totals'), dict) else {}
        s['totals'] = {'trades': int(t.get('trades') or 0),
                       'earned_plat': round(float(t.get('earned_plat') or 0), 2),
                       'skipped': int(t.get('skipped') or 0),
                       'held': int(t.get('held') or 0)}
        s['done'] = [d for d in (s.get('done') or []) if isinstance(d, dict)]
        s['plat_start'] = s.get('plat_start') if isinstance(s.get('plat_start'), (int, float)) else None
        out['session'] = s
    out['pending'] = [p for p in (doc.get('pending') or []) if isinstance(p, dict)][-PENDING_KEEP:]
    for p in out['pending']:
        p['state'] = p.get('state') if p.get('state') in STATES else CONTACTED
    out['confirmed'] = [str(x) for x in (doc.get('confirmed') or []) if x][-500:]
    return out


def new_session_id(now):
    return 's-%s-%04x' % (time.strftime('%Y%m%d-%H%M', time.localtime(now)),
                          int(now * 1000) & 0xFFFF)


def row_key(slug, rank):
    return '%s#%s' % (slug, 'r%s' % rank if rank is not None else 'any')


def _int(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- queue
def _rank_of(row):
    """The rank a recommendation was made for. report rows use lane_rank, plans use 'rank N'."""
    if not isinstance(row, dict):
        return None
    if isinstance(row.get('lane_rank'), int):
        return row['lane_rank']
    if isinstance(row.get('rank'), int):
        return row['rank']
    lane = row.get('lane')
    if isinstance(lane, str) and lane.startswith('rank '):
        tail = lane[5:].strip()
        if tail.isdigit():
            return int(tail)
    return None


def _advisor_of(advisor, slug):
    items = advisor.get('items') if isinstance(advisor, dict) else None
    if isinstance(items, dict):
        rec = items.get(slug)
        if isinstance(rec, dict):
            return rec
    if isinstance(items, list):
        for rec in items:
            if isinstance(rec, dict) and rec.get('item') == slug:
                return rec
    return {}


def _report_of(report, slug):
    for key in ('sell_now', 'patient'):
        for row in (report.get(key) or []) if isinstance(report, dict) else []:
            if isinstance(row, dict) and row.get('slug') == slug:
                return row
    return {}


def _runqueue_of(runqueue, slug):
    """The live buyer row for a slug, if the run queue names one (it carries no rank of its own)."""
    if not isinstance(runqueue, dict):
        return None
    for row in (runqueue.get('queue') or []):
        if isinstance(row, dict) and row.get('slug') == slug and row.get('buyer'):
            return row
    return None


def _buyer(row, status_summary):
    if not row:
        return None
    status = str(row.get('buyer_status') or '').strip().lower() or None
    return {'user': str(row.get('buyer') or '').strip()[:32],
            'status': status,
            'qty': _int(row.get('qty')),
            'plat': _int(row.get('buy_price')),
            'my_price': _int(row.get('my_price')),
            'why': str(row.get('why') or '')[:160],
            'summary': status_summary}


def _why(report_row, adv, buyer, runqueue):
    """Only facts that exist. Anything missing is omitted, never guessed (spec §7)."""
    out = {}
    safe = _int(report_row.get('sellable_count'))
    if safe is None:
        safe = _int(adv.get('sellable'))
    if safe:
        out['safe_copies'] = safe
    vol = _int(report_row.get('vol48'))
    if vol is None:
        vol = _int(adv.get('vol48'))
    if vol is not None:
        out['sales_48h'] = vol
    try:
        out['buyers_online'] = int((runqueue.get('summary') or {}).get('ingame') or 0) + \
                               int((runqueue.get('summary') or {}).get('online') or 0)
    except Exception:
        pass
    med = report_row.get('med')
    if med is None:
        med = adv.get('median')
    if med is not None:
        out['median'] = round(float(med), 1)
    pct = adv.get('price_trend_pct')
    if isinstance(pct, (int, float)):
        out['week_pct'] = round(float(pct), 1)
    if adv.get('liquidity'):
        out['liquidity'] = str(adv['liquidity'])
    if isinstance(report_row.get('n_buy'), int):
        out['buy_orders'] = report_row['n_buy']
    if isinstance(report_row.get('n_sell'), int):
        out['sell_orders'] = report_row['n_sell']
    if adv.get('lane_rank') is not None:
        out['rank'] = adv['lane_rank']
    if buyer and buyer.get('plat') and buyer.get('my_price'):
        out['buyer_pays'] = buyer['plat']
    reasons = [str(x)[:120] for x in (adv.get('reasons') or []) if isinstance(x, str)][:4]
    if reasons:
        out['reasons'] = reasons
    return out


def _confidence(why):
    """High/Medium/Low, and *why* — never an unexplained score (spec §7)."""
    notes = []
    vol = why.get('sales_48h') or 0
    buyers = why.get('buyers_online') or 0
    buys = why.get('buy_orders') or 0
    if buyers >= 1:
        notes.append('%d buyer%s live' % (buyers, '' if buyers == 1 else 's'))
    if vol >= 10:
        notes.append('%d sales in 48h' % vol)
    elif vol:
        notes.append('%d sale%s in 48h' % (vol, '' if vol == 1 else 's'))
    if buys >= 1:
        notes.append('%d buy order%s' % (buys, '' if buys == 1 else 's'))
    if buyers >= 1 and vol >= 10:
        level = 'high'
    elif buys >= 1 or vol >= 3:
        level = 'medium'
    else:
        level = 'low'
    return {'level': level, 'reasons': notes}


def build_queue(plan, advisor, report, runqueue, limit=QUEUE_LIMIT):
    """Session queue from the payloads the app already produces. Returns [] when nothing qualifies.

    Order: the listing plan's own order first (that is the engine's recommendation order, and the
    order Home already uses), then the advisor's ranked list for slugs the plan does not mention.
    A row is only queued when it has a price and at least one sellable copy.
    """
    plan = plan if isinstance(plan, dict) else {}
    advisor = advisor if isinstance(advisor, dict) else {}
    report = report if isinstance(report, dict) else {}
    runqueue = runqueue if isinstance(runqueue, dict) else {}
    rows, seen = [], set()

    def add(slug, name, qty, price, rank, source):
        key = row_key(slug, rank)
        if key in seen or not slug:
            return
        rep = _report_of(report, slug)
        adv = _advisor_of(advisor, slug)
        safe = _int(rep.get('sellable_count'))
        if safe is None:
            safe = _int(adv.get('sellable'))
        qty = _int(qty) or _int(adv.get('recommended_quantity')) or 1
        if safe is not None:
            qty = max(0, min(qty, safe))
        price = _int(price) or _int(adv.get('recommended_price')) or _int(rep.get('lane_ask')) \
            or _int(rep.get('wts'))
        if not price or qty < 1:
            return
        rq = _runqueue_of(runqueue, slug)
        buyer = _buyer(rq, runqueue.get('summary'))
        rq_rank = _rank_of(rq) if rq else None
        mismatch = None
        if buyer and rq_rank is not None and rank is not None and rq_rank != rank:
            buyer = None                      # never pair a rank-10 stack with a rank-0 order
            mismatch = 'buyer is for rank %s' % rq_rank
        why = _why(rep, adv, buyer, runqueue)
        if mismatch:
            why['rank_mismatch'] = mismatch
        rows.append({'slug': slug, 'name': name or rep.get('name') or adv.get('name') or slug,
                     'rank': rank, 'qty': qty, 'price': price, 'cat': rep.get('cat') or adv.get('cat'),
                     'buyer': buyer, 'why': why, 'confidence': _confidence(why),
                     'source': source, 'state': READY, 'added_ts': int(time.time())})
        seen.add(key)

    for row in (plan.get('plan') or []):
        if not isinstance(row, dict):
            continue
        add(row.get('slug'), row.get('name'), row.get('per_trade') or row.get('qty'),
            row.get('price'), _rank_of(row), 'plan')
    ranked = advisor.get('ranked')
    if isinstance(ranked, list):
        for slug in ranked:
            adv = _advisor_of(advisor, slug)
            if str(adv.get('recommendation') or '').lower() not in ('list', 'sell'):
                continue
            add(slug, adv.get('name'), adv.get('recommended_quantity'),
                adv.get('recommended_price'), _rank_of(adv), 'advisor')
    return rows[:max(1, int(limit))]


# --------------------------------------------------------------------------- session lifecycle
def start(doc, queue, now=None, account=None, plat_start=None, session_id=None):
    """Open a session over `queue`. Returns (doc, started_bool)."""
    now = int(now or time.time())
    doc = normalise(doc)
    if doc.get('session'):
        return doc, False                     # one live session at a time; never silently replace it
    rows = []
    for r in queue or []:
        if not isinstance(r, dict) or not r.get('slug'):
            continue
        row = dict(r)
        row.setdefault('state', READY)
        row['added_ts'] = int(row.get('added_ts') or now)
        rows.append(row)
    doc['session'] = {'id': session_id or new_session_id(now), 'started_ts': now, 'ended_ts': None,
                      'account': account, 'cursor': 0, 'plat_start': plat_start,
                      'queue': rows, 'done': [],
                      'totals': {'trades': 0, 'earned_plat': 0, 'skipped': 0, 'held': 0}}
    return doc, True


def focus(doc, index=None, slug=None, now=None):
    """Point the session at a queue row. Returns the row (or None)."""
    s = (doc or {}).get('session') or {}
    q = s.get('queue') or []
    if not q:
        return None
    if isinstance(index, int) and 0 <= index < len(q):
        s['cursor'] = index
    elif slug:
        for i, r in enumerate(q):
            if r.get('slug') == slug:
                s['cursor'] = i
                break
    return q[min(s.get('cursor') or 0, len(q) - 1)]


def set_state(doc, slug, rank=None, state=SKIPPED, note='', now=None):
    """SKIPPED / HELD / READY on a queue row, and the matching session counter. Idempotent."""
    s = (doc or {}).get('session') or {}
    q = s.get('queue') or []
    hit = None
    for r in q:
        if r.get('slug') == slug and (rank is None or r.get('rank') == rank):
            hit = r
            break
    if hit is None:
        return None
    was = hit.get('state')
    if state not in STATES:
        return None
    hit['state'] = state
    if note:
        hit['note'] = str(note)[:160]
    t = s.setdefault('totals', {'trades': 0, 'earned_plat': 0, 'skipped': 0, 'held': 0})
    for key, val in (('skipped', SKIPPED), ('held', HELD)):
        if val == state and was != val:
            t[key] = int(t.get(key) or 0) + 1
        elif val == was and state != val:
            t[key] = max(0, int(t.get(key) or 0) - 1)
    if state == SKIPPED:
        advance(doc, now)                     # a skip moves the session on, a hold does not
    return hit


def advance(doc, now=None):
    """Move the cursor to the next row that still has work in it."""
    s = (doc or {}).get('session') or {}
    q = s.get('queue') or []
    i = int(s.get('cursor') or 0) + 1
    while i < len(q) and q[i].get('state') in (SKIPPED, HELD, COMPLETED):
        i += 1
    s['cursor'] = min(i, max(0, len(q) - 1))
    return s['cursor']


def end(doc, now=None):
    """Close the session but keep it (and its queue) as history."""
    s = (doc or {}).get('session')
    if not s:
        return None
    s['ended_ts'] = int(now or time.time())
    return s


def summary(doc, now=None, limits=None):
    """The live session summary (spec §6). Everything here is counted, nothing is invented."""
    now = int(now or time.time())
    s = (doc or {}).get('session')
    rows = (s or {}).get('queue') or []
    done = (s or {}).get('done') or []
    t = (s or {}).get('totals') or {}
    earned = round(float(t.get('earned_plat') or 0), 2)
    trades = int(t.get('trades') or 0)
    started = int((s or {}).get('started_ts') or now) if s else now
    ended = int(s['ended_ts']) if s and s.get('ended_ts') else None
    remaining = [r for r in rows if r.get('state') not in (COMPLETED, SKIPPED)]
    out = {'id': (s or {}).get('id'), 'active': bool(s and not s.get('ended_ts')),
           'started_ts': (s or {}).get('started_ts'), 'ended_ts': ended,
           'seconds': max(0, (ended or now) - started) if s else 0,
           'trades': trades, 'earned_plat': earned,
           'average_plat': round(earned / trades, 1) if trades else None,
           'skipped': int(t.get('skipped') or 0), 'held': int(t.get('held') or 0),
           'queue_total': len(rows), 'queue_remaining': len(remaining),
           'completed_rows': len(done) or trades,
           'plat_start': (s or {}).get('plat_start'),
           'best': (max(done, key=lambda d: d.get('plat') or 0) if done else None),
           'trades_left_today': None}
    if isinstance(limits, dict):
        left = limits.get('trades_left')
        out['trades_left_today'] = int(left) if isinstance(left, int) else None
        out['trade_cap'] = limits.get('trade_cap')
        out['plat_now'] = limits.get('plat')
    out['complete'] = bool(s) and not remaining
    return out


def payload(data_dir, plan=None, advisor=None, report=None, runqueue=None, limits=None, now=None):
    """The /api/session body: the session, its focus row, the pending trades and the summary."""
    now = int(now or time.time())
    doc = load(data_dir)
    s = doc.get('session')
    focus_row = focus(doc, now=now) if s else None
    pend = [p for p in doc.get('pending') if p.get('state') in (CONTACTED, POSSIBLE)]
    fresh = [p for p in pend if now - int(p.get('ts') or 0) <= STALE_PENDING_S]
    stale = [p for p in pend if now - int(p.get('ts') or 0) > STALE_PENDING_S]
    return {'ok': True, 'session': s, 'focus': focus_row,
            'focus_index': (s or {}).get('cursor'),
            'summary': summary(doc, now, limits),
            'pending': fresh, 'stale_pending': stale,
            'queue': (s or {}).get('queue') or [],
            'states': list(STATES),
            'suggested': build_queue(plan or {}, advisor or {}, report or {}, runqueue or {}) if not s else []}


def start_payload(data_dir, plan, advisor, report, runqueue, limits=None, limit=QUEUE_LIMIT, now=None):
    """POST /api/session/start — queue from the live recommendations, unless one is already open."""
    now = int(now or time.time())
    doc = load(data_dir)
    if doc.get('session'):
        return {'ok': True, 'started': False, 'reason': 'a session is already open',
                'session': doc['session'], 'summary': summary(doc, now, limits)}
    queue = build_queue(plan, advisor, report, runqueue, limit)
    if not queue:
        return {'ok': False, 'error': 'nothing to sell yet — run the trader plan first'}
    plat_start = None
    if isinstance(limits, dict) and isinstance(limits.get('plat'), (int, float)):
        plat_start = int(limits['plat'])
    account = (limits or {}).get('account') if isinstance(limits, dict) else None
    doc, started = start(doc, queue, now=now, account=account, plat_start=plat_start)
    save(data_dir, doc)
    return {'ok': True, 'started': started, 'session': doc['session'],
            'summary': summary(doc, now, limits)}
