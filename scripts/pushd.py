#!/usr/bin/env python3
r"""WFM push daemon: one grouped digest per run for whatever is NEW since the last run.

Runs as a one-shot cycle (cron / Task Scheduler friendly). Every trigger keeps its own
last-seen marker inside data/pushd_state.json, so each message fires exactly once and a
re-run with nothing new is silent.

Triggers (state marker -> message):
  (a) new data/trade_log.json events      marker: trade_log.last_ts + trade_log.sigs
      An event is new when its signature (ts|kind|slug-or-name|qty|plat) is unknown AND
      its ts is at least the marker's last_ts - so nothing already sent fires again, a
      same-second sibling is still caught by the signature, and backfilled history
      (older ts, e.g. an AlecaFrame import) is recorded but never alerted.
      Lines: '[sale] Name x1 @ 42p - with Buyer' / '[buy] Name x6 @ 7p (42p total)'.
  (b) new data/watchlist.json alerts[]    marker: watch_alerts.seen
      Alert key = level|slug|floor; a key not seen before fires exactly once.
      Line:  '[watch] <the alert's own one-line message>'.
  (c) trades exhausted                    marker: limits.last_window
      data/trader_limits.json trades_left <= 0 fires once per reset window (window key =
      reset_epoch, else reset_utc / reset_melbourne / generated_utc). The marker is not
      cleared when trades come back, so a second zero inside the same window stays quiet.
      Line:  '[limits] trades exhausted - 0/22 left, resets 2026-09-26T10:00:00+10:00'.
  (d) kill switch armed                   marker: kill_switch.last_active
      data/kill_switch.json active false -> true fires once; re-arming after a disarm
      fires again. A file that exists but cannot be read is reported ARMED (fail-closed,
      same rule as scripts/trader/killswitch.py). An absent file is simply not armed.
      Line:  '[safety] kill switch ARMED - <note>'.
  (e) Baro window open                    marker: baro.last_active
      data/baro.json trader.active false -> true fires once, with the relay and close time.
      Line:  '[baro] Baro Ki'Teer window open - Kronia Relay (Saturn), closes ...'.

First run (no readable state file yet): (a) and (b) are baselined - pre-existing events and
alerts are recorded, never messaged - while (c)/(d)/(e) fire immediately if already true,
because a zero-trade stock, an armed kill switch or an open Baro window is current state
worth hearing about once.

Delivery: every due line is grouped into ONE digest handed to scripts/notify.py as
send(title='WFM Trader digest', body='\n'.join(lines), rule='digest'). notify's config,
rules switchboard and dry_run are honoured by notify itself - nothing here bypasses them.
When notify rules the digest out, or a delivery ends 'failed'/'skipped', the state file is
NOT advanced: those lines stay pending and go out on a later run instead of being
silently dropped. Lines are ordered safety -> baro -> limits -> trades -> watch.

Usage:
  python scripts/pushd.py            # one scan + one digest (--once is the same thing)
  python scripts/pushd.py --print    # compose and print; no send, no state write
  python scripts/pushd.py --selftest # fully offline fixture checks (tmp dirs, no network)

Writes: data/pushd_state.json only, atomically (tmp file + os.replace). Reads the five
data files above read-only. Env hooks: PUSHD_DATA_DIR, PUSHD_STATE_PATH.
Exit codes: 0 = ok (including nothing to send), 1 = delivery problem, 2 = bad args.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, 'data')
sys.path.insert(0, HERE)
import notify  # noqa: E402  (scripts/notify.py - the shared sender core, never bypassed)

VERSION = 1
STATE_NAME = 'pushd_state.json'
INPUTS = ('trade_log.json', 'watchlist.json', 'trader_limits.json', 'kill_switch.json',
          'baro.json')
DIGEST_TITLE = 'WFM Trader digest'
DIGEST_RULE = 'digest'
ALERT_KINDS = ('sale', 'purchase')
PREFIX = {'sale': '[sale]', 'purchase': '[buy]'}
SIG_KEEP = 300          # newest event signatures remembered
SEEN_KEEP = 300         # newest watchlist alert keys remembered
NOTE_CLIP = 70          # event note embedded in a sale line
MAX_LINES = 20          # digest lines per run ('+N more' beyond this)
BODY_LIMIT = 1800       # digest body cap (notify clips its own payloads too)


# ------------------------------------------------------------------- json / paths / text
def rel(path):
    """Path relative to the repo root, forward slashes (falls back to the raw path)."""
    try:
        return os.path.relpath(path, ROOT).replace('\\', '/')
    except ValueError:
        return str(path).replace('\\', '/')


def utc_now(epoch=None):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ',
                         time.gmtime(int(epoch if epoch is not None else time.time())))


def one_line(value, width=None):
    """Single-line plain-ASCII text: control/PUA chars dropped, runs squeezed, clipped.

    ASCII-only keeps stdout safe on a cp1252 Windows pipe (house style) and keeps the
    digest body a list of clean one-liners.
    """
    text = str(value) if value is not None else ''
    text = ''.join(ch if ch.isprintable() else ' ' for ch in text)
    text = ' '.join(text.split())
    text = text.encode('ascii', 'replace').decode('ascii')
    if width is not None and len(text) > width:
        text = text[:max(0, width - 3)] + '...'
    return text


def jload(path):
    """(doc, error). Missing file -> (None, None); unreadable -> (None, short reason)."""
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh), None
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as exc:
        return None, '%s: %s' % (type(exc).__name__, exc)


def jdump(path, doc):
    """Atomic write: same-dir tmp file + os.replace, so readers never see a half file."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, indent=1)
    os.replace(tmp, path)


def resolve_paths():
    """Env-overridable paths, resolved per call so tests/selftest redirect all of them."""
    data = os.environ.get('PUSHD_DATA_DIR') or DATA
    paths = {'data': data,
             'state': os.environ.get('PUSHD_STATE_PATH') or os.path.join(data, STATE_NAME)}
    for name in INPUTS:
        paths[name[:-5]] = os.path.join(data, name)
    return paths


# ------------------------------------------------------------------------------- state
def blank_state():
    """The documented state shape: one marker block per trigger, nothing shared."""
    return {'version': VERSION, 'last_run_utc': None, 'digests_sent': 0,
            'last_digest_utc': None,
            'trade_log': {'last_ts': None, 'sigs': []},
            'watch_alerts': {'seen': []},
            'limits': {'last_window': None},
            'kill_switch': {'last_active': False},
            'baro': {'last_active': False}}


def normalize_state(raw):
    """Tolerant read: fill missing/invalid keys from the blank shape, never raise."""
    out = blank_state()
    if not isinstance(raw, dict):
        return out
    for key in ('last_run_utc', 'last_digest_utc'):
        if isinstance(raw.get(key), str):
            out[key] = raw[key]
    if isinstance(raw.get('digests_sent'), int) and not isinstance(raw['digests_sent'], bool):
        out['digests_sent'] = max(0, raw['digests_sent'])
    tl = raw.get('trade_log') if isinstance(raw.get('trade_log'), dict) else {}
    ts = tl.get('last_ts')
    if isinstance(ts, int) and not isinstance(ts, bool):
        out['trade_log']['last_ts'] = ts
    if isinstance(tl.get('sigs'), list):
        out['trade_log']['sigs'] = [s for s in tl['sigs'] if isinstance(s, str)][-SIG_KEEP:]
    wa = raw.get('watch_alerts') if isinstance(raw.get('watch_alerts'), dict) else {}
    if isinstance(wa.get('seen'), list):
        out['watch_alerts']['seen'] = [s for s in wa['seen'] if isinstance(s, str)][-SEEN_KEEP:]
    lim = raw.get('limits') if isinstance(raw.get('limits'), dict) else {}
    if isinstance(lim.get('last_window'), (str, int)) and not isinstance(lim['last_window'], bool):
        out['limits']['last_window'] = str(lim['last_window'])
    for key in ('kill_switch', 'baro'):
        block = raw.get(key) if isinstance(raw.get(key), dict) else {}
        if isinstance(block.get('last_active'), bool):
            out[key]['last_active'] = block['last_active']
    return out


# ---------------------------------------------------------------------------- triggers
def sig_of(event):
    """Event identity: ts + items (kind, slug/name, qty, plat) - stable across re-imports."""
    return '%s|%s|%s|%s|%s' % (event.get('ts'), event.get('kind'),
                               event.get('slug') or event.get('name'),
                               event.get('qty'), event.get('plat'))


def trade_event_line(event):
    name = one_line(event.get('name') or event.get('slug') or '?')
    qty, plat, total = event.get('qty'), event.get('plat'), event.get('total')
    if plat is None:
        money = 'price n/a'
    elif qty not in (None, 1) and total and total != plat:
        money = '%sp each (%sp total)' % (plat, total)
    else:
        money = '%sp' % plat
    line = '%s %s x%s @ %s' % (PREFIX.get(event.get('kind'), '[trade]'), name,
                               qty if qty is not None else '?', money)
    note = one_line(event.get('note'), NOTE_CLIP)
    return '%s - %s' % (line, note) if note else line


def watch_alert_key(alert):
    """Alert identity: level + slug + floor, exactly as the watchlist reports them."""
    return '%s|%s|%s' % (alert.get('level'), alert.get('slug'), alert.get('floor'))


def watch_alert_line(alert):
    message = one_line(alert.get('message'))
    if message:
        return '[watch] %s' % message
    level = str(alert.get('level') or 'hit').upper()
    name = one_line(alert.get('name') or alert.get('slug') or '?')
    floor = alert.get('floor')
    return '[watch] %s %s%s' % (level, name,
                                ' (floor %sp)' % floor if floor is not None else '')


def limit_window(doc):
    """Reset-window identity for the once-per-window limits message."""
    if not isinstance(doc, dict):
        return None
    for key in ('reset_epoch', 'reset_utc', 'reset_melbourne', 'generated_utc'):
        value = doc.get(key)
        if value not in (None, ''):
            return '%s=%s' % (key, value)
    return 'unknown'


def trade_trigger(rows, marker, first_run):
    """(lines, new marker, info). New = unknown signature with ts >= the marker's last_ts."""
    sigs = list(marker.get('sigs') or [])
    known = set(sigs)
    last_ts = marker.get('last_ts')
    newest = last_ts if isinstance(last_ts, int) else None
    lines, fresh = [], 0
    for event in rows if isinstance(rows, list) else []:
        if not isinstance(event, dict):
            continue
        ts = event.get('ts')
        if not isinstance(ts, int) or isinstance(ts, bool):
            continue
        sig = sig_of(event)
        if not first_run and last_ts is not None and sig not in known and ts >= last_ts:
            fresh += 1
            if event.get('kind') in ALERT_KINDS:
                lines.append(trade_event_line(event))
        if sig not in known:
            known.add(sig)
            sigs.append(sig)
        if newest is None or ts > newest:
            newest = ts
    total = len(rows) if isinstance(rows, list) else 0
    info = '%d event(s), %d new, %d line(s)%s' % (total, fresh, len(lines),
                                                  ' (first run: baseline)' if first_run else '')
    return lines, {'last_ts': newest, 'sigs': sigs[-SIG_KEEP:]}, info


def watch_trigger(alerts, marker, first_run):
    """(lines, new marker, info). One line per alert key never seen before."""
    seen = list(marker.get('seen') or [])
    known = set(seen)
    lines, fresh, total = [], 0, 0
    for alert in alerts if isinstance(alerts, list) else []:
        if not isinstance(alert, dict):
            continue
        total += 1
        key = watch_alert_key(alert)
        if key in known:
            continue
        known.add(key)
        seen.append(key)
        fresh += 1
        if not first_run:
            lines.append(watch_alert_line(alert))
    info = '%d alert(s), %d new, %d line(s)%s' % (total, fresh, len(lines),
                                                  ' (first run: baseline)' if first_run else '')
    return lines, {'seen': seen[-SEEN_KEEP:]}, info


def limits_trigger(doc, marker):
    """(lines, new marker, info). trades_left <= 0 fires once per reset window."""
    left = doc.get('trades_left') if isinstance(doc, dict) else None
    if not isinstance(left, int) or isinstance(left, bool) or left > 0:
        return [], marker, 'trades_left %s' % left
    window = limit_window(doc)
    if marker.get('last_window') == window:
        return [], marker, 'trades_left %d (window %s already sent)' % (left, window)
    cap = doc.get('trade_cap')
    resets = doc.get('reset_melbourne') or doc.get('reset_utc') or 'unknown reset'
    line = '[limits] trades exhausted - %d%s left, resets %s' % (
        left, '/%s' % cap if cap is not None else '', resets)
    return [line], {'last_window': window}, 'trades_left %d (window %s)' % (left, window)


def kill_trigger(doc, error, marker):
    """(lines, new marker, info). false -> true fires once; unreadable reads as ARMED."""
    if error:
        active, detail = True, 'unreadable - fail-closed'
    else:
        active = bool(isinstance(doc, dict) and doc.get('active'))
        detail = one_line((doc or {}).get('note'), 80) if isinstance(doc, dict) else ''
    if not active:
        return [], {'last_active': False}, 'off'
    if marker.get('last_active') is True:
        return [], marker, 'armed (already reported)'
    line = '[safety] kill switch ARMED' + (' - %s' % detail if detail
                                           else ' (data/kill_switch.json)')
    return [line], {'last_active': True}, 'armed'


def baro_trigger(doc, marker):
    """(lines, new marker, info). trader.active false -> true fires once."""
    trader = (doc or {}).get('trader') if isinstance(doc, dict) else {}
    trader = trader if isinstance(trader, dict) else {}
    if not trader.get('active'):
        return [], {'last_active': False}, 'closed'
    if marker.get('last_active') is True:
        return [], marker, 'open (already reported)'
    where = one_line(trader.get('location'))
    closes = one_line(trader.get('expiry_text') or trader.get('closes_in'))
    line = '[baro] %s window open' % one_line(trader.get('character') or 'Baro')
    if where:
        line += ' - %s' % where
    if closes:
        line += ', closes %s' % closes
    return [line], {'last_active': True}, 'open'


def compose(lines):
    """One digest: line-count and body-size capped, input order preserved."""
    shown = [one_line(line) for line in lines]
    extra = max(0, len(shown) - MAX_LINES)
    body = '\n'.join(shown[:MAX_LINES])
    if extra:
        body += '\n(+%d more this run)' % extra
    if len(body) > BODY_LIMIT:
        body = body[:BODY_LIMIT - 3] + '...'
    return DIGEST_TITLE, body


# --------------------------------------------------------------------------- cycle
def run(paths=None, print_only=False, now=None):
    """One poll cycle: scan, compose, deliver, persist. 0 = ok, 1 = delivery problem."""
    paths = paths or resolve_paths()
    now = int(time.time() if now is None else now)

    raw, state_error = jload(paths['state'])
    first_run = not isinstance(raw, dict)
    if state_error:
        print('WARN %s unreadable (%s) - starting a fresh baseline'
              % (rel(paths['state']), state_error))
    elif raw is not None and not isinstance(raw, dict):
        print('WARN %s is not a JSON object - starting a fresh baseline' % rel(paths['state']))
    state = normalize_state(raw)

    trade_doc, _ = jload(paths['trade_log'])
    trade_lines, trade_marker, trade_info = trade_trigger(trade_doc, state['trade_log'],
                                                          first_run)
    watch_doc, _ = jload(paths['watchlist'])
    watch_lines, watch_marker, watch_info = watch_trigger(
        (watch_doc or {}).get('alerts') if isinstance(watch_doc, dict) else None,
        state['watch_alerts'], first_run)
    limits_doc, _ = jload(paths['trader_limits'])
    limits_lines, limits_marker, limits_info = limits_trigger(limits_doc, state['limits'])
    kill_doc, kill_error = jload(paths['kill_switch'])
    kill_lines, kill_marker, kill_info = kill_trigger(kill_doc, kill_error,
                                                      state['kill_switch'])
    baro_doc, _ = jload(paths['baro'])
    baro_lines, baro_marker, baro_info = baro_trigger(baro_doc, state['baro'])

    state.update(trade_log=trade_marker, watch_alerts=watch_marker, limits=limits_marker,
                 kill_switch=kill_marker, baro=baro_marker, last_run_utc=utc_now(now))
    lines = kill_lines + baro_lines + limits_lines + trade_lines + watch_lines

    print('pushd: scan %s (state %s)' % (rel(paths['data']), rel(paths['state'])))
    print('  trade_log   %s' % trade_info)
    print('  watchlist   %s' % watch_info)
    print('  limits      %s' % limits_info)
    print('  kill_switch %s' % kill_info)
    print('  baro        %s' % baro_info)

    if not lines:
        print('nothing to send%s' % (' (first run: baseline recorded)' if first_run else ''))
        if print_only:
            print('--print: %s not written' % rel(paths['state']))
            return 0
        jdump(paths['state'], state)
        return 0

    title, body = compose(lines)
    if print_only:
        print(title)
        for line in body.split('\n'):
            print('  %s' % line)
        print('--print: composed %d message(s); notify.send() not called, %s not written'
              % (len(lines), rel(paths['state'])))
        return 0

    try:
        rows = notify.send(title, body, rule=DIGEST_RULE)
    except notify.NotifyError as exc:
        print('delivery problem: %s' % exc)
        print('state not advanced - %d message(s) stay pending for the next run' % len(lines))
        return 1
    if not rows:
        print("digest held back by notify's rules switchboard (rules.%s = false in %s)"
              % (DIGEST_RULE, notify.rel(notify.CONFIG_PATH)))
        print('state not advanced - %d message(s) stay pending for the next run' % len(lines))
        return 0

    bad = [row for row in rows if row.get('status') in ('failed', 'skipped')]
    if bad:
        print('digest delivery failed (%s) - state not advanced, %d message(s) stay pending'
              % (', '.join('%s:%s' % (row.get('to'), row.get('status')) for row in bad),
                 len(lines)))
        return 1

    state['digests_sent'] += 1
    state['last_digest_utc'] = utc_now(now)
    jdump(paths['state'], state)
    statuses = ', '.join(sorted({str(row.get('status')) for row in rows}))
    print('digest delivered: %d line(s) -> %d target(s) (%s)' % (len(lines), len(rows), statuses))
    return 0


# ----------------------------------------------------------------------- selftest
def selftest():
    """Fully offline: tmp fixtures, notify.send patched to a recorder, no network.

    The real data/ files (state, notify config, outbox) are hashed before and after to
    prove the selftest never touches them.
    """
    results = []

    def check(label, ok, detail=''):
        ok = bool(ok)
        results.append(ok)
        print('%s  %s%s' % ('PASS' if ok else 'FAIL', label, (' - %s' % detail) if detail else ''))
        return ok

    def write(path, doc):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh, indent=1)
        return path

    def write_raw(path, text):
        """Deliberately broken file content (json.dump would make a valid JSON string)."""
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(text)
        return path

    tmp = tempfile.mkdtemp(prefix='pushd_selftest_')
    real = {p: notify.file_hash(p) for p in (os.path.join(DATA, STATE_NAME),
                                             notify.CONFIG_PATH, notify.OUTBOX_PATH)}
    real_send = notify.send
    sent = []

    def recorder(title, body='', **kwargs):
        sent.append({'title': title, 'body': body, 'kwargs': kwargs})
        return [{'ts': 'selftest', 'to': 'recorder', 'title': title, 'body': body,
                 'status': 'dry_run'}]

    try:
        notify.send = recorder
        data = os.path.join(tmp, 'data')
        os.makedirs(data)
        paths = {'data': data, 'state': os.path.join(data, STATE_NAME)}
        for name in INPUTS:
            paths[name[:-5]] = os.path.join(data, name)

        def go(now):
            return run(paths, now=now)

        # ---------------- fixtures: two pre-existing events, one alert, a healthy account
        sale = {'ts': 1000, 'kind': 'sale', 'name': 'Primed Continuity', 'qty': 1, 'plat': 42,
                'total': 42, 'note': 'with BuyerOne'}
        buy = {'ts': 1001, 'kind': 'purchase', 'name': 'Neo D3 Relic', 'qty': 6, 'plat': 7,
               'total': 42, 'note': 'with SellerOne'}
        alert = {'level': 'buy', 'slug': 'primed_target_cracker', 'name': 'Primed Target Cracker',
                 'floor': 35, 'target': 60, 'distance_p': 25, 'vol48': 129,
                 'message': 'BUY Primed Target Cracker: floor 35p <= max_buy 60p'}
        write(paths['trade_log'], [sale, buy])
        write(paths['watchlist'], {'alerts': [alert]})
        write(paths['trader_limits'], {'trades_left': 22, 'trade_cap': 22, 'reset_epoch': 5000,
                                       'reset_melbourne': '2026-09-26T10:00:00+10:00'})
        write(paths['kill_switch'], {'active': False, 'note': '', 'ts': 900})
        write(paths['baro'], {'trader': {'active': False, 'character': "Baro Ki'Teer"}})

        # 1. first run baselines (a) and (b), sends nothing, writes the documented shape
        rc = go(2000)
        st = jload(paths['state'])[0]
        check('first run baselines pre-existing events/alerts and sends nothing',
              rc == 0 and sent == [])
        check('state file written with the documented shape',
              isinstance(st, dict) and sorted(st) == ['baro', 'digests_sent', 'kill_switch',
                                                      'last_digest_utc', 'last_run_utc',
                                                      'limits', 'trade_log', 'version',
                                                      'watch_alerts']
              and st['version'] == VERSION
              and st['trade_log']['last_ts'] == 1001 and len(st['trade_log']['sigs']) == 2
              and st['watch_alerts']['seen'] == ['buy|primed_target_cracker|35']
              and st['kill_switch']['last_active'] is False
              and st['baro']['last_active'] is False and st['limits']['last_window'] is None,
              'shape=%s' % sorted(st) if isinstance(st, dict) else repr(st))
        check('state timestamps are UTC Z strings',
              str(st['last_run_utc']).endswith('Z') and st['digests_sent'] == 0)
        go(2001)
        check('a second run with nothing new stays silent', sent == [])

        # 2. a new sale fires once and never again
        rows = [sale, buy,
                {'ts': 1500, 'kind': 'sale', 'name': 'Wukong Prime Systems Blueprint',
                 'qty': 1, 'plat': 14, 'total': 14, 'note': 'with BuyerTwo'}]
        write(paths['trade_log'], rows)
        go(2002)
        check('a new sale fires one digest',
              len(sent) == 1 and sent[0]['title'] == DIGEST_TITLE)
        check('sale line format is a short one-liner',
              sent and sent[0]['body'].splitlines() ==
              ['[sale] Wukong Prime Systems Blueprint x1 @ 14p - with BuyerTwo'])
        check('notify is asked for the digest rule and nothing else is overridden',
              sent and sent[0]['kwargs'].get('rule') == 'digest'
              and 'dry_run' not in sent[0]['kwargs'])
        go(2003)
        check('the same sale never fires twice', len(sent) == 1)
        write(paths['trade_log'], rows + [rows[-1]])
        go(2004)
        check('a duplicated row (same ts + items) is not re-sent', len(sent) == 1)
        write(paths['trade_log'], rows + [rows[-1]] +
              [{'ts': 900, 'kind': 'sale', 'name': 'Backfilled Sale', 'qty': 1, 'plat': 5,
                'total': 5, 'note': 'imported'}])
        go(2005)
        check('backfilled history (older ts) is recorded, never alerted', len(sent) == 1)

        # 3. watchlist alert dedupe on level+slug+floor
        alert_sell = dict(alert, level='sell', slug='galvanized_hell', name='Galvanized Hell',
                          floor=8, message='SELL Galvanized Hell: floor 8p >= min_sell 6p')
        write(paths['watchlist'], {'alerts': [alert, alert_sell]})
        go(2006)
        check('a new watchlist alert fires once',
              len(sent) == 2 and sent[1]['body'] ==
              '[watch] SELL Galvanized Hell: floor 8p >= min_sell 6p')
        go(2007)
        check('watchlist alerts are deduped by level+slug+floor', len(sent) == 2)
        alert_floor = dict(alert, floor=99)
        write(paths['watchlist'], {'alerts': [alert, alert_sell, alert_floor]})
        go(2008)
        check('same level+slug with a new floor is a new alert key',
              len(sent) == 3 and sent[2]['body'].startswith('[watch] BUY '))

        # 4. trades exhausted: once per reset window
        write(paths['trader_limits'], {'trades_left': 0, 'trade_cap': 22, 'reset_epoch': 5000,
                                       'reset_melbourne': '2026-09-26T10:00:00+10:00'})
        go(2009)
        check('trades_left 0 fires the limits line once',
              len(sent) == 4 and sent[3]['body'] ==
              '[limits] trades exhausted - 0/22 left, resets 2026-09-26T10:00:00+10:00')
        go(2010)
        check('limits stay quiet for the rest of the reset window', len(sent) == 4)
        write(paths['trader_limits'], {'trades_left': 0, 'trade_cap': 22, 'reset_epoch': 6000,
                                       'reset_melbourne': '2026-09-27T10:00:00+10:00'})
        go(2011)
        check('the next reset window fires again',
              len(sent) == 5 and sent[4]['body'].startswith('[limits] trades exhausted'))
        write(paths['trader_limits'], {'trades_left': 22, 'trade_cap': 22, 'reset_epoch': 6000,
                                       'reset_melbourne': '2026-09-27T10:00:00+10:00'})
        go(2012)
        check('trades back above zero is silent', len(sent) == 5)

        # 5. kill switch: transition fires once, unreadable reads as ARMED (fail-closed)
        write(paths['kill_switch'], {'active': True, 'note': 'manual test', 'ts': 1000})
        go(2013)
        check('kill switch armed transition fires once',
              len(sent) == 6 and sent[5]['body'] == '[safety] kill switch ARMED - manual test')
        go(2014)
        check('an armed kill switch does not repeat', len(sent) == 6)
        write(paths['kill_switch'], {'active': False, 'note': '', 'ts': 1001})
        go(2015)
        check('disarming is silent', len(sent) == 6)
        write_raw(paths['kill_switch'], '{not json')
        go(2016)
        check('an unreadable-but-present kill switch file reads as ARMED (fail-closed)',
              len(sent) == 7 and sent[6]['body'] ==
              '[safety] kill switch ARMED - unreadable - fail-closed')
        go(2017)
        check('the fail-closed report does not repeat', len(sent) == 7)
        write(paths['kill_switch'], {'active': False, 'note': '', 'ts': 1002})
        go(2018)
        check('a repaired disarmed file is silent (marker back to off)', len(sent) == 7)
        write(paths['kill_switch'], {'active': True, 'note': 'again', 'ts': 1003})
        go(2019)
        check('re-arming after a disarm fires again',
              len(sent) == 8 and sent[7]['body'].endswith('- again'))

        # 6. Baro window opens once
        write(paths['baro'], {'trader': {'active': True, 'character': "Baro Ki'Teer",
                                         'location': 'Kronia Relay (Saturn)',
                                         'expiry_text': 'Sun 2026-10-04 13:00 UTC'}})
        go(2020)
        check('Baro window transition fires once with relay and close time',
              len(sent) == 9 and sent[8]['body'] ==
              "[baro] Baro Ki'Teer window open - Kronia Relay (Saturn), closes "
              'Sun 2026-10-04 13:00 UTC')
        go(2021)
        check('an open Baro window does not repeat', len(sent) == 9)

        # 7. digest grouping: everything due in one run becomes ONE ordered digest
        write(paths['kill_switch'], {'active': False, 'note': ''})
        write(paths['baro'], {'trader': {'active': False, 'character': "Baro Ki'Teer"}})
        go(2022)                                        # both transitions back, quietly
        write(paths['kill_switch'], {'active': True, 'note': 'grouped run'})
        write(paths['baro'], {'trader': {'active': True, 'character': "Baro Ki'Teer",
                                         'location': 'Kronia Relay (Saturn)',
                                         'expiry_text': 'Sun 2026-10-04 13:00 UTC'}})
        write(paths['trader_limits'], {'trades_left': 0, 'trade_cap': 22, 'reset_epoch': 7000,
                                       'reset_melbourne': '2026-09-28T10:00:00+10:00'})
        rows = rows + [{'ts': 3000, 'kind': 'sale', 'name': 'Trinity Prime Systems Blueprint',
                        'qty': 3, 'plat': 9, 'total': 27, 'note': 'with BuyerThree'}]
        write(paths['trade_log'], rows)
        write(paths['watchlist'], {'alerts': [alert, alert_sell,
                                              dict(alert, slug='arcane_energize',
                                                   name='Arcane Energize', floor=150)]})
        before = len(sent)
        go(2023)
        body = sent[-1]['body'].splitlines() if len(sent) > before else []
        check('five due triggers group into exactly ONE send', len(sent) == before + 1)
        check('digest order is safety -> baro -> limits -> trades -> watch',
              [line.split(' ', 1)[0] for line in body[:5]] ==
              ['[safety]', '[baro]', '[limits]', '[sale]', '[watch]'],
              'got %s' % [line[:14] for line in body[:5]])
        check('sale line carries qty x price each and the total',
              any(line == '[sale] Trinity Prime Systems Blueprint x3 @ 9p each (27p total) '
                         '- with BuyerThree' for line in body))
        go(2023)
        check('the grouped digest does not fire again', len(sent) == before + 1)

        # 8. state atomicity + corrupt-state recovery + --print is read-only
        leftovers = sorted(f for f in os.listdir(data) if f.endswith('.tmp'))
        check('no .tmp leftovers after all those writes', leftovers == [], str(leftovers))
        check('state file still parses after every write', jload(paths['state'])[1] is None)

        write_raw(paths['state'], '{broken state')
        before = len(sent)
        rc = go(2024)
        recovered = jload(paths['state'])[0]
        body = sent[-1]['body'].splitlines() if len(sent) > before else []
        check('a corrupt state file starts a fresh baseline instead of crashing',
              rc == 0 and isinstance(recovered, dict) and jload(paths['state'])[1] is None)
        check('the recovery run re-reports only live state, never old trades/alerts',
              all(not line.startswith(('[sale]', '[watch]')) for line in body)
              and any(line.startswith('[safety]') for line in body),
              'body=%s' % body)

        write(paths['state'], 'valid JSON but not an object')
        rc = go(2025)
        check('a state file that is valid JSON but not an object also re-baselines cleanly',
              rc == 0 and isinstance(jload(paths['state'])[0], dict)
              and jload(paths['state'])[1] is None)

        write(paths['trade_log'], rows + [{'ts': 4000, 'kind': 'sale', 'name': 'Preview Sale',
                                           'qty': 1, 'plat': 3, 'total': 3, 'note': ''}])
        before = len(sent)
        state_hash = notify.file_hash(paths['state'])
        rc = run(paths, print_only=True, now=2026)
        check('--print composes without calling notify.send and without writing state',
              rc == 0 and len(sent) == before and notify.file_hash(paths['state']) == state_hash)
        go(2027)
        check('the previewed message is still pending for the next real run',
              len(sent) == before + 1 and sent[-1]['body'] == '[sale] Preview Sale x1 @ 3p')

        check('the repo data/ files are untouched by the selftest',
              {p: notify.file_hash(p) for p in real} == real)
    finally:
        notify.send = real_send
        shutil.rmtree(tmp, ignore_errors=True)

    failed = results.count(False)
    print('[pushd.selftest] %d/%d checks passed%s'
          % (len(results) - failed, len(results), '' if not failed else ' - FAILURES ABOVE'))
    print('selftest %s (tmp fixtures only, notify.send patched to a recorder, no network)'
          % ('OK' if not failed else 'FAILED'))
    return 0 if not failed else 1


# --------------------------------------------------------------------------- main
def build_parser():
    parser = argparse.ArgumentParser(
        prog='pushd.py',
        description='WFM push daemon: one grouped digest per run for whatever is new since '
                    'the last run (sales, watchlist hits, trade limits, kill switch, Baro).',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='examples:\n'
               '  pushd.py            # one scan + one digest (cron / Task Scheduler)\n'
               '  pushd.py --print    # show what a run would send; nothing sent or written\n'
               '  pushd.py --selftest # offline fixture checks\n')
    parser.add_argument('--once', action='store_true',
                        help='run a single scan cycle (the default; kept for cron clarity)')
    parser.add_argument('--print', dest='print_only', action='store_true',
                        help='compose and print the digest; notify.send() is not called and '
                             'the state file is not written')
    parser.add_argument('--selftest', action='store_true',
                        help='offline checks in tmp dirs (notify.send patched, no network)')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv[1:] if argv else None)
    if args.selftest:
        return selftest()
    return run(print_only=bool(args.print_only))


if __name__ == '__main__':
    sys.exit(main())
