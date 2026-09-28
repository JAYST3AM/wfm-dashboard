"""Stage 8 id check: did anything leave the settings DOM?

    python design/_stage8/verify_ids.py

Reads design/_stage8/ids_before.json (static/settings.html before the category split) and
design/_stage8/qa_settings.json (the ids a real browser rendered after clicking through all six
categories), and reports every id that existed before and no longer exists.

Exit code 0 = nothing lost, 1 = something is unaccounted for.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BEFORE = os.path.join(HERE, 'ids_before.json')
AFTER = os.path.join(HERE, 'qa_settings.json')


def main():
    if not os.path.exists(AFTER):
        print('no %s yet - run: node design/_stage8/qa_settings.js' % os.path.basename(AFTER))
        return 2
    before = json.load(open(BEFORE, encoding='utf-8'))
    report = json.load(open(AFTER, encoding='utf-8'))
    missing = report['ids']['missing']
    rendered = report['ids']['rendered']
    print('ids before %3d : %s' % (len(before['ids']), ', '.join(before['ids'])))
    print('ids after  %3d (whole click-through, union across the six categories)' % rendered)
    print('missing    %3d : %s' % (len(missing), missing or '-'))
    if missing:
        print('\nLOST: ' + ', '.join(missing))
        return 1
    print('\nOK - every settings id from the pre-stage-8 snapshot is still in the rendered DOM.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
