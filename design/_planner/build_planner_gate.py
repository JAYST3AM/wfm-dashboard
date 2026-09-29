"""design/_planner/build_planner_gate.py — run the Phase 2 build-planner browser gate.

    python design/_planner/build_planner_gate.py

1. boots this repo's real server.py as a module against a throwaway WFM_DATA (no autosync, no
   writes into the repo's data/), the same way tests/test_session_api.py does it,
2. runs design/_planner/build_planner_gate.js against it with puppeteer-core,
3. writes design/_planner/build-planner-report.md (timestamped, mechanical verdict) and keeps
   design/_planner/build-planner-raw.json (every number the gate measured).

The engine under the planner is the real builds/ package and the real data/build_data.json -
nothing here is a fixture, so a number this gate reads is a number a user would see.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import importlib.util
from datetime import datetime
from http.server import ThreadingHTTPServer
from urllib.request import urlopen

REPO = r'F:/VSC Projects/wfm-dashboard'
OUT = os.path.join(REPO, 'design', '_planner')
RAW = os.path.join(OUT, 'build-planner-raw.json')
FIXTURES = os.path.join(OUT, 'fixtures')
SAVE_ENV = 'WFM_PLAYER_SAVE'
CACHE_ENV = 'WFM_PLAYER_CACHE'
REPORT = os.path.join(OUT, 'build-planner-report.md')
SHOTS = os.path.join(tempfile.gettempdir(), 'planner-gate-shots')
NODE_GATE = os.path.join(OUT, 'build_planner_gate.js')
GIT = 'git'


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def boot(port, data):
    """The server the page will talk to: module import, DATA pointed at a scratch dir."""
    os.environ['WFM_DATA'] = data
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    spec = importlib.util.spec_from_file_location('gate_server', os.path.join(REPO, 'server.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DATA = data
    srv = ThreadingHTTPServer(('127.0.0.1', port), mod.H)
    return srv


def wait_ready(base, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urlopen(base + '/api/planner/meta', timeout=4) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def read_current(base):
    with urlopen(base + '/api/planner/current', timeout=15) as r:
        return json.loads(r.read().decode('utf-8'))


def source_state_checks(base, data):
    """Phase 3: every failure mode of the local source, measured on the booted server.

    The card's happy path is measured in the browser; these are the states a player hits when the
    save is missing or damaged, and each one must be a named state rather than an empty card.
    """
    cases = [
        ('a readable save imports as ok', 'save-full.json', 'ok'),
        ('a truncated save reads as malformed, never as empty', 'save-malformed.json', 'malformed'),
        ('a save without a loadout says so', 'save-empty.json', 'no_build_data'),
        ('a missing file names the path it looked for', 'does-not-exist.dat', 'missing'),
    ]
    checks = []
    saved = os.environ.get(SAVE_ENV)
    for title, name, want in cases:
        os.environ[SAVE_ENV] = os.path.join(FIXTURES, name)
        os.environ[CACHE_ENV] = os.path.join(data, 'current-%s.json' % want)
        try:
            payload = read_current(base)
            got = payload.get('state')
            ok = got == want
            if want == 'missing':
                ok = ok and 'expected' in (payload.get('detail') or {})
            checks.append({'section': 'current', 'title': title, 'ok': bool(ok),
                           'expected': want, 'observed': str(got), 'note': '', 'diagnostic': False})
        except Exception as e:                                     # the server should still answer
            checks.append({'section': 'current', 'title': title, 'ok': False, 'expected': want,
                           'observed': 'error: %s' % e, 'note': '', 'diagnostic': False})
    if saved is not None:
        os.environ[SAVE_ENV] = saved
    return checks


def git_facts():
    def run(args):
        try:
            p = subprocess.run([GIT] + args, cwd=REPO, capture_output=True, text=True, timeout=30)
            return (p.stdout or p.stderr).strip()
        except Exception as exc:
            return 'git failed: %s' % exc
    return {
        'sha': run(['rev-parse', '--short', 'HEAD']),
        'subject': run(['log', '-1', '--pretty=%s']),
        'dirty': run(['status', '--porcelain']) or '(clean)',
    }


def md_table(head, rows):
    out = ['| ' + ' | '.join(head) + ' |', '|' + '|'.join(['---'] * len(head)) + '|']
    for row in rows:
        out.append('| ' + ' | '.join(str(c).replace('|', '\\|') for c in row) + ' |')
    return '\n'.join(out)


def esc(s, limit=220):
    s = str(s if s is not None else '')
    s = s.replace('\n', ' ').replace('|', '\\|')
    return s if len(s) <= limit else s[:limit] + '…'


def build_report(raw, facts, boot_lines, kept):
    v = raw.get('verdict') or {}
    ok = 'PASS' if v.get('pass') else 'FAIL'
    lines = []
    lines.append('# Build planner — browser workflow gate (Phase 2)')
    lines.append('')
    lines.append('*ran %s · verdict **%s** · %s checks, %s failed*' % (
        raw.get('finished') or datetime.now().isoformat(timespec='seconds'), ok,
        v.get('checks_total'), v.get('checks_failed')))
    lines.append('')
    lines.append(md_table(['field', 'value'], [
        ['repo', REPO],
        ['commit', '%s  "%s"' % (facts['sha'], facts['subject'])],
        ['working tree', 'dirty (%d changed paths)' % len(facts['dirty'].splitlines())
            if facts['dirty'] != '(clean)' else 'clean'],
        ['server', 'server.py booted as a module, WFM_DATA=' + esc(kept)],
        ['page', raw.get('base') + '/planner.html'],
        ['puppeteer', esc(raw.get('puppeteer'))],
        ['chrome', esc(raw.get('chrome'))],
        ['raw numbers', os.path.basename(RAW)],
        ['screenshots', esc(os.path.dirname(SHOTS), 200)],
    ]))
    lines.append('')
    if raw.get('error'):
        lines.append('## Aborted')
        lines.append('')
        lines.append('```\n%s\n```' % raw['error'])
        lines.append('')
    lines.append('## Checks')
    lines.append('')
    rows = []
    for c in raw.get('checks') or []:
        rows.append(['✅' if c['ok'] else '❌', c['section'], esc(c['title']),
                     esc(c['expected'], 90), esc(c['observed'], 150)])
    lines.append(md_table(['', 'area', 'what was checked', 'expected', 'observed'], rows))
    lines.append('')
    failed = [c for c in (raw.get('checks') or []) if not c['ok']]
    if failed:
        lines.append('## Failures')
        lines.append('')
        for c in failed:
            lines.append('- **%s / %s** — expected %s, observed %s' % (
                c['section'], c['title'], esc(c['expected'], 120), esc(c['observed'], 200)))
        lines.append('')
    lines.append('## The engine facts this run used')
    lines.append('')
    lines.append('The gate compares what the page shows against `/api/planner/compute` for the same')
    lines.append('build JSON, and pins two Phase 1 numbers so engine drift fails loudly:')
    lines.append('')
    rows = []
    for k, v2 in sorted((raw.get('steps') or {}).items()):
        if isinstance(v2, dict):
            bits = []
            for kk in ('damage_total', 'modded', 'api_crit', 'api_damage', 'cap_used',
                       'api_used_after', 'forma', 'moved', 'panel_mark'):
                if kk in v2:
                    bits.append('%s=%s' % (kk, esc(v2[kk], 40)))
            if bits:
                rows.append([k, '; '.join(bits)])
    lines.append(md_table(['step', 'values measured'], rows) if rows else '_(no scalar steps recorded)_')
    lines.append('')
    lines.append('## Hygiene over the whole drive')
    lines.append('')
    lines.append(md_table(['signal', 'count'], [
        ['console errors', len(raw.get('console') or [])],
        ['page errors', len(raw.get('pageerrors') or [])],
        ['failed requests (outside the dev-server burst class)',
         len(raw.get('failed') or [])],
        ['blocked-CDN requests', len(raw.get('blocked_cdn') or [])],
        ['duplicate ids in the rendered page', len(((raw.get('steps') or {}).get('hygiene') or {})
                                                   .get('dupes') or [])],
    ]))
    lines.append('')
    lines.append('## How to re-run')
    lines.append('')
    lines.append('```bash')
    lines.append('cd "%s"' % REPO)
    lines.append('python design/_planner/build_planner_gate.py')
    lines.append('```')
    lines.append('')
    lines.append('The gate edits nothing on the app: it clicks, types and drops on the planner page,')
    lines.append('reads localStorage, and reloads. The only writes are its own report, the raw JSON')
    lines.append('and the screenshots.')
    lines.append('')
    return '\n'.join(lines)


def main():
    facts = git_facts()
    data = tempfile.mkdtemp(prefix='planner_gate_data_')
    port = free_port()
    base = 'http://127.0.0.1:%d' % port
    srv = boot(port, data)
    import threading
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    boot_lines = ['booted server.py on %s with WFM_DATA=%s' % (base, data)]
    print(boot_lines[0])
    if not wait_ready(base):
        print('server never answered /api/planner/meta - aborting')
        sys.exit(2)
    # Phase 3: the current-loadout card reads a synthetic, reproducible source. The gate never
    # points at the real AlecaFrame save, so no player data reaches the report.
    os.environ[SAVE_ENV] = os.path.join(FIXTURES, 'save-full.json')
    os.environ[CACHE_ENV] = os.path.join(data, 'current-ok.json')
    env = dict(os.environ)
    env['WFM_BASE'] = base
    env['WFM_RAW'] = RAW
    env['WFM_SHOTS'] = SHOTS
    print('running %s' % NODE_GATE)
    proc = subprocess.run(['node', NODE_GATE], cwd=REPO, env=env, capture_output=True, text=True,
                          timeout=900)
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.stderr:
        print(proc.stderr.rstrip(), file=sys.stderr)
    raw = {}
    if os.path.exists(RAW):
        with open(RAW, encoding='utf-8') as fh:
            raw = json.load(fh)
    else:
        raw = {'error': 'the node gate wrote no raw JSON (exit %s)' % proc.returncode,
               'verdict': {'pass': False, 'checks_total': 0, 'checks_failed': 0}}
    extra = source_state_checks(base, data)
    if isinstance(raw.get('checks'), list):
        raw['checks'].extend(extra)
        failed = [c for c in raw['checks'] if not c.get('ok')]
        verdict = raw.setdefault('verdict', {})
        verdict['checks_total'] = len(raw['checks'])
        verdict['checks_failed'] = len(failed)
        verdict['failed'] = [c.get('section', '') + ' / ' + c.get('title', '') for c in failed]
        verdict['pass'] = not failed
    text = build_report(raw, facts, boot_lines, data)
    with open(REPORT, 'w', encoding='utf-8') as fh:
        fh.write(text)
    print('')
    print('report  -> %s' % REPORT)
    print('raw     -> %s' % RAW)
    print('shots   -> %s' % SHOTS)
    v = raw.get('verdict') or {}
    print('verdict -> %s (%s checks, %s failed)' % (
        'PASS' if v.get('pass') else 'FAIL', v.get('checks_total'), v.get('checks_failed')))
    srv.shutdown()
    sys.exit(0 if v.get('pass') else 1)


if __name__ == '__main__':
    main()
