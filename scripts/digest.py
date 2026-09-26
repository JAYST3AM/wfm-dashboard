"""Daily digest v1: one Discord-ready message composed from the dashboard's data files.

This script NEVER scans the market - it composes from what the other dashboard scripts have
already written, so it stays cheap enough to run on a cron/at any moment:

  account   data/trader_limits.json (+ plat_history / kill_switch / session_stats)
  flips     data/flip_digest.json      (the digest's own ranking, never re-ranked here)
  demand    data/trends.json           (falls back to data/meta_watch.json)
  baro      data/baro.json             (countdown + ducats + buy list)
  nudges    data/nudges.json           (READY / ONE_AWAY sets, most urgent first)
  wishlist  data/wishlist.json         (BUY_NOW rows + budget headroom)
  plan      data/trader_plan.json      (orders / copies / est plat)
  timing    data/sell_timing.json      (verdict + next window + sample size)
  data      footer: generated stamp + the mtime age of every source file

Every section is 1-5 lines and every section whose source file is missing or older than
STALE_MIN reads as "no data (data/<file> <age> old)" - the composer says what it does not
know instead of guessing, and the footer always carries the real mtimes.

Writes data/daily_digest.json (atomic) and nothing else; stdlib only, no network. The blob is
ASCII-only so it survives a cp1252 Windows console, and it is hard-capped at DISCORD_LIMIT
characters by degrading sections one rung at a time (ranked lists keep their lines longest);
the untruncated text is kept in the json under discord_markdown_full.

Usage:
  python scripts/digest.py              # compose, print a status line + markdown, write json
  python scripts/digest.py --print      # markdown only on stdout (status line goes to stderr)
  python scripts/digest.py --save       # write data/daily_digest.json (the default)
  python scripts/digest.py --no-save    # compose only, write nothing (plan only)
  python scripts/digest.py --notify     # also hand the blob to trader/notify_rules.emit()
  python scripts/digest.py --selftest   # offline fixture checks in a tmp dir, writes nothing
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

OUT_NAME = 'daily_digest.json'
REL_OUT = 'data/' + OUT_NAME
VERSION = 1
TZ_NAME = 'Australia/Melbourne'
TZ_FALLBACK_HOURS = 10
DISCORD_LIMIT = 1800          # Discord's per-message ceiling (chars)
STALE_MIN = 1440.0            # a source older than this reads as 'no data' (age still printed)
TOP_FLIPS = 3
TOP_DEMAND = 2
TOP_NUDGES = 3
TOP_WISHLIST = 3

# (file, footer label) - the footer prints the mtime age of every one of these, in order.
SOURCES = (
    ('trader_limits.json', 'limits'),
    ('session_stats.json', 'sessions'),
    ('plat_history.json', 'plat'),
    ('kill_switch.json', 'killsw'),
    ('flip_digest.json', 'flips'),
    ('trends.json', 'trends'),
    ('meta_watch.json', 'meta'),
    ('baro.json', 'baro'),
    ('nudges.json', 'nudges'),
    ('wishlist.json', 'wishlist'),
    ('trader_plan.json', 'plan'),
    ('sell_timing.json', 'timing'),
)

# Graceful-degradation ladder for the Discord blob: the first rung whose render fits wins.
# Rungs 1-3 shave the OPTIONAL lines first (last-session, baro stock/ducats detail, extra
# wishlist rows, held-back note, the flips tally, the nudge tally, the plan breakdown) so the
# facts the digest exists for - account/trades/kill-switch, 3 fresh flips, 2 spikes + 2 fades,
# the Baro countdown, the READY/ONE_AWAY sets, the wishlist budget, the plan totals and the
# timing verdict - survive as long as possible. The last rungs squeeze every section to 2 then
# 1 lines, and the hard clip is the final backstop (text is never over the limit).
DEGRADE_LADDER = (
    ({'account': 3, 'flips': 4, 'demand': 4, 'baro': 3, 'nudges': 4, 'wishlist': 4, 'plan': 3,
      'timing': 2, 'data': 1}, None, 'trim-session'),
    ({'account': 3, 'flips': 4, 'demand': 4, 'baro': 2, 'nudges': 4, 'wishlist': 4, 'plan': 2,
      'timing': 2, 'data': 1}, None, 'trim-stock'),
    ({'account': 3, 'flips': 4, 'demand': 4, 'baro': 2, 'nudges': 4, 'wishlist': 3, 'plan': 2,
      'timing': 2, 'data': 1}, None, 'trim-rows'),
    ({'account': 3, 'flips': 4, 'demand': 4, 'baro': 2, 'nudges': 3, 'wishlist': 3, 'plan': 1,
      'timing': 2, 'data': 1}, None, 'trim-tally'),
    ({'account': 3, 'flips': 4, 'demand': 4, 'baro': 1, 'nudges': 3, 'wishlist': 2, 'plan': 1,
      'timing': 2, 'data': 1}, None, 'trim-ducats'),
    ({'account': 3, 'flips': 3, 'demand': 4, 'baro': 1, 'nudges': 3, 'wishlist': 2, 'plan': 1,
      'timing': 2, 'data': 1}, None, 'trim-provenance'),
    (None, 2, 'uniform-2'),
    (None, 1, 'uniform-1'),
)


# ------------------------------------------------------------------------------- helpers
def local_tz():
    """Australia/Melbourne, with a fixed UTC+10 fallback for Windows boxes with no tz db."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(TZ_NAME)
    except Exception:
        return timezone(timedelta(hours=TZ_FALLBACK_HOURS), 'AEST')


def iso(epoch):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(epoch))


def local_stamp(epoch, tz=None):
    """'2026-09-25 23:58 AEST' - the stamp a human reads in the message."""
    when = datetime.fromtimestamp(epoch, tz or local_tz())
    return when.strftime('%Y-%m-%d %H:%M %Z')


def as_num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def jload(path):
    """(doc, err): doc None on any failure, err 'missing'/'unreadable'/None."""
    if not os.path.exists(path):
        return None, 'missing'
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh), None
    except Exception:
        return None, 'unreadable'


def jdump(path, obj):
    """Atomic write (tmp + replace), same shape as the other dashboard scripts."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path + '.tmp', 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, indent=1)
    os.replace(path + '.tmp', path)


def fmt_num(value, places=2):
    """Numbers without trailing zeros: 52.5 -> '52.5', 128.0 -> '128', None -> '?'."""
    if value is None:
        return '?'
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    rounded = round(float(value), places)
    if rounded == int(rounded):
        return str(int(rounded))
    return ('%.*f' % (places, rounded)).rstrip('0').rstrip('.')


def fmt_int(value):
    try:
        return '{:,}'.format(int(round(float(value))))
    except (TypeError, ValueError):
        return '?'


def fmt_age(minutes):
    """Compact mtime age: '4m' / '2.1h' / '3.4d'."""
    if minutes is None:
        return '?'
    if minutes < 1:
        return 'now'
    if minutes < 90:
        return '%.0fm' % minutes
    if minutes < 2880:
        return '%.1fh' % (minutes / 60.0)
    return '%.1fd' % (minutes / 1440.0)


def fmt_ago(minutes):
    """'53m ago' / '2.1h ago' / 'just now' / 'missing' - footer wording for an mtime age."""
    if minutes is None:
        return 'missing'
    if minutes < 1:
        return 'just now'
    return '%s ago' % fmt_age(minutes)


def fmt_dur(seconds):
    """Compact countdown: '47m' / '10h 59m' / '7d 0h'."""
    if seconds is None:
        return '?'
    seconds = int(seconds)
    if seconds <= 0:
        return 'now'
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return '%dd %dh' % (days, hours)
    if hours:
        return '%dh %dm' % (hours, minutes)
    return '%dm' % minutes


def stamp_short(epoch):
    """'2026-09-25 23:58' from an epoch, or '?' when absent."""
    num = as_num(epoch)
    if num is None:
        return '?'
    return datetime.fromtimestamp(num, local_tz()).strftime('%Y-%m-%d %H:%M')


def clip(text, width):
    text = str(text)
    return text if len(text) <= width else text[:max(0, width - 3)].rstrip() + '...'


def section(sec_id, title, lines):
    return {'id': sec_id, 'title': title, 'lines': [str(line) for line in lines if str(line)]}


def parse_now(text):
    """--now accepts epoch seconds or an ISO/local timestamp; default is the wall clock."""
    if not text:
        return int(time.time())
    try:
        return int(float(text))
    except (TypeError, ValueError):
        pass
    try:
        when = datetime.fromisoformat(str(text))
    except ValueError:
        raise SystemExit('--now: give epoch seconds or an ISO timestamp, got %r' % text)
    if when.tzinfo is None:
        when = when.replace(tzinfo=local_tz())
    return int(when.timestamp())


def plat_last_point(doc):
    """Last point of data/plat_history.json (a list of {ts, plat, ...}), or None."""
    if not isinstance(doc, list):
        return None
    for row in reversed(doc):
        if isinstance(row, dict) and as_num(row.get('plat')) is not None:
            return row
    return None


class Source:
    """One input file: doc, mtime age, and the honest wording when it cannot be used."""

    def __init__(self, root, name, label, now):
        self.name = name
        self.label = label
        self.rel = 'data/' + name
        self.path = os.path.join(root, 'data', name)
        self.age = self._age(now)
        self.doc, self.err = jload(self.path)

    def _age(self, now):
        try:
            return max(0.0, (now - os.path.getmtime(self.path)) / 60.0)
        except OSError:
            return None

    @property
    def fresh(self):
        return self.pick() is not None

    def pick(self):
        """The document when present AND fresh; a stale file reads as no data."""
        if self.doc is None or self.age is None or self.age > STALE_MIN:
            return None
        return self.doc

    def brief(self):
        if self.age is None:
            return '%s missing' % self.rel
        if self.doc is None:
            return '%s unreadable (%s old)' % (self.rel, fmt_age(self.age))
        return '%s %s old' % (self.rel, fmt_age(self.age))

    def no_data(self):
        return 'no data (%s)' % self.brief()


# ----------------------------------------------------------------------- section builders
def sec_account(src, now):
    tl = src['trader_limits.json']
    limits = tl.pick()
    lines = []

    account, mr, plat, plat_src = 'unknown account', None, None, None
    if limits:
        account = limits.get('account') or account
        mr = as_num(limits.get('mr'))
        plat = as_num(limits.get('plat'))
        if plat is not None:
            plat_src = 'trader_limits'
    head = str(account)
    if mr is not None:
        head += ' | MR %s' % fmt_num(mr)
    if plat is None:
        point = plat_last_point(src['plat_history.json'].doc)
        if point is not None:
            plat = as_num(point.get('plat'))
            age = src['plat_history.json'].age
            plat_src = 'plat_history%s' % (' %s' % fmt_ago(age) if age is not None else '')
    head += ' | %sp (%s)' % (fmt_int(plat), plat_src) if plat is not None else ' | plat unknown'
    lines.append(head)

    if limits:
        cap = as_num(limits.get('trade_cap'))
        used = as_num(limits.get('trades_used'))
        left = as_num(limits.get('trades_left'))
        if used is None and cap is not None and left is not None:
            used = cap - left
        line = 'trades %s/%s used' % (fmt_num(used), fmt_num(cap)) if cap is not None else 'trades used %s' % fmt_num(used)
        if left is not None:
            line += ' - %s left' % fmt_num(left)
        reset_epoch = as_num(limits.get('reset_epoch'))
        if reset_epoch is None:
            seconds = as_num(limits.get('seconds_until_reset'))
            reset_epoch = now + seconds if seconds is not None else None
        reset_at = limits.get('reset_melbourne')
        if reset_at:
            line += ' | reset %s' % str(reset_at)[:16].replace('T', ' ')
        if reset_epoch is not None:
            line += ' (in %s)' % fmt_dur(reset_epoch - now)
        lines.append(line)
    else:
        lines.append(tl.no_data())

    kill = src['kill_switch.json']
    kdoc = kill.pick()
    if kdoc is None:
        lines.append('kill switch: ' + kill.no_data())
    elif kdoc.get('active'):
        note = clip(kdoc.get('note') or 'trading halted', 70)
        lines.append('kill switch: ARMED - %s' % note)
    else:
        lines.append('kill switch: off')

    ss = src['session_stats.json']
    sdoc = ss.pick()
    if sdoc is None:
        lines.append('last session: ' + ss.no_data())
    else:
        sessions = [s for s in (sdoc.get('sessions') or []) if isinstance(s, dict)]
        if sessions:
            last = sessions[0]
            detail = []
            if last.get('kind'):
                detail.append(str(last['kind']))
            if as_num(last.get('sales')) is not None:
                detail.append('%s sales' % fmt_num(last.get('sales')))
            if as_num(last.get('net')) is not None:
                detail.append('net %sp' % fmt_num(last.get('net')))
            tail = ''
            if as_num(last.get('dur_min')) is not None:
                tail = ' (%sm)' % fmt_num(last.get('dur_min'))
            lines.append('last session %s - %s%s'
                         % (last.get('end_at') or last.get('start_at') or '?',
                            ', '.join(detail) or 'no events', tail))
    return section('account', 'Account', lines)


def flip_line(index, row):
    head = '%d. %s' % (index, row.get('name') or row.get('slug') or '?')
    if row.get('kind'):
        head += ' [%s]' % row['kind']
    bits = []
    buy, sell = as_num(row.get('buy_at')), as_num(row.get('sell_at'))
    if buy is not None and sell is not None:
        bits.append('%sp -> %sp' % (fmt_num(buy), fmt_num(sell)))
    profit = as_num(row.get('profit'))
    if profit is not None:
        margin = '+%sp' % fmt_num(profit)
        if as_num(row.get('margin_pct')) is not None:
            margin += ' (%+.1f%%)' % row['margin_pct']
        bits.append(margin)
    if as_num(row.get('sales_day')) is not None:
        bits.append('%s/day' % fmt_num(row.get('sales_day')))
    if as_num(row.get('queue_ahead')) is not None:
        bits.append('queue %s' % fmt_num(row.get('queue_ahead')))
    return '%s | %s' % (head, ' | '.join(bits)) if bits else head


def sec_flips(src):
    fd = src['flip_digest.json']
    if not fd.fresh:
        return section('flips', 'Fresh flips', [fd.no_data()])
    doc = fd.doc or {}
    rows = doc.get('digest') or doc.get('flips') or doc.get('safe_flips') or []
    counts = doc.get('counts') or {}
    lines = []
    if rows:
        for i, row in enumerate(rows[:TOP_FLIPS], 1):
            lines.append(flip_line(i, row))
        fresh_n, stale_n = counts.get('fresh'), counts.get('stale_excluded')
        if fresh_n is not None:
            # provenance last: if the Discord blob has to drop a line, it drops this one, never
            # one of the three ranked flips
            lines.append('%s fresh, %s stale hidden' % (fmt_num(fresh_n),
                                                        fmt_num(stale_n) if stale_n is not None else '?'))
    else:
        lines.append('no ranked flips in data/flip_digest.json (digest has no rows)')
    return section('flips', 'Fresh flips', lines)


def demand_line(row, tag, source):
    per_day = as_num(row.get('vol48_per_day'))
    if per_day is None:
        per_day = (as_num(row.get('vol48')) or 0) / 2.0
    bits = []
    ratio = as_num(row.get('ratio'))
    if ratio is not None:
        bits.append('%.2fx/30d' % ratio)
    bits.append('%s/day' % fmt_num(per_day))
    pct = as_num(row.get('price_trend_pct'))
    bits.append('price %+.1f%%' % pct if pct is not None else 'price n/a')
    if row.get('post_patch'):
        bits.append('post-patch')
    return '%s %s - %s [%s]' % (tag, row.get('name') or row.get('slug') or '?', ', '.join(bits), source)


def sec_demand(src):
    trends, meta = src['trends.json'], src['meta_watch.json']
    lines = []
    picks = (
        ('SPIKE', 'top_spikes', 'spike', trends, meta),
        ('FADE', 'top_fades', 'sink', trends, meta),
    )
    for tag, trends_key, meta_key, primary, secondary in picks:
        rows, source = [], None
        if primary.fresh and (primary.doc or {}).get(trends_key):
            rows, source = primary.doc[trends_key][:TOP_DEMAND], primary.label
        elif secondary.fresh and (secondary.doc or {}).get(meta_key):
            rows, source = secondary.doc[meta_key][:TOP_DEMAND], secondary.label
        for row in rows:
            if isinstance(row, dict):
                lines.append(demand_line(row, tag, source))
    if not lines:
        lines.append('no data (%s; %s)' % (trends.brief(), meta.brief()))
    return section('demand', 'Demand', lines)


def sec_baro(src):
    baro = src['baro.json']
    if not baro.fresh:
        return section('baro', 'Baro', [baro.no_data()])
    doc = baro.doc or {}
    trader = doc.get('trader') or {}
    who = trader.get('character') or "Baro Ki'Teer"
    lines = []
    if trader.get('active'):
        head = '%s: ACTIVE at %s' % (who, trader.get('location') or 'relay')
        if trader.get('closes_in'):
            head += ' - closes in %s' % trader['closes_in']
    else:
        status = str(trader.get('status_text') or '').replace(' -- ', ' - ')
        for prefix in ('NOT active - ', 'NOT active -- ', 'Not active - '):
            if status.startswith(prefix):
                status = status[len(prefix):]
        if not status:
            status = 'next visit in %s' % trader['starts_in'] if trader.get('starts_in') else 'not active'
        head = "%s: %s" % (who, status)
        if trader.get('location') and trader.get('starts_in') and trader['starts_in'] not in head:
            head += ' (in %s)' % trader['starts_in']
    lines.append(head)
    player = doc.get('player') or {}
    summary = doc.get('summary') or {}
    if as_num(player.get('ducats')) is not None:
        money = 'ducats %s' % fmt_int(player['ducats'])
        burn, parts = as_num(summary.get('ducats_from_burnable_parts')), as_num(summary.get('burnable_parts'))
        if burn and parts:
            money += ' (+%s from %s burnable parts)' % (fmt_int(burn), fmt_num(parts))
        if as_num(player.get('credits')) is not None:
            money += ' | credits %s' % fmt_int(player['credits'])
        lines.append(money)
    buys = [b for b in (doc.get('wishlist_buys') or []) if isinstance(b, dict)]
    rows = doc.get('rows') or []
    if buys:
        names = ', '.join(str(b.get('name') or b.get('slug')) for b in buys[:3])
        lines.append('buy list: %d item(s) - %s%s' % (len(buys), clip(names, 80),
                                                     ' ...' if len(buys) > 3 else ''))
    elif not rows:
        lines.append('stock: no rows - his inventory is only published while he is here')
    return section('baro', 'Baro', lines[:4])


def nudge_line(row, tag):
    name = row.get('name') or row.get('slug') or '?'
    action = ''
    if tag == 'ONE_AWAY' and row.get('missing_name'):
        action = 'buy %s' % row['missing_name']
        if as_num(row.get('cost_est')) is not None:
            action += ' (~%sp)' % fmt_num(row.get('cost_est'))
        if as_num(row.get('set_value')) is not None:
            action += ' -> set sale %sp' % fmt_num(row.get('set_value'))
    else:
        action = str(row.get('action') or '').strip()
        if as_num(row.get('set_value')) is not None:
            action = ('%s, ' % action if action else '') + '%sp' % fmt_num(row.get('set_value'))
        trades = as_num(row.get('trades_to_complete'))
        if trades:
            action = ('%s, ' % action if action else '') + '%s trade(s)' % fmt_num(trades)
    return '[%s] %s%s' % (tag, name, ' - %s' % action if action else '')


def sec_nudges(src):
    nd = src['nudges.json']
    if not nd.fresh:
        return section('nudges', 'Nearly built', [nd.no_data()])
    doc = nd.doc or {}
    pool = [(r, 'READY') for r in (doc.get('ready') or []) if isinstance(r, dict)]
    pool += [(r, 'ONE_AWAY') for r in (doc.get('one_away') or []) if isinstance(r, dict)]
    pool.sort(key=lambda pair: (-(as_num(pair[0].get('urgency')) or as_num(pair[0].get('profit'))
                                  or as_num(pair[0].get('set_value')) or 0.0),
                                str(pair[0].get('name') or '')))
    lines = [nudge_line(row, tag) for row, tag in pool[:TOP_NUDGES]]
    if not pool:
        lines.append('no READY or ONE_AWAY sets right now')
    counts = doc.get('counts') or {}
    tally = []
    for key, label in (('ready', 'ready'), ('one_away', 'one-away'), ('two_away', 'two-away')):
        if as_num(counts.get(key)) is not None:
            tally.append('%s %s' % (fmt_num(counts[key]), label))
    if tally:
        line = 'sets: ' + ', '.join(tally)
        if as_num(counts.get('conflicts')):
            line += ' (%s conflict(s) flagged)' % fmt_num(counts['conflicts'])
        lines.append(line)
    return section('nudges', 'Nearly built', lines[:5])


def sec_wishlist(src):
    wl = src['wishlist.json']
    if not wl.fresh:
        return section('wishlist', 'Wishlist', [wl.no_data()])
    doc = wl.doc or {}
    summary = doc.get('summary') or {}
    suggested = doc.get('suggested') or []
    buy = [e for e in suggested if isinstance(e, dict) and str(e.get('status') or '').upper() == 'BUY_NOW']
    if not buy:
        buy = [e for e in (doc.get('affordable_plan') or [])
               if isinstance(e, dict) and str(e.get('status') or 'BUY_NOW').upper() == 'BUY_NOW']
    lines = []
    if summary:
        lines.append('BUY_NOW %s - %sp of %sp (headroom %sp, %s trades)' % (
            fmt_num(summary.get('buy_now_count') if summary.get('buy_now_count') is not None else len(buy)),
            fmt_int(summary.get('budget_needed')), fmt_int(summary.get('budget_available')),
            fmt_int(summary.get('budget_leftover')), fmt_num(summary.get('trades_needed'))))
    for entry in buy[:TOP_WISHLIST]:
        cost = entry.get('cost') if as_num(entry.get('cost')) is not None else entry.get('max_price')
        extra = []
        if as_num(entry.get('floor')) is not None:
            extra.append('floor %s' % fmt_num(entry['floor']))
        if as_num(entry.get('ratio')) is not None:
            extra.append('ratio %s' % fmt_num(entry['ratio']))
        if entry.get('set_action'):
            extra.append(str(entry['set_action']))
        lines.append('%s %sp%s' % (entry.get('name') or entry.get('slug') or '?', fmt_num(cost),
                                   ' (%s)' % ', '.join(extra) if extra else ''))
    if not buy:
        lines.append('no BUY_NOW rows in data/wishlist.json')
    if str(summary.get('status') or '').upper() == 'DEGRADED':
        lines.append('budget flagged DEGRADED (source %s)' % (summary.get('budget_source') or '?'))
    return section('wishlist', 'Wishlist', lines[:5])


def sec_plan(src):
    tp = src['trader_plan.json']
    if not tp.fresh:
        return section('plan', 'Plan', [tp.no_data()])
    doc = tp.doc or {}
    plan = [r for r in (doc.get('plan') or []) if isinstance(r, dict)]
    summary = doc.get('summary') or {}
    orders = summary.get('orders') if summary.get('orders') is not None else len(plan)
    copies = summary.get('copies')
    est = sum(as_num(r.get('est_total')) or 0 for r in plan)
    lines = ['%s orders / %s copies - est %sp' % (fmt_num(orders),
                                                  fmt_num(copies) if copies is not None else '?',
                                                  fmt_int(est))]
    if doc.get('dry_run') is not None:
        lines[0] += ' (dry_run %s, live orders %s)' % (str(bool(doc.get('dry_run'))).lower(),
                                                       fmt_num(doc.get('live_orders')))
    by_section = summary.get('by_section') or {}
    if by_section:
        lines.append('sections: ' + ', '.join(
            '%s %s/%s' % (key, fmt_num(val.get('orders')), fmt_num(val.get('copies')))
            for key, val in by_section.items() if isinstance(val, dict)))
    held = doc.get('held_list') or []
    if held:
        note = '%s rows held back' % fmt_num(len(held))
        first = held[0] if isinstance(held[0], (list, tuple)) else None
        if first:
            note += ' - e.g. %s: %s' % (first[0], first[1] if len(first) > 1 else '')
        lines.append(note)
    return section('plan', 'Plan', lines[:4])


def sec_timing(src):
    stt = src['sell_timing.json']
    if not stt.fresh:
        return section('timing', 'Timing', [stt.no_data()])
    doc = stt.doc or {}
    lines = []
    if doc.get('verdict'):
        line = str(doc['verdict'])
        if doc.get('verdict_reason'):
            line += ' - %s' % clip(doc['verdict_reason'], 150)
        lines.append(line)
    bits = []
    window = (doc.get('next_window') or {}).get('label')
    if window:
        bits.append('next window %s' % window)
    sample = doc.get('sample') or {}
    if as_num(sample.get('sales_total')) is not None:
        text = 'sample %s sales' % fmt_num(sample['sales_total'])
        if as_num(sample.get('active_days')) is not None:
            text += ' over %s active days' % fmt_num(sample['active_days'])
        bits.append(text)
    if bits:
        lines.append(' | '.join(bits))
    if not lines:
        lines.append('no verdict in data/sell_timing.json')
    return section('timing', 'Timing', lines)


def sec_data(src, now):
    ages = ', '.join('%s %s' % (label, fmt_ago(src[name].age)) for name, label in SOURCES)
    return section('data', 'Data', [
        'generated %s | ages: %s' % (local_stamp(now), ages),
    ])


# ------------------------------------------------------------------------- markdown render
def render_markdown(title, sections, caps=None, uniform=None):
    """(text, clipped_ids): bold section titles and one line per fact, ASCII only."""
    parts = [title]
    clipped = []
    for sec in sections:
        lines = list(sec.get('lines') or [])
        if not lines:
            continue
        cap = uniform if uniform is not None else (caps or {}).get(sec['id'])
        if cap is not None and len(lines) > max(1, cap):
            hidden = len(lines) - max(1, cap)
            lines = lines[:max(1, cap)]
            lines[-1] = '%s ... (+%d more)' % (lines[-1], hidden)
            clipped.append(sec['id'])
        parts.append('**%s**' % sec['title'])
        parts.extend(lines)
    return '\n'.join(parts), clipped


def hard_clip(text, limit=DISCORD_LIMIT):
    """Last-resort cut that never leaves a dangling '**' opener or a mid-word run-on."""
    if len(text) <= limit:
        return text
    cut = text[:max(1, limit - 3)].rstrip()
    while cut and cut[-1] == '*':
        cut = cut[:-1].rstrip()
    return cut + '...'


def compose_markdown(title, sections, limit=DISCORD_LIMIT):
    """(text, info) - the first ladder rung that fits the limit wins; text is never over."""
    full, _ = render_markdown(title, sections)
    if len(full) <= limit:
        return full, {'truncated': False, 'stage': 'full', 'clipped': []}
    for caps, uniform, stage in DEGRADE_LADDER:
        text, clipped = render_markdown(title, sections, caps=caps, uniform=uniform)
        if len(text) <= limit:
            return text, {'truncated': True, 'stage': stage, 'clipped': clipped}
    text, clipped = render_markdown(title, sections, uniform=1)
    return hard_clip(text, limit), {'truncated': True, 'stage': 'hard-clip', 'clipped': clipped}


# ------------------------------------------------------------------------------- compose
def build(root, now=None):
    """The full data/daily_digest.json document for one repo root."""
    now = int(time.time()) if now is None else int(now)
    root = os.path.abspath(root)
    src = {name: Source(root, name, label, now) for name, label in SOURCES}

    sections = [
        sec_account(src, now),
        sec_flips(src),
        sec_demand(src),
        sec_baro(src),
        sec_nudges(src),
        sec_wishlist(src),
        sec_plan(src),
        sec_timing(src),
    ]
    sections.append(sec_data(src, now))

    title = '**WFM daily digest - %s**' % local_stamp(now)
    text, info = compose_markdown(title, sections)
    if info['truncated']:
        # the notice rides the footer's own line so no cap rung can clip it away
        sections[-1]['lines'][0] += ' | truncated to fit - full text in %s' % REL_OUT
        text, info = compose_markdown(title, sections)
    full_text, _ = render_markdown(title, sections)

    ages = {name: (None if src[name].age is None else round(src[name].age, 1)) for name, _ in SOURCES}
    missing = [name for name, _ in SOURCES if src[name].age is None]
    stale = [name for name, _ in SOURCES if src[name].age is not None and src[name].age > STALE_MIN]
    notes = []
    if missing:
        notes.append('missing source file(s): %s' % ', '.join(missing))
    if stale:
        notes.append('stale source file(s) over %s: %s'
                     % (fmt_age(STALE_MIN), ', '.join('%s (%s old)' % (n, fmt_age(src[n].age)) for n in stale)))
    if info['truncated']:
        notes.append('discord_markdown truncated at stage %s; discord_markdown_full kept' % info['stage'])
    if not notes:
        notes.append('all sources present and fresh')

    return {
        'version': VERSION,
        'generated': now,
        'generated_iso': iso(now),
        'generated_local': local_stamp(now),
        'sections': sections,
        'discord_markdown': text,
        'discord_markdown_full': full_text,
        'markdown_chars': len(text),
        'markdown_limit': DISCORD_LIMIT,
        'truncated': info['truncated'],
        'truncate_stage': info['stage'],
        'clipped_sections': info['clipped'],
        'source_ages': ages,
        'missing': missing,
        'stale': stale,
        'notes': notes,
    }


def save(root, doc):
    path = os.path.join(os.path.abspath(root), 'data', OUT_NAME)
    jdump(path, doc)
    return path


# ------------------------------------------------------------------------------- notify
def load_module(mod_name, path, extra_paths=()):
    """Import a python file by path, with sibling dirs briefly on sys.path."""
    import importlib.util
    inserted = []
    for folder in extra_paths:
        sys.path.insert(0, folder)
        inserted.append(folder)
    try:
        spec = importlib.util.spec_from_file_location(mod_name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(mod_name, None)
            raise
        return mod
    finally:
        for folder in inserted:
            try:
                sys.path.remove(folder)
            except ValueError:
                pass


def notify_emit(root, doc):
    """Hand the blob to the private trader bridge when it exists; never raise, never guess.

    scripts/trader/* is gitignored and owned by other agents, so this is an optional import:
    absent module -> 'absent', no emit() -> 'no-emit', unexpected failure -> 'error'. The
    emit() call is tried in the call shapes the sibling agents are likely to accept.
    """
    path = os.path.join(os.path.abspath(root), 'scripts', 'trader', 'notify_rules.py')
    if not os.path.exists(path):
        print('[notify] skipped: scripts/trader/notify_rules.py is not present (sibling work in progress)')
        return 'absent'
    try:
        mod = load_module('wfm_notify_rules', path,
                          extra_paths=[os.path.dirname(path), os.path.join(os.path.abspath(root), 'scripts')])
    except Exception as exc:                                  # noqa: BLE001 - never fatal
        print('[notify] skipped: notify_rules.py failed to import (%s: %s)' % (type(exc).__name__, exc))
        return 'error'
    emit = getattr(mod, 'emit', None)
    if not callable(emit):
        print('[notify] skipped: notify_rules.py has no emit() (found: %s)'
              % ', '.join(sorted(n for n in dir(mod) if not n.startswith('_'))[:8] or 'nothing public'))
        return 'no-emit'
    body = doc['discord_markdown']
    attempts = (
        lambda: emit('daily_digest', body),
        lambda: emit('daily_digest', body=body),
        lambda: emit('daily_digest', text=body),
        lambda: emit(kind='daily_digest', body=body),
    )
    last = None
    for index, attempt in enumerate(attempts, 1):
        try:
            result = attempt()
        except TypeError as exc:
            last = exc
            continue
        except Exception as exc:                              # noqa: BLE001 - never fatal
            print('[notify] emit() raised %s: %s' % (type(exc).__name__, exc))
            return 'error'
        print('[notify] emit(daily_digest, ...) accepted call shape %d -> %r' % (index, result))
        return 'sent'
    print('[notify] skipped: emit() signature not recognised (%s)' % last)
    return 'unsupported'


# ---------------------------------------------------------------------------------- main
def build_parser():
    parser = argparse.ArgumentParser(
        prog='digest.py',
        description='Compose the daily digest (one Discord-ready message) from the dashboard '
                    'data files - never re-runs a scanner, never touches the network.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='examples:\n'
               '  digest.py              # compose, print status + markdown, write data/daily_digest.json\n'
               '  digest.py --print      # markdown only on stdout\n'
               '  digest.py --no-save    # plan only: compose and print, write nothing\n'
               '  digest.py --notify     # also hand the blob to scripts/trader/notify_rules.emit()\n'
               '  digest.py --selftest   # offline fixture checks\n')
    parser.add_argument('--root', default=ROOT, help='repo root holding data/ (default: repo)')
    parser.add_argument('--now', default=None, help='override now: epoch seconds or ISO timestamp')
    parser.add_argument('--print', dest='print_only', action='store_true',
                        help='print the Discord markdown only (the status line goes to stderr)')
    parser.add_argument('--save', action='store_true',
                        help='write %s (the default; flag kept for cron clarity)' % REL_OUT)
    parser.add_argument('--no-save', dest='no_save', action='store_true',
                        help='write nothing (dry run / tests)')
    parser.add_argument('--notify', action='store_true',
                        help='hand the blob to scripts/trader/notify_rules.py emit() when present')
    parser.add_argument('--selftest', action='store_true',
                        help='offline fixture checks in a tmp dir, writes nothing')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv[1:] if argv else None)
    if args.selftest:
        return selftest()

    root = os.path.abspath(args.root)
    now = parse_now(args.now)
    doc = build(root, now)

    status = 'wrote %s' % REL_OUT
    if args.no_save:
        status = 'not saved (--no-save)'
    else:
        status = 'wrote %s' % os.path.relpath(save(root, doc), root).replace('\\', '/')
    status = ('[digest] %d sections | markdown %d/%d chars | truncated %s | %s'
              % (len(doc['sections']), doc['markdown_chars'], doc['markdown_limit'],
                 'yes (%s)' % doc['truncate_stage'] if doc['truncated'] else 'no', status))

    if args.print_only:
        print(doc['discord_markdown'])
        print(status, file=sys.stderr)
    else:
        print(status)
        print(doc['discord_markdown'])

    if args.notify:
        notify_emit(root, doc)
    return 0


# ------------------------------------------------------------------------------- selftest
def selftest():
    """Fully offline fixture checks: tmp roots only, no network, nothing written outside tmp."""
    import shutil
    import tempfile

    checks = []
    now = int(time.time())    # frozen for the whole selftest so fixture ages are exact

    def check(name, got, want):
        if got != want:
            raise AssertionError('%s: got %r want %r' % (name, got, want))
        checks.append(name)

    def ok(name, cond):
        if not cond:
            raise AssertionError('%s: condition false' % name)
        checks.append(name)

    def write(root, name, obj, age_min=0.0):
        path = os.path.join(root, 'data', name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(obj, fh, indent=1)
        if age_min:
            stamp = now - age_min * 60.0
            os.utime(path, (stamp, stamp))
        return path

    limits = {'account': 'SampleTennoIX', 'mr': 22, 'trade_cap': 22, 'trades_used': 3,
              'trades_left': 19, 'plat': 1247, 'reset_epoch': now + 39476,
              'reset_melbourne': '2026-09-26T10:00:00+10:00'}
    plat_history = [{'ts': now - 90000, 'plat': 6190}, {'ts': now - 60, 'plat': 1022}]
    kill_off = {'active': False, 'note': '', 'ts': now - 300}
    kill_on = {'active': True, 'note': 'wallet reset', 'ts': now - 300}
    sessions = {'generated': '2026-09-25 22:37', 'gap_min': 45,
                'totals': {'sessions': 125}, 'sessions': [
                    {'date': '2026-09-25', 'end_at': '2026-09-25 22:18', 'kind': 'idle',
                     'sales': 0, 'net': 0, 'dur_min': 96.5}]}
    flip_digest = {
        'generated': now - 3600, 'counts': {'fresh': 309, 'stale_excluded': 80},
        'digest': [
            {'slug': 'zzz_mod', 'name': 'Zzz Mod', 'kind': 'undercut', 'buy_at': 175, 'sell_at': 299,
             'profit': 124, 'margin_pct': 70.9, 'sales_day': 52.5, 'queue_ahead': 2, 'score': 100.0},
            {'slug': 'aaa_mod', 'name': 'Aaa Mod', 'kind': 'spread', 'buy_at': 69, 'sell_at': 300,
             'profit': 231, 'margin_pct': 334.8, 'sales_day': 128.0, 'queue_ahead': 19, 'score': 99.0},
            {'slug': 'mmm_mod', 'name': 'Mmm Mod', 'kind': 'spread', 'buy_at': 5, 'sell_at': 20,
             'profit': 15, 'margin_pct': 300.0, 'sales_day': 4.0, 'queue_ahead': 0, 'score': 1.0},
            {'slug': 'hidden_mod', 'name': 'Should Not Show', 'profit': 9999, 'margin_pct': 900.0},
        ],
        'flips': [{'slug': 'zzz_mod', 'name': 'Zzz Mod', 'profit': 124, 'margin_pct': 70.9,
                   'sales_day': 52.5}]}
    trends = {'generated': now - 600, 'top_spikes': [
                  {'slug': 's1', 'name': 'Spike One', 'vol48': 60, 'ratio': 5.39, 'price_trend_pct': -40.0},
                  {'slug': 's2', 'name': 'Spike Two', 'vol48': 109, 'ratio': 2.04, 'price_trend_pct': 20.0},
                  {'slug': 's3', 'name': 'Spike Three', 'vol48': 3, 'ratio': 2.0, 'price_trend_pct': None}],
              'top_fades': [
                  {'slug': 'f1', 'name': 'Fade One', 'vol48': 0, 'ratio': 0.3, 'price_trend_pct': None},
                  {'slug': 'f2', 'name': 'Fade Two', 'vol48': 30, 'ratio': 0.62, 'price_trend_pct': 66.5},
                  {'slug': 'f3', 'name': 'Fade Three', 'vol48': 5, 'ratio': 0.4, 'price_trend_pct': 1.0}]}
    meta_watch = {'generated': now - 120, 'spike': [
                      {'slug': 'm1', 'name': 'Meta Spike', 'vol48_per_day': 30.0, 'ratio': 5.39,
                       'price_trend_pct': -40.0, 'post_patch': True}],
                  'sink': [{'slug': 'm2', 'name': 'Meta Sink', 'vol48_per_day': 60.5, 'ratio': 0.38,
                            'price_trend_pct': 28.6, 'post_patch': True}]}
    baro = {'generated': now - 600, 'trader': {'character': "Baro Ki'Teer", 'active': False,
                                              'location': 'Kronia Relay (Saturn)',
                                              'starts_in': '7d 0h 8m',
                                              'status_text': "NOT active -- next visit in 7d 0h 8m"},
            'player': {'ducats': 6250, 'credits': 3893672},
            'summary': {'burnable_parts': 29, 'ducats_from_burnable_parts': 2360},
            'wishlist_buys': [], 'rows': []}
    nudges = {'generated': now - 600,
              'counts': {'ready': 5, 'one_away': 9, 'two_away': 24, 'conflicts': 1},
              'ready': [{'slug': 'hydroid_prime_set', 'name': 'Hydroid Prime Set', 'category': 'READY',
                         'action': 'assemble + sell, 1 trade', 'set_value': 73.0, 'urgency': 73.0},
                        {'slug': 'inaros_prime_set', 'name': 'Inaros Prime Set', 'category': 'READY',
                         'action': 'assemble + sell, 1 trade', 'set_value': 61.0, 'urgency': 61.0}],
              'one_away': [{'slug': 'larkspur_prime_set', 'name': 'Larkspur Prime Set',
                            'category': 'ONE_AWAY', 'missing_name': 'Larkspur Prime Stock',
                            'cost_est': 6.7, 'set_value': 62.7, 'urgency': 33.6},
                           {'slug': 'harrow_prime_set', 'name': 'Harrow Prime Set',
                            'category': 'ONE_AWAY', 'missing_name': 'Harrow Prime Neuroptics Blueprint',
                            'cost_est': 6.7, 'set_value': 54.7, 'urgency': 28.8}]}
    wishlist = {'generated': now - 600,
                'summary': {'buy_now_count': 6, 'budget_needed': 94, 'budget_available': 1247,
                            'budget_leftover': 1153, 'trades_needed': 6, 'status': 'OK'},
                'suggested': [
                    {'slug': 'bronco_prime_barrel', 'name': 'Bronco Prime Barrel', 'status': 'BUY_NOW',
                     'max_price': 7, 'floor': 2, 'ratio': 3.5, 'set_action': 'COMPLETE_MAYBE'},
                    {'slug': 'revenant_prime_blueprint', 'name': 'Revenant Prime Blueprint',
                     'status': 'BUY_NOW', 'max_price': 34, 'floor': 20, 'ratio': 1.7,
                     'set_action': 'COMPLETE'},
                    {'slug': 'harrow_prime_neuroptics_blueprint', 'name': 'Harrow Prime Neuroptics BP',
                     'status': 'BUY_NOW', 'max_price': 7, 'floor': 5, 'ratio': 1.4,
                     'set_action': 'COMPLETE'},
                    {'slug': 'nope', 'name': 'Wait Row', 'status': 'WAIT', 'max_price': 9, 'floor': 1}]}
    trader_plan = {'generated': now - 600, 'dry_run': True, 'live_orders': 0,
                   'summary': {'orders': 19, 'copies': 130,
                               'by_section': {'mod': {'orders': 8, 'copies': 36},
                                              'relic': {'orders': 6, 'copies': 71}}},
                   'plan': [{'slug': 'primed_continuity', 'name': 'Primed Continuity', 'qty': 3,
                             'est_total': 141},
                            {'slug': 'neo_d3_relic', 'name': 'Neo D3 Relic', 'qty': 18,
                             'est_total': 126}],
                   'held_list': [['Esher Devar', 'below min price (1p < 3p)']]}
    sell_timing = {'generated': now - 300, 'verdict': 'HOLD',
                   'verdict_reason': '23:00 AEST has 5 sales in sample; next window Mon 02:00 (in 2.1d)',
                   'next_window': {'dow': 0, 'hour': 2, 'label': 'Mon 02:00 (in 2.1d)'},
                   'sample': {'sales_total': 122, 'active_days': 17, 'span_days': 455.7}}
    fixtures = {'trader_limits.json': limits, 'plat_history.json': plat_history,
                'kill_switch.json': kill_off, 'session_stats.json': sessions,
                'flip_digest.json': flip_digest, 'trends.json': trends, 'meta_watch.json': meta_watch,
                'baro.json': baro, 'nudges.json': nudges, 'wishlist.json': wishlist,
                'trader_plan.json': trader_plan, 'sell_timing.json': sell_timing}

    tmp = tempfile.mkdtemp(prefix='digest_selftest_')
    try:
        root = os.path.join(tmp, 'repo')
        os.makedirs(os.path.join(root, 'data'))

        # 1) nothing on disk at all: every section says 'no data', nothing raises
        empty_doc = build(root, now)
        check('missing-files: 9 sections', len(empty_doc['sections']), 9)
        check('missing-files: section ids', [s['id'] for s in empty_doc['sections']],
              ['account', 'flips', 'demand', 'baro', 'nudges', 'wishlist', 'plan', 'timing', 'data'])
        check('missing-files: flips says no data',
              empty_doc['sections'][1]['lines'][0], 'no data (data/flip_digest.json missing)')
        ok('missing-files: markdown still fits',
           len(empty_doc['discord_markdown']) <= DISCORD_LIMIT)
        check('missing-files: source_ages are None', set(empty_doc['source_ages'].values()), {None})
        check('missing-files: missing list', len(empty_doc['missing']), len(SOURCES))

        # 2) the full fixture: every section carries real numbers
        for name, obj in fixtures.items():
            write(root, name, obj)
        write(root, 'trends.json', trends, age_min=10)     # exact footer age for the check below
        doc = build(root, now)
        by_id = {s['id']: s for s in doc['sections']}
        check('fixture: sections', len(doc['sections']), 9)
        check('fixture: account line', by_id['account']['lines'][0],
              'SampleTennoIX | MR 22 | 1,247p (trader_limits)')
        check('fixture: trades line', by_id['account']['lines'][1].split(' | ')[0],
              'trades 3/22 used - 19 left')
        check('fixture: kill switch line', by_id['account']['lines'][2], 'kill switch: off')
        check('fixture: last session line', by_id['account']['lines'][3],
              'last session 2026-09-25 22:18 - idle, 0 sales, net 0p (96.5m)')
        ok('fixture: flips keep the digest order (no re-rank)',
           by_id['flips']['lines'][0].startswith('1. Zzz Mod [undercut]'))
        ok('fixture: flip line shows margin + sales/day',
           '124p (+70.9%)' in by_id['flips']['lines'][0] and '52.5/day' in by_id['flips']['lines'][0])
        check('fixture: 3 flips + provenance line', len(by_id['flips']['lines']), 4)
        check('fixture: demand spikes+fades', len(by_id['demand']['lines']), 4)
        ok('fixture: spike line', by_id['demand']['lines'][0].startswith('SPIKE Spike One - 5.39x/30d'))
        ok('fixture: fade line', by_id['demand']['lines'][2].startswith('FADE Fade One - 0.30x/30d'))
        ok('fixture: baro countdown', "in 7d 0h 8m" in by_id['baro']['lines'][0])
        ok('fixture: baro money line', by_id['baro']['lines'][1].startswith('ducats 6,250 (+2,360 from 29 burnable parts)'))
        check('fixture: nudges rows', len(by_id['nudges']['lines']), 4)
        ok('fixture: most urgent nudge first', by_id['nudges']['lines'][0].startswith('[READY] Hydroid Prime Set'))
        ok('fixture: one-away row spells the missing part',
           '[ONE_AWAY] Larkspur Prime Set - buy Larkspur Prime Stock (~6.7p)' in by_id['nudges']['lines'][2])
        ok('fixture: wishlist budget', by_id['wishlist']['lines'][0].startswith('BUY_NOW 6 - 94p of 1,247p (headroom 1,153p'))
        ok('fixture: wishlist rows exclude WAIT', len(by_id['wishlist']['lines']) == 4)
        ok('fixture: plan line', by_id['plan']['lines'][0].startswith('19 orders / 130 copies - est 267p'))
        ok('fixture: timing verdict', by_id['timing']['lines'][0].startswith('HOLD - 23:00 AEST has 5 sales'))
        ok('fixture: timing sample', 'sample 122 sales over 17 active days' in by_id['timing']['lines'][1])
        ok('fixture: footer carries the source ages',
           by_id['data']['lines'][0].startswith('generated ') and 'trends 10m ago' in by_id['data']['lines'][0])
        ok('fixture: markdown fits', len(doc['discord_markdown']) <= DISCORD_LIMIT)
        ok('fixture: footer ages survive the cut', 'ages:' in doc['discord_markdown'])
        ok('fixture: every title survives',
           all(('**%s**' % s['title']) in doc['discord_markdown'] for s in doc['sections']))
        check('fixture: markdown_chars matches', doc['markdown_chars'], len(doc['discord_markdown']))
        check('fixture: generated honours --now', doc['generated'], now)
        ok('fixture: source ages are minutes', doc['source_ages']['trends.json'] == 10.0)

        # 2b) a lean digest (one row per section) must fit without any truncation
        lean_root = os.path.join(tmp, 'lean')
        os.makedirs(os.path.join(lean_root, 'data'))
        lean = dict(fixtures)
        lean['flip_digest.json'] = {'counts': {'fresh': 4, 'stale_excluded': 1},
                                    'digest': [flip_digest['digest'][0]]}
        lean['trends.json'] = {'top_spikes': trends['top_spikes'][:1], 'top_fades': trends['top_fades'][:1]}
        lean['nudges.json'] = {'counts': {'ready': 1}, 'ready': [nudges['ready'][0]]}
        lean['wishlist.json'] = {'summary': wishlist['summary'], 'suggested': [wishlist['suggested'][0]]}
        lean['trader_plan.json'] = {'dry_run': True, 'summary': {'orders': 1, 'copies': 3},
                                    'plan': [{'est_total': 30}]}
        for name, obj in lean.items():
            write(lean_root, name, obj)
        lean_doc = build(lean_root, now)
        check('lean fixture: not truncated', lean_doc['truncated'], False)
        ok('lean fixture: fits with room', len(lean_doc['discord_markdown']) <= DISCORD_LIMIT)
        ok('lean fixture: all titles present',
           all(('**%s**' % s['title']) in lean_doc['discord_markdown'] for s in lean_doc['sections']))

        # 3) plat falls back to the plat_history last point
        write(root, 'trader_limits.json', dict(limits, plat=None))
        ok('plat fallback: plat_history last point wins',
           '1,022p (plat_history' in build(root, now)['sections'][0]['lines'][0])
        write(root, 'trader_limits.json', limits)

        # 4) a stale file reads as no data with its age; demand falls back to the other source
        write(root, 'trends.json', trends, age_min=3 * 1440)
        stale_doc = build(root, now)
        ok('stale: demand falls back to the fresh meta_watch',
           stale_doc['sections'][2]['lines'][0].startswith('SPIKE Meta Spike'))
        check('stale: stale list names the file', stale_doc['stale'], ['trends.json'])
        ok('stale: notes mention the stale file',
           any('stale source file(s)' in note and 'trends.json' in note for note in stale_doc['notes']))
        write(root, 'meta_watch.json', meta_watch, age_min=3 * 1440)
        both = build(root, now)
        check('stale: both demand sources stale -> no data with ages', both['sections'][2]['lines'][0],
              'no data (data/trends.json 3.0d old; data/meta_watch.json 3.0d old)')
        write(root, 'trends.json', trends)
        write(root, 'meta_watch.json', meta_watch)

        # 5) empty (but valid) documents never crash and say what is missing
        for name in fixtures:
            write(root, name, {})
        blank = build(root, now)
        check('empty docs: still 9 sections', len(blank['sections']), 9)
        ok('empty docs: no ranked flips wording', blank['sections'][1]['lines'][0].startswith('no ranked flips'))
        ok('empty docs: nudges wording', blank['sections'][4]['lines'][0].startswith('no READY or ONE_AWAY'))
        ok('empty docs: plan wording', blank['sections'][6]['lines'][0].startswith('0 orders / ? copies'))
        ok('empty docs: markdown fits', len(blank['discord_markdown']) <= DISCORD_LIMIT)

        # 6) truncation: long lines across every section must degrade, never overflow
        for name, obj in fixtures.items():
            write(root, name, obj)
        write(root, 'wishlist.json', {
            'summary': wishlist['summary'],
            'suggested': [dict(wishlist['suggested'][0],
                               name='Wishlist Row With An Absurdly Long Name ' + 'x' * 90, ratio=1.5),
                          dict(wishlist['suggested'][1], name='Second Very Long Wishlist Row ' + 'y' * 90),
                          dict(wishlist['suggested'][2], name='Third Very Long Wishlist Row ' + 'z' * 90),
                          dict(wishlist['suggested'][3])]})
        write(root, 'flip_digest.json', {
            'counts': flip_digest['counts'],
            'digest': [dict(flip_digest['digest'][0], name='A Very Long Flip Name ' + 'a' * 120),
                       dict(flip_digest['digest'][1], name='Another Very Long Flip Name ' + 'b' * 120),
                       dict(flip_digest['digest'][2], name='Third Very Long Flip Name ' + 'c' * 120),
                       dict(flip_digest['digest'][3])]})
        busy = build(root, now)
        ok('truncation: hard cap honoured', len(busy['discord_markdown']) <= DISCORD_LIMIT)
        check('truncation: flagged', busy['truncated'], True)
        ok('truncation: full text kept', len(busy['discord_markdown_full']) >= len(busy['discord_markdown']))
        ok('truncation: every title survives',
           all(('**%s**' % s['title']) in busy['discord_markdown'] for s in busy['sections']))
        ok('truncation: clipped sections are named', isinstance(busy['clipped_sections'], list))
        ok('truncation: notice in the footer',
           any('truncated to fit' in line for line in busy['sections'][-1]['lines']))
        ok('truncation: stage recorded', busy['truncate_stage'] in
           ('trim-session', 'trim-stock', 'trim-rows', 'trim-tally', 'trim-ducats',
            'trim-provenance', 'uniform-2', 'uniform-1', 'hard-clip'))

        # 7) the composer writes the json atomically and reads it back
        for name, obj in fixtures.items():
            write(root, name, obj)
        saved = build(root, now)
        out = save(root, saved)
        with open(out, encoding='utf-8') as fh:
            loaded = json.load(fh)
        check('save: path', os.path.basename(out), OUT_NAME)
        check('save: sections round-trip', len(loaded['sections']), 9)
        check('save: markdown round-trip', loaded['discord_markdown'], saved['discord_markdown'])
        ok('save: source_ages keys', set(loaded['source_ages']) == {n for n, _ in SOURCES})
        ok('save: no tmp file left behind', not os.path.exists(out + '.tmp'))

        # 8) a data/ dir that does not exist at all is not fatal
        bare = os.path.join(tmp, 'bare')
        os.makedirs(bare)
        bare_doc = build(bare, now)
        check('no data dir: still composes', len(bare_doc['sections']), 9)

        # 9) notify bridge: absent module -> skipped, stub module -> called
        status = notify_emit(root, saved)
        check('notify: absent module is skipped', status, 'absent')
        trader_dir = os.path.join(root, 'scripts', 'trader')
        os.makedirs(trader_dir)
        calls = []
        with open(os.path.join(trader_dir, 'notify_rules.py'), 'w', encoding='utf-8') as fh:
            fh.write('calls = []\n\n\ndef emit(kind, body):\n'
                     '    calls.append((kind, body))\n'
                     '    return {"kind": kind, "chars": len(body)}\n')
        status = notify_emit(root, saved)
        check('notify: stub module accepted the first call shape', status, 'sent')
        with open(os.path.join(trader_dir, 'notify_rules.py'), 'w', encoding='utf-8') as fh:
            fh.write('calls = []\n\n\ndef emit(kind, *, body):\n'
                     '    calls.append((kind, body))\n'
                     '    return {"kind": kind, "chars": len(body)}\n')
        status = notify_emit(root, saved)
        check('notify: keyword-only stub falls back to shape 2', status, 'sent')
        with open(os.path.join(trader_dir, 'notify_rules.py'), 'w', encoding='utf-8') as fh:
            fh.write('def emit(*args, **kwargs):\n    raise RuntimeError("boom")\n')
        status = notify_emit(root, saved)
        check('notify: raising stub is reported, not fatal', status, 'error')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('selftest OK - %d checks (tmp fixtures, no network, nothing written outside tmp)' % len(checks))
    return 0


if __name__ == '__main__':
    sys.exit(main())
