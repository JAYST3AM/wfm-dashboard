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
    """Coerce anything half-formed into the documented shape (never raises).

    Returns a **new** dict: `load()` uses it. Functions that take a `doc` and are documented as
    mutating (contact/set_state/focus/end) mutate the caller's dict in place - if this were applied
    there instead, the caller would keep saving an untouched copy.
    """
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
    # the two order-book numbers the recommendation rides on, straight from the same report row:
    # wts is the lowest live sell, wtb the highest live buy (spec §1 price block)
    low = _int(report_row.get('wts'))
    if low:
        out['lowest_sell'] = low
    high = _int(report_row.get('wtb'))
    if high:
        out['highest_buy'] = high
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


# --------------------------------------------------------------------------- contact (the whisper)
def pending_id(slug, rank, buyer, now):
    raw = '%s|%s|%s|%d' % (slug, rank, buyer or '', int(now))
    return 'p-%d-%s' % (int(now * 1000), hashlib.sha1(raw.encode('utf-8')).hexdigest()[:6])


def contact(doc, slug, rank=None, qty=1, price=None, buyer=None, now=None,
            inv_before=None, plat_before=None, kind='sell', note=''):
    """A whisper went out: mark the queue row CONTACTED and open one pending trade.

    This is the only writer of a pending row, and it is called from exactly one place in the app -
    the /api/whisper success branch (spec §3). Whispering the same buyer again updates the row's
    timestamp instead of stacking a second one, so reconciliation never sees a phantom twin.
    """
    now = int(now or time.time())
    if not isinstance(doc, dict):                 # mutate the caller's doc: they save it, not us
        raise TypeError('contact() needs a doc dict (see trade_session.empty())')
    doc.setdefault('session', None)
    if not isinstance(doc.get('pending'), list):
        doc['pending'] = []
    row = None
    for r in ((doc.get('session') or {}).get('queue') or []):
        if r.get('slug') == slug and (rank is None or r.get('rank') == rank):
            row = r
            break
    key = (slug, rank, buyer)
    for p in doc['pending']:
        if (p.get('slug'), p.get('rank'), p.get('buyer')) == key and p.get('state') in (CONTACTED, POSSIBLE):
            p['ts'] = now
            p['note'] = str(note or p.get('note') or '')[:160]
            if row is not None:
                row['state'] = CONTACTED
            return p
    pend = {'id': pending_id(slug, rank, buyer, now), 'session_id': (doc.get('session') or {}).get('id'),
            'slug': slug, 'name': (row or {}).get('name') or slug, 'rank': rank,
            'qty': max(1, int(qty or (row or {}).get('qty') or 1)),
            'expected_plat': _int(price) or (row or {}).get('price'), 'buyer': buyer or None,
            'kind': kind, 'ts': now, 'state': CONTACTED,
            'inv_before': _int(inv_before), 'plat_before': _int(plat_before),
            'note': str(note or '')[:160]}
    doc['pending'].append(pend)
    doc['pending'] = doc['pending'][-PENDING_KEEP:]
    if row is not None:
        row['state'] = CONTACTED
        row['contacted_ts'] = now
    return pend


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


def inv_now_map(report, pending):
    """{row_key: copies owned now} for the stacks the pending trades are about.

    Same numbers the app renders (report.json sell_now/patient). A stack the report does not
    mention is simply absent - propose() then answers UNKNOWN rather than assuming a number.
    """
    out = {}
    for p in pending or []:
        if not isinstance(p, dict) or p.get('state') not in (CONTACTED, POSSIBLE):
            continue
        slug, rank = p.get('slug'), p.get('rank')
        key = row_key(slug, rank)
        if key in out:
            continue
        for field in ('sell_now', 'patient'):
            for row in ((report or {}).get(field) or []):
                if isinstance(row, dict) and row.get('slug') == slug and \
                        (rank is None or row.get('lane_rank') == rank):
                    n = _int(row.get('sellable_count'))
                    if n is not None:
                        out[key] = n
                    break
    return out


def payload(data_dir, plan=None, advisor=None, report=None, runqueue=None, limits=None, now=None):
    """The /api/session body: the session, its focus row, the pending trades and the summary."""
    now = int(now or time.time())
    doc = load(data_dir)
    s = doc.get('session')
    focus_row = focus(doc, now=now) if s else None
    pend = [p for p in doc['pending'] if p.get('state') in (CONTACTED, POSSIBLE)]
    fresh = [p for p in pend if now - int(p.get('ts') or 0) <= STALE_PENDING_S]
    stale = [p for p in pend if now - int(p.get('ts') or 0) > STALE_PENDING_S]
    plat_now = None
    if isinstance(limits, dict) and isinstance(limits.get('plat'), (int, float)):
        plat_now = int(limits['plat'])
    # The check rides the payload the panel already gets, so the screen shows what happened without
    # a second ask. It is a proposal either way - nothing here writes a trade (spec §4).
    try:
        checks = propose(pend, inv_now_map(report, pend), plat_now, now=now)
    except Exception:
        checks = {'proposals': [], 'counts': {}, 'needs_you': 0}
    return {'ok': True, 'session': s, 'focus': focus_row,
            'focus_index': (s or {}).get('cursor'),
            'summary': summary(doc, now, limits),
            'pending': fresh, 'stale_pending': stale,
            'proposals': checks['proposals'], 'checks': checks['counts'],
            'needs_you': checks['needs_you'],
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
# --------------------------------------------------------------------------- reconciliation (spec §4)
# The one place a pending trade is compared against what actually moved. It NEVER writes a trade:
# it returns a proposal the user confirms (or does not), because the repo already has a private,
# auto-confirming detector and the public loop is deliberately not that (docs/.../§4, §11).
EXACT = 'exact'
AMBIGUOUS = 'ambiguous'
NOTHING = 'none'
UNKNOWN = 'unknown'


def _evidence(*pairs):
    """Short player-language facts, 'label: value' - the UI shows them, it never invents them."""
    return ['%s: %s' % (label, value) for label, value in pairs if value is not None]


def propose(pending, inv_now, plat_now, now=None):
    """Propose what happened to each pending trade. -> {proposals: [...], counts: {...}}

    pending : the doc's pending rows (CONTACTED / POSSIBLE MATCH are the live ones)
    inv_now : {row_key(slug, rank): copies owned right now} - from the same report.json the app shows
    plat_now: platinum right now (the newest reading)
    """
    now = int(now or time.time())
    out, counts = [], {EXACT: 0, AMBIGUOUS: 0, NOTHING: 0, UNKNOWN: 0}
    for p in pending or []:
        if not isinstance(p, dict) or p.get('state') not in (CONTACTED, POSSIBLE):
            continue
        slug, rank = p.get('slug'), p.get('rank')
        qty = max(1, int(p.get('qty') or 1))
        expected = _int(p.get('expected_plat'))
        total = (expected or 0) * qty
        now_inv = _int((inv_now or {}).get(row_key(slug, rank)))
        before = _int(p.get('inv_before'))
        plat_before = _int(p.get('plat_before'))
        age = now - int(p.get('ts') or now)
        if before is None or plat_before is None or now_inv is None or plat_now is None:
            verdict, why = UNKNOWN, _evidence(('before', 'no snapshot'),
                                             ('now', 'platinum unknown' if plat_now is None else None))
            left = delta_plat = None
        else:
            left = before - now_inv                    # copies that left your inventory
            delta_plat = int(plat_now) - plat_before    # platinum that arrived
            if left <= 0 and delta_plat < (total or 1):
                verdict, why = NOTHING, _evidence(('copies left', 0), ('platinum', delta_plat))
            elif left >= qty and total and delta_plat >= total:
                verdict, why = EXACT, _evidence(('copies left', left), ('platinum', '+%d' % delta_plat),
                                                ('asked', total), ('extra', delta_plat - total or None))
            elif left >= qty and total and delta_plat < total:
                verdict, why = AMBIGUOUS, _evidence(('copies left', left),
                                                    ('platinum', '+%d' % delta_plat),
                                                    ('asked', total))
            elif 0 < left < qty:
                verdict, why = AMBIGUOUS, _evidence(('copies left', left), ('asked', qty))
            elif left <= 0 < delta_plat:
                verdict, why = AMBIGUOUS, _evidence(('copies left', 0), ('platinum', '+%d' % delta_plat),
                                                    ('that stack', 'untouched'))
            else:
                verdict, why = NOTHING, _evidence(('copies left', left), ('platinum', delta_plat))
        counts[verdict] += 1
        out.append({'verdict': verdict, 'pending_id': p.get('id'), 'slug': slug, 'name': p.get('name'),
                    'rank': rank, 'qty': qty, 'buyer': p.get('buyer'), 'age_s': age,
                    'expected_plat': expected, 'total_plat': total or None,
                    'inv_before': before, 'inv_now': now_inv,
                    'plat_before': plat_before, 'plat_now': _int(plat_now),
                    'copies_left': left, 'plat_delta': delta_plat, 'evidence': why,
                    'stale': age > STALE_PENDING_S,
                    'trade': trade_draft(p, plat=(expected or 0) * qty if verdict == EXACT else None)})
    order = {EXACT: 0, AMBIGUOUS: 1, UNKNOWN: 2, NOTHING: 3}
    out.sort(key=lambda r: (order.get(r['verdict'], 9), -(r['plat_delta'] or 0)))
    return {'proposals': out, 'counts': counts,
            'needs_you': counts[EXACT] + counts[AMBIGUOUS]}


def trade_draft(pending, plat=None, quote=None):
    """The record a confirmation would write, ready for confirm(). Never written by propose()."""
    slug, rank = pending.get('slug'), pending.get('rank')
    qty = max(1, int(pending.get('qty') or 1))
    plat = _int(plat)
    if plat is None:
        plat = (quote or {}).get('plat')
    draft = {'kind': 'sale', 'slug': slug, 'item': slug, 'name': pending.get('name'),
             'rank': rank, 'qty': qty, 'plat': plat or (pending.get('expected_plat') or 0) * qty,
             'user': pending.get('buyer'), 'buyer': pending.get('buyer'),
             'source': 'session', 'session_id': pending.get('session_id'),
             'pending_id': pending.get('id'), 'ts': int(pending.get('ts') or time.time())}
    draft['id'] = trade_id(draft)
    return draft


def trade_id(rec):
    """A stable id for a trade record: same content -> same id, so a retry cannot double-log it."""
    if isinstance(rec, dict) and rec.get('id'):
        return str(rec['id'])
    rec = rec or {}
    raw = '|'.join(str(rec.get(k) or '') for k in ('kind', 'slug', 'rank', 'qty', 'plat', 'user', 'ts'))
    return 't-%d-%s' % (int(rec.get('ts') or time.time()) * 1000,
                        hashlib.sha1(raw.encode('utf-8')).hexdigest()[:6])


# --------------------------------------------------------------------------- confirm (spec §5, §11)
# The one canonical completion path: one idempotent transaction that appends the trade, closes the
# pending record, moves the session on and lets the derived stores (Home today, sessions, inventory,
# ledger) recompute from the same event. Nothing else in the public tree writes a trade record with
# an id, and no other code path may mark a trade complete.
TRADE_LOG = 'trade_log.json'
KINDS = ('sale', 'purchase', 'listing', 'unlist', 'reprice', 'note')


def append_event(data_dir, rec):
    """Append one event to trade_log.json atomically, refusing a duplicate id.

    trade_log had four writers and none of them used tmp+os.replace (design/_session/audit-backend).
    Returns (record, created_bool).
    """
    path = os.path.join(data_dir, TRADE_LOG)
    hist = jload(path)
    if not isinstance(hist, list):
        if hist is not None or os.path.exists(path):
            try:
                os.replace(path, path + '.corrupt-' + time.strftime('%Y%m%d-%H%M%S'))
            except Exception:
                pass
        hist = []
    rec = dict(rec or {})
    rec.setdefault('ts', int(time.time()))
    rec['id'] = trade_id(rec)
    for old in hist:
        if isinstance(old, dict) and old.get('id') == rec['id']:
            return old, False
    hist.append(rec)
    _atomic_write(path, hist)
    return rec, True


def confirm(data_dir, rec, now=None, source='user'):
    """Complete a trade: append it, close the pending row, move the session on. Idempotent.

    rec is either a proposal's `trade` draft, a manual sale ({'slug','qty','plat',...}) or a
    correction (an explicit 'id' updates nothing - a new id is a new record). -> (result, created)
    """
    now = int(now or time.time())
    doc = load(data_dir)
    if not isinstance(rec, dict) or not (rec.get('slug') or rec.get('item')):
        return {'ok': False, 'error': 'slug required'}, False
    rec = dict(rec)
    rec['slug'] = str(rec.get('slug') or rec.get('item')).strip().lower()
    rec['item'] = rec['slug']
    rec['kind'] = rec.get('kind') if rec.get('kind') in KINDS else 'sale'
    try:
        rec['qty'] = max(1, int(rec.get('qty') or 1))
    except (TypeError, ValueError):
        return {'ok': False, 'error': 'qty must be a number'}, False
    plat = _int(rec.get('plat') if rec.get('plat') is not None else rec.get('price'))
    if plat is None or plat < 0:
        return {'ok': False, 'error': 'plat must be a number'}, False
    rec['plat'] = plat
    rec['rank'] = _int(rec.get('rank'))
    rec.setdefault('ts', now)
    rec['source'] = str(rec.get('source') or source)[:24]
    rec['confirmed_ts'] = now
    if rec.get('id') and str(rec['id']) in doc.get('confirmed', []):
        return {'ok': True, 'already': True, 'trade': rec, 'session_payload': None,
                'summary': summary(doc, now)}, False
    written, created = append_event(data_dir, rec)
    if not created:
        doc.setdefault('confirmed', []).append(str(written['id']))
        save(data_dir, doc)
        return {'ok': True, 'already': True, 'trade': written, 'summary': summary(doc, now)}, False

    # close the pending trade this came from, if any
    pend_id = rec.get('pending_id')
    for p in doc.get('pending', []):
        if (pend_id and p.get('id') == pend_id) or \
           (not pend_id and p.get('slug') == rec['slug'] and p.get('rank') == rec['rank']
                and p.get('state') in (CONTACTED, POSSIBLE)):
            p['state'] = COMPLETED
            p['completed_ts'] = now
            p['completed_trade'] = written['id']

    # move the session on and count it
    s = doc.get('session')
    if s:
        for r in (s.get('queue') or []):
            if r.get('slug') == rec['slug'] and (rec['rank'] is None or r.get('rank') == rec['rank']):
                r['state'] = COMPLETED
                r['completed_ts'] = now
                break
        t = s.setdefault('totals', {'trades': 0, 'earned_plat': 0, 'skipped': 0, 'held': 0})
        t['trades'] = int(t.get('trades') or 0) + 1
        t['earned_plat'] = round(float(t.get('earned_plat') or 0) + plat, 2)
        s.setdefault('done', []).insert(0, {'id': written['id'], 'slug': rec['slug'],
                                           'name': rec.get('name'), 'rank': rec['rank'],
                                           'qty': rec['qty'], 'plat': plat,
                                           'buyer': rec.get('user') or rec.get('buyer'),
                                           'ts': now})
        s['done'] = s['done'][:200]
        advance(doc, now)
    doc.setdefault('confirmed', []).append(str(written['id']))
    save(data_dir, doc)
    return {'ok': True, 'already': False, 'trade': written, 'summary': summary(doc, now)}, True


def confirm_payload(data_dir, rec, now=None, source='user'):
    """The route's body: the trade, the moved session and the proposal list it came from."""
    out, created = confirm(data_dir, rec, now=now, source=source)
    if out.get('ok'):
        doc = load(data_dir)
        out['session_payload'] = None
        out['session'] = doc.get('session')
        out['created'] = created
    return out


