"""WFM Trader dashboard config (data/config.json): the dashboard-side knobs.

One read / validate / atomic-write path for the small config the dashboard server and the
static UI consume: bind port + host, default theme, auto-refresh seconds, display
preferences, the save-watch poll interval and the payload caps server.py slices. The trader
guardrail knobs (dry_run, listing caps, price floors, poll_seconds) belong to
scripts/trader/settings.json — this file never owns or shadows them.

Guarantees:
  * created with defaults (plus its `_comment` notes) on first use — `--init`, or the first
    `--set` — and after that NEVER regenerated: every later write starts from the file as it
    is, keeps its key order, its notes and any key this engine does not know;
  * every value is validated BEFORE anything is written and the write is atomic (same-dir
    tmp file + os.replace), so a refused value leaves the file byte-identical;
  * reading never writes: --show / --get / read() leave the file alone, and a file that is
    not valid JSON is refused, never rewritten.

Usage:
  python scripts/config.py --show              # effective knobs as JSON (read-only)
  python scripts/config.py --get port          # one bare value (127.0.0.1, 8787, true ...)
  python scripts/config.py --set theme=3       # validate + atomic write (repeatable)
  python scripts/config.py --init              # create data/config.json if absent
  python scripts/config.py --schema            # knob rows for the dashboard settings panel
  python scripts/config.py --selftest          # offline checks on tmp fixtures
  python scripts/config.py --set port=8080 --show
Exit codes: 0 ok | 1 selftest failure | 2 invalid/refused input
Env: WFM_CONFIG   override the config path (tests / selftest)

Reads : data/config.json (env-overridable), plus scripts/trader/settings.py + its
        settings.json when present, only for the "no shared keys" guard. No network.
Writes: data/config.json, and only from --init / --set / ensure().
"""
import argparse
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_PATH = os.path.join(ROOT, 'data', 'config.json')
TRADER_SETTINGS_PY = os.path.join(ROOT, 'scripts', 'trader', 'settings.py')
TRADER_SETTINGS_JSON = os.path.join(ROOT, 'scripts', 'trader', 'settings.json')

NOTE = '_comment'          # top-of-file note (preserved, never a knob)
NOTE_PREFIX = '_comment_'  # one note per knob, written directly above its knob

HEADER = ("WFM Trader dashboard config - dashboard-side knobs only. Edit by hand (the "
          "_comment_<key> note above each knob holds its range/meaning) or run "
          "python scripts/config.py --set key=value. These notes and any unknown key are "
          "preserved, and this file is never regenerated. Trader guardrails (dry_run, listing "
          "caps, price floors, poll_seconds) live in scripts/trader/settings.json.")

# Every dashboard knob, in the order a fresh file gets them. Ranges (task spec + the
# hardcoded values found in server.py / static/): 1024..65535 port, 15..3600 auto refresh,
# 0..29 theme (static/theme.js ships 30 palettes), 60..86400 gamenews cache,
# 1..200 deals rows, 1..60 session rows, 5..600 save-watch poll.
SPEC = [
    dict(key='port', type='min/max', min=1024, max=65535, default=8787, choices=None, step=1,
         consumed_by='server.py (WFM_PORT env still wins)',
         help='TCP port the dashboard server binds.',
         note='TCP port the dashboard server binds (server.py PORT). Range 1024..65535.'),
    dict(key='host', type='choice', min=None, max=None, default='127.0.0.1',
         choices=('127.0.0.1', '0.0.0.0'), step=None,
         consumed_by='server.py (bind address)',
         help='Bind address: this PC only, or also reachable from the LAN.',
         note="Bind address: '127.0.0.1' = this PC only, '0.0.0.0' = also reachable from "
              "other devices on your LAN."),
    dict(key='theme', type='min/max', min=0, max=29, default=0, choices=None, step=1,
         consumed_by='static/theme.js (default palette; localStorage wfm.theme wins)',
         help='Default palette index into WFM_THEMES (0 = Vor Orange .. 29 = Nebula).',
         note='Default palette index into static/theme.js WFM_THEMES (0 = Vor Orange, '
              '29 = Nebula). A palette picked in the UI is remembered per browser.'),
    dict(key='auto_refresh_seconds', type='min/max', min=15, max=3600, default=60,
         choices=None, step=1,
         consumed_by='static/app.js auto-refresh poll',
         help='Seconds between dashboard data polls (15..3600).',
         note='Seconds between dashboard data polls. Lower = fresher, more CPU.'),
    dict(key='currency_display', type='choice', min=None, max=None, default='p',
         choices=('p', 'plat', 'none'), step=None,
         consumed_by='static/app.js, chart.js, lookup.js (platinum suffix)',
         help="Platinum suffix in the UI: 'p' (100p), 'plat' (100 plat) or 'none' (100).",
         note="Platinum suffix in the UI: 'p' (100p), 'plat' (100 plat), 'none' (100)."),
    dict(key='advanced', type='bool', min=None, max=None, default=False, choices=None, step=None,
         consumed_by='static/adv.js (html[data-adv] -> .explain visibility)',
         help='Show the extra explanations, hints and footnotes across the dashboard.',
         note='false = pages stay clean (labels, values and status only). true = the extra '
              'explanations, setting hints and footnotes appear again.'),
    dict(key='clan_name', type='text', min=None, max=32, default='', choices=None, step=None,
         consumed_by='static/app.js, player page (clan card)',
         help='Your clan name, shown on the Player page.',
         note='Shown on the Player page as the clan label (leave blank to hide it).'),
    dict(key='gifs', type='bool', min=None, max=None, default=False, choices=None, step=None,
         consumed_by='static UI (celebration GIFs; nothing reads it yet)',
         help='Allow animated GIF extras in the dashboard UI.',
         note='true = allow animated GIF extras in the dashboard UI (reserved: no code reads '
              'it yet).'),
    dict(key='gamenews_cache_seconds', type='min/max', min=60, max=86400, default=1800,
         choices=None, step=1,
         consumed_by='server.py gamenews_payload (refresh TTL)',
         help='How long data/gamenews.json may be reused before a refetch.',
         note='How long server.py may reuse data/gamenews.json before refetching (60..86400; '
              '1800 = 30 min).'),
    dict(key='deals_shown', type='min/max', min=1, max=200, default=60, choices=None, step=1,
         consumed_by='server.py feature_payload("deals") row cap',
         help='Most deal rows /api/feature/deals returns.',
         note='Most deal rows /api/feature/deals returns (1..200).'),
    dict(key='sessions_shown', type='min/max', min=1, max=60, default=12, choices=None, step=1,
         consumed_by='server.py feature_payload("sessions") row cap',
         help='Most session rows /api/feature/sessions returns.',
         note='Most session rows /api/feature/sessions returns (1..60).'),
    dict(key='watch_save_seconds', type='min/max', min=5, max=600, default=20, choices=None,
         step=1,
         consumed_by='scripts/watch_save.py (AlecaFrame save poll interval)',
         help='Seconds between AlecaFrame save checks (5..600; lower = fresher inventory).',
         note='Seconds between AlecaFrame save checks (scripts/watch_save.py): the watcher '
              'refreshes owned.json when the game rewrites the save. 5..600; 20 = every 20 s.'),
]
SPEC_KEYS = [row['key'] for row in SPEC]
DEFAULTS = {row['key']: row['default'] for row in SPEC}
_BOOL_TRUE = ('true', '1', 'yes', 'on', 't', 'y')
_BOOL_FALSE = ('false', '0', 'no', 'off', 'f', 'n')


def path():
    """Config path; WFM_CONFIG (env) overrides it for tests/selftest."""
    return os.environ.get('WFM_CONFIG') or DEFAULT_PATH


def is_note(key):
    """True for a `_comment*` documentation key (preserved, never read as a knob)."""
    return str(key).startswith(NOTE)


def spec_for(name):
    """Spec row for a knob key (case-insensitive); None when unknown."""
    n = str(name or '').strip().lower()
    for row in SPEC:
        if n == row['key'].lower():
            return row
    return None


def schema():
    """Dashboard rows: one per knob, with type/min/max/default/choices/step/help/consumed_by."""
    return [dict(row) for row in SPEC]


def load(p=None):
    """(doc, error, exists) for the config file. Never raises; doc is {} when unreadable."""
    p = p or path()
    try:
        with open(p, encoding='utf-8') as f:
            raw = f.read()
    except FileNotFoundError:
        return {}, None, False
    except Exception as e:
        return {}, f'{e!r}'[:160], True
    try:
        doc = json.loads(raw)
        if not isinstance(doc, dict):
            raise ValueError(f'not a JSON object: {type(doc).__name__}')
        return doc, None, True
    except Exception as e:
        return {}, f'{e!r}'[:160], True


def effective(doc):
    """Knobs in file order with missing ones appended at their default; notes dropped;
    other unknown keys kept so --show reveals them instead of hiding stray edits."""
    out = {k: v for k, v in (doc or {}).items() if not is_note(k)}
    for key in SPEC_KEYS:
        out.setdefault(key, DEFAULTS[key])
    return out


def audit(doc):
    """Informational check of the values as stored. Returns a list of problem strings."""
    problems = []
    for row in SPEC:
        key = row['key']
        if key not in doc:
            continue                      # absent knob: the default applies, not a problem
        ok, _, err = coerce(row, doc[key])
        if not ok:
            problems.append(err)
    return problems


def coerce(row, raw):
    """Validate one raw value for a knob row. Returns (ok, value, error)."""
    key = row['key']
    if row['type'] == 'bool':
        if isinstance(raw, bool):
            return True, raw, None
        v = str(raw).strip().lower()
        if v in _BOOL_TRUE:
            return True, True, None
        if v in _BOOL_FALSE:
            return True, False, None
        return False, None, f'{key} expects true/false (got {str(raw).strip()!r})'
    if row['type'] == 'text':
        if raw is None:
            return True, row['default'], None
        if isinstance(raw, (dict, list, bool)):
            return False, None, f'{key} expects a line of text (got {raw!r})'
        v = str(raw).strip()
        bad = ('\r', '\n', '	')
        if any(ch in v for ch in bad):
            return False, None, f'{key} expects a single line of text'
        if row['max'] is not None:
            v = v[:row['max']]
        return True, v, None
    if row['type'] == 'choice':
        if not isinstance(raw, str):
            return False, None, (f'{key} expects one of {", ".join(row["choices"])} '
                                 f'(got {raw!r})')
        v = raw.strip().lower()
        if v not in row['choices']:
            return False, None, (f'{key} expects one of {", ".join(row["choices"])} '
                                 f'(got {raw.strip()!r})')
        return True, v, None
    if isinstance(raw, bool):
        return False, None, f'{key} expects a whole number (got {raw!r})'
    if isinstance(raw, int):
        num = raw
    elif isinstance(raw, float) and raw.is_integer():
        num = int(raw)
    elif isinstance(raw, float):
        return False, None, f'{key} expects a whole number (got {raw!r})'
    else:
        text = str(raw).strip()
        try:
            num = int(text)
        except ValueError:
            try:
                as_float = float(text)
            except ValueError:
                return False, None, f'{key} expects a whole number (got {text!r})'
            if not as_float.is_integer():
                return False, None, f'{key} expects a whole number (got {text!r})'
            num = int(as_float)
    if not (row['min'] <= num <= row['max']):
        return False, None, f'{key}={num} out of range {row["min"]}..{row["max"]}'
    return True, num, None


def validate(key, raw):
    """(ok, value, error) for a raw value; (False, None, msg) for an unknown knob."""
    row = spec_for(key)
    if row is None:
        return False, None, f'unknown key {key!r} (known: {", ".join(SPEC_KEYS)})'
    return coerce(row, raw)


def fresh_doc():
    """The first-use document: header note, then a note + its value for every knob."""
    doc = {NOTE: HEADER}
    for row in SPEC:
        doc[NOTE_PREFIX + row['key']] = row['note']
        doc[row['key']] = row['default']
    return doc


def _newline_of(p):
    """Line ending to write back: the file's own ('\\r\\n' when it uses CRLF), else '\\n'."""
    try:
        with open(p, 'rb') as f:
            return '\r\n' if b'\r\n' in f.read() else '\n'
    except OSError:
        return '\n'


def _write_atomic(doc, p):
    """Write doc as JSON (indent 2 + trailing newline, the file's own line endings) via tmp +
    os.replace. newline= stops Windows text mode translating '\\n' to CRLF, so re-writing an
    unchanged doc is byte-idempotent and a hand-edited config never gets reformatted."""
    d = os.path.dirname(os.path.abspath(p)) or '.'
    os.makedirs(d, exist_ok=True)
    newline = _newline_of(p)
    fd, tmp = tempfile.mkstemp(prefix='.config.', suffix='.tmp', dir=d)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline=newline) as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _refuse_if_corrupt(doc_err, exists, p, out):
    """Shared corrupt-file refusal: never rewrite a file we cannot parse."""
    if exists and doc_err:
        out['error'] = (f'{os.path.basename(p)} is not valid JSON ({doc_err}) - refusing to '
                        f'rewrite it; fix or delete the file by hand first')
        return True
    return False


def ensure(p=None):
    """Create the config with defaults (and its notes) when absent; otherwise write nothing.

    The create-once path: an existing file is left byte-identical, never re-serialised.
    Returns {'ok','code','error','path','created','doc'}.
    """
    p = p or path()
    out = {'ok': False, 'code': 2, 'error': None, 'path': p, 'created': False, 'doc': None}
    doc, err, exists = load(p)
    if _refuse_if_corrupt(err, exists, p, out):
        return out
    if exists:
        out.update(ok=True, code=0, doc=effective(doc))
        return out
    fresh = fresh_doc()
    try:
        _write_atomic(fresh, p)
    except Exception as e:
        out['error'] = f'write failed: {e!r}'[:200]
        return out
    out.update(ok=True, code=0, created=True, doc=fresh)
    return out


def apply_changes(pairs, p=None):
    """Validate every (key, raw_value) pair, then write once. Nothing is written on any error.

    A missing file is created from defaults; an existing one is merged into (its key order,
    notes and unknown keys kept, missing knobs filled at their default).
    Returns {'ok','code','error','path','created','changes' {key: {'from','to','unchanged'}},
              'preserved' [unknown non-note keys kept], 'notes' [note keys kept], 'doc',
              'problems'}. code: 0 ok | 2 invalid/refused input.
    """
    p = p or path()
    out = {'ok': False, 'code': 2, 'error': None, 'path': p, 'created': False, 'changes': {},
           'preserved': [], 'notes': [], 'doc': None, 'problems': []}
    wants = []
    for key, raw in pairs:
        row = spec_for(key)
        if row is None:
            out['error'] = f'unknown key {key!r} (known: {", ".join(SPEC_KEYS)})'
            return out
        ok, value, err = coerce(row, raw)
        if not ok:
            out['error'] = err
            return out
        wants.append((row['key'], value))

    doc, err, exists = load(p)
    if _refuse_if_corrupt(err, exists, p, out):
        return out
    merged = dict(doc) if exists else fresh_doc()
    for key in SPEC_KEYS:
        merged.setdefault(key, DEFAULTS[key])
    for key, value in wants:
        old = merged.get(key)
        if old == value:
            out['changes'][key] = {'from': old, 'to': value, 'unchanged': True}
        else:
            out['changes'][key] = {'from': old, 'to': value, 'unchanged': False}
        merged[key] = value
    out['preserved'] = sorted(k for k in merged if spec_for(k) is None and not is_note(k))
    out['notes'] = sorted(k for k in merged if is_note(k))
    out['created'] = not exists
    try:
        _write_atomic(merged, p)
    except Exception as e:
        out['error'] = f'write failed: {e!r}'[:200]
        return out
    out.update(ok=True, code=0, doc=merged, problems=audit(merged))
    return out


def read(p=None):
    """Effective knob values — every spec key present, defaults when the file/knob is bad.

    The consumer entry point (server.py): never raises, never writes, and a value that fails
    validation is replaced by its default instead of crashing the caller.
    """
    doc, _err, exists = load(p)
    out = {}
    for row in SPEC:
        raw = doc.get(row['key'], row['default']) if exists else row['default']
        ok, value, _err2 = coerce(row, raw)
        out[row['key']] = value if ok else row['default']
    return out


def _fmt(value):
    """Bare shell-friendly text for --get: true/false for bools, digits/words otherwise."""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def get_value(key, p=None):
    """(ok, text, error) for one --get key: a knob (validated), or a non-note key in the file."""
    p = p or path()
    name = str(key or '').strip()
    doc, err, exists = load(p)
    if err:
        return False, None, f'{os.path.basename(p)} is not valid JSON ({err})'
    row = spec_for(name)
    if row is not None:
        raw = doc.get(row['key'], row['default']) if exists else row['default']
        ok, value, verr = coerce(row, raw)
        if not ok:
            return False, None, f'{verr} (in {p})'
        return True, _fmt(value), None
    if exists and name in doc and not is_note(name):
        return True, json.dumps(doc[name], ensure_ascii=False), None
    return False, None, f'unknown key {name!r} (known: {", ".join(SPEC_KEYS)})'


def show_text(p=None):
    """The effective knobs as pretty JSON; raises SystemExit(2) on an unreadable file."""
    p = p or path()
    doc, err, exists = load(p)
    if err:
        print(f'error: {os.path.basename(p)} is not valid JSON: {err}', file=sys.stderr)
        raise SystemExit(2)
    eff = effective(doc)
    if not exists:
        print(f'note: {p} is absent - showing defaults (create it with --init)', file=sys.stderr)
    for problem in audit(doc):
        print(f'warning: {problem}', file=sys.stderr)
    return json.dumps(eff, indent=2, ensure_ascii=False)


def _say_change(res):
    """One-line-per-knob report for the CLI. Returns the exit code."""
    if not res['ok']:
        print(f'error: {res["error"]}', file=sys.stderr)
        print(f'nothing written -> {res["path"]}', file=sys.stderr)
        return res['code']
    for key, ch in res['changes'].items():
        if ch.get('unchanged'):
            print(f'{key} = {ch["to"]} (unchanged)')
        else:
            print(f'{key} = {ch["to"]} (was {ch["from"]})')
    note = ' (file created with defaults)' if res['created'] else ''
    print(f'config written -> {res["path"]} ({len(res["doc"])} keys, '
          f'{len(res["notes"])} notes, {len(res["preserved"])} unknown kept){note}')
    for problem in res['problems']:
        print(f'warning: {problem}')
    return 0


def selftest():
    """Offline checks (tmp fixtures only; the real data/config.json is never written)."""
    tmpdir = tempfile.mkdtemp(prefix='dashconfig_selftest_')
    real = DEFAULT_PATH
    real_hash = _hash(real)
    old_env = os.environ.get('WFM_CONFIG')
    os.environ['WFM_CONFIG'] = os.path.join(tmpdir, 'config.json')
    p = path()
    checks = []

    def chk(name, cond):
        checks.append((name, bool(cond)))

    def jload(q):
        with open(q, encoding='utf-8') as f:
            return json.load(f)

    try:
        rows = schema()
        chk('schema has a row per spec key', [r['key'] for r in rows] == SPEC_KEYS)
        chk('schema rows carry the UI fields',
            all({'key', 'type', 'min', 'max', 'default', 'choices', 'step', 'help',
                 'consumed_by', 'note'} <= set(r) for r in rows))
        chk('schema types are min/max, choice or bool',
            {r['type'] for r in rows} == {'min/max', 'choice', 'bool', 'text'})
        chk('schema is JSON-serializable', bool(json.dumps(rows)))
        chk('keys are unique and none is a _comment note',
            len(set(SPEC_KEYS)) == len(SPEC_KEYS) and not any(is_note(k) for k in SPEC_KEYS))
        rng = {r['key']: (r['type'], r['min'], r['max'], r['default']) for r in rows}
        chk('range: port 1024..65535 default 8787', rng['port'] == ('min/max', 1024, 65535, 8787))
        chk('range: auto_refresh_seconds 15..3600 default 60',
            rng['auto_refresh_seconds'] == ('min/max', 15, 3600, 60))
        chk('range: theme 0..29 default 0 (theme.js ships 30 palettes)',
            rng['theme'] == ('min/max', 0, 29, 0))
        chk('range: gamenews cache 60..86400 default 1800',
            rng['gamenews_cache_seconds'] == ('min/max', 60, 86400, 1800))
        chk('range: payload caps deals 1..200 default 60 / sessions 1..60 default 12',
            rng['deals_shown'] == ('min/max', 1, 200, 60)
            and rng['sessions_shown'] == ('min/max', 1, 60, 12))
        chk('range: watch_save_seconds 5..600 default 20 (watch_save.py poll)',
            rng['watch_save_seconds'] == ('min/max', 5, 600, 20))
        chk('choices: host bind addresses + platinum suffixes',
            spec_for('host')['choices'] == ('127.0.0.1', '0.0.0.0')
            and spec_for('currency_display')['choices'] == ('p', 'plat', 'none'))
        chk('gifs is a bool defaulting false and port is the first knob',
            rng['gifs'][0] == 'bool' and rng['gifs'][3] is False and SPEC_KEYS[0] == 'port')
        chk('every knob documents its consumer, help and file note',
            all(r['consumed_by'] and r['help'] and r['note'] for r in rows))
        chk('spec_for is case-insensitive, unknown keys return None',
            spec_for('PORT')['key'] == 'port' and spec_for('nope') is None)
        chk('no knob shadows a trader guardrail key in scripts/trader/settings.json',
            (not os.path.exists(TRADER_SETTINGS_JSON))
            or not (set(SPEC_KEYS) & set(jload(TRADER_SETTINGS_JSON))))
        trader_spec_keys = _trader_spec_keys()
        if trader_spec_keys:
            chk('no knob shadows a key in scripts/trader/settings.py SPEC',
                not (set(SPEC_KEYS) & set(trader_spec_keys)))

        for raw, want in [('1024', True), ('65535', True), (1024, True), ('8787.0', True),
                          ('1023', False), ('65536', False), ('0', False), ('80', False),
                          ('abc', False), ('', False), (True, False), (False, False),
                          (None, False), ('8787p', False), (12.5, False)]:
            ok, _val, err = validate('port', raw)
            chk(f'port {raw!r} -> {"accepted" if want else "refused"}', ok is want)
            if not want and ok is False:
                chk(f'port {raw!r} refusal explains itself', bool(err))
        ok, val, _ = validate('port', '8787.0')
        chk('integral float text accepted, stored as int', ok and val == 8787
            and isinstance(val, int))
        for raw, want in [('15', True), ('3600', True), ('14', False), ('3601', False),
                          ('30', True), ('60000', False), ('1.5', False)]:
            chk(f'auto_refresh_seconds {raw!r} -> {"accepted" if want else "refused"}',
                validate('auto_refresh_seconds', raw)[0] is want)
        for raw, want in [('0', True), ('29', True), ('30', False), ('-1', False),
                          ('abc', False), (None, False)]:
            chk(f'theme {raw!r} -> {"accepted" if want else "refused"}',
                validate('theme', raw)[0] is want)
        for raw, want in [('5', True), ('20', True), ('600', True), ('4', False),
                          ('601', False), ('1.5', False), (True, False)]:
            chk(f'watch_save_seconds {raw!r} -> {"accepted" if want else "refused"}',
                validate('watch_save_seconds', raw)[0] is want)
        for raw, want in [('127.0.0.1', True), ('0.0.0.0', True), (' 127.0.0.1 ', True),
                          ('localhost', False), ('8.8.8.8', False), ('::1', False),
                          ('0.0.0.0/0', False), (True, False), (None, False), ('', False)]:
            chk(f'host {raw!r} -> {"accepted" if want else "refused"}',
                validate('host', raw)[0] is want)
        ok, val, _ = validate('host', ' 0.0.0.0 ')
        chk('host is trimmed to the stored form', ok and val == '0.0.0.0')
        for raw, want in [('p', True), ('PLAT', True), ('none', True), (' gold', False),
                          ('platinum', False), ('', False), (1, False)]:
            chk(f'currency_display {raw!r} -> {"accepted" if want else "refused"}',
                validate('currency_display', raw)[0] is want)
        chk('currency_display normalises case',
            validate('currency_display', 'PLAT') == (True, 'plat', None))
        chk('host refusal lists both allowed addresses',
            '127.0.0.1' in validate('host', 'localhost')[2]
            and '0.0.0.0' in validate('host', 'localhost')[2])
        for raw, want in [('true', True), ('on', True), ('1', True), (True, True),
                          ('false', False), ('off', False), ('0', False), (False, False)]:
            ok, val, _ = validate('gifs', raw)
            chk(f'gifs {raw!r} -> {want}', ok and val is want)
        for raw in ('maybe', '2', '', None, 1.5):
            chk(f'gifs {raw!r} refused', validate('gifs', raw)[0] is False)
        chk('number knobs refuse bools', validate('theme', True)[0] is False
            and validate('deals_shown', False)[0] is False)
        chk('unknown knob refused with the known list',
            (lambda r: (not r[0]) and 'port' in r[2] and 'theme' in r[2])(validate('list_cap', 5)))
        chk('a _comment key can never be set', validate('_comment_port', 'hi')[0] is False)

        chk('path() honours WFM_CONFIG', path() == p)
        chk('load() reports a missing file without raising', load(p) == ({}, None, False))
        before = _hash(p)
        eff = effective({})
        chk('effective({}) is defaults only, no notes',
            set(eff) == set(SPEC_KEYS) and not any(is_note(k) for k in eff))
        chk('read() on a missing file returns every default',
            read(p) == DEFAULTS and _hash(p) == before)
        with _quiet_stderr():
            text = show_text(p)
        chk('--show on a missing file prints defaults and writes nothing',
            json.loads(text) == DEFAULTS and _hash(p) == before and not os.path.exists(p))
        ok, val, _ = get_value('port', p)
        chk('--get on a missing file returns the default', ok and val == '8787')

        res = ensure(p)
        chk('first use creates the file with defaults', res['ok'] and res['created']
            and os.path.exists(p))
        doc = jload(p)
        chk('created file has every knob at its default',
            all(doc[k] == DEFAULTS[k] for k in SPEC_KEYS) and len(doc) == 2 * len(SPEC_KEYS) + 1)
        chk('created file documents itself with _comment notes',
            doc[NOTE] == HEADER and all(doc[NOTE_PREFIX + k] == spec_for(k)['note']
                                        for k in SPEC_KEYS))
        raw_bytes = open(p, 'rb').read()
        chk('file style: indent 2 + LF + trailing newline',
            raw_bytes.endswith(b'}\n') and b'\r' not in raw_bytes and b'\n  "' in raw_bytes)
        chk('no tmp files left behind', os.listdir(tmpdir) == ['config.json'])
        chk('audit of the created file is clean', audit(doc) == [])
        created_hash = _hash(p)
        res = ensure(p)
        chk('second use never rewrites (created False, byte-identical)',
            res['ok'] and res['created'] is False and _hash(p) == created_hash)
        text = show_text(p)
        chk('--show hides the notes but keeps every knob',
            set(json.loads(text)) == set(SPEC_KEYS))
        chk('--show never writes', _hash(p) == created_hash)
        ok, val, _ = get_value('host', p)
        chk('--get prints bare values', ok and val == '127.0.0.1')
        chk('--schema output is JSON rows',
            json.loads(json.dumps(schema()))[0]['key'] == 'port')

        nested = os.path.join(tmpdir, 'deep', 'data', 'config.json')
        res = ensure(nested)
        chk('first use creates missing parent directories',
            res['ok'] and res['created'] and os.path.exists(nested))
        res = apply_changes([('theme', '7'), ('host', '0.0.0.0')], p=p)
        chk('a later write keeps the notes and reports from/to',
            res['ok'] and res['created'] is False and 'theme' in jload(p) and
            res['changes']['host'] == {'from': '127.0.0.1', 'to': '0.0.0.0', 'unchanged': False})
        chk('a later write is not a regeneration',
            len(res['notes']) == len(SPEC_KEYS) + 1 and jload(p)['theme'] == 7)

        with open(p, 'w', encoding='utf-8') as f:            # a hand-edited config
            json.dump({'theme': 11, 'future_knob': 7, 'port': 8080}, f, indent=4)
        edited_hash = _hash(p)
        res = apply_changes([('auto_refresh_seconds', '120')], p=p)
        doc = jload(p)
        chk('hand edits survive a write (value, order, unknown key)',
            res['ok'] and doc['theme'] == 11 and doc['future_knob'] == 7
            and doc['port'] == 8080 and list(doc)[:3] == ['theme', 'future_knob', 'port'])
        chk('missing knobs are appended at their default, existing order untouched',
            doc['auto_refresh_seconds'] == 120 and doc['host'] == '127.0.0.1'
            and list(doc)[:3] == ['theme', 'future_knob', 'port'])
        chk('a user who deleted the notes does not get them back',
            not any(is_note(k) for k in doc) and res['preserved'] == ['future_knob'])
        h2 = _hash(p)
        apply_changes([('auto_refresh_seconds', '120')], p=p)   # same value again
        chk('re-writing an unchanged doc is byte-idempotent', _hash(p) == h2)

        crlf = os.path.join(tmpdir, 'crlf.json')
        with open(crlf, 'wb') as f:
            f.write(b'{\r\n  "port": 9000,\r\n  "theme": 2\r\n}\r\n')
        res = apply_changes([('theme', '3')], p=crlf)
        served = open(crlf, 'rb').read()
        chk('a CRLF file keeps CRLF while gaining missing knobs',
            res['ok'] and b'"theme": 3' in served and b'"port": 9000' in served
            and served.count(b'\r\n') == served.count(b'\n') > 4)

        for pairs in ([('port', '80')], [('port', '65536')], [('host', 'localhost')],
                      [('theme', '30')], [('auto_refresh_seconds', '5')],
                      [('gifs', 'maybe')], [('nonsense', '1')], [('port', 'abc')]):
            before_refuse = _hash(p)
            res = apply_changes(pairs, p=p)
            chk(f'refused {"=".join(map(str, pairs[0]))!r} (code 2, nothing written)',
                (not res['ok']) and res['code'] == 2 and _hash(p) == before_refuse)
        batch_hash = _hash(p)
        res = apply_changes([('theme', '5'), ('port', '99')], p=p)
        chk('one bad value refuses the whole batch', (not res['ok']) and _hash(p) == batch_hash
            and jload(p)['theme'] == 11)
        res = apply_changes([('port', '99')], p=p)
        chk('out-of-range refusal carries the range', '1024..65535' in res['error'])

        with open(p, 'w', encoding='utf-8') as f:
            f.write('{"port": 8787, "theme": 3,')
        bad_hash = _hash(p)
        res = apply_changes([('theme', '4')], p=p)
        chk('corrupt file is never rewritten', (not res['ok']) and 'not valid JSON' in res['error']
            and _hash(p) == bad_hash)
        res = ensure(p)
        chk('create-once refuses to touch a corrupt file',
            (not res['ok']) and res['code'] == 2 and _hash(p) == bad_hash)
        with _quiet_stderr():
            code = _capture_exit(show_text, p)
        chk('--show refuses a corrupt file (exit 2)', code == 2)
        ok, _val, err = get_value('port', p)
        chk('--get refuses a corrupt file', (not ok) and 'not valid JSON' in err)
        chk('read() never raises on a corrupt file, falls back to defaults',
            read(p) == DEFAULTS)
        before_bad = _hash(p)
        chk('a corrupt file is left byte-identical by every read path',
            _hash(p) == before_bad == bad_hash)

        with open(p, 'w', encoding='utf-8') as f:
            json.dump({'port': 'not a number', 'theme': 99, 'host': '0.0.0.0',
                       'future_knob': 7}, f)
        eff = read(p)
        chk('read() substitutes the default for an unreadable value only',
            eff['port'] == 8787 and eff['theme'] == 0 and eff['host'] == '0.0.0.0'
            and eff['gifs'] is False and set(eff) == set(SPEC_KEYS))
        problems = audit(jload(p))
        chk('audit flags both bad values and nothing else',
            len(problems) == 2 and any('port' in x for x in problems)
            and any('theme' in x for x in problems))
        chk('audit ignores unknown keys and missing knobs',
            audit({'future_knob': 1}) == [] and audit({}) == [])
        ok, val, _ = get_value('future_knob', p)
        chk('--get can still read a preserved unknown key', ok and val == '7')
        ok, _val, err = get_value('_comment', p)
        chk('--get refuses a _comment key', (not ok) and 'unknown key' in err)
    finally:
        if old_env is None:
            os.environ.pop('WFM_CONFIG', None)
        else:
            os.environ['WFM_CONFIG'] = old_env
        _rmtree(tmpdir)

    chk('real data/config.json untouched by selftest', _hash(real) == real_hash)
    failed = [name for name, ok in checks if not ok]
    for name in failed:
        print(f'FAIL: {name}')
    if failed:
        print(f'selftest: {len(failed)} of {len(checks)} checks failed')
        return 1
    print(f'selftest: all {len(checks)} checks passed')
    return 0


def _trader_spec_keys():
    """SPEC_KEYS of the private trader settings engine when it is on disk, else []."""
    if not os.path.exists(TRADER_SETTINGS_PY):
        return []
    import importlib.util
    name = 'wfm_config_selftest_trader'
    try:
        spec = importlib.util.spec_from_file_location(name, TRADER_SETTINGS_PY)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return list(getattr(mod, 'SPEC_KEYS', []) or [])
    except Exception:
        return []


def _capture_exit(fn, *a):
    """Exit code of a fn that signals errors with SystemExit (selftest helper)."""
    try:
        fn(*a)
        return 0
    except SystemExit as e:
        return int(e.code or 0)


def _quiet_stderr():
    """Context manager that swallows stderr (selftest: expected error lines)."""
    import contextlib
    import io

    @contextlib.contextmanager
    def _cm():
        with contextlib.redirect_stderr(io.StringIO()):
            yield
    return _cm()


def _hash(q):
    import hashlib
    try:
        return hashlib.sha256(open(q, 'rb').read()).hexdigest()
    except Exception:
        return None


def _rmtree(d):
    import shutil
    shutil.rmtree(d, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Dashboard config: show / get / validate / atomic write (data/config.json).')
    ap.add_argument('--show', action='store_true',
                    help='print the effective knobs as JSON (read-only)')
    ap.add_argument('--get', action='append', default=[], metavar='KEY',
                    help='print one knob value bare (repeatable)')
    ap.add_argument('--set', action='append', default=[], metavar='KEY=VALUE',
                    help='validate and write one knob (repeatable)')
    ap.add_argument('--init', action='store_true',
                    help='create the config with defaults when it is absent')
    ap.add_argument('--schema', action='store_true',
                    help='print the knob rows as JSON (dashboard settings panel)')
    ap.add_argument('--selftest', action='store_true', help='offline checks on tmp fixtures')
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()

    if a.init:
        res = ensure()
        if not res['ok']:
            print(f'error: {res["error"]}', file=sys.stderr)
            return res['code']
        state = 'created with defaults' if res['created'] else 'already exists - left unchanged'
        print(f'config {state} -> {res["path"]} ({len(res["doc"])} keys)')
    if a.set:
        pairs = []
        for item in a.set:
            if '=' not in item:
                print(f'error: --set needs KEY=VALUE (got {item!r})', file=sys.stderr)
                return 2
            key, raw = item.split('=', 1)
            pairs.append((key.strip(), raw.strip()))
        code = _say_change(apply_changes(pairs))
        if code:
            return code
    if a.get:
        for i, key in enumerate(a.get):
            ok, text, err = get_value(key)
            if not ok:
                print(f'error: {err}', file=sys.stderr)
                return 2
            print(text if len(a.get) == 1 else f'{key.strip()} = {text}')
    if a.show:
        print(show_text())
    if a.schema:
        print(json.dumps(schema(), indent=2, ensure_ascii=False))
    if not (a.init or a.set or a.get or a.show or a.schema):
        ap.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
