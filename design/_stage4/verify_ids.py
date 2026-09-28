"""Stage 4 id check: did anything leave the rendered DOM when Trade was reworked?

    python design/_stage4/verify_ids.py

Reads design/_stage4/ids_before.json (the `view-trade` block of design/_stage1/ids_before.json -
the 48 ids the Trade surface carried before stage 4) and design/_stage4/qa_trade.json (what a real
browser rendered after it), and reports every id that existed before and no longer exists.

Stage 4 added three ids (tt-advanced, tp-advanced, postMode) and moved nothing out of #view-trade:
every card the brief calls an engine internal is now inside #tp-advanced, and every other id keeps
its name. Anything missing is a lost control.

Exit code 0 = nothing lost, 1 = something is unaccounted for.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BEFORE = os.path.join(HERE, 'ids_before.json')
AFTER = os.path.join(HERE, 'qa_trade.json')

# additive on purpose: the stage-4 tabs/panel + the posting-mode chip. Nothing was renamed.
ADDED = ['tt-advanced', 'tp-advanced', 'postMode']


def load(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def main():
    if not os.path.exists(AFTER):
        print('no %s yet - run: node design/_stage4/qa_trade.js' % os.path.relpath(AFTER, ROOT))
        return 2
    before = load(BEFORE)
    report = load(AFTER)
    rendered = set(report['ids'].get('all') or [])
    missing = [i for i in before if i not in rendered]
    dups = report['ids'].get('dups') or []
    print('ids before        %3d  (the #view-trade block of the stage 1 snapshot)' % len(before))
    print('ids rendered      %3d  after the rework' % len(rendered))
    print('stage-4 additions %s' % ', '.join(ADDED))
    print('missing           %3d  %s' % (len(missing), missing or '-'))
    print('duplicates        %3d  %s' % (len(dups), dups or '-'))
    if missing or dups:
        print('\nLOST: ' + ', '.join(missing + dups))
        return 1
    print('\nOK - every id the Trade surface carried before stage 4 is still in the rendered DOM.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
