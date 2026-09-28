"""Stage 1 acceptance report: id diff (source + rendered), chrome inventory, verification numbers.

Run from the repo root:  python3 design/_stage1/verify_ids.py
Reads design/_stage1/ids_before.json (the pre-stage-1 snapshot) and design/_stage1/qa_shell.json
(the headless run) and prints the numbers the stage is judged on.
"""
import io
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
S = os.path.join(ROOT, 'static')
PAGES = ['index', 'collection', 'cards', 'settings', 'item']

ID_RE = re.compile(r'\bid="([^"]+)"')


def ids_of(path):
    return ID_RE.findall(io.open(path, encoding='utf-8').read())


def main():
    before = json.load(io.open(os.path.join(ROOT, 'design', '_stage1', 'ids_before.json'), encoding='utf-8'))
    qa = json.load(io.open(os.path.join(ROOT, 'design', '_stage1', 'qa_shell.json'), encoding='utf-8'))
    shell_src = set(ids_of(os.path.join(S, 'shell.js')))
    # two ids are built from the page registry at render time (id: 'settingsBtn' -> id="settingsBtn")
    shell_src |= set(re.findall(r"id:\s*'([A-Za-z0-9_-]+)'", io.open(os.path.join(S, 'shell.js'), encoding='utf-8').read()))
    print('shell.js declares %d ids' % len(shell_src))

    ok = True
    for page in PAGES:
        page_src = set(ids_of(os.path.join(S, page + '.html')))
        want = set(before[page])
        missing_src = sorted(want - page_src - shell_src)
        dupes_src = sorted(i for i in page_src if ids_of(os.path.join(S, page + '.html')).count(i) > 1)
        rendered = set(qa['pages'][page]['ids'])
        missing_dom = sorted(want - rendered)
        extra_dom = sorted(rendered - want - shell_src)
        status = 'OK ' if not (missing_src or missing_dom or dupes_src) else 'FAIL'
        if status == 'FAIL':
            ok = False
        print('%s %-11s source: %3d before -> %3d page+shell (missing %d, dupes %d) | '
              'rendered: %3d dom (missing %d)' %
              (status, page, len(want), len(page_src | shell_src), len(missing_src), len(dupes_src),
               len(rendered), len(missing_dom)))
        if missing_src:
            print('      missing from source:', missing_src)
        if missing_dom:
            print('      missing from DOM   :', missing_dom)
        if extra_dom:
            print('      new in DOM         :', extra_dom[:12], '(+%d)' % max(0, len(extra_dom) - 12))

    chrome = ['mainnav', 'chips', 'soundBtn', 'themeBtn', 'themePanel', 'themeName', 'themeGrid']
    print('\nchrome ids in every page DOM:')
    for cid in chrome:
        have = [p for p in PAGES if cid in qa['pages'][p]['ids']]
        print('  %-10s %s' % (cid, 'OK all 5' if len(have) == 5 else 'MISSING on ' + str([p for p in PAGES if p not in have])))
    opt = {'search': [p for p in PAGES if 'search' in qa['pages'][p]['ids'] and qa['pages'][p]['search']],
           'searchDrop': [p for p in PAGES if 'searchDrop' in qa['pages'][p]['ids']],
           'syncState': [p for p in PAGES if 'syncState' in qa['pages'][p]['ids']],
           'refresh': [p for p in PAGES if 'refresh' in qa['pages'][p]['ids']],
           'btnExportPng': [p for p in PAGES if 'btnExportPng' in qa['pages'][p]['ids']]}
    for k, v in opt.items():
        print('  %-12s -> %s' % (k, v))

    print('\nper page:')
    for p in PAGES:
        d = qa['pages'][p]
        print('  %-11s pills=%d active=%s subnav=%s foot=%s themeItems=%d themeOpen=%s sound=%s '
              'chips=%s brand=%r' % (
                  p, len(d['pills']), d['active'], len(d['subnav']) if d['subnav'] else '-',
                  bool(d['foot']), d['theme']['items'], d['theme']['open'],
                  (str(d['sound'].get('after')) + ('' if d['sound'].get('before') != d['sound'].get('after') else ' (NO TOGGLE)')), bool(d['chipsText']), d['brand']))
        print('              over1920 x=%s y=%s | over1366 x=%s y=%s | over820 x=%s | fold=%s' % (
            d['m1920']['overX'], d['m1920']['overY'], d['m1366']['overX'], d['m1366']['overY'],
            d['m820']['overX'], json.dumps(d['fold'])))
    print('\nindex fit rules (pageOver must be 0):', json.dumps(qa.get('fit', {})))
    print('\nconsole errors per page:', {k: len(v) for k, v in qa['errors'].items()})
    print('\nRESULT:', 'ALL CLEAN' if ok else 'PROBLEMS ABOVE')


main()
