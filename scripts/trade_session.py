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
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import trade_schema as schema   # noqa: E402  (one record shape, one lane identity)

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

# A lane that names less than the whole item: a mod rank or a relic refinement. The report carries
# one row per item, so evidence for one of these can only be whole-item evidence unless the report
# itself names the lane - and a whole-item delta could be another lane's copy selling.
NARROWED_LANES = ('r',) + schema.REFINEMENTS

QUEUE_LIMIT = 12          # a session queue is a session's worth of work, not the whole plan
STALE_PENDING_S = 6 * 3600  # a CONTACTED trade older than this is flagged, never auto-resolved
PENDING_KEEP = 40         # finished/abandoned pending rows kept for recovery


# --------------------------------------------------------------------------- io
def lane_is_narrowed(lane):
    """Does this lane name less than the whole item (a mod rank, a relic refinement)?

    A row whose lane is empty sells the item as the item, so whole-item evidence is its own evidence.
    """
    n = schema.norm_lane(lane)
    return n.startswith('r') or n in schema.REFINEMENTS


def _settled(doc, tid):
    """Has this trade already been settled in the session? Never evicted, so a retry is safe.

    `confirmed` is capped for display; the idempotency key is `settled`, which is not. An id is a
    score of bytes, and a session store that had forgotten one would let a retry count the same sale
    twice (outside review, round 3: the capped list is why an evicted id could settle again).
    """
    if not tid:
        return False
    want = str(tid)
    for key in ('settled', 'confirmed'):
        for x in (doc.get(key) or []):
            if str(x) == want:
                return True
    return False


def _mark_settled(doc, tid):
    if not tid:
        return doc
    ids = [str(x) for x in (doc.get('settled') or []) if str(x) != str(tid)]
    doc['settled'] = [str(tid)] + ids
    return doc


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


def write_json_atomic(path, obj):
    """The public atomic writer for the stores this workflow and the importers rewrite wholesale.

    Same file shape the repo already uses (indent 1, unescaped names - item names carry Japanese
    characters), written through a tmp file so a crash cannot leave a half store behind.
    """
    _atomic_write(path, obj)


def load(data_dir):
    """The stored doc, or a fresh one. A corrupt/partial file is quarantined, not clobbered.

    A confirmation the process died in the middle of is finished or rolled back here (see
    recover()): the intent is written before the trade, so the next load can tell which half ran.
    """
    path = _path(data_dir)
    doc = jload(path)
    if isinstance(doc, dict):
        return recover(data_dir, normalise(doc))    # partly shaped is fine; normalise() coerces it
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
    return {'version': VERSION, 'session': None, 'pending': [], 'confirmed': [], 'settled': [],
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
            r['lane'] = lane_of(r)
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
        p['lane'] = lane_of(p) or None          # every pending row has its lane, derived if need be
    out['confirmed'] = [str(x) for x in (doc.get('confirmed') or []) if x][-500:]
    # `settled` is the idempotency key for a retry and is deliberately NOT capped: the visible
    # `confirmed` list is trimmed for display, and a retry of a trade remembered only there could
    # settle a second time. An id is a score of bytes; a long-running store stays small.
    out['settled'] = [str(x) for x in (doc.get('settled') or []) if x]
    # The two keys a recoverable confirm needs, and they must survive a save: `confirming` is the
    # durable intent written before the trade reaches trade_log, `recovered` the note that the next
    # load finished or undid one. Dropping them here would silently break crash recovery.
    cf = doc.get('confirming')
    if isinstance(cf, dict) and cf.get('id'):
        out['confirming'] = {'id': str(cf['id']), 'rec': dict(cf.get('rec') or {}),
                             'ts': int(cf.get('ts') or 0)}
    rc = doc.get('recovered')
    if isinstance(rc, dict) and rc.get('trade'):
        out['recovered'] = {'ts': int(rc.get('ts') or 0), 'trade': str(rc.get('trade')),
                            'result': rc.get('result') or '', 'note': rc.get('note') or ''}
    return out


def new_session_id(now):
    return 's-%s-%04x' % (time.strftime('%Y%m%d-%H%M', time.localtime(now)),
                          int(now * 1000) & 0xFFFF)


def row_key(slug, rank=None, lane=None):
    """The identity of a queue or pending row: its slug and its lane (trade_schema.lane_key).

    The lane, not the rank, is what tells two rows apart. Intact and Radiant versions of one relic
    share a slug and have no rank at all, and a mod's rank is part of the order rather than a
    different stack, so a slug alone pairs the wrong pair of them. `row_key(slug, rank)` still
    spells a mod's lane the way stored state always did (`'x#r0'`), so nothing that resolves today
    stops resolving.
    """
    if lane is None:
        lane = 'rank %d' % rank if rank is not None else ''
    return schema.lane_key(slug, lane)


def lane_of(row):
    """A row's lane: `'rank 6'`, `'intact'`, `'radiant'`, `''` for no dimension (trade_schema)."""
    return schema.lane_of(row)


def key_of(row, slug=None):
    """The identity of a row dict — what pending rows, inventory maps and the confirm tail key on."""
    return schema.key_of(row, slug)


def money_of(ev):
    """The platinum a stored event moved: `total`, or `plat × qty` for a pre-canonical record."""
    return schema.money_of(ev)


def _int(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- queue
def _rank_of(row):
    """The rank a recommendation was made for (trade_schema.rank_of: lane_rank, rank or 'rank N')."""
    return schema.rank_of(row)


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


def _runqueue_any(runqueue, slug):
    """Any live buyer row for this slug, whatever lane it names - for diagnosis only.

    The queue never pairs a buyer from here: it exists so a row can say *why* it has none (the run
    queue holds a buyer for another rank or another refinement of this item).
    """
    if not isinstance(runqueue, dict):
        return None
    for row in (runqueue.get('queue') or []):
        if isinstance(row, dict) and row.get('slug') == slug and row.get('buyer'):
            return row
    return None


def _runqueue_of(runqueue, slug, lane=None):
    """The live buyer row for one LANE of an item, if the run queue names one.

    Keyed on (slug, lane), not on the slug: two relic refinements or two mod ranks of one item are
    different rows, and taking the first slug match is exactly how a Radiant row gets an Intact
    buyer. When a lane is asked for and the row does not name one, there is no match - the caller
    then says the pairing is unverified rather than implying it was checked. `lane=None` keeps the
    old slug-only lookup for callers that genuinely have no lane.
    """
    if not isinstance(runqueue, dict):
        return None
    want = None if lane is None else schema.norm_lane(lane)
    for row in (runqueue.get('queue') or []):
        if not isinstance(row, dict) or row.get('slug') != slug or not row.get('buyer'):
            continue
        if want is None:
            return row
        row_lane = schema.lane_of(row)
        if row_lane and schema.norm_lane(row_lane) == want:
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

    def add(slug, name, qty, price, rank, source, lane=None):
        slug = str(slug or '').strip().lower()
        lane = schema.lane_of({'lane': lane}) if lane else (schema.lane_of({'rank': rank}) if rank is not None else '')
        key = row_key(slug, lane=lane)
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
        rq = _runqueue_of(runqueue, slug, lane or None)
        alt = _runqueue_any(runqueue, slug) if (rq is None and lane) else None
        buyer = _buyer(rq, runqueue.get('summary'))
        note = None
        if lane and buyer is None:
            # A lane was asked for, so only a buyer naming the same lane may be acted on. A row for
            # another lane is a different stack's order and one from an older producer names no lane
            # at all, so neither can be checked from here: the row says which it is and exposes no
            # actionable whisper either way (outside review, round 3).
            alt_lane = schema.lane_of(alt) if alt else ''
            if alt_lane:
                note = ('rank_mismatch', 'buyer is for %s' % alt_lane)
            elif alt is not None:
                note = ('rank_unverified', 'the run queue names no lane for this buyer')
        why = _why(rep, adv, buyer, runqueue)
        if note:
            why[note[0]] = note[1]
        rows.append({'slug': slug, 'name': name or rep.get('name') or adv.get('name') or slug,
                     'lane': lane, 'rank': rank, 'qty': qty, 'price': price,
                     'cat': rep.get('cat') or adv.get('cat'),
                     'buyer': buyer, 'why': why, 'confidence': _confidence(why),
                     'source': source, 'state': READY, 'added_ts': int(time.time())})
        seen.add(key)

    for row in (plan.get('plan') or []):
        if not isinstance(row, dict):
            continue
        add(row.get('slug'), row.get('name'), row.get('per_trade') or row.get('qty'),
            row.get('price'), _rank_of(row), 'plan', lane=lane_of(row))
    ranked = advisor.get('ranked')
    if isinstance(ranked, list):
        for slug in ranked:
            adv = _advisor_of(advisor, slug)
            if str(adv.get('recommendation') or '').lower() not in ('list', 'sell'):
                continue
            add(slug, adv.get('name'), adv.get('recommended_quantity'),
                adv.get('recommended_price'), _rank_of(adv), 'advisor', lane=lane_of(adv))
    return rows[:max(1, int(limit))]


# --------------------------------------------------------------------------- contact (the whisper)
def pending_id(slug, rank, buyer, now, lane=None):
    """A stable id for one contacted trade: the same contact gets the same id, and two lanes of one
    item never share one - Intact and Radiant copies of a relic have the same slug and no rank, so
    the lane has to be part of the hash."""
    raw = '%s|%s|%s|%s|%d' % (slug, lane if lane is not None else '', rank, buyer or '', int(now))
    return 'p-%d-%s' % (int(now * 1000), hashlib.sha1(raw.encode('utf-8')).hexdigest()[:6])


def contact(doc, slug, rank=None, qty=1, price=None, buyer=None, now=None,
            inv_before=None, plat_before=None, kind='sell', note='', inv_basis=None, lane=None):
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
    lane = schema.lane_of({'lane': lane}) if lane else (schema.lane_of({'rank': rank}) if rank is not None else '')
    want = schema.lane_key(slug, lane)
    row = None
    for r in ((doc.get('session') or {}).get('queue') or []):
        if key_of(r) == want:
            row = r
            break
    key = (want, buyer)
    for p in doc['pending']:
        if (key_of(p), p.get('buyer')) == key and p.get('state') in (CONTACTED, POSSIBLE):
            p['ts'] = now
            p['note'] = str(note or p.get('note') or '')[:160]
            if row is not None:
                row['state'] = CONTACTED
            return p
    pend = {'id': pending_id(slug, rank, buyer, now, lane=lane),
            'session_id': (doc.get('session') or {}).get('id'),
            'slug': slug, 'name': (row or {}).get('name') or slug, 'rank': rank, 'lane': lane or None,
            'qty': max(1, int(qty or (row or {}).get('qty') or 1)),
            'expected_plat': _int(price) or (row or {}).get('price'), 'buyer': buyer or None,
            'kind': kind, 'ts': now, 'state': CONTACTED,
            'inv_before': _int(inv_before), 'plat_before': _int(plat_before),
            'inv_basis': inv_basis or None,   # 'lane' or 'item': which count that snapshot is
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


def focus(doc, index=None, slug=None, now=None, lane=None):
    """Point the session at a queue row. Returns the row (or None)."""
    s = (doc or {}).get('session') or {}
    q = s.get('queue') or []
    if not q:
        return None
    if isinstance(index, int) and 0 <= index < len(q):
        s['cursor'] = index
    elif slug:
        want = schema.lane_key(slug, lane) if lane is not None else None
        for i, r in enumerate(q):
            if r.get('slug') == slug and (want is None or key_of(r) == want):
                s['cursor'] = i
                break
    return q[min(s.get('cursor') or 0, len(q) - 1)]


def set_state(doc, slug, rank=None, state=SKIPPED, note='', now=None, lane=None):
    """SKIPPED / HELD / READY on a queue row, and the matching session counter. Idempotent."""
    s = (doc or {}).get('session') or {}
    q = s.get('queue') or []
    want = schema.lane_key(slug, lane) if lane is not None else None
    hit = None
    for r in q:
        if r.get('slug') == slug and (want is not None and key_of(r) == want
                                      or want is None and (rank is None or r.get('rank') == rank)):
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


def inv_of(report, slug, rank=None, lane=None):
    """(copies, basis) - sellable copies of one item, from the same report.json the app renders.

    The report carries one row per item, tagged with `lane_rank` when it is a mod rank. A lane the
    report does not mention would otherwise snapshot as None and leave that trade UNKNOWN for ever,
    so this falls back to the item's total sellable count across lanes - the number that really
    moves when a copy sells - and says which of the two it used ('lane' / 'item') so the check can
    be honest about its basis. `lane` may be given instead of `rank` (a relic refinement); the
    report carries no refinement rows today, so those come back as the item total on purpose. The
    caller decides what that basis is worth: see NARROWED_LANES in propose().
    """
    total, seen = 0, False
    item_total = None
    want = schema.norm_lane(lane_of({'lane': lane})) if lane is not None else None
    for field in ('sell_now', 'patient'):
        for row in ((report or {}).get(field) or []):
            if not isinstance(row, dict) or row.get('slug') != slug:
                continue
            n = _int(row.get('sellable_count'))
            if n is None:
                continue
            if item_total is None:
                item_total = 0
            item_total += n
            if want:
                row_lane = schema.lane_of(row)
                if row_lane and schema.norm_lane(row_lane) == want:
                    total, seen = n, True
            elif want is None and rank is not None and row.get('lane_rank') == rank:
                total, seen = n, True
    if seen:
        return total, 'lane'
    return (item_total, 'item') if item_total is not None else (None, None)


def inv_now_map(report, pending):
    """{row_key: copies owned now} for the stacks the pending trades are about.

    A stack the report does not mention is simply absent - propose() then answers UNKNOWN rather
    than assuming a number.
    """
    out = {}
    for p in pending or []:
        if not isinstance(p, dict) or p.get('state') not in (CONTACTED, POSSIBLE):
            continue
        slug, rank = p.get('slug'), p.get('rank')
        key = key_of(p)
        if key in out:
            continue
        n, _basis = inv_of(report, slug, rank, lane=lane_of(p))
        if n is not None:
            out[key] = n
    return out


def inv_basis_map(report, pending):
    """{lane key: 'lane' | 'item'} - which count inv_now_map used, so a check can say so."""
    out = {}
    for p in pending or []:
        if not isinstance(p, dict) or p.get('state') not in (CONTACTED, POSSIBLE):
            continue
        key = key_of(p)
        if key not in out:
            _n, basis = inv_of(report, p.get('slug'), p.get('rank'), lane=lane_of(p))
            if basis:
                out[key] = basis
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
        checks = propose(pend, inv_now_map(report, pend), plat_now, now=now,
                         inv_basis=inv_basis_map(report, pend))
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


def propose(pending, inv_now, plat_now, now=None, inv_basis=None):
    """Propose what happened to each pending trade. -> {proposals: [...], counts: {...}}

    pending  : the doc's pending rows (CONTACTED / POSSIBLE MATCH are the live ones)
    inv_now  : {row_key(slug, rank): copies owned right now} - from the same report.json the app shows
    plat_now : platinum right now (the newest reading)
    inv_basis: {row_key: 'lane' | 'item'} - 'item' means the count is the item's total across lanes
               because the report carries no row for that exact lane; the check says so rather than
               letting a total look like a stack count
    """
    now = int(now or time.time())
    out, counts = [], {EXACT: 0, AMBIGUOUS: 0, NOTHING: 0, UNKNOWN: 0}
    watchers = {}
    for p in pending or []:
        if isinstance(p, dict) and p.get('state') in (CONTACTED, POSSIBLE):
            watchers[key_of(p)] = watchers.get(key_of(p), 0) + 1
    for p in pending or []:
        if not isinstance(p, dict) or p.get('state') not in (CONTACTED, POSSIBLE):
            continue
        slug, rank = p.get('slug'), p.get('rank')
        qty = max(1, int(p.get('qty') or 1))
        expected = _int(p.get('expected_plat'))
        total = (expected or 0) * qty
        now_inv = _int((inv_now or {}).get(key_of(p)))
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
            elif left == qty and total and delta_plat == total:
                # Spec §4: an exact match is item + rank + quantity + inventory delta + platinum
                # delta agreeing. Anything that moved MORE than this trade is not exact - other
                # sales may be in the same change - so it is presented as evidence, not a claim.
                verdict, why = EXACT, _evidence(('copies left', left), ('platinum', '+%d' % delta_plat),
                                                ('asked', total))
            elif left >= qty and total and delta_plat >= total:
                verdict, why = AMBIGUOUS, _evidence(
                    ('copies left', left), ('platinum', '+%d' % delta_plat), ('asked', total),
                    ('more moved than this trade', '%s +%dp' % (
                        ('%d extra copy' % (left - qty)) + ('ies' if left - qty > 1 else '')
                        if left > qty else 'no extra copies',
                        delta_plat - total)))
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
        basis = (inv_basis or {}).get(key_of(p))
        if basis == 'item':
            why = _evidence(('basis', 'item total')) + why
        if verdict == EXACT and basis == 'item' and lane_is_narrowed(p.get('lane') or rank):
            # Whole-item evidence for a lane that names less than the item: the copies that moved may
            # be another rank's or another refinement's. It is shown with its numbers and offered for
            # confirmation, but it is not claimed as an exact match (outside review, round 3).
            verdict = AMBIGUOUS
            why = _evidence(('basis', 'the whole item, not this lane')) + why
        if verdict == EXACT and watchers.get(key_of(p), 0) > 1:
            # Two live pending trades on one lane would each read the same single movement as their
            # own. One physical sale cannot satisfy two trades, so neither of them can be exact.
            verdict = AMBIGUOUS
            why = _evidence(('same lane', '%d pending trades; one movement cannot be split'
                             % watchers[key_of(p)])) + why
        counts[verdict] += 1
        out.append({'verdict': verdict, 'pending_id': p.get('id'), 'slug': slug, 'name': p.get('name'),
                    'lane': lane_of(p), 'rank': rank, 'qty': qty, 'buyer': p.get('buyer'), 'age_s': age,
                    'expected_plat': expected, 'total_plat': total or None,
                    'inv_before': before, 'inv_now': now_inv,
                    'plat_before': plat_before, 'plat_now': _int(plat_now),
                    'copies_left': left, 'plat_delta': delta_plat, 'evidence': why,
                    'stale': age > STALE_PENDING_S,
                    # the draft carries the per-copy price: trade_draft turns it into
                    # plat=unit / total=unit*qty, which is the shape every reader sums. Passing
                    # the sum here would have stored it as the unit and multiplied it again.
                    'trade': trade_draft(p, plat=expected if verdict == EXACT else None)})
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
    unit = _int(plat) or _int((pending.get('expected_plat'))) or 0
    draft = {'kind': 'sale', 'slug': slug, 'item': slug, 'name': pending.get('name'),
             'rank': rank, 'lane': pending.get('lane') or '', 'qty': qty,
             'plat': unit, 'total': unit * qty,
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
    This is now the one writer, so the record shape is enforced here as well as in confirm(): a
    caller that hands over `{kind: 'sale', qty: 3, plat: 48}` gets `total: 144` stored, and one that
    hands over a sale with no price at all gets a ValueError instead of an unsummable row.

    Returns (record, created_bool). Raises ValueError on a record that cannot be canonicalised.
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
    rec = schema.canonical(rec, now=int(time.time()))
    for old in hist:
        if isinstance(old, dict) and old.get('id') == rec['id']:
            return old, False
    hist.append(rec)
    _atomic_write(path, hist)
    return rec, True


def recover(data_dir, doc):
    """Finish or undo a confirm the process died inside. It never guesses - see confirm().

    One question decides it: is the intent's trade id in trade_log.json?
      - yes -> the append landed: the finalisation is replayed (close the pending row, count the
        session, advance), which is idempotent because a trade already in `confirmed` is skipped.
      - no  -> the append never landed: the intent is dropped. The pending row was never touched,
        so the trade is still open and the user can simply confirm it again.
    """
    if not isinstance(doc, dict):
        return doc
    intent = doc.get('confirming')
    if not isinstance(intent, dict):
        return doc
    rec = intent.get('rec') if isinstance(intent.get('rec'), dict) else {}
    tid = str(intent.get('id') or rec.get('id') or '')
    landed = None
    hist = jload(os.path.join(data_dir, TRADE_LOG))
    if tid and isinstance(hist, list):
        for e in hist:
            if isinstance(e, dict) and str(e.get('id')) == tid:
                landed = e
                break
    at = int(intent.get('ts') or 0) or int(time.time())
    if landed is None:
        doc.pop('confirming', None)
        doc['recovered'] = {'ts': at, 'trade': tid, 'result': 'rolled back',
                            'note': 'the trade was never written; nothing is claimed'}
    else:
        doc = _finalise(data_dir, doc, landed, rec, at)
        doc['recovered'] = {'ts': at, 'trade': tid, 'result': 'finished',
                            'note': 'the trade was written before the crash; the session caught up'}
    save(data_dir, doc)
    return doc


def _finalise(data_dir, doc, written, rec, now, pending_id=None, rank=None):
    """Everything a confirmed trade has to update, in one place, once, idempotently.

    Spec section 5 asks for one transaction that updates history, session earnings, the sales count,
    the pending row, the queue and the cursor. History is already written by the time this runs, so
    a replay only ever settles the session side - a trade already in `confirmed` is skipped.
    """
    tid = str((written or {}).get('id') or '')
    slug = rec.get('slug') or rec.get('item')
    if rank is None:
        rank = rec.get('rank')
    lane = schema.lane_of(rec)
    money = money_of(rec)
    if tid and _settled(doc, tid):
        doc.pop('confirming', None)              # already settled: only the intent needs clearing
        return doc

    pid = pending_id if pending_id is not None else rec.get('pending_id')
    want = key_of(rec)
    for p in doc.get('pending', []):
        if (pid and p.get('id') == pid) or \
           (not pid and key_of(p) == want and p.get('state') in (CONTACTED, POSSIBLE)):
            p['state'] = COMPLETED
            p['completed_ts'] = now
            p['completed_trade'] = tid

    s = doc.get('session')
    if s:
        for r in (s.get('queue') or []):
            if key_of(r) == want:
                r['state'] = COMPLETED
                r['completed_ts'] = now
                break
        t = s.setdefault('totals', {'trades': 0, 'earned_plat': 0, 'skipped': 0, 'held': 0})
        t['trades'] = int(t.get('trades') or 0) + 1
        t['earned_plat'] = round(float(t.get('earned_plat') or 0) + money, 2)
        s.setdefault('done', []).insert(0, {'id': tid, 'slug': slug, 'name': rec.get('name'),
                                            'lane': lane or None, 'rank': rank,
                                            'qty': max(1, int(rec.get('qty') or 1)),
                                            'plat': money, 'buyer': rec.get('user') or rec.get('buyer'),
                                            'ts': now})
        s['done'] = s['done'][:200]
        advance(doc, now)
    # The idempotency key for a retry: never evicted (unlike `confirmed`, which the UI caps), so a
    # retry of a trade whose id has fallen out of the visible list still cannot settle twice.
    _mark_settled(doc, tid)
    doc.setdefault('confirmed', []).append(tid)
    doc['confirmed'] = doc['confirmed'][-400:]
    doc.pop('confirming', None)
    save(data_dir, doc)
    return doc


_CONFIRM_LOCK = threading.RLock()      # the server is threaded; confirm is a read-modify-write


def confirm(data_dir, rec, now=None, source='user'):
    """Complete a trade: append it, close the pending row, move the session on. Idempotent.

    Serialised: the dashboard's server is a ThreadingHTTPServer, so two Confirm clicks (or a click and
    a retry) arriving together would otherwise both read the session store, both decide the trade was
    new, and settle it twice. The lock covers the whole transaction, not just the file write.
    """
    with _CONFIRM_LOCK:
        return _confirm(data_dir, rec, now=now, source=source)


def _confirm(data_dir, rec, now=None, source='user'):
    """The body of confirm(), under its lock.

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
    # The record shape is not decided here any more: trade_schema.canonical() owns it, so the route
    # (/api/session/confirm), /api/trades, this path and the retry all store exactly the same fields.
    # It refuses a sale that carries no price rather than storing one nothing can sum.
    try:
        rec = schema.canonical(rec, source=source, now=now)
    except ValueError as e:
        return {'ok': False, 'error': str(e)}, False
    rec['confirmed_ts'] = now
    if str(rec['id']) in [str(x) for x in (doc.get('settled') or [])]:
        return {'ok': True, 'already': True, 'trade': rec, 'session_payload': None,
                'summary': summary(doc, now)}, False

    # Two-phase write. The intent (this record and its id) is durable in the session store BEFORE
    # the trade reaches trade_log, because the two files cannot be written together: whichever way
    # the process dies, the next load() can tell which half happened and finish or undo it
    # (recover()). Without this, a crash in between logged a sale that the session never saw.
    doc['confirming'] = {'id': rec['id'], 'rec': rec, 'ts': now}
    save(data_dir, doc)
    written, created = append_event(data_dir, rec)
    if not created:
        doc = _finalise(data_dir, doc, written, rec, now)   # someone else wrote it: settle ours
        return {'ok': True, 'already': True, 'trade': written, 'summary': summary(doc, now)}, False

    # One transaction for everything the spec lists in section 5 - the pending row, the queue, the
    # session totals, the sales count, the cursor - and it is the same code path a crash-recovery
    # replay uses, so the two can never drift.

    doc = _finalise(data_dir, doc, written, rec, now)
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


