"""One trade record, one lane identity — the shape and the key every reader shares.

Two things live here because getting them wrong has already cost real money in this app:

**The record.** `{slug, name, rank, qty, kind, ts, id, src, source, user, plat, total}` where `plat` is
the price per copy and `total` is the money for the trade. `server.trades_payload()`,
`scripts/session_stats.py` and `scripts/plat_ledger.py` all sum `total`: a record whose `plat` held
the money was absent from every earnings figure in the app, and one whose `plat` held the sum double
counted it. `canonical()` is the only normaliser and the only writer boundary that has to be trusted,
so a record is stored one way no matter which route it arrives on — and it *rejects* a sale or
purchase that carries no price at all rather than storing something no reader can sum.

**The lane.** A row's identity is `(slug, lane)` where the lane is `'rank 6'`, `'intact'`,
`'radiant'`, `''` (no dimension). A slug alone cannot tell two lanes apart: Intact and Radiant versions
of one relic share a slug and are different items at different prices, and a mod's rank is part of the
order, not of the item. `lane_key()` is that identity, used for queue dedupe, buyer lookup, pending
trades, the inventory maps, reconciliation and the confirm tail, so one row cannot be confused with
another that happens to share its slug.

Stdlib only, no import-time side effects, no network.
"""
import hashlib
import time

KINDS = ('sale', 'purchase', 'listing', 'unlist', 'reprice', 'note')
MONEY_KINDS = ('sale', 'purchase')

# The refinements a relic lane can name. Kept explicit so a lane is never silently lower-cased into
# something else: 'Intact' and 'intact' are the same lane, 'Intact ' is too, 'Intac' is not a lane.
REFINEMENTS = ('intact', 'exceptional', 'flawless', 'radiant')

LANE_NONE = 'n'          # the key fragment for a row with no rank dimension and no refinement


def _int(v, default=None):
    """A whole number from anything number-like, else the default. Never raises."""
    if isinstance(v, bool) or v is None:
        return default
    if isinstance(v, int):
        return v
    try:
        return int(round(float(str(v).strip())))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- the lane
def rank_of(row):
    """The rank a row was made for: report rows carry `lane_rank`, plans and queue rows `lane`."""
    if not isinstance(row, dict):
        return None
    for key in ('lane_rank', 'rank'):
        v = row.get(key)
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            return v
        n = _int(v)
        if n is not None:
            return n
    lane = row.get('lane')
    if isinstance(lane, str):
        tail = lane.strip()[5:].strip() if lane.strip().lower().startswith('rank ') else ''
        if tail.isdigit():
            return int(tail)
    return None


def lane_of(row):
    """A row's lane, as the app names it: `'rank 6'`, `'intact'`, `'radiant'`, `''` for no dimension.

    The row's own `lane` wins when it has one (it is what the plan and the run queue carry), and
    otherwise the lane is derived from the rank, so a row built from report fields still has one.
    """
    if not isinstance(row, dict):
        return ''
    lane = row.get('lane')
    if isinstance(lane, str) and lane.strip():
        return lane.strip()
    if lane is not None and not isinstance(lane, str):
        n = _int(lane)
        if n is not None:
            return 'rank %d' % n
    rank = rank_of(row)
    return 'rank %d' % rank if rank is not None else ''


def norm_lane(lane):
    """A lane as a key fragment: `'rank 6'` -> `'r6'`, `''` -> `'n'`, `'Radiant'` -> `'radiant'`."""
    s = ('' if lane is None else str(lane)).strip().lower()   # never `lane or ''`: rank 0 is falsy
    if s.startswith('rank ') and s[5:].strip().isdigit():
        return 'r%d' % int(s[5:].strip())
    if s.startswith('rank') and s[4:].strip().isdigit():
        return 'r%d' % int(s[4:].strip())
    if s.isdigit():
        return 'r%d' % int(s)
    if s in REFINEMENTS:
        return s
    return s or LANE_NONE


def lane_key(slug, lane):
    """The identity of a queue or pending row: its slug and its lane.

    `lane_key('primed_continuity', 'rank 0')` is `'primed_continuity#r0'`, which is the spelling the
    stored session state already used for a rank, so existing state keeps resolving.
    """
    return '%s#%s' % (str(slug or '').strip().lower(), norm_lane(lane))


def key_of(row, slug=None):
    """`lane_key` for a row dict (anything carrying `slug` plus `lane`/`rank`)."""
    if not isinstance(row, dict):
        return lane_key(slug, '')
    return lane_key(slug if slug is not None else row.get('slug'), lane_of(row))


def same_lane(a, b):
    """Do two rows (or two `(slug, lane)` pairs) name the same lane? One place decides it."""
    return key_of(a) == key_of(b)


# --------------------------------------------------------------------------- the record
def trade_id(rec):
    """A stable id for a trade record: same content -> same id, so a retry cannot double-log it."""
    if isinstance(rec, dict) and rec.get('id'):
        return str(rec['id'])
    rec = rec or {}
    raw = '|'.join(str(rec.get(k) or '')
                   for k in ('kind', 'slug', 'lane', 'rank', 'qty', 'plat', 'user', 'ts'))
    return 't-%d-%s' % (int(rec.get('ts') or time.time()) * 1000,
                        hashlib.sha1(raw.encode('utf-8')).hexdigest()[:6])


def canonical(rec, source=None, now=None):
    """The stored shape of one trade record. Raises ValueError if it cannot be one.

    `plat` is the price per copy and `total` is the money. A caller may send either name for the unit
    (`plat` or `price`) and either the money (`total`) or nothing at all, and both numbers come out
    right — but a sale or a purchase that carries no price is refused rather than stored, because a
    record no reader can sum is worse than a rejected one.
    """
    if not isinstance(rec, dict):
        raise ValueError('record must be a dict')
    out = dict(rec)
    kind = out.get('kind') if out.get('kind') in KINDS else None
    if out.get('kind') is not None and kind is None:
        raise ValueError('unknown kind %r' % (out.get('kind'),))
    out['kind'] = kind or 'sale'
    slug = out.get('slug') if out.get('slug') is not None else out.get('item')
    if slug is not None:
        out['slug'] = str(slug).strip().lower()
        out['item'] = out['slug']
    unit = _int(out.get('plat') if out.get('plat') is not None else out.get('price'))
    money = _int(out.get('total'))
    if out['kind'] in MONEY_KINDS:
        qty = _int(out.get('qty'), 1) or 1
        if qty < 1:
            raise ValueError('qty must be at least 1')
        out['qty'] = qty
        if unit is None and money is None:
            raise ValueError('a %s needs a price: plat (per copy) or total (the money)' % out['kind'])
        if unit is None:
            unit = int(round(float(money) / qty))
        if money is None:
            money = unit * qty
        if unit < 0 or money < 0:
            raise ValueError('plat and total cannot be negative')
        out['plat'], out['total'] = unit, money
    else:
        if unit is not None:
            out['plat'] = unit
        if money is not None:
            out['total'] = money
    if 'rank' in out:
        out['rank'] = _int(out.get('rank'))
    if out.get('lane') is not None:
        out['lane'] = lane_of(out)
    out.setdefault('ts', int(now or time.time()))
    if out.get('source') is None:
        out['source'] = str(source or out.get('src') or 'user')[:24]
    if out.get('src') is None:
        out['src'] = out['source']
    if not out.get('id'):
        out['id'] = trade_id(out)
    return out


# --------------------------------------------------------------------------- reading a record
def unit_of(ev):
    """The price per copy a stored event carries, or None. `plat` is the unit; `price` was an alias."""
    if not isinstance(ev, dict):
        return None
    unit = _int(ev.get('plat'))
    if unit is not None:
        return unit
    unit = _int(ev.get('price'))
    if unit is not None:
        return unit
    money = _int(ev.get('total'))
    if money is None:
        return None
    return int(round(money / max(1, _int(ev.get('qty'), 1) or 1)))


def money_of(ev):
    """The platinum a stored event moved — what every total in this app sums.

    `total` when the record has it. A record without one is the pre-canonical shape: its `plat` is a
    price per copy, so the money is `plat × qty` (they coincide for a single copy, which is the
    historical case). A record with neither is 0 — it moved nothing it can account for.
    """
    if not isinstance(ev, dict):
        return 0
    money = _int(ev.get('total'))
    if money is not None:
        return money
    unit = _int(ev.get('plat'))
    if unit is None:
        return 0
    return unit * max(1, _int(ev.get('qty'), 1) or 1)
