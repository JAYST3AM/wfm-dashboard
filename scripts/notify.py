#!/usr/bin/env python3
r"""Notification sender core - one local outbox, then optional webhook delivery.

Config : data/notify_config.json  (created on first run, NEVER overwritten)
Outbox : data/notify_outbox.json  (append-only ledger, newest OUTBOX_KEEP rows kept)

Behavior
  dry_run true (the default): nothing leaves the machine. Every message is appended to
      the outbox with status 'dry_run' and echoed to stdout.
  dry_run false: each resolved webhook that has a url gets a POST -
      kind 'discord': {"content": "<title>\n\n<body>"} truncated to 2000 chars
      any other kind: {"title": ..., "body": ...}
      Discord answers 204 No Content on success; a failed attempt is retried once.
      A webhook with an empty url is skipped with a clear message - never guessed at.

Usage
  python scripts/notify.py --send "Sale ping" --body "3x Primed Continuity listed at 42p"
  python scripts/notify.py --send "Watchlist hit" --body "..." --to my-channel
  python scripts/notify.py --send "Daily digest" --body "..." --all --rule digest
  python scripts/notify.py --outbox --limit 10
  python scripts/notify.py --selftest

Other dashboard scripts call send(...) to deliver watchlist alerts and sale pings.
No webhook url is hardcoded anywhere in this file: every url comes from the config the
user fills in. Webhook urls are secrets - they are never echoed to stdout, never logged
and never copied into the outbox.

Exit codes: 0 = ok, 1 = nothing delivered / config problem, 2 = bad args.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CONFIG_PATH = os.path.join(DATA, 'notify_config.json')
OUTBOX_PATH = os.path.join(DATA, 'notify_outbox.json')

UA = 'WFMTrader/0.1 (local personal tool; github.com/JAYST3AM/wfm-dashboard)'
DISCORD_LIMIT = 2000      # Discord hard-caps message content at 2000 characters
TIMEOUT = 15              # seconds per attempt
TRIES = 2                 # first attempt + one retry
RETRY_WAIT = 1.0          # seconds between attempts (tests set this to 0)
OUTBOX_KEEP = 500         # ledger keeps the newest N rows
OUTBOX_LIMIT = 10         # --outbox default rows shown


class NotifyError(Exception):
    """Raised for unusable config/message situations (one-line message, exit 1)."""


# ---------------------------------------------------------------------------- io
def default_config():
    """The documented config shape, url deliberately empty - fill it in yourself."""
    return {
        '_comment': ('edit me: paste your webhook url(s) into "webhooks" '
                     '(Discord: channel settings -> integrations -> webhooks) and set '
                     '"dry_run": false when you want messages to actually leave this PC'),
        'dry_run': True,
        'webhooks': [{'name': 'my-channel', 'url': '', 'kind': 'discord'}],
        'rules': {'sales': True, 'alerts': True, 'digest': False},
    }


def normalize(doc):
    """Fill missing/invalid keys from the default shape; never rewrite the file.

    A 'webhooks' list that is present - even an empty one - is the user's choice and is
    respected; only a missing/unusable one falls back to the placeholder entry.
    """
    out = default_config()
    if isinstance(doc.get('_comment'), str):
        out['_comment'] = doc['_comment']
    if isinstance(doc.get('dry_run'), bool):
        out['dry_run'] = doc['dry_run']
    raw = doc.get('webhooks')
    if isinstance(raw, list):
        hooks = []
        for i, row in enumerate(raw):
            if not isinstance(row, dict):
                continue
            name = str(row.get('name') or '').strip()
            if not name:
                print('WARN webhook entry #%d has no name - ignored' % (i + 1))
                continue
            hooks.append({'name': name,
                          'url': str(row.get('url') or '').strip(),
                          'kind': (str(row.get('kind') or '').strip().lower() or 'discord')})
        out['webhooks'] = hooks
    rules = dict(out['rules'])
    for key, value in (doc.get('rules') or {}).items() if isinstance(doc.get('rules'), dict) else []:
        if isinstance(value, bool):
            rules[str(key)] = value
    out['rules'] = rules
    return out


def load_config(path=None, create=True):
    """Read the config; write the documented default once, the first time, only.

    An existing file is never overwritten - edits (urls, dry_run, rules) are the
    user's. An unreadable file is reported and the safe defaults are used instead.
    """
    path = path or CONFIG_PATH
    if not os.path.exists(path):
        if not create:
            return normalize({})
        doc = default_config()
        atomic_write(path, doc)
        print('created %s (dry_run on, no webhook urls yet)' % rel(path))
        return normalize(doc)
    try:
        with open(path, encoding='utf-8') as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        print('WARN cannot read %s: %s - using defaults (dry_run on, no urls)'
              % (rel(path), exc))
        return normalize({})
    if not isinstance(doc, dict):
        print('WARN %s is not a JSON object - using defaults' % rel(path))
        return normalize({})
    return normalize(doc)


def load_outbox(path=None):
    """Outbox rows (list of dicts); unreadable content is moved aside, never dropped."""
    path = path or OUTBOX_PATH
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding='utf-8') as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        spare = '%s.corrupt-%s' % (path, time.strftime('%Y%m%d-%H%M%S', time.gmtime()))
        try:
            os.replace(path, spare)
            print('WARN %s unreadable (%s) - moved aside to %s, starting a fresh ledger'
                  % (rel(path), exc, rel(spare)))
        except OSError:
            print('WARN %s unreadable (%s) - starting a fresh ledger' % (rel(path), exc))
        return []
    if not isinstance(doc, list):
        print('WARN %s is not a JSON list - starting a fresh ledger' % rel(path))
        return []
    return [row for row in doc if isinstance(row, dict)]


def atomic_write(path, doc):
    """tmp file + os.replace, so a half-written ledger never lands."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, indent=1)
    os.replace(tmp, path)


def append_outbox(rows, path=None):
    """Append rows to the ledger (newest OUTBOX_KEEP kept); returns the whole ledger."""
    path = path or OUTBOX_PATH
    doc = load_outbox(path)
    if not rows:
        return doc
    doc.extend(rows)
    if OUTBOX_KEEP > 0 and len(doc) > OUTBOX_KEEP:
        doc = doc[-OUTBOX_KEEP:]
    atomic_write(path, doc)
    return doc


# ------------------------------------------------------------------------ format
def ascii_(value):
    return str(value).encode('ascii', 'replace').decode('ascii')


def clip(text, width):
    """ASCII, single-line, at most `width` characters ('...' marks the cut)."""
    text = ascii_(str(text or '')).replace('\r', ' ').replace('\n', ' ')
    return text if len(text) <= width else text[:max(0, width - 3)] + '...'


def clip_discord(title, body):
    """Discord 'content': title, blank line, body - hard-capped at 2000 characters."""
    head, tail = str(title or '').strip(), str(body or '').strip()
    text = '%s\n\n%s' % (head, tail) if head and tail else (head or tail)
    if len(text) <= DISCORD_LIMIT:
        return text
    return text[:DISCORD_LIMIT - 3] + '...'


def utc_stamp():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def file_hash(path):
    """sha256 hex of a file, or None when it does not exist (isolation checks)."""
    try:
        with open(path, 'rb') as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def rel(path):
    """Path relative to the repo root, forward slashes (falls back to the raw path)."""
    try:
        return os.path.relpath(path, ROOT).replace('\\', '/')
    except ValueError:
        return str(path).replace('\\', '/')


def render(headers, rows):
    """Plain-ASCII aligned table (same shape as cli.py's render)."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def line(cells):
        return '  '.join(c.ljust(widths[i]) for i, c in enumerate(cells)).rstrip()

    lines = [line(list(headers)), '  '.join('-' * w for w in widths)]
    lines += [line(list(row)) for row in rows]
    return '\n'.join(lines)


# ---------------------------------------------------------------------- delivery
def rule_enabled(cfg, name):
    """Config rules switchboard; rule names the config does not know stay enabled."""
    rules = cfg.get('rules') or {}
    return True if name not in rules else bool(rules[name])


def resolve_targets(cfg, to=None, every=False):
    """Pick webhook entries: --to NAME, --all, else the first configured webhook."""
    hooks = cfg.get('webhooks') or []
    if to:
        hits = [h for h in hooks if h['name'] == to]
        if not hits:
            known = ', '.join(h['name'] for h in hooks) or '(none configured)'
            raise NotifyError("no webhook named '%s' in %s - known: %s"
                              % (to, rel(CONFIG_PATH), known))
        return hits
    if not hooks:
        raise NotifyError('no webhooks in %s - add one (see the "_comment" line)'
                          % rel(CONFIG_PATH))
    return list(hooks) if every else hooks[:1]


def payload_for(kind, title, body):
    """Discord wants {'content': ...}; anything else gets {'title': ..., 'body': ...}."""
    if str(kind or '').strip().lower() == 'discord':
        return {'content': clip_discord(title, body)}
    return {'title': str(title or ''), 'body': str(body or '')}


def post(url, payload, tries=TRIES, timeout=TIMEOUT):
    """POST a JSON payload; returns (ok, detail). 2xx - 204 included - is success.

    Attempts the request `tries` times in total (default 2 = one retry).
    """
    target = url.strip() if isinstance(url, str) else ''
    if not target.lower().startswith(('http://', 'https://')):
        return False, 'not an http(s) url - fix it in data/notify_config.json'
    body = json.dumps(payload).encode('utf-8')
    attempts = max(1, int(tries))
    last = 'no attempt made'
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(target, data=body, method='POST', headers={
            'User-Agent': UA, 'Content-Type': 'application/json', 'Accept': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                code = int(getattr(resp, 'status', 0) or resp.getcode() or 0)
                if 200 <= code < 300:
                    return True, 'HTTP %d (attempt %d/%d)' % (code, attempt, attempts)
                last = 'HTTP %d' % code
        except urllib.error.HTTPError as exc:
            last = 'HTTP %d' % exc.code
            try:
                exc.close()
            except Exception:
                pass
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last = '%s: %s' % (type(exc).__name__, exc)
        if attempt < attempts:
            time.sleep(RETRY_WAIT)
    return False, last


def deliver(cfg, title, body, to=None, every=False, dry_run=None, outbox=None):
    """Deliver one message to the resolved targets; returns the outbox rows written."""
    hooks = resolve_targets(cfg, to=to, every=every)
    dry = bool(cfg.get('dry_run', True)) if dry_run is None else bool(dry_run)
    rows = []
    for hook in hooks:
        status, detail = 'dry_run', ''
        if not dry:
            if not hook['url']:
                status = 'skipped'
                detail = ("no url for webhook '%s' - add it to %s, then retry"
                          % (hook['name'], rel(CONFIG_PATH)))
            else:
                ok, detail = post(hook['url'], payload_for(hook['kind'], title, body))
                status = 'sent' if ok else 'failed'
        row = {'ts': utc_stamp(), 'to': hook['name'], 'title': str(title or ''),
               'body': str(body or ''), 'status': status}
        if detail:
            row['detail'] = detail
        rows.append(row)
    append_outbox(rows, path=outbox)
    return rows


def report(rows, cfg, path=None):
    """Echo what happened (never the url itself - webhook urls are secrets)."""
    path = path or OUTBOX_PATH
    for row in rows:
        print('%-8s %-20s %s' % (row['status'], clip(row['to'], 20), clip(row['title'], 60)))
        if row.get('body'):
            print('         %s' % clip(row['body'], 100))
        if row.get('detail'):
            print('         %s' % clip(row['detail'], 120))
    if rows and cfg.get('dry_run', True):
        print('%d row(s) appended to %s - set "dry_run": false in %s to deliver for real'
              % (len(rows), rel(path), rel(CONFIG_PATH)))
    elif rows:
        print('%d row(s) appended to %s' % (len(rows), rel(path)))


def send(title, body='', to=None, every=False, rule=None, dry_run=None, outbox=None):
    """Programmatic entry point for the other dashboard scripts.

    Loads the config, honours the rules switchboard and the dry_run flag, delivers one
    message and prints the summary. Returns the outbox rows written ([] when a rule
    blocks the message).
    """
    cfg = load_config()
    if rule and not rule_enabled(cfg, rule):
        print("notify: rule '%s' is disabled in %s (rules.%s = false) - nothing sent"
              % (rule, rel(CONFIG_PATH), rule))
        return []
    rows = deliver(cfg, title, body, to=to, every=every, dry_run=dry_run, outbox=outbox)
    report(rows, cfg, path=outbox)
    return rows


# ---------------------------------------------------------------------- commands
def cmd_outbox(args, path=None):
    path = path or OUTBOX_PATH
    rows = load_outbox(path)
    limit = getattr(args, 'limit', None) or OUTBOX_LIMIT
    if not rows:
        print('outbox is empty: %s (nothing sent yet)' % rel(path))
        return 0
    newest = rows[-limit:][::-1]
    print('outbox: %s (%d row(s), newest first, showing %d)'
          % (rel(path), len(rows), len(newest)))
    print(render(['ts', 'to', 'status', 'title', 'body'],
                 [[clip(r.get('ts'), 20), clip(r.get('to'), 18), clip(r.get('status'), 8),
                   clip(r.get('title'), 40), clip(r.get('body'), 44)] for r in newest]))
    return 0


def cmd_send(args):
    rows = send(args.send, args.body, to=args.to, every=args.every, rule=args.rule)
    if any(r.get('status') in ('failed', 'skipped') for r in rows):
        return 1
    return 0


# ----------------------------------------------------------------------- selftest
class Sink:
    """Loopback HTTP sink for --selftest: records POSTs, answers `status` (default 204).

    `fail_first` makes the first recorded request answer 500 so the one-retry path is
    exercised. Nothing here touches the network beyond 127.0.0.1.
    """

    def __init__(self, status=204, fail_first=False):
        self.records = []
        self.status = int(status)
        self.fail_first = bool(fail_first)
        sink = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get('Content-Length') or 0)
                sink.records.append({
                    'path': self.path,
                    'headers': {k.lower(): v for k, v in self.headers.items()},
                    'body': self.rfile.read(length),
                })
                code = 500 if (sink.fail_first and len(sink.records) == 1) else sink.status
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', '0')
                self.end_headers()

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.port = self.httpd.server_address[1]
        self.url = 'http://127.0.0.1:%d/webhook' % self.port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def json(self, index=-1):
        """Decoded JSON body of a recorded request (default: the newest)."""
        return json.loads(self.records[index]['body'].decode('utf-8'))


def selftest():
    """Fully offline check: loopback sink + a throwaway directory, no real config/data."""
    results = []

    def check(label, ok, detail=''):
        ok = bool(ok)
        results.append(ok)
        print('%s  %s%s' % ('PASS' if ok else 'FAIL', label, (' - %s' % detail) if detail else ''))
        return ok

    tmp = tempfile.mkdtemp(prefix='notify_selftest_')
    try:
        cfg_path = os.path.join(tmp, 'data', 'notify_config.json')
        out_path = os.path.join(tmp, 'data', 'notify_outbox.json')
        real_files = {p: file_hash(p) for p in (CONFIG_PATH, OUTBOX_PATH)}

        cfg = load_config(cfg_path)
        with open(cfg_path, encoding='utf-8') as fh:
            raw = json.load(fh)
        check('config bootstrapped with the documented shape',
              set(raw) == {'_comment', 'dry_run', 'webhooks', 'rules'}
              and raw['dry_run'] is True
              and raw['webhooks'] == [{'name': 'my-channel', 'url': '', 'kind': 'discord'}]
              and raw['rules'] == {'sales': True, 'alerts': True, 'digest': False})

        with Sink() as sink:
            edited = {'dry_run': False,
                      'webhooks': [{'name': 'keep', 'url': sink.url, 'kind': 'discord'}],
                      'rules': {'digest': True}}
            with open(cfg_path, 'w', encoding='utf-8') as fh:
                json.dump(edited, fh)
            again = load_config(cfg_path)
            check('existing config is never overwritten',
                  again['dry_run'] is False and again['webhooks'][0]['url'] == sink.url
                  and again['rules']['digest'] is True)

            # dry run: ledger row only, nothing posted
            dry_cfg = normalize({'dry_run': True, 'webhooks': [
                {'name': 'sink', 'url': sink.url, 'kind': 'discord'}]})
            rows = deliver(dry_cfg, 'Dry title', 'Dry body', outbox=out_path)
            ledger = load_outbox(out_path)
            check('dry_run appends one row and posts nothing',
                  len(sink.records) == 0 and len(ledger) == 1
                  and rows[0]['status'] == 'dry_run'
                  and set(rows[0]) == {'ts', 'to', 'title', 'body', 'status'}
                  and rows[0]['ts'].endswith('Z'))

            # live discord: {"content": ...}, 204 = success
            live_cfg = normalize({'dry_run': False, 'webhooks': [
                {'name': 'sink', 'url': sink.url, 'kind': 'discord'}]})
            rows = deliver(live_cfg, 'Live title', 'Live body', outbox=out_path)
            check('discord POST body is {"content": title/body}',
                  len(sink.records) == 1 and sink.json() == {'content': 'Live title\n\nLive body'}
                  and sink.records[0]['headers'].get('content-type') == 'application/json')
            check('204 No Content counts as sent',
                  rows[0]['status'] == 'sent' and 'HTTP 204' in rows[0].get('detail', '')
                  and load_outbox(out_path)[-1]['status'] == 'sent')

            # 2000-char cap
            deliver(live_cfg, 'Long', 'x' * 2500, outbox=out_path)
            content = sink.json()['content']
            check('discord content is truncated to 2000 chars',
                  len(content) == DISCORD_LIMIT and content.endswith('...'))

            # generic kind
            generic_cfg = normalize({'dry_run': False, 'webhooks': [
                {'name': 'sink', 'url': sink.url, 'kind': 'generic'}]})
            deliver(generic_cfg, 'Gen title', 'Gen body', outbox=out_path)
            check('generic kind posts {"title","body"}',
                  sink.json() == {'title': 'Gen title', 'body': 'Gen body'})

            # empty url is skipped, not guessed at
            empty_cfg = normalize({'dry_run': False, 'webhooks': [
                {'name': 'my-channel', 'url': '', 'kind': 'discord'}]})
            before = len(sink.records)
            rows = deliver(empty_cfg, 'Nope', 'Nope', outbox=out_path)
            check('empty url is skipped with a clear message',
                  rows[0]['status'] == 'skipped' and 'no url' in rows[0].get('detail', '')
                  and len(sink.records) == before)

            # rules switchboard
            check('rules gate honours the config',
                  rule_enabled(dry_cfg, 'sales') and not rule_enabled(
                      normalize({'rules': {'digest': False}}), 'digest'))

            # ledger listing (temp path only - the real outbox is never touched here)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                listed = cmd_outbox(argparse.Namespace(limit=5), path=out_path)
            shown = buf.getvalue()
            check('--outbox lists the ledger, newest first',
                  listed == 0 and 'Dry title' in shown and 'Nope' in shown
                  and shown.index('Nope') < shown.index('Dry title'))

            check('http-only url guard', post('not-a-url', {})[0] is False)

        with Sink(fail_first=True) as flaky:
            cfg = normalize({'dry_run': False, 'webhooks': [
                {'name': 'flaky', 'url': flaky.url, 'kind': 'discord'}]})
            rows = deliver(cfg, 'Retry me', 'body', outbox=out_path)
            check('a failed attempt is retried once and then succeeds',
                  rows[0]['status'] == 'sent' and len(flaky.records) == 2)

        with Sink(status=500) as broken:
            cfg = normalize({'dry_run': False, 'webhooks': [
                {'name': 'broken', 'url': broken.url, 'kind': 'discord'}]})
            rows = deliver(cfg, 'Never lands', 'body', outbox=out_path)
            check('a permanently failing webhook ends as failed',
                  rows[0]['status'] == 'failed' and 'HTTP 500' in rows[0].get('detail', '')
                  and len(broken.records) == 2)

        check('the real data/ files are untouched by the selftest',
              {p: file_hash(p) for p in real_files} == real_files)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = results.count(False)
    print('selftest %s (%d checks, %d failed, loopback sink only - no network)'
          % ('OK' if not failed else 'FAILED', len(results), failed))
    return 0 if not failed else 1


# --------------------------------------------------------------------------- main
def positive_int(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError('expected an integer, got %r' % text)
    if value <= 0:
        raise argparse.ArgumentTypeError('expected a positive integer, got %r' % text)
    return value


def build_parser():
    parser = argparse.ArgumentParser(
        prog='notify.py',
        description='Notification sender core for the dashboard: plan-only outbox by '
                    'default, webhook delivery when the config says so.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='examples:\n'
               '  notify.py --send "Sale ping" --body "3x Primed Continuity at 42p"\n'
               '  notify.py --send "Watchlist hit" --body "..." --to my-channel\n'
               '  notify.py --send "Digest" --body "..." --all --rule digest\n'
               '  notify.py --outbox --limit 10\n'
               '  notify.py --selftest\n')
    parser.add_argument('--send', metavar='TITLE', default=None,
                        help='send one message: the title line')
    parser.add_argument('--body', metavar='TEXT', default='',
                        help='message body (used with --send)')
    parser.add_argument('--to', metavar='NAME', default=None,
                        help='webhook name from data/notify_config.json')
    parser.add_argument('--all', dest='every', action='store_true',
                        help='send to every configured webhook')
    parser.add_argument('--rule', metavar='NAME', default=None,
                        help='gate the message on the config rules map (sales/alerts/digest)')
    parser.add_argument('--outbox', action='store_true',
                        help='list recent outbox entries (newest first)')
    parser.add_argument('--limit', type=positive_int, default=OUTBOX_LIMIT, metavar='N',
                        help='rows shown by --outbox (default %d)' % OUTBOX_LIMIT)
    parser.add_argument('--selftest', action='store_true',
                        help='offline selftest against a loopback sink (no network)')
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    modes = [bool(args.selftest), bool(args.outbox), args.send is not None]
    if sum(modes) > 1:
        print('use one of --send / --outbox / --selftest at a time')
        return 2
    if args.selftest:
        return selftest()
    if args.outbox:
        return cmd_outbox(args)
    if args.send is not None:
        if args.to and args.every:
            print('--to and --all are mutually exclusive')
            return 2
        try:
            return cmd_send(args)
        except NotifyError as exc:
            print(str(exc))
            return 1
        except (OSError, ValueError, TypeError, KeyError) as exc:
            print('notify error: %s: %s' % (type(exc).__name__, exc))
            return 1
    if args.to or args.every or args.rule:
        print('--to / --all / --rule need --send')
        return 2
    parser.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
