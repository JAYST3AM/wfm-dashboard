#!/usr/bin/env python3
"""Icon cache - the collection page's icons, served from this PC's own disk.

The collection log points every item at a public CDN icon
(https://cdn.warframestat.us/img/<imageName>.png, which 301-redirects to
raw.githubusercontent.com/wfcd/warframe-items - both verified to serve the PNG). This script
copies each of those images into static/colimg/ once, so the browser loads them from the local
server with no redirect, no CDN dependency and no per-view network traffic.

Input
  data/collection_log.json    every item of all 13 categories (only `icon` is read)
Output
  static/colimg/<basename>    the images: file name = the URL's path basename (path-safe)
  static/colimg/index.json    {schema, updated, count, files: {url: {file, bytes}}, failed}

Resumable: a run only fetches what is missing (a file counts as present when it exists AND is
bigger than 0 bytes); --limit N bounds one run, re-run to continue where it stopped.
--refresh re-fetches everything, --offline never touches the network, --dry-run lists the
work and writes nothing at all.

One bad image never aborts the run: a failure is counted, printed in the summary and kept in
index.json's `failed` array. A non-image body or an HTTP error is never written to a file.

Usage
  python scripts/icon_cache.py --once        # fetch what is missing, write the index (default)
  python scripts/icon_cache.py --limit 100   # at most 100 downloads this run
  python scripts/icon_cache.py --refresh     # re-fetch every wanted icon
  python scripts/icon_cache.py --dry-run     # list what would download, write nothing
  python scripts/icon_cache.py --offline     # use what is already cached, no network
  python scripts/icon_cache.py --out-dir D   # write somewhere else (default static/colimg)
  python scripts/icon_cache.py --json        # dump index.json to stdout
  python scripts/icon_cache.py --selftest    # offline checks against tmp fixtures
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.environ.get('WFM_DATA_DIR') or os.path.join(ROOT, 'data')
COLIMG = os.path.join(ROOT, 'static', 'colimg')

SCHEMA = 1
# same browser-like UA collection_log.py uses to verify the CDN serves real images
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/124.0 Safari/537.36')
TIMEOUT = 60
SLEEP = 0.05                                   # polite pause between downloads
MAX_BYTES = 8 * 1024 * 1024                    # an icon is never this big
SAFE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,180}\Z')
IMAGE_MAGIC = ((b'\x89PNG\r\n\x1a\n', 'png'), (b'GIF87a', 'gif'), (b'GIF89a', 'gif'),
               (b'\xff\xd8\xff', 'jpeg'))


# ------------------------------------------------------------------ helpers
def log_path():
    return os.path.join(DATA, 'collection_log.json')


def index_path(out_dir):
    return os.path.join(out_dir, 'index.json')


def jload(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def atomic_write(path, doc):
    """tmp + os.replace, so a reader never sees a half-written index."""
    tmp = path + '.tmp'
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
        fh.write('\n')
    os.replace(tmp, path)


def atomic_write_bytes(path, blob):
    tmp = path + '.tmp'
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(tmp, 'wb') as fh:
        fh.write(blob)
    os.replace(tmp, path)


def iso_z(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def ascii_s(value):
    return str(value).encode('ascii', 'replace').decode('ascii')


def file_name_for(url):
    """URL path basename as a path-safe file name, or None when it cannot be used.

    Only the last path segment, and only that segment when it is [A-Za-z0-9._-] with an
    alphanumeric head: a hostile or percent-encoded URL can then never climb out of the output
    directory (no separators, no '..', no dot-file, no control characters).
    """
    if not isinstance(url, str) or not url:
        return None
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ('http', 'https') or not parts.netloc:
        return None
    name = parts.path.rsplit('/', 1)[-1]
    return name if SAFE_NAME.fullmatch(name) else None


def collect_wanted(doc):
    """(wanted, items, no_icon) - wanted: {icon URL: file name or None} in log order."""
    wanted, items, no_icon = {}, 0, 0
    for cat in (doc or {}).get('categories') or []:
        if not isinstance(cat, dict):
            continue
        for row in cat.get('items') or []:
            if not isinstance(row, dict):
                continue
            items += 1
            url = row.get('icon')
            if not url:
                no_icon += 1
                continue
            wanted.setdefault(str(url), file_name_for(url))
    return wanted, items, no_icon


def scan_existing(out_dir, wanted):
    """{url: (file name, size)} for wanted URLs already on disk with size > 0."""
    present = {}
    for url, name in wanted.items():
        if not name:
            continue
        try:
            size = os.path.getsize(os.path.join(out_dir, name))
        except OSError:
            continue
        if size > 0:
            present[url] = (name, size)
    return present


def fetch_bytes(url, timeout=TIMEOUT):
    """(status, body) for one icon URL; urllib follows the CDN's 301 to GitHub by default."""
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'image/*,*/*'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = int(getattr(resp, 'status', 200) or 200)
        body = resp.read(MAX_BYTES + 1)
    return status, body


def image_kind(blob):
    """'png' / 'gif' / 'jpeg' / 'webp' / 'svg' when the bytes look like an image, else None."""
    if not blob:
        return None
    if blob[:4] == b'RIFF' and blob[8:12] == b'WEBP':
        return 'webp'
    for magic, kind in IMAGE_MAGIC:
        if blob.startswith(magic):
            return kind
    head = blob[:512].lstrip()
    if head[:4] == b'<svg' or head[:5] == b'<?xml':
        return 'svg'
    return None


def short_reason(exc):
    text = '%s: %s' % (type(exc).__name__, exc)
    return text[:120].replace('\n', ' ').replace('\r', ' ')


def summary_line(counts):
    return 'icon_cache: want %d | cached %d | downloaded %d | failed %d' % (
        counts.get('want', 0), counts.get('cached', 0), counts.get('downloaded', 0),
        counts.get('failed', 0))


# ------------------------------------------------------------------ the run
def run_once(out_dir=None, limit=0, refresh=False, dry_run=False, offline=False,
             fetch_fn=None, sleep_fn=None, log_file=None, now=None):
    """One cache pass. Returns {'counts': {...}, 'doc': index, 'would': [...], 'wrote': bool}."""
    out_dir = out_dir or COLIMG
    log_file = log_file or log_path()
    fetch_fn = fetch_fn or fetch_bytes
    sleep_fn = sleep_fn if sleep_fn is not None else time.sleep

    wanted, items, no_icon = collect_wanted(jload(log_file))
    present = scan_existing(out_dir, wanted)
    todo = [] if offline else [u for u in wanted if refresh or u not in present]
    planned = len(todo)
    if limit and limit > 0:
        todo = todo[:limit]
    left = max(0, planned - len(todo))

    would = [wanted.get(u) or u for u in todo] if dry_run else []
    downloaded, failed = {}, []
    if not dry_run:
        for url in todo:
            name = wanted.get(url)
            if not name:
                failed.append({'url': url, 'file': None, 'reason': 'unsafe file name'})
                continue
            try:
                status, blob = fetch_fn(url)
                if status != 200:
                    raise ValueError('HTTP %s' % status)
                if len(blob) > MAX_BYTES:
                    raise ValueError('too large (%d bytes)' % len(blob))
                kind = image_kind(blob)
                if not kind:
                    raise ValueError('not an image (%d bytes)' % len(blob))
                atomic_write_bytes(os.path.join(out_dir, name), blob)
            except Exception as exc:                    # noqa: BLE001 - one bad icon is enough
                failed.append({'url': url, 'file': name, 'reason': short_reason(exc)})
                continue
            downloaded[url] = (name, len(blob))
            if sleep_fn:
                sleep_fn(SLEEP)

    files = {}
    for url, (name, size) in present.items():
        if url not in downloaded:
            files[url] = {'file': name, 'bytes': size}
    for url, (name, size) in downloaded.items():
        files[url] = {'file': name, 'bytes': size}

    ts = int(now if now is not None else time.time())
    doc = {'schema': SCHEMA, 'updated': ts, 'count': len(files),
           'files': {url: files[url] for url in sorted(files)}, 'failed': failed}
    wrote = False
    if not dry_run:
        atomic_write(index_path(out_dir), doc)
        wrote = True

    counts = {'want': len(wanted), 'cached': len(present), 'downloaded': len(downloaded),
              'failed': len(failed), 'planned': planned, 'left': left, 'items': items,
              'no_icon': no_icon, 'missing': len(wanted) - len(files),
              'bytes': sum(f['bytes'] for f in files.values())}
    return {'counts': counts, 'doc': doc, 'would': would, 'wrote': wrote, 'out_dir': out_dir}


def print_detail(result, counts, limit=0, offline=False, dry_run=False):
    doc = result['doc']
    print('  out: %s' % ascii_s(os.path.abspath(result['out_dir']).replace('\\', '/')))
    print('  disk: %.1f MB in %d files (updated %s)'
          % (counts['bytes'] / 1048576.0, doc['count'], iso_z(doc['updated'])))
    if limit:
        print('  limit %d - %d left for the next run' % (limit, counts['left']))
    if offline:
        print('  offline - no network; %d of %d not on disk' % (counts['missing'], counts['want']))
    elif dry_run:
        print('  dry run - would download %d, wrote nothing, no network' % counts['planned'])
    elif counts['missing']:
        print('  %d of %d wanted icons not on disk yet' % (counts['missing'], counts['want']))
    if counts['no_icon']:
        print('  items without an icon URL: %d' % counts['no_icon'])
    for row in doc['failed'][:5]:
        print('  failed: %s (%s)' % (ascii_s(row['file'] or row['url']), ascii_s(row['reason'])))
    if len(doc['failed']) > 5:
        print('  ... and %d more failures' % (len(doc['failed']) - 5))


# ------------------------------------------------------------------ selftest
FIXTURE_LOG = {'version': 1, 'categories': [
    {'key': 'warframes', 'name': 'Warframes', 'items': [
        {'name': 'Ash', 'icon': 'https://cdn.example/img/Ash.png'},
        {'name': 'Ash Prime', 'icon': 'https://cdn.example/img/Ash.png'},      # same file
        {'name': 'Atlas', 'icon': 'https://cdn.example/img/Atlas.png'},
    ]},
    {'key': 'primary', 'name': 'Primary', 'items': [
        {'name': 'Braton', 'icon': 'https://cdn.example/img/Braton.png'},
        {'name': 'No Icon Item', 'icon': None},
    ]},
]}
FIXTURE_PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
FIXTURE_HTML = b'<html><body>not an image</body></html>'
FIXTURE_ICONS = {'https://cdn.example/img/Ash.png': FIXTURE_PNG,
                 'https://cdn.example/img/Atlas.png': FIXTURE_PNG,
                 'https://cdn.example/img/Braton.png': FIXTURE_PNG}


def fake_fetch(mapping, calls=None, exc=None):
    """fetch_fn for offline runs: 200 + fixture bytes, or the injected error."""
    def fetch(url):
        if calls is not None:
            calls.append(url)
        if exc is not None:
            raise exc
        body = mapping.get(url)
        if body is None:
            raise OSError('no fixture for %s' % url)
        return 200, body
    return fetch


def selftest():
    """Offline checks - tmp fixtures only, fake fetch, no network, no repo writes."""
    checks = []

    def check(label, cond):
        checks.append((label, bool(cond)))
        print('  %-58s %s' % (label, 'ok' if cond else 'FAIL'))

    tmp = tempfile.mkdtemp(prefix='icon_cache_selftest_')
    log = os.path.join(tmp, 'collection_log.json')
    out = os.path.join(tmp, 'colimg')
    with open(log, 'w', encoding='utf-8') as fh:
        json.dump(FIXTURE_LOG, fh)

    check('file name rule: basename kept',
          file_name_for('https://cdn.warframestat.us/img/Ash.png') == 'Ash.png')
    for bad in ('', None, 'Ash.png', 'https://cdn.example/img/', 'https://cdn.example/img/a b.png',
                'https://cdn.example/img/%2e%2e.png', 'https://cdn.example/img/.hidden.png',
                'https:///img/Ash.png', 'file:///etc/passwd'):
        check('file name rule: refused %r' % (bad,), file_name_for(bad) is None)

    wanted, items, no_icon = collect_wanted(FIXTURE_LOG)
    check('collect: 3 unique URLs from 5 items', len(wanted) == 3 and items == 5)
    check('collect: the item without an icon is counted', no_icon == 1)

    first = run_once(out_dir=out, fetch_fn=fake_fetch(FIXTURE_ICONS), sleep_fn=lambda s: None,
                     log_file=log, now=1700000000)
    c = first['counts']
    check('run 1: want 3, cached 0, downloaded 3', (c['want'], c['cached'], c['downloaded'],
                                                    c['failed']) == (3, 0, 3, 0))
    check('run 1: summary line', summary_line(c) == 'icon_cache: want 3 | cached 0 | '
          'downloaded 3 | failed 0')
    check('run 1: files on disk with size > 0',
          all(os.path.getsize(os.path.join(out, n)) > 0
              for n in ('Ash.png', 'Atlas.png', 'Braton.png')))
    doc = first['doc']
    check('index shape', sorted(doc) == ['count', 'failed', 'files', 'schema', 'updated'])
    check('index: schema/updated/count', (doc['schema'], doc['updated'], doc['count'])
          == (1, 1700000000, 3))
    check('index: url -> {file, bytes}',
          doc['files']['https://cdn.example/img/Ash.png'] == {'file': 'Ash.png',
                                                              'bytes': len(FIXTURE_PNG)})
    check('index: no .tmp left', not [n for n in os.listdir(out) if n.endswith('.tmp')])

    calls = []
    second = run_once(out_dir=out, fetch_fn=fake_fetch(FIXTURE_ICONS, calls=calls,
                                                       exc=AssertionError('network used')),
                      sleep_fn=lambda s: None, log_file=log)
    check('resume: nothing downloaded, all cached', (second['counts']['downloaded'],
                                                      second['counts']['cached']) == (0, 3))
    check('resume: no fetch attempted', calls == [])

    os.remove(os.path.join(out, 'Ash.png'))
    third = run_once(out_dir=out, limit=1, fetch_fn=fake_fetch(FIXTURE_ICONS),
                     sleep_fn=lambda s: None, log_file=log)
    check('limit: exactly 1 downloaded, 2 remain cached', (third['counts']['downloaded'],
                                                           third['counts']['cached']) == (1, 2))

    refresh_calls = []
    fourth = run_once(out_dir=out, refresh=True,
                      fetch_fn=fake_fetch(FIXTURE_ICONS, calls=refresh_calls),
                      sleep_fn=lambda s: None, log_file=log)
    check('refresh: re-downloads every wanted icon', (fourth['counts']['downloaded'],
                                                      len(refresh_calls)) == (3, 3))

    failed_run = run_once(out_dir=out, refresh=True,
                          fetch_fn=fake_fetch(FIXTURE_ICONS,
                                              exc=OSError('HTTP 503 Service Unavailable')),
                          sleep_fn=lambda s: None, log_file=log)
    check('failure: recorded, count kept, run not aborted',
          failed_run['counts']['failed'] == 3 and len(failed_run['doc']['failed']) == 3)
    check('failure: reason kept in index.json',
          failed_run['doc']['failed'][0]['reason'].startswith('OSError'))

    os.remove(os.path.join(out, 'Atlas.png'))
    bad_body = dict(FIXTURE_ICONS, **{'https://cdn.example/img/Atlas.png': FIXTURE_HTML})
    html_run = run_once(out_dir=out, fetch_fn=fake_fetch(bad_body), sleep_fn=lambda s: None,
                        log_file=log)
    check('non-image body: recorded as a failure, no file written',
          not os.path.exists(os.path.join(out, 'Atlas.png'))
          and any('not an image' in f['reason'] for f in html_run['doc']['failed']))
    check('non-image body: only that file is affected',
          (html_run['counts']['downloaded'], html_run['counts']['cached'])
          == (0, 2) and html_run['doc']['count'] == 2)

    dry_out = os.path.join(tmp, 'dry')
    dry_calls = []
    dry = run_once(out_dir=dry_out, dry_run=True,
                   fetch_fn=fake_fetch(FIXTURE_ICONS, calls=dry_calls), sleep_fn=lambda s: None,
                   log_file=log)
    check('dry run: lists all wanted, writes nothing, no fetch',
          dry['counts']['planned'] == 3 and len(dry['would']) == 3
          and not os.path.exists(dry_out) and dry_calls == [])

    empty_out = os.path.join(tmp, 'empty')
    off = run_once(out_dir=empty_out, offline=True, log_file=log)
    check('offline: no network, missing reported',
          off['counts']['downloaded'] == 0 and off['counts']['missing'] == 3)

    failed = [label for label, ok in checks if not ok]
    print('selftest: %d checks, %d failed' % (len(checks), len(failed)))
    for label in failed:
        print('  FAILED: %s' % label)
    return 1 if failed else 0


# ------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description='Cache the collection page icons on disk')
    ap.add_argument('--once', action='store_true', default=True,
                    help='fetch what is missing (default)')
    ap.add_argument('--limit', type=int, default=0, metavar='N',
                    help='download at most N files in this run')
    ap.add_argument('--refresh', action='store_true', help='re-fetch every wanted icon')
    ap.add_argument('--out-dir', default=None, help='output directory (default static/colimg)')
    ap.add_argument('--json', action='store_true', help='dump index.json to stdout')
    ap.add_argument('--dry-run', action='store_true', help='list what would download, write nothing')
    ap.add_argument('--offline', action='store_true', help='use what is cached, never fetch')
    ap.add_argument('--selftest', action='store_true', help='offline checks against tmp fixtures')
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    if not os.path.exists(log_path()):
        print('icon_cache: want 0 | cached 0 | downloaded 0 | failed 0')
        print('no collection log at %s' % ascii_s(os.path.abspath(log_path()).replace('\\', '/')))
        print('run scripts/collection_log.py first')
        return 1

    result = run_once(out_dir=args.out_dir or COLIMG, limit=args.limit, refresh=args.refresh,
                      dry_run=args.dry_run, offline=args.offline)
    counts = result['counts']
    line = summary_line(counts)
    if args.json:
        print(line, file=sys.stderr)
        print(json.dumps(result['doc'], ensure_ascii=False, indent=1))
    else:
        print(line)
        print_detail(result, counts, limit=args.limit, offline=args.offline,
                     dry_run=args.dry_run)
    return 0


if __name__ == '__main__':
    sys.exit(main())
