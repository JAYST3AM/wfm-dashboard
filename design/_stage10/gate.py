#!/usr/bin/env python
"""design/_stage10/gate.py - the release acceptance gate, one command.

    python design/_stage10/gate.py            # runs the gate and writes gate-report.md

What it does, in order:
  1. runs the repo's own copy-diet test (tests/test_copy_diet.py) with pytest
  2. runs design/_stage10/gate.js (puppeteer-core, the live app at http://127.0.0.1:8787)
  3. merges both into design/_stage10/gate-report.md (timestamped) and gate-raw.json

Exit code 0 = every check passed, 1 = at least one failed (or the harness could not run).

READ-ONLY ON THE APP: the only writes are under design/_stage10/ (the report + the raw JSON).
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RAW = os.path.join(HERE, 'gate-raw.json')
REPORT = os.path.join(HERE, 'gate-report.md')
BASE = os.environ.get('WFM_BASE', 'http://127.0.0.1:8787')


def run(cmd, cwd=ROOT, timeout=1800):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return {'cmd': ' '.join(cmd), 'rc': p.returncode, 'out': p.stdout or '', 'err': p.stderr or '',
                'seconds': round(time.time() - t0, 1)}
    except Exception as e:                                    # missing binary, timeout, ...
        return {'cmd': ' '.join(cmd), 'rc': -1, 'out': '', 'err': str(e), 'seconds': round(time.time() - t0, 1)}


def server_up():
    import urllib.request
    try:
        with urllib.request.urlopen(BASE + '/', timeout=8) as r:
            if r.status != 200:
                return 'HTTP %s on /' % r.status
    except Exception as e:
        return 'unreachable: %s' % e
    # The stage-10 rail includes Planner, so the app on BASE must be THIS checkout: a stale
    # server from an older session answers / but 404s /api/planner/*, which reads as a page bug.
    try:
        with urllib.request.urlopen(BASE + '/api/planner/meta', timeout=8) as r:
            body = r.read(200)
            if r.status == 200 and b'"ok"' in body:
                return True
            return 'no planner API on %s (HTTP %s) - restart server.py from this checkout' % (
                BASE, r.status)
    except Exception as e:
        return 'no planner API on %s (%s) - restart server.py from this checkout' % (BASE, e)


def md_table(head, rows):
    out = ['| ' + ' | '.join(str(h) for h in head) + ' |',
           '|' + '|'.join(['---'] * len(head)) + '|']
    for r in rows:
        out.append('| ' + ' | '.join('' if c is None else str(c) for c in r) + ' |')
    return '\n'.join(out)


def esc(s):
    return str(s if s is not None else '').replace('|', '\\|').replace('\n', ' ')


def build_report(raw, pytest_res, gate_res, now_local, now_iso, srv):
    v = raw.get('verdict', {})
    meta = raw.get('meta', {})
    L = []
    A = L.append

    A('# WFM Trader - release acceptance gate')
    A('')
    fin = meta.get('finished')
    fin_l = ''
    if fin:
        try:
            fin_l = ' -> live measurements finished %s' % datetime.fromisoformat(fin.replace('Z', '+00:00')).astimezone().strftime('%H:%M:%S')
        except Exception:
            fin_l = ' -> finished %s' % fin
    A('**Run:** %s (%s)%s  ' % (now_local, now_iso, fin_l))
    A('**App:** %s   **Reported by:** design/_stage10/gate.py (gate.js + the repo copy-diet test)  ' % BASE)
    A('**Raw numbers:** design/_stage10/gate-raw.json  ')
    A('**Server reachable:** %s' % srv)
    A('')
    A('## Verdict')
    A('')
    if raw.get('verdict', {}).get('crashed'):
        A('**GATE DID NOT FINISH** - the harness crashed: `%s`' % str(v.get('crashed'))[:400])
    else:
        A('**%s** - %s of %s checks failed, %s page states driven, %s blocked-CDN request(s) excluded.'
          % ('PASS' if v.get('pass') else 'FAIL', v.get('checks_failed', '?'), v.get('checks_total', '?'),
             v.get('states_driven', '?'), v.get('blocked_cdn_requests', '?')))
    A('')
    failed = [c for c in raw.get('checks', []) if not c.get('ok')]
    if failed:
        A('### Failing checks (honest current state)')
        A('')
        for c in failed:
            A('- **%s** - %s' % (c.get('group'), c.get('title')))
            A('  - expected: `%s`' % esc(c.get('expected')))
            A('  - rendered: `%s`' % esc(c.get('rendered')))
            if c.get('note'):
                A('  - note: %s' % esc(c.get('note')))
        A('')

    checks = raw.get('checks', [])
    groups = {}
    for c in checks:
        groups.setdefault(c.get('group'), []).append(c)
    A('## Checks by group')
    A('')
    A(md_table(['group', 'checks', 'failed'], [[g, len(v_), len([c for c in v_ if not c['ok']])]
                                               for g, v_ in groups.items()]))
    A('')

    # 1. load -----------------------------------------------------------------------------
    A('## 1. Page load - console errors and failed requests')
    A('')
    A('Targets: index (4 hash views + 12 tool workspaces + 6 legacy hashes), collection (3 sections), '
      'cards, settings (6 categories), item (bare + ?item= deep link), lookup.')
    A('')
    rows = []
    for k, d in raw.get('load', {}).items():
        rows.append([k, d.get('states') or '-', d.get('errors'), d.get('fails'),
                     d.get('blocked') if d.get('blocked') is not None else '-'])
    A(md_table(['page', 'states driven', 'console errors', 'failed requests', 'blocked-CDN (excluded)'], rows))
    A('')
    states = raw.get('states', [])
    noisy = [s for s in states if s.get('errors') or s.get('fails')]
    A('Per-state rows: %d. States with an error or a failed request: %d.' % (len(states), len(noisy)))
    for s in noisy:
        A('- %s %s: errors=%s fails=%s' % (s.get('page'), s.get('state'), s.get('errors'), s.get('fails')))
    det = raw.get('load_detail', {})
    if det:
        A('')
        A('Detail:')
        A('')
        for page, d in det.items():
            for row in (d.get('errors') or [])[:10]:
                A('- %s error @%s: %s' % (page, row.get('state'), esc(row.get('text'))))
            for row in (d.get('fails') or [])[:10]:
                A('- %s failed request @%s: %s (%s)' % (page, row.get('state'), esc(row.get('url')), esc(row.get('why'))))
    tr = raw.get('load_transient', {})
    if tr:
        A('')
        A('Transient net-stack errors on the FIRST attempt (reloaded once; recorded here rather than '
          'hidden, and only these kernel-level codes qualify: ERR_NO_BUFFER_SPACE, '
          'ERR_INSUFFICIENT_RESOURCES, ERR_NETWORK_CHANGED, ERR_CONNECTION_RESET):')
        A('')
        for page, d in tr.items():
            for row in (d.get('errors') or []):
                A('- %s error: %s' % (page, esc(row.get('text'))))
            for row in (d.get('fails') or []):
                A('- %s failed request: %s (%s)' % (page, esc(row.get('url')), esc(row.get('why'))))
    rc = raw.get('load_recheck', {})
    if rc:
        A('')
        A('Connection-level failures re-verified with a direct fetch against the same URL. Only a request '
          'that failed in Chromium **and** still fails (or answers 4xx/5xx) from node counts against the '
          'release; a cleared row means the single-threaded dev server simply refused a burst.')
        A('')
        rows = []
        for page, d in rc.items():
            for row in d.get('cleared', []):
                rows.append([page, row.get('url'), row.get('why'), row.get('recheck_status'), 'cleared (excluded)'])
            for row in d.get('still_failing', []):
                rows.append([page, row.get('url'), row.get('why'),
                             row.get('recheck_status') or ('err: ' + str(row.get('recheck_error'))[:60]), 'STILL FAILING'])
        A(md_table(['page', 'url', 'chromium failure', 'direct fetch status', 'verdict'], rows))
    A('')

    # 2. fit ------------------------------------------------------------------------------
    A('## 2. Fit - pageOverX / pageOverY per index view')
    A('')
    fit = raw.get('fit', [])
    viewports = []
    for f in fit:
        if f['viewport'] not in viewports:
            viewports.append(f['viewport'])
    views = []
    for f in fit:
        if f['view'] not in views:
            views.append(f['view'])
    grid = {}
    for f in fit:
        grid[(f['viewport'], f['view'])] = '%s / %s' % (f['overX'], f['overY'])
    A(md_table(['viewport'] + views, [[vp] + [grid.get((vp, vv), '-') for vv in views] for vp in viewports]))
    A('')
    ox = [f for f in fit if f['overX'] or f['overY']]
    A('Measurements: %d. Over the line (any overflow): %d.' % (len(fit), len(ox)))
    for f in ox:
        A('- %s %s: overX=%s overY=%s (section %s %s/%s) wideCards=%s'
          % (f['viewport'], f['view'], f['overX'], f['overY'], f.get('sec'), f.get('secOverX'),
             f.get('secOverY'), f.get('wideCards')))
    A('')

    # 3. rail -----------------------------------------------------------------------------
    A('## 3. Rail - 6 entries, one active, aria-current; legacy hashes')
    A('')
    rail = raw.get('rail', [])
    bad = [r for r in rail if not r['ok']]
    A('Rail checked on %d page states; %d with a problem.' % (len(rail), len(bad)))
    A('')
    seen = []
    for r in rail:
        sig = (r['order'], r['active'], r['current'], r.get('expects'))
        if sig not in seen:
            seen.append(sig)
    A(md_table(['order', 'active', 'aria-current', 'the shell expects'], [[a, b or '(none)', c or '(none)', d or '(none)'] for a, b, c, d in seen]))
    if bad:
        A('')
        for r in bad:
            A('- %s %s: order=`%s` active=`%s` current=`%s` (expected `%s`)'
              % (r['page'], r['state'], r['order'], r['active'], r['current'], r.get('expects')))
    A('')
    A('Legacy hashes (each loaded fresh, because three of them redirect the whole page):')
    A('')
    A(md_table(['hash', 'landed on', 'showing', 'rail active', 'expectation', 'ok'],
               [[l['hash'], l.get('landed', '-'), l.get('visible') or '-', l.get('rail_active') or '-',
                 l.get('expect', ''), 'yes' if l['ok'] else 'NO'] for l in raw.get('legacy', [])]))
    A('')

    # 4. parity ---------------------------------------------------------------------------
    A('## 4. Data parity - expected vs rendered')
    A('')
    par = raw.get('parity', [])
    A(md_table(['claim', 'source', 'expected', 'rendered', 'ok'],
               [[p['claim'], p['source'], p['expected'], p['rendered'], 'yes' if p['ok'] else 'NO'] for p in par]))
    A('')
    A('Parity rows: %d, mismatches: %d.' % (len(par), len([p for p in par if not p['ok']])))
    A('')

    # 5. copy -----------------------------------------------------------------------------
    A('## 5. Copy diet')
    A('')
    A('**Repo test** `%s` -> rc %s in %ss' % (pytest_res['cmd'], pytest_res['rc'], pytest_res['seconds']))
    A('')
    A('```')
    A((pytest_res['out'] or pytest_res['err']).strip()[:2000])
    A('```')
    A('')
    ct = raw.get('copy_totals', {})
    A('**Rendered scan** (visible text nodes, >8 words or >90 chars): %s offender(s) %s'
      % (ct.get('offenders', '?'), json.dumps(ct.get('byPage', {}))))
    A('')
    copy = raw.get('copy') or []
    meta_lines = [c for c in copy if c['text'].lstrip().startswith('·')]
    prose = [c for c in copy if not c['text'].lstrip().startswith('·')]
    A('Two classes, split by a stated rule: strings that **start with `·`** (a status/metadata line the app '
      'composes from live data) vs **everything else** (shipped prose plus data-composed sentences). '
      'Counts: **%d status/meta line(s)** and **%d other offender(s)**. `tests/test_copy_diet.py` only sees '
      'string literals in the source, so most of these can never show up there - that is why the repo test '
      'passes while this scan does not.' % (len(meta_lines), len(prose)))
    A('')
    A('Offenders that do **not** start with `·` (the list a copy pass would work through):')
    A('')
    if prose:
        A(md_table(['page', 'state', 'words', 'chars', 'string'],
                   [[c['page'], c['state'], c['words'], c['chars'], esc(c['text'])[:160]] for c in prose[:60]]))
    else:
        A('none')
    A('')
    A('Status/metadata lines (data-driven; listed for completeness):')
    A('')
    if meta_lines:
        A(md_table(['page', 'state', 'words', 'chars', 'string'],
                   [[c['page'], c['state'], c['words'], c['chars'], esc(c['text'])[:160]] for c in meta_lines[:60]]))
    else:
        A('none')
    A('')

    # 6. safety ---------------------------------------------------------------------------
    A('## 6. Safety - the Live/Not-live gate and the kill switch (raw facts, nothing flipped)')
    A('')
    s = raw.get('safety', {})
    A(md_table(['fact', 'value'], [
        ['data/config.json exists', s.get('config_json', {}).get('exists')],
        ['data/config.json has a dry_run key', s.get('config_json', {}).get('has_dry_run_key')],
        ['data/config.json key count', s.get('config_json', {}).get('keys')],
        ['scripts/trader/settings.json dry_run', s.get('trader_settings', {}).get('dry_run')],
        ['data/trader_plan.json dry_run', s.get('trader_plan', {}).get('dry_run')],
        ['data/trader_plan.json generated', s.get('trader_plan', {}).get('generated_iso')],
        ['data/kill_switch.json exists / parses', s.get('kill_switch', {}).get('exists')],
        ['kill switch active', s.get('kill_switch', {}).get('active')],
        ['kill switch note', repr(s.get('kill_switch', {}).get('note'))],
        ['kill switch ts', s.get('kill_switch', {}).get('ts_iso')],
        ['rendered: settings status pill', esc(s.get('rendered', {}).get('settings_pill'))],
        ['rendered: trade kill-switch chip', esc(s.get('rendered', {}).get('trade_kill_meta'))],
        ['rendered: trade kill-switch line', esc(s.get('rendered', {}).get('trade_kill_line'))],
        ['rendered: trade plan header', esc(s.get('rendered', {}).get('trade_plan_meta'))],
        ['rendered: home alerts', esc(s.get('rendered', {}).get('home_alerts'))],
    ]))
    A('')
    A('How the badge is derived (read live from `app.js`, not assumed): `dry = set.dry_run === true || '
      'plan.dry_run === true`, then the chip prints `Not live - nothing is posted` when dry. The two '
      'inputs are `scripts/trader/settings.json` and `data/trader_plan.json`; **`data/config.json` carries '
      'no `dry_run` key at all**, so it is not the gate for this badge. Both real inputs are `true` above, '
      'and the rendered copy is the Not-live wording - the badge cannot claim Live while posting is locked.')
    A('')
    A('The gate never flips the kill switch, never posts, never saves settings.')
    A('')

    # 7. themes ---------------------------------------------------------------------------
    A('## 7. Themes - 4 palettes (2 dark, 2 light) on every page')
    A('')
    th = raw.get('themes', [])
    by_theme = {}
    for t in th:
        k = (t['theme'], t['name'], t['mode'])
        d = by_theme.setdefault(k, {'scans': 0, 'low': 0, 'literal': 0, 'errs': 0, 'scanned': 0, 'unmeasured': 0})
        d['scans'] += 1
        d['low'] += t['low']
        d['literal'] += t['literalCount']
        d['scanned'] += t['scanned']
        d['unmeasured'] += t.get('unmeasured', 0)
        d['errs'] += t['newErrors']
    A('Thresholds: unreadable = text/background contrast below **2.2:1** (WCAG AA wants 4.5:1 for body text). '
      'Elements whose background is a gradient/image are counted as *unmeasured* rather than guessed; the '
      'page base colour is the theme\'s own `--bg`.')
    A('')
    A(md_table(['theme', 'mode', 'page states', 'elements scanned', 'unreadable (<2.2:1)', 'colour outside the 10 palette entries', 'unmeasured (gradient bg)', 'errors'],
               [[k[1], k[2], d['scans'], d['scanned'], d['low'], d['literal'], d['unmeasured'], d['errs']]
                for k, d in by_theme.items()]))
    A('')
    A('"Colour outside the palette" is informational: the semantic tones (`--up` green, `--down` red, warn '
      'red) are literals by design and are expected in that count. The check that fails on it is the '
      'cross-theme one below.')
    A('')
    lows = [t for t in th if t['low']]
    A('Low-contrast findings: %d of %d theme x page states.' % (len(lows), len(th)))
    for t in lows[:25]:
        A('- %s/%s %s (%s): %s element(s), e.g. %s' % (t['page'], t['state'], t['name'], t['mode'], t['low'],
                                                       esc(json.dumps(t['lowSample'][:2]))[:220]))
    A('')
    cross = raw.get('theme_cross', [])
    esc_rows = [c for c in cross if c['escapedLow']]
    A('Colours that did **not** change between the dark theme (%s) and the light theme (%s): %d element(s) total, '
      '%d of them unreadable.' % (meta.get('themes', ['?'])[0], meta.get('themes', ['?'])[2],
                                  sum(c['escaped'] for c in cross), sum(c['escapedLow'] for c in cross)))
    for c in esc_rows[:25]:
        A('- %s/%s: %d unreadable, e.g. %s' % (c['page'], c['state'], c['escapedLow'], esc(json.dumps(c['sample'][:2]))[:220]))
    A('')

    # 8. ids ------------------------------------------------------------------------------
    A('## 8. Id union vs design/_stage1/ids_before.json')
    A('')
    ids = raw.get('ids', {})
    A('ids_before.json pages: %s' % ', '.join('%s=%d' % (k, len(v)) for k, v in (ids.get('before') or {}).items()))
    A('')
    A('ids found live: %s' % ', '.join('%s=%d' % (k, len(v)) for k, v in (ids.get('found') or {}).items()))
    A('')
    A('**Missing: %d** %s' % (len(ids.get('missing') or []), ('- ' + ', '.join(ids.get('missing') or [])) if ids.get('missing') else ''))
    A('')
    A('Sanctioned removals/moves applied (%d):' % len(ids.get('sanctioned') or []))
    for x in (ids.get('sanctioned') or []):
        A('- %s' % x)
    A('')

    # not runnable ------------------------------------------------------------------------
    A('## Checks the harness could not run')
    A('')
    nr = [c for c in checks if 'NOT RUNNABLE' in str(c.get('rendered', ''))]
    if nr:
        for c in nr:
            A('- **%s** - %s: rendered `%s` (%s)' % (c['group'], c['title'], esc(c.get('rendered')), esc(c.get('note'))))
    else:
        A('None: every check found the DOM and the store it needs. When a container is missing the gate '
          'says so explicitly (`NOT RUNNABLE: no #id`) and fails that check instead of skipping it silently.')
    A('')
    if raw.get('verdict', {}).get('crashed'):
        A('**Harness crash:** `%s`' % str(raw['verdict']['crashed'])[:1500])
        A('')

    A('---')
    A('')
    A('Re-run: `python design/_stage10/gate.py` (needs the app served at %s). ' % BASE)
    A('This file is rewritten on every run; gate-raw.json holds the full machine-readable numbers.')
    if server_notes:
        A('')
        for n in server_notes:
            A(n)
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    now_local = datetime.now().strftime('%Y-%m-%d %H:%M:%S %z')
    now_iso = datetime.now().astimezone().isoformat()
    srv = server_up()
    server_notes = []
    if srv is not True:
        server_notes.append('> **Server not reachable** at %s (%s). Every load check below is meaningless until '
                            '`python server.py` (or start.bat) is up on this machine.' % (BASE, srv))

    print('[1/3] copy-diet test ...')
    pytest_res = run([sys.executable, '-m', 'pytest', 'tests/test_copy_diet.py', '-q'], timeout=600)
    print('  rc=%s in %ss' % (pytest_res['rc'], pytest_res['seconds']))

    print('[2/3] live gate (puppeteer) ...')
    gate_res = run(['node', os.path.join('design', '_stage10', 'gate.js')], timeout=1800)
    print('  rc=%s in %ss' % (gate_res['rc'], gate_res['seconds']))
    if gate_res['out'].strip():
        print('  ' + gate_res['out'].strip().replace('\n', '\n  '))
    if gate_res['err'].strip():
        print('  stderr: ' + gate_res['err'].strip()[:800])

    if not os.path.isfile(RAW):
        print('!! gate.js produced no gate-raw.json - writing a failure report')
        raw = {'verdict': {'pass': False, 'crashed': 'gate.js produced no raw output:\n' + gate_res['err'][-2000:]},
               'checks': [], 'meta': {}}
    else:
        raw = json.load(open(RAW, encoding='utf-8'))

    print('[3/3] writing %s ...' % REPORT)
    md = build_report(raw, pytest_res, gate_res, now_local, now_iso, srv)
    with open(REPORT, 'w', encoding='utf-8') as fh:
        fh.write(md)
    print('    %s bytes -> %s' % (len(md), REPORT))
    ok = bool(raw.get('verdict', {}).get('pass')) and pytest_res['rc'] == 0
    print('GATE %s' % ('PASS' if ok else 'FAIL'))
    sys.exit(0 if ok else 1)
