"""Profile manager: one data profile per Warframe account (multi-account isolation).

Each account the dashboard trades for gets its own profile directory data/profiles/<name>/
holding a copy of every PROFILE-SCOPED data file - the files the trader engines and the
dashboard actually read for account state (MANIFEST below names the read path that justifies
each entry). The live data/ folder always holds exactly one account's files;
data/profiles/current.json is the marker naming which profile that is (no marker = the live
data was never switched, i.e. unmanaged).

Reads : data/* (live state), data/profiles/*, data/kill_switch.json (safety gate)
Writes: data/profiles/<name>/ (--create), data/* + data/profiles/current.json (--switch --apply),
        data/backups/*.zip (pre-switch safety zip via scripts/backup.py)
Never : deletes a file, touches secrets.json, or goes near the network. Every write is atomic
        (tmp file + os.replace), and the outgoing state always stays in its profile dir.

Usage:
  python scripts/profiles.py --list
  python scripts/profiles.py --create SampleTennoIX
  python scripts/profiles.py --switch Alt            (DRY RUN: prints the switch plan)
  python scripts/profiles.py --switch Alt --apply    (backup zip -> save live -> restore Alt)
  python scripts/profiles.py --current
  python scripts/profiles.py --manifest              (what is profile-scoped, and why)
  python scripts/profiles.py --selftest              (offline, tmp dirs, no repo data)

Env overrides (tests / selftest): WFM_DATA_DIR (live data dir), WFM_PROFILES_ROOT (profiles).
Exit codes: 0 = ok, 1 = error (missing profile/data), 2 = refused (bad args, name collision,
kill switch engaged, --apply without --switch).
"""
import argparse
import contextlib
import glob
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)                          # same-dir import style used by trader scripts
from cli import kv_block, render                  # noqa: E402  (house terminal helpers)

TOOL = 'scripts/profiles.py'
BACKUP_SCRIPT = os.path.join(HERE, 'backup.py')
PROFILE_META = 'profile.json'                     # lives INSIDE a profile dir, never copied out
NAME_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z')
RESERVED = ('current', 'profiles', 'backups', 'exports')
STATUS_WORD = {'same': 'identical', 'update': 'replace', 'restore': 'restore',
               'kept': 'left in place', 'missing': 'absent'}


# ------------------------------------------------------------------------ manifest
def entry(name, default, why, kind='json'):
    """One profile-scoped data file: name, the body a fresh profile starts from, and why."""
    return {'name': name, 'kind': kind, 'default': default, 'why': why}


# The MANIFEST is the contract: --create copies the CURRENT live state of these files into a
# profile, --switch --apply moves them between the profile dir and data/. 'why' quotes the real
# read/write path that makes the file account-scoped.
MANIFEST = [
    # --- this account's own state (written from the game save / the account's own actions) ---
    entry('lastData.dec.json', {}, 'decrypted AlecaFrame save: plat, MR, trades left, inventory '
          '(scripts/refresh.py:54 writes; server.summary_payload, trader/lister.py, '
          'trader/inuse.py and trader/detector.py read it)'),
    entry('owned.json', [], 'inventory rollup from that save (scripts/refresh.py:101 writes; read '
          'by cli.py, server.py, report/sets/ducats/nudges/deal_scanner/craft/rivens/relic_ev/'
          'trends/meta_watcher/invdiff/price_history and trader/inuse.py + trader/flipper.py)'),
    entry('trade_log.json', [], "this account's sale/purchase/listing events (scripts/log_trade.py, "
          'scripts/import_aleca_stats.py, server POST /api/trades, trader/detector.py)'),
    entry('plat_history.json', [], 'plat + credit snapshots for this account (scripts/snapshot_plat.py, '
          'scripts/import_aleca_stats.py, server /api/plat_history)'),
    entry('inuse.json', {}, 'copies slotted in loadouts, built from lastData.dec.json + owned.json '
          'by trader/inuse.py; trader/lister.py never lists an equipped copy'),
    entry('trader_state.json', {}, 'trader daemon state; carries the account name (trader/detector.py '
          'writes, trader/limits.py:account_name reads, server /api/trader)'),
    entry('detector_inventory.json', {}, 'per-(slug,lane) owned-copy baseline for sale detection v1 '
          '(trader/detector.py writes on each cycle; a baseline from another account would '
          'mis-confirm inventory-drop signals)'),
    entry('self_orders.json', [], 'order ids this account created; excluded from sale inference so '
          'relists never look like sales (trader/detector.py --mark-self/--unmark-self)'),
    entry('player_balance.json', {}, 'optional player ducats/credits override (scripts/baro.py:398) - '
          "an account's own balance"),
    # --- the account's own configuration (user-edited, never machine-overwritten) ---
    entry('wishlist_config.json', {'entries': []}, "user-editable buy targets; scripts/wishlist.py: "
          "'this file is created once and never rewritten'"),
    entry('watchlist_config.json', {'entries': []}, "user-editable watch rows; scripts/watchlist.py: "
          "'created once, NEVER overwritten'"),
    # --- plans + outputs the trader engines act on for this account ---
    entry('trader_plan.json', {}, "today's listing plan for this account (trader/lister.py writes; "
          'cli.py plan, server /api/trader, trader/hygiene.py, trader/runqueue.py, nudges.py read)'),
    entry('trader_limits.json', {}, "trades left today, trade cap, plat and MR from this account's "
          "live save (trader/limits.py writes; cli.py status, server feature 'limits')"),
    entry('trader_undercuts.json', {}, "this account's live order snapshot (trader/watcher.py writes; "
          'server /api/trader)'),
    entry('trader_relist_queue.json', [], "relist queue for this account's orders (trader/detector.py "
          'writes; server /api/trader)'),
    entry('run_queue.json', {}, 'in-game run queue built from trader_plan.json + trader_state.json '
          '(trader/runqueue.py)'),
    entry('hygiene_plan.json', {}, 'relist hygiene plan from trader_state.json + trader_plan.json '
          '(trader/hygiene.py)'),
    entry('flipper_plan.json', {}, 'budget-limited buy plan from flip_digest.json + deals.json + '
          'owned.json (trader/flipper.py)'),
    # --- market snapshots whose tracking set is this account's inventory ---
    entry('prices.json', {}, 'price snapshot for the slugs in owned.json only (scripts/fetch_prices.py:8 '
          'reads owned -> writes prices); read by ~30 call sites'),
    entry('stats.json', {}, 'vol48/med48 for that same owned set (scripts/fetch_stats.py:45 reads '
          'prices -> writes stats)'),
    entry('deals.json', {}, 'orderbook scan output; the scan pool is owned-first (deal_scanner.py:171 '
          "sorts owned slugs first) so its rotation follows this account's inventory"),
    entry('market_scan_state.json', {}, 'cursor + pool hash for that same owned-weighted pool '
          '(deal_scanner.py:236 writes it)'),
    entry('flip_digest.json', {}, 'throughput re-rank of deals.json over this account tracking set '
          '(scripts/flip_digest.py; server feature flips, watchlist.py + flipper.py read)'),
    entry('trends.json', {}, 'per-slug trend rows over the tracking set (deal slugs then liquid owned, '
          'scripts/trends.py:179-183)'),
    entry('price_history.json', {}, 'daily price points for the priced set from prices.json/owned.json '
          '(scripts/price_history.py)'),
    entry('price_movers.json', {}, '24h movers output of price_history (server feature movers)'),
    entry('meta_watch.json', {}, 'post-patch meta watch over the same bounded tracking set - '
          "meta_watcher.py: 'deal slugs by vol48 first, then liquid owned'"),
    # --- this account's analytics ---
    entry('report.json', {}, 'sell_now/flips report built from owned+prices+stats (scripts/report.py; '
          'cli.py picks, trader/lister.py lists from sell_now, server /api/report)'),
    entry('report.md', '', 'the same report as markdown (scripts/report.py:120)', kind='text'),
    entry('session_stats.json', {}, "this account's session analytics from trade_log.json + "
          'plat_history.json (scripts/session_stats.py; server feature sessions)'),
    entry('sell_timing.json', {}, 'which local hours THIS ACCOUNT sells in (scripts/sell_timing.py, '
          'trade_log.json input)'),
    entry('invdiff.json', {}, "inventory diff against this account's snapshots (scripts/invdiff.py; "
          'server feature invdiff)'),
    entry('inventory_snapshots', {}, 'daily owned.json snapshot copies (scripts/invdiff.py SNAPS); '
          'copied as a directory', kind='dir'),
    entry('sets.json', {}, 'set completion from owned.json (scripts/sets.py; cli.py sets, server '
          'feature sets, nudges.py reads)'),
    entry('ducats.json', {}, 'ducat burn/sell plan from owned.json (scripts/ducats.py; cli.py ducats, '
          'server feature ducats)'),
    entry('relic_ev.json', {}, 'relic EV over owned relics + prices (scripts/relic_ev.py; server '
          'feature relics)'),
    entry('rivens.json', {}, 'veiled riven bands + owned riven valuation (scripts/rivens.py reads '
          'owned.json via RIVENS_OWNED_PATH)'),
    entry('craft.json', {}, 'craft-vs-buy per recipe this account owns a blueprint/part for '
          '(scripts/craft.py reads owned.json + prices.json)'),
    entry('nudges.json', {}, 'near-complete nudges from sets.json + trader_plan.json + prices/owned '
          '(scripts/nudges.py; server feature nudges)'),
    entry('wishlist.json', {}, 'wishlist evaluation output (server feature wishlist)'),
    entry('watchlist.json', {}, "watchlist alert feed for this account's watch rows (scripts/watchlist.py)"),
]

# Same read-path count, but these files do NOT belong to an account: they are market/game
# catalogs, network caches, or global by design. Listed so the exclusion is explicit.
SHARED = [
    ('wfm_items_v2.json', 'warframe.market item catalog (regenerated from the market; identical '
                          'for every account)'),
    ('recipes_cache.json', 'WFCD crafting-recipe cache (game data)'),
    ('relic_prices.json', 'market price cache behind relic_ev.json'),
    ('riven_items_cache.json', 'market catalog cache for the riven bands'),
    ('riven_prices_cache.json', 'market quote cache for the riven bands'),
    ('meta_stats_cache.json', 'statistics-endpoint cache (TTL 12h) behind meta_watch.json'),
    ('trends_cache.json', 'raw market day rows behind trends.json'),
    ('baro.json', 'Void Trader stock/state (game-wide worldstate)'),
    ('baro_worldstate.json', 'worldstate cache (game-wide)'),
    ('gamenews.json', 'forum/Steam news cache (game-wide)'),
    ('notify_config.json', 'notification channel config (transport, not account state)'),
    ('notify_outbox.json', 'notification outbox (transport, not account state)'),
    ('kill_switch.json', 'GLOBAL safety interlock - deliberately never copied: --apply refuses '
                         'while it is engaged, and a switch must not carry or clear it'),
    ('backups/', 'generated backup zips (pre-switch zips land here too)'),
    ('exports/', 'generated export files (report.py/backup.py output)'),
    ('scripts/trader/settings.json', 'trader engine settings (engine config, outside data/)'),
    ('secrets.json', 'credentials (outside data/) - never read or written by this tool'),
]
ENTRIES = {e['name']: e for e in MANIFEST}


class Refused(Exception):
    """Action refused by a safety rule (exit 2)."""


class ProfileError(Exception):
    """Missing/unusable profile or data (exit 1)."""


# ---------------------------------------------------------------------------- paths
def data_dir():
    """Live data dir; WFM_DATA_DIR (env) overrides it for tests/selftest."""
    return os.environ.get('WFM_DATA_DIR') or os.path.join(ROOT, 'data')


def profiles_root():
    """Profile root; WFM_PROFILES_ROOT (env) overrides it for tests/selftest."""
    return os.environ.get('WFM_PROFILES_ROOT') or os.path.join(data_dir(), 'profiles')


def marker_path():
    return os.path.join(profiles_root(), 'current.json')


def rel(path):
    """Repo-relative forward-slash path for messages (absolute when it is outside the repo)."""
    text = str(path)
    try:
        out = os.path.relpath(text, ROOT)
        if not out.startswith('..'):
            text = out
    except Exception:                            # different drive on Windows: keep it absolute
        pass
    return text.replace('\\', '/')


def check_name(name):
    """(ok, why) for a profile name: one path-safe directory component, nothing reserved."""
    if not name:
        return False, 'empty profile name'
    if not NAME_RE.match(name):
        return False, ('bad profile name %r - use letters/digits/._- (start with a letter or digit, '
                       'max 64 chars)' % name)
    if name.lower() in RESERVED:
        return False, 'reserved profile name %r' % name
    return True, ''


def profile_dir(name):
    ok, why = check_name(name)
    if not ok:
        raise Refused(why)
    return os.path.join(profiles_root(), name)


# ------------------------------------------------------------------------ file utils
def iso(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def fmt_bytes(n):
    if n is None:
        return '-'
    if n < 1024:
        return '%dB' % n
    if n < 1024 * 1024:
        return '%.1fK' % (n / 1024.0)
    return '%.1fM' % (n / (1024.0 * 1024.0))


def _atomic_write(path, data):
    """Write bytes via a sibling tmp file + os.replace: readers never see a partial file."""
    d = os.path.dirname(os.path.abspath(path)) or '.'
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + os.path.basename(path) + '.', suffix='.tmp', dir=d)
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path, obj):
    _atomic_write(path, (json.dumps(obj, indent=1, ensure_ascii=False) + '\n').encode('utf-8'))


def write_text(path, text):
    _atomic_write(path, text.encode('utf-8'))


def fingerprint(path):
    """{'size': n, 'sha1': hex12} for a file, or None when missing/unreadable."""
    h, n = hashlib.sha1(), 0
    try:
        with open(path, 'rb') as fh:
            for chunk in iter(lambda: fh.read(65536), b''):
                h.update(chunk)
                n += len(chunk)
    except OSError:
        return None
    return {'size': n, 'sha1': h.hexdigest()[:12]}


def scan_tree(path):
    """{relative name: {'size', 'sha1'}} for every file under path ({} when missing)."""
    out = {}
    if not os.path.isdir(path):
        return out
    for base, dirs, files in os.walk(path):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(base, name)
            fp = fingerprint(full)
            if fp:
                out[os.path.relpath(full, path).replace('\\', '/')] = fp
    return out


def entries_under(state, name):
    """Slice of a scan_tree() result belonging to one manifest entry (file itself or dir tree)."""
    return {k: v for k, v in state.items() if k == name or k.startswith(name + '/')}


def copy_file(src, dst, skip_identical=True):
    """Atomic byte copy. True when written, False when the target already holds those bytes."""
    with open(src, 'rb') as fh:
        data = fh.read()
    if skip_identical:
        fp = fingerprint(dst)
        if fp and fp['sha1'] == hashlib.sha1(data).hexdigest()[:12]:
            return False
    _atomic_write(dst, data)
    return True


def copy_entry(entry_, src_dir, dst_dir):
    """Copy one manifest entry (file or dir tree) between two data dirs. Copy-only."""
    name = entry_['name']
    src, dst = os.path.join(src_dir, name), os.path.join(dst_dir, name)
    if entry_['kind'] == 'dir':
        os.makedirs(dst, exist_ok=True)
        state, n = scan_tree(src), 0
        for relp in sorted(state):
            sp = os.path.join(src, relp.replace('/', os.sep))
            dp = os.path.join(dst, relp.replace('/', os.sep))
            if copy_file(sp, dp):
                n += 1
        return n
    if not os.path.isfile(src):
        return 0
    return 1 if copy_file(src, dst) else 0


def manifest_present(pdir, entry_):
    """True when a profile dir holds this manifest entry (file exists / dir exists)."""
    p = os.path.join(pdir, entry_['name'])
    return os.path.isdir(p) if entry_['kind'] == 'dir' else os.path.isfile(p)


def manifest_gaps(pdir):
    """Manifest entries missing from a profile dir - the completeness invariant."""
    return [e['name'] for e in MANIFEST if not manifest_present(pdir, e)]


def live_summary():
    n = sum(1 for e in MANIFEST if manifest_present(data_dir(), e))
    return '%d/%d manifest files present' % (n, len(MANIFEST))


# ---------------------------------------------------------------------------- state
def read_marker():
    """(marker, warning): marker holds current/switched/previous; a corrupt file only warns."""
    p = marker_path()
    blank = {'current': None, 'switched': None, 'previous': None, 'path': p}
    if not os.path.exists(p):
        return blank, None
    try:
        with open(p, encoding='utf-8') as fh:
            doc = json.load(fh)
        if not isinstance(doc, dict):
            raise ValueError('marker is not a JSON object')
        cur = doc.get('current')
        if cur is not None:
            ok, why = check_name(str(cur))
            if not ok:
                raise ValueError(why)
        doc['path'] = p
        return doc, None
    except (OSError, ValueError) as exc:
        blank['corrupt'] = str(exc)
        return blank, ('warning: %s is unreadable (%s) - treating the live data as unmanaged'
                       % (rel(p), exc))


def killswitch_state():
    """(engaged, note): True while data/kill_switch.json says active. Fail-open, like hygiene.py."""
    try:
        with open(os.path.join(data_dir(), 'kill_switch.json'), encoding='utf-8') as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        doc = None
    if isinstance(doc, dict) and doc.get('active'):
        return True, str(doc.get('note') or '')
    return False, ''


def write_marker(name, previous, files):
    now = int(time.time())
    doc = {'current': name, 'switched': now, 'switched_iso': iso(now), 'previous': previous,
           'files': files, 'tool': TOOL}
    write_json(marker_path(), doc)
    return doc


def list_profiles():
    """Profiles on disk, sorted: {name, dir, files, bytes, meta} (meta from profile.json)."""
    root, out = profiles_root(), []
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        pdir = os.path.join(root, name)
        if not os.path.isdir(pdir) or name.startswith('.'):
            continue
        if not check_name(name)[0]:
            continue
        state = scan_tree(pdir)
        state.pop(PROFILE_META, None)
        meta = {}
        try:
            with open(os.path.join(pdir, PROFILE_META), encoding='utf-8') as fh:
                doc = json.load(fh)
            if isinstance(doc, dict):
                meta = doc
        except (OSError, ValueError):
            meta = {}
        out.append({'name': name, 'dir': pdir, 'files': len(state),
                    'bytes': sum(v['size'] for v in state.values()), 'meta': meta})
    return out


# --------------------------------------------------------------------------- backup
def _load_module(path, modname):
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise ImportError('cannot load %s' % path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pre_switch_backup():
    """Safety zip of data/ before a switch: scripts/backup.py's make_zip(), stdlib fallback.

    Returns (zip path, file count, how). backup.py is reused as a module with DATA/BACKUPS
    pointed at this run's data dir (so tests/selftest stay inside their tmp dir).
    """
    d, backups = data_dir(), os.path.join(data_dir(), 'backups')
    how = 'scripts/backup.py make_zip()'
    try:
        mod = _load_module(BACKUP_SCRIPT, 'wfm_profiles_backup')
        mod.DATA, mod.BACKUPS = d, backups
        mod.EXPORTS = os.path.join(d, 'exports')
        out, n, _kept = mod.make_zip()
        return out, n, how
    except Exception as exc:                      # noqa: BLE001 - any failure falls back
        how = 'stdlib fallback zip (backup.py unusable: %s)' % str(exc)[:60]
    os.makedirs(backups, exist_ok=True)
    out = os.path.join(backups, time.strftime('wfm-profiles-%Y%m%d-%H%M%S.zip'))
    skip_dirs, skip_ext, n = {'backups', 'exports'}, {'.log', '.zip'}, 0
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for base, dirs, files in os.walk(d):      # mirrors backup.py's own walk rules
            sub = os.path.relpath(base, d)
            dirs[:] = [x for x in dirs if x not in skip_dirs]
            for name in files:
                if os.path.splitext(name)[1].lower() in skip_ext:
                    continue
                arc = name if sub == '.' else os.path.join(sub, name)
                z.write(os.path.join(base, name), arc)
                n += 1
    return out, n, how


# --------------------------------------------------------------------------- create
def create_profile(name):
    """Copy the CURRENT live data state into a fresh profile. Copy-only, atomic, no overwrites."""
    ok, why = check_name(name)
    if not ok:
        raise Refused(why)
    root, pdir = profiles_root(), profile_dir(name)
    if os.path.isdir(pdir):
        raise Refused("profile '%s' already exists (%s) - pick another name, or --switch %s to use it"
                      % (name, rel(pdir), name))
    os.makedirs(root, exist_ok=True)
    staging = tempfile.mkdtemp(prefix='.create-%s.' % name, dir=root)
    rows, copied, defaults, empty = [], 0, 0, 0
    try:
        for e in MANIFEST:
            src = os.path.join(data_dir(), e['name'])
            dst = os.path.join(staging, e['name'])
            if e['kind'] == 'dir':
                os.makedirs(dst, exist_ok=True)
                state = scan_tree(src)
                for relp in sorted(state):
                    copy_file(os.path.join(src, relp.replace('/', os.sep)),
                              os.path.join(dst, relp.replace('/', os.sep)))
                copied += len(state)
                if not state:
                    empty += 1
                rows.append([e['name'] + '/', 'copied %d file(s)' % len(state) if state else 'created empty',
                             fmt_bytes(sum(v['size'] for v in state.values()))])
                continue
            have = fingerprint(src) is not None
            if have:
                copy_file(src, dst)
                copied += 1
                note = 'copied from live'
            elif e['kind'] == 'text':
                write_text(dst, e['default'])
                defaults += 1
                note = 'empty default'
            else:
                write_json(dst, e['default'])
                defaults += 1
                note = 'default %s' % json.dumps(e['default'])
            rows.append([e['name'], note, fmt_bytes((fingerprint(dst) or {}).get('size', 0))])
        meta = {'name': name, 'created': int(time.time()), 'created_iso': iso(time.time()),
                'source': 'live data', 'manifest_files': len(MANIFEST),
                'copied': copied, 'defaults': defaults, 'tool': TOOL}
        write_json(os.path.join(staging, PROFILE_META), meta)
        os.replace(staging, pdir)                 # atomic: a half-built profile never appears
        staging = None
    finally:
        if staging and os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)

    print("profile '%s' created -> %s" % (name, rel(pdir)))
    print('  %d/%d manifest entries: %d copied from live data, %d defaults, %d empty dir(s)%s'
          % (len(MANIFEST) - len(manifest_gaps(pdir)), len(MANIFEST), copied, defaults, empty,
             '' if not manifest_gaps(pdir) else '  MISSING: %s' % ', '.join(manifest_gaps(pdir))))
    print(render(['file', 'source', 'size'], rows, right={2}))
    print('live data/ untouched. Switch with: %s --switch %s' % (TOOL, name))
    return {'name': name, 'dir': pdir, 'copied': copied, 'defaults': defaults}


# --------------------------------------------------------------------------- switch
def plan_switch(name):
    """Everything --apply would do, computed read-only (nothing is written)."""
    ok, why = check_name(name)
    if not ok:
        raise Refused(why)
    pdir = profile_dir(name)
    if not os.path.isdir(pdir):
        raise ProfileError("no profile '%s' (%s does not exist) - --list shows the profiles on disk"
                           % (name, rel(pdir)))
    marker, warn = read_marker()
    cur = marker.get('current')
    live_state, prof_state = scan_tree(data_dir()), scan_tree(pdir)
    rows, counts = [], {'same': 0, 'update': 0, 'restore': 0, 'kept': 0, 'missing': 0}
    for e in MANIFEST:
        nm, kind = e['name'], e['kind']
        live_files, prof_files = entries_under(live_state, nm), entries_under(prof_state, nm)
        if kind == 'dir':
            has_prof = os.path.isdir(os.path.join(pdir, nm))
            lhash = {k: v['sha1'] for k, v in live_files.items()}
            phash = {k: v['sha1'] for k, v in prof_files.items()}
            if not has_prof:
                status = 'kept' if live_files else 'missing'
            elif lhash == phash:
                status = 'same'
            else:
                status = 'update' if live_files else 'restore'
        else:
            lf, pf = live_files.get(nm), prof_files.get(nm)
            if lf and pf:
                status = 'same' if lf['sha1'] == pf['sha1'] else 'update'
            elif pf:
                status = 'restore'
            elif lf:
                status = 'kept'
            else:
                status = 'missing'
        counts[status] += 1
        rows.append({'name': nm, 'kind': kind, 'status': status,
                     'live_bytes': sum(v['size'] for v in live_files.values()) if live_files else None,
                     'profile_bytes': sum(v['size'] for v in prof_files.values()) if prof_files else None})
    odir = os.path.join(profiles_root(), cur) if cur else None
    ostate = scan_tree(odir) if odir and os.path.isdir(odir) else {}
    out_rows, out_counts = [], {'save': 0, 'same': 0, 'absent': 0}
    for e in MANIFEST:
        nm = e['name']
        live_files = entries_under(live_state, nm)
        if not live_files:
            out_counts['absent'] += 1
            out_rows.append({'name': nm, 'state': 'absent'})
            continue
        same = ({k: v['sha1'] for k, v in live_files.items()}
                == {k: v['sha1'] for k, v in entries_under(ostate, nm).items()})
        out_counts['same' if same else 'save'] += 1
        out_rows.append({'name': nm, 'state': 'same' if same else 'save',
                         'bytes': sum(v['size'] for v in live_files.values())})
    return {'name': name, 'pdir': pdir, 'live_dir': data_dir(),
            'outgoing': cur, 'outgoing_dir': odir, 'outgoing_exists': bool(odir and os.path.isdir(odir)),
            'marker': marker, 'marker_file': marker_path(), 'marker_warning': warn,
            'gaps': manifest_gaps(pdir), 'rows': rows, 'counts': counts,
            'out_rows': out_rows, 'out_counts': out_counts}


def print_plan(plan, do_apply):
    c, oc = plan['counts'], plan['out_counts']
    print('SWITCH PLAN%s' % ('' if do_apply else ' (DRY RUN - nothing is written)'))
    print(kv_block([
        ('incoming', 'profile %s (%s)  ->  live data/' % (plan['name'], rel(plan['pdir']))),
        ('outgoing', 'live data/  ->  profile %s' % (plan['outgoing'] or 'none (live data is unmanaged)')),
        ('marker', rel(plan['marker_file'])),
    ]))
    print('')
    moving = [r for r in plan['rows'] if r['status'] != 'same']
    if moving:
        print('files that would move (profile %s -> live data/):' % plan['name'])
        print(render(['file', 'action', 'live', 'profile'],
                     [[r['name'] + ('/' if r['kind'] == 'dir' else ''), STATUS_WORD[r['status']],
                       fmt_bytes(r['live_bytes']), fmt_bytes(r['profile_bytes'])] for r in moving],
                     right={2, 3}))
    else:
        print('files that would move: none - the live data already matches profile %r' % plan['name'])
    print('%s replaced, %s restored, %s identical, %s left in place (missing from the profile)'
          % (c['update'], c['restore'], c['same'], c['kept']))
    if plan['outgoing'] and plan['outgoing_exists']:
        print('outgoing: %s file(s) to save into the outgoing profile, %s already in sync, %s absent from live'
              % (oc['save'], oc['same'], oc['absent']))
    else:
        print('outgoing: %s - the pre-switch backup zip is the only copy of the current live state'
              % ('live data is unmanaged' if not plan['outgoing']
                 else "profile '%s' is missing on disk" % plan['outgoing']))
    if c['kept']:
        print('note: %s live file(s) the profile does not have stay in place - nothing is ever deleted'
              % c['kept'])
    if plan['gaps']:
        print('warning: profile %r is incomplete - %d manifest file(s) missing (%s); '
              'live copies of those files stay in place' % (plan['name'], len(plan['gaps']),
                                                            ', '.join(plan['gaps'][:8])
                                                            + (' ...' if len(plan['gaps']) > 8 else '')))
    if not do_apply:
        print('nothing is ever deleted: the outgoing state is copied into the outgoing profile dir first.')
        print('run again with --apply to perform the switch (a safety zip of data/ is written first).')


def apply_switch(plan):
    """Perform the plan: backup zip -> save live into the outgoing profile -> restore target.

    Returns an exit code: 0 on success, 1 when a copy is interrupted (the caller then points at
    the safety zip - every individual file write is atomic, so no file is ever half-written).
    """
    t0 = time.time()
    name, pdir, live = plan['name'], plan['pdir'], plan['live_dir']
    os.makedirs(live, exist_ok=True)
    try:
        zip_path, n_zip, how = pre_switch_backup()
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print('error: cannot write the pre-switch backup (%s: %s) - switch refused, nothing changed'
              % (type(exc).__name__, exc))
        return 1
    print('[1/5] safety backup: %s (%d file(s), %s)' % (rel(zip_path), n_zip, how))

    try:
        if plan['outgoing'] and plan['outgoing_exists']:
            saved = same = 0
            for r in plan['out_rows']:
                if r['state'] == 'save':
                    saved += copy_entry(ENTRIES[r['name']], live, plan['outgoing_dir'])
                elif r['state'] == 'same':
                    same += 1
            print("[2/5] live state saved into outgoing profile '%s': %d file(s) written, %d already in sync"
                  % (plan['outgoing'], saved, same))
        else:
            print('[2/5] no outgoing profile (%s) - the backup zip above is the only copy of the previous state'
                  % ('live data was unmanaged' if not plan['outgoing']
                     else "profile '%s' is missing on disk" % plan['outgoing']))

        replaced = restored = 0
        for r in plan['rows']:
            if r['status'] in ('update', 'restore'):
                copy_entry(ENTRIES[r['name']], pdir, live)
                if r['status'] == 'update':
                    replaced += 1
                else:
                    restored += 1
        print('[3/5] profile %r restored into live data: %d replaced, %d restored, %d identical, %d left in place'
              % (name, replaced, restored, plan['counts']['same'], plan['counts']['kept']))
        if plan['counts']['kept']:
            print('      left in place (never deleted): %s'
                  % ', '.join(r['name'] for r in plan['rows'] if r['status'] == 'kept'))

        write_marker(name, plan['outgoing'], len(MANIFEST))
    except (OSError, ValueError, KeyError) as exc:
        print('error: switch interrupted (%s: %s) - the outgoing profile and the safety zip are intact: %s'
              % (type(exc).__name__, exc, rel(zip_path)))
        print('       re-run --switch %s --apply once the cause is fixed' % name)
        return 1
    print('[4/5] marker written: %s -> %r (was %s)'
          % (rel(plan['marker_file']), name, plan['outgoing'] or 'unmanaged'))
    print('[5/5] switch complete in %.1fs - restart the server to apply (stop.bat, then start.bat)'
          % (time.time() - t0))
    print('      live data now holds profile %r (%s)' % (name, live_summary()))
    return 0


# -------------------------------------------------------------------------- commands
_JSON = False          # set by main() for --json (machine-readable --list / --current)


def json_list_payload():
    """Machine-readable --list: marker state + every profile (the dashboard card reads this)."""
    marker, warn = read_marker()
    cur = marker.get('current')
    return {
        'managed': bool(cur),
        'current': cur or None,
        'switched': marker.get('switched') or None,
        'previous': marker.get('previous') or None,
        'marker': rel(marker_path()),
        'root': rel(profiles_root()),
        'warning': warn or None,
        'live': live_summary(),
        'profiles': [{'name': p['name'], 'files': p['files'], 'bytes': p['bytes'],
                      'created': (p['meta'] or {}).get('created'),
                      'current': p['name'] == cur} for p in list_profiles()],
    }


def json_current_payload():
    marker, warn = read_marker()
    cur = marker.get('current')
    out = {'managed': bool(cur), 'current': cur or None,
           'switched': marker.get('switched') or None, 'previous': marker.get('previous') or None,
           'marker': rel(marker_path()), 'warning': warn or None, 'live': live_summary()}
    if cur:
        pdir = os.path.join(profiles_root(), cur)
        out['profile_dir'] = rel(pdir)
        out['profile_dir_exists'] = os.path.isdir(pdir)
    return out


def cmd_list():
    if _JSON:
        print(json.dumps(json_list_payload(), indent=1))
        return 0
    marker, warn = read_marker()
    cur = marker.get('current')
    if warn:
        print(warn)
    print('profiles root: %s' % rel(profiles_root()))
    if cur:
        when = iso(marker['switched']) if marker.get('switched') else '-'
        print('current      : %s (switched %s)' % (cur, when))
    else:
        print('current      : none - the live data is unmanaged (%s)' % rel(marker_path()))
    plist = list_profiles()
    if not plist:
        print('no profiles yet - --create NAME copies the current live data into a new profile')
    else:
        rows = []
        for p in plist:
            meta = p['meta']
            created = iso(meta['created']) if meta.get('created') else '-'
            rows.append([p['name'], str(p['files']), fmt_bytes(p['bytes']), created,
                         '* current' if p['name'] == cur else ''])
        print(render(['profile', 'files', 'size', 'created', ''], rows, right={1, 2}))
    print('live data    : %s' % live_summary())
    return 0


def cmd_current():
    if _JSON:
        print(json.dumps(json_current_payload(), indent=1))
        return 0
    marker, warn = read_marker()
    if warn:
        print(warn)
    cur = marker.get('current')
    pairs = [('current profile', cur or 'none (live data is unmanaged)')]
    if cur:
        pdir = os.path.join(profiles_root(), cur)
        pairs += [('switched', iso(marker['switched']) if marker.get('switched') else '-'),
                  ('previous', marker.get('previous') or '-'),
                  ('profile dir', rel(pdir) + ('' if os.path.isdir(pdir) else '  (MISSING on disk)'))]
    pairs += [('marker', rel(marker_path())), ('live data', live_summary())]
    print(kv_block(pairs))
    return 0


def cmd_manifest():
    print('PROFILE-SCOPED FILES (%d) - copied by --create / --switch, one set per account' % len(MANIFEST))
    for e in MANIFEST:
        print('%s  [%s]' % (e['name'] + ('/' if e['kind'] == 'dir' else ''), e['kind']))
        print('    %s' % e['why'])
    print('')
    print('SHARED FILES (%d) - never copied: market/game catalogs, caches, global by design' % len(SHARED))
    for name, why in SHARED:
        print('%s  [shared]' % name)
        print('    %s' % why)
    return 0


def cmd_create(name):
    create_profile(name)
    return 0


def cmd_switch(name, do_apply):
    plan = plan_switch(name)
    if plan['marker_warning']:
        print(plan['marker_warning'])
    if plan['outgoing'] == name:
        print("profile '%s' is already current - nothing to do (%s)" % (name, rel(plan['marker_file'])))
        return 1
    engaged, note = killswitch_state()
    if engaged and do_apply:
        print('kill switch engaged (data/kill_switch.json%s) - refusing to switch profiles'
              % (': %s' % note if note else ''))
        print('clear it first (scripts/trader/killswitch.py) if the account really should be swapped.')
        return 2
    print_plan(plan, do_apply)
    if not do_apply:
        if engaged:
            print('note: the kill switch is engaged - --apply would refuse right now')
        return 0
    return apply_switch(plan)


# -------------------------------------------------------------------------- selftest
def selftest():
    """Offline self-test in a tmp dir (WFM_DATA_DIR + WFM_PROFILES_ROOT overridden)."""
    checks, fails = [], []

    def chk(label, got, want):
        checks.append(label)
        if got != want:
            fails.append('%s: got %r, want %r' % (label, got, want))

    def run(argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            try:
                code = main(argv)
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return code, buf.getvalue()

    def read_json(path):
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)

    owned_a = [{'slug': 'primed_continuity', 'name': 'Primed Continuity', 'count': 2}]
    owned_b = owned_a + [{'slug': 'archon_flow', 'name': 'Archon Flow', 'count': 1}]
    owned_c = [{'slug': 'growing_power', 'name': 'Growing Power', 'count': 4}]
    root = tempfile.mkdtemp(prefix='wfm-profiles-selftest-')
    saved = {k: os.environ.get(k) for k in ('WFM_DATA_DIR', 'WFM_PROFILES_ROOT')}
    os.environ['WFM_DATA_DIR'] = os.path.join(root, 'data')
    os.environ['WFM_PROFILES_ROOT'] = os.path.join(root, 'data', 'profiles')
    try:
        d = data_dir()
        chk('WFM_PROFILES_ROOT honoured', profiles_root(), os.path.join(root, 'data', 'profiles'))
        # live fixture: some manifest files present, some missing (defaults), one shared file
        os.makedirs(os.path.join(d, 'inventory_snapshots'), exist_ok=True)
        write_json(os.path.join(d, 'owned.json'), owned_a)
        write_json(os.path.join(d, 'trade_log.json'), [{'kind': 'sale', 'total': 20, 'qty': 1}])
        write_json(os.path.join(d, 'trader_state.json'), {'account': 'TESTER', 'plat': 500})
        write_json(os.path.join(d, 'lastData.dec.json'), {'PremiumCredits': 500, 'PlayerLevel': 22})
        write_json(os.path.join(d, 'kill_switch.json'), {'active': False, 'note': '', 'ts': 0})
        write_json(os.path.join(d, 'gamenews.json'), {'items': [1]})            # shared, never moves
        write_json(os.path.join(d, 'inventory_snapshots', 'owned_2026-01-01.json'), [{'slug': 'x'}])

        # -- manifest sanity ---------------------------------------------------
        names = [e['name'] for e in MANIFEST]
        chk('manifest: no duplicate names', len(names), len(set(names)))
        chk('manifest: every entry has a reason', [e['name'] for e in MANIFEST if not e.get('why')], [])
        chk('manifest: globals excluded', [n for n in names
                                           if n in ('kill_switch.json', 'secrets.json', PROFILE_META,
                                                    'wfm_items_v2.json', 'gamenews.json')], [])
        chk('manifest: no sha1 defaults explosion', all(e['kind'] in ('json', 'text', 'dir') for e in MANIFEST), True)
        bad_defaults = []
        for e in MANIFEST:
            if e['kind'] == 'json':
                try:
                    json.dumps(e['default'])
                except TypeError as exc:
                    bad_defaults.append('%s (%s)' % (e['name'], exc))
        chk('manifest: JSON defaults serialise', bad_defaults, [])
        required = {'owned.json', 'prices.json', 'stats.json', 'trade_log.json', 'plat_history.json',
                    'report.json', 'trader_plan.json', 'trader_state.json', 'inuse.json',
                    'trader_limits.json', 'wishlist_config.json', 'watchlist_config.json'}
        chk('manifest: covers the account files the task names', sorted(required - set(names)), [])

        # -- marker handling: no marker yet -----------------------------------
        code, out = run(['--current'])
        chk('current with no marker: exit', code, 0)
        chk('current with no marker: says unmanaged', 'unmanaged' in out, True)
        code, out = run(['--list'])
        chk('list with no profiles: exit', code, 0)
        chk('list with no profiles: says none', 'no profiles yet' in out, True)

        # -- create ------------------------------------------------------------
        code, out = run(['--create', 'alpha'])
        chk('create alpha: exit', code, 0)
        alpha = os.path.join(profiles_root(), 'alpha')
        chk('create alpha: dir exists', os.path.isdir(alpha), True)
        chk('create alpha: manifest complete', manifest_gaps(alpha), [])
        chk('create alpha: live file copied', read_json(os.path.join(alpha, 'owned.json')), owned_a)
        chk('create alpha: missing file defaulted', read_json(os.path.join(alpha, 'stats.json')), {})
        chk('create alpha: text file created', os.path.isfile(os.path.join(alpha, 'report.md')), True)
        chk('create alpha: snapshot dir copied',
            read_json(os.path.join(alpha, 'inventory_snapshots', 'owned_2026-01-01.json')), [{'slug': 'x'}])
        chk('create alpha: profile meta', read_json(os.path.join(alpha, PROFILE_META)).get('name'), 'alpha')
        chk('create alpha: kill switch NOT copied', os.path.isfile(os.path.join(alpha, 'kill_switch.json')), False)
        chk('create alpha: warns live untouched', 'live data/ untouched' in out, True)

        # -- collision + bad names --------------------------------------------
        before = scan_tree(alpha)
        code, out = run(['--create', 'alpha'])
        chk('create collision: exit', code, 2)
        chk('create collision: clear message', 'already exists' in out, True)
        chk('create collision: profile untouched', scan_tree(alpha), before)
        for bad in ('..', 'a/b', 'two words', ''):
            code, _ = run(['--create', bad] if bad != '' else ['--create', ''])
            chk('create refuses %r' % bad, code, 2)
        code, out = run(['--list'])
        chk('list shows the profile', 'alpha' in out, True)
        code, out = run(['--current'])
        chk('current still unmanaged (create is not a switch)', 'unmanaged' in out, True)

        # -- dry run ------------------------------------------------------------
        live_before = scan_tree(d)
        code, out = run(['--switch', 'alpha'])
        chk('switch dry-run: exit', code, 0)
        chk('switch dry-run: labelled dry run', 'DRY RUN' in out, True)
        chk('switch dry-run: lists files that would move',
            any(n in out for n in ('report.md', 'stats.json', 'prices.json')), True)
        chk('switch dry-run: counts line', 'identical' in out and 'left in place' in out, True)
        chk('switch dry-run: names the marker', 'current.json' in out, True)
        chk('switch dry-run: nothing written', scan_tree(d), live_before)
        chk('switch dry-run: profiles untouched', scan_tree(alpha), before)
        code, _ = run(['--switch', 'nope'])
        chk('switch missing profile: exit', code, 1)

        # -- create beta from live, then apply alpha ---------------------------
        code, _ = run(['--create', 'beta'])
        chk('create beta: exit', code, 0)
        beta = os.path.join(profiles_root(), 'beta')
        chk('create beta: complete', manifest_gaps(beta), [])
        write_json(os.path.join(d, 'owned.json'), owned_b)      # live drifts after the profiles
        write_json(os.path.join(d, 'stats.json'), {'x': {'vol48': 5}})
        beta_before = scan_tree(beta)
        code, out = run(['--switch', 'alpha', '--apply'])
        chk('switch apply: exit', code, 0)
        chk('switch apply: live owned restored', read_json(os.path.join(d, 'owned.json')), owned_a)
        chk('switch apply: live stats restored', read_json(os.path.join(d, 'stats.json')), {})
        chk('switch apply: marker current', read_json(marker_path()).get('current'), 'alpha')
        chk('switch apply: marker previous empty', read_json(marker_path()).get('previous'), None)
        chk('switch apply: says restart', 'restart the server' in out, True)
        chk('switch apply: live complete', manifest_gaps(d), [])
        chk('switch apply: backup zip written', len(glob.glob(os.path.join(d, 'backups', '*.zip'))) >= 1, True)
        chk('switch apply: shared file untouched', read_json(os.path.join(d, 'gamenews.json')), {'items': [1]})
        chk('switch apply: unattached profile untouched', scan_tree(beta), beta_before)
        chk('switch apply: kill switch never carried', os.path.isfile(os.path.join(alpha, 'kill_switch.json')), False)

        # -- round trip --------------------------------------------------------
        write_json(os.path.join(d, 'owned.json'), owned_c)
        code, _ = run(['--switch', 'beta', '--apply'])
        chk('round trip: switch beta exit', code, 0)
        chk('round trip: live is beta state', read_json(os.path.join(d, 'owned.json')), owned_a)
        chk('round trip: outgoing alpha preserved live drift',
            read_json(os.path.join(alpha, 'owned.json')), owned_c)
        chk('round trip: marker beta', read_json(marker_path()).get('current'), 'beta')
        chk('round trip: marker records previous', read_json(marker_path()).get('previous'), 'alpha')
        code, out = run(['--switch', 'alpha', '--apply'])
        chk('round trip: back to alpha exit', code, 0)
        chk('round trip: live restored to alpha state', read_json(os.path.join(d, 'owned.json')), owned_c)
        chk('round trip: marker alpha again', read_json(marker_path()).get('current'), 'alpha')
        code, out = run(['--switch', 'alpha'])
        chk('switch to current: exit', code, 1)
        chk('switch to current: says already current', 'already current' in out, True)

        # -- a live file the target profile lacks is never deleted -------------
        os.remove(os.path.join(beta, 'sets.json'))
        write_json(os.path.join(d, 'sets.json'), {'live': True})
        code, out = run(['--switch', 'beta'])
        chk('incomplete profile: dry run warns', 'is incomplete' in out, True)
        code, out = run(['--switch', 'beta', '--apply'])
        chk('live-only file: switch exit', code, 0)
        chk('live-only file: left in place', read_json(os.path.join(d, 'sets.json')), {'live': True})
        chk('live-only file: reported', 'left in place' in out, True)
        chk('live-only file: saved into outgoing profile',
            read_json(os.path.join(alpha, 'sets.json')), {'live': True})

        # -- kill switch refusal ----------------------------------------------
        write_json(os.path.join(d, 'kill_switch.json'), {'active': True, 'note': 'hold', 'ts': 0})
        marker_before = open(marker_path(), 'rb').read()
        live_marker_state = scan_tree(d)
        code, out = run(['--switch', 'alpha', '--apply'])
        chk('kill switch: apply refused', code, 2)
        chk('kill switch: says so', 'kill switch engaged' in out, True)
        chk('kill switch: marker untouched', open(marker_path(), 'rb').read(), marker_before)
        chk('kill switch: live data untouched', scan_tree(d), live_marker_state)
        code, out = run(['--switch', 'alpha'])
        chk('kill switch: dry run still allowed', code, 0)
        chk('kill switch: dry run warns', '--apply would refuse' in out, True)
        write_json(os.path.join(d, 'kill_switch.json'), {'active': False, 'note': '', 'ts': 0})

        # -- corrupt marker ----------------------------------------------------
        write_text(marker_path(), '{ not json')
        code, out = run(['--current'])
        chk('corrupt marker: exit', code, 0)
        chk('corrupt marker: warns', 'warning' in out.lower(), True)
        chk('corrupt marker: treated as unmanaged', 'unmanaged' in out, True)
        code, out = run(['--list'])
        chk('corrupt marker: list still works', code, 0)
        code, _ = run(['--switch', 'alpha', '--apply'])
        chk('corrupt marker: switch still works', code, 0)
        chk('corrupt marker: rewritten', read_json(marker_path()).get('current'), 'alpha')

        # -- argument handling -------------------------------------------------
        code, _ = run(['--apply'])
        chk('apply without switch: exit', code, 2)
        code, _ = run(['--list', '--current'])
        chk('two actions: exit', code, 2)
        code, out = run([])
        chk('no args: prints help', code, 2)
        chk('no args: help mentions --switch', '--switch' in out, True)
        code, out = run(['--manifest'])
        chk('manifest listing: exit', code, 0)
        chk('manifest listing: shows owned.json', 'owned.json' in out, True)
        chk('manifest listing: shows kill_switch as shared', 'kill_switch.json  [shared]' in out, True)

        # -- nothing of the repo's own data was touched ------------------------
        chk('everything ran inside the tmp root', str(d).startswith(root), True)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(root, ignore_errors=True)

    bad = len(fails)
    print('selftest: %s %d/%d' % ('FAIL' if bad else 'PASS', len(checks) - bad, len(checks)))
    for f in fails:
        print('  FAIL %s' % f)
    return 1 if bad else 0


# ------------------------------------------------------------------------------ main
def build_parser():
    p = argparse.ArgumentParser(
        prog='profiles.py',
        description='Profile manager: one data profile per Warframe account (data/profiles/<name>/).',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='examples:\n'
               '  profiles.py --list\n'
               '  profiles.py --create SampleTennoIX\n'
               '  profiles.py --switch Alt              (dry run: prints the plan)\n'
               '  profiles.py --switch Alt --apply      (backup zip, save live, restore Alt)\n'
               '  profiles.py --current\n'
               '  profiles.py --manifest\n'
               '  profiles.py --selftest\n')
    g = p.add_mutually_exclusive_group()
    g.add_argument('--list', action='store_true', help='list profiles + which one the live data holds')
    g.add_argument('--current', action='store_true',
                   help='print the profile the live data holds (marker data/profiles/current.json)')
    g.add_argument('--manifest', action='store_true',
                   help='print the profile-scoped file manifest (and what is shared) with reasons')
    p.add_argument('--create', metavar='NAME', default=None,
                   help='create a profile from the CURRENT live data state (refused if it exists)')
    p.add_argument('--switch', metavar='NAME', default=None,
                   help='switch the live data to this profile (DRY RUN unless --apply)')
    p.add_argument('--apply', action='store_true',
                   help='with --switch: perform the switch (pre-switch backup zip first)')
    p.add_argument('--selftest', action='store_true',
                   help='offline self-test in a temp dir (no repo data touched)')
    p.add_argument('--json', action='store_true',
                   help='with --list / --current: print machine-readable JSON (used by the dashboard)')
    return p


def main(argv=None):
    global _JSON
    parser = build_parser()
    args = parser.parse_args(argv)
    _JSON = bool(getattr(args, 'json', False))
    if args.json and not (args.list or args.current):
        print('--json is only meaningful with --list or --current')
        return 2
    if args.selftest:
        if any([args.list, args.current, args.manifest, args.create, args.switch, args.apply]):
            print('--selftest runs on its own')
            return 2
        return selftest()
    actions = [n for n, v in (('--list', args.list), ('--current', args.current),
                              ('--manifest', args.manifest), ('--create', args.create),
                              ('--switch', args.switch)) if v]
    if args.apply and not args.switch:
        print('--apply only makes sense with --switch NAME')
        return 2
    if not actions:
        parser.print_help()
        return 2
    if len(actions) > 1:
        print('pick one action, got %s' % ' + '.join(actions))
        return 2
    try:
        if args.list:
            return cmd_list()
        if args.current:
            return cmd_current()
        if args.manifest:
            return cmd_manifest()
        if args.create:
            return cmd_create(args.create)
        return cmd_switch(args.switch, args.apply)
    except Refused as exc:
        print('refused: %s' % exc)
        return 2
    except ProfileError as exc:
        print(str(exc))
        return 1
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print('error: %s: %s' % (type(exc).__name__, exc))
        return 1


if __name__ == '__main__':
    sys.exit(main())
