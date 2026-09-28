"""Stage 2 id check: did anything leave the rendered DOM?

    python design/_stage2/verify_ids.py

Reads design/_stage1/ids_before.json (the id snapshot taken before the nav rebuild) and
design/_stage2/qa_ia.json (what a real browser rendered on index / collection / cards / settings /
item after it), and reports every id that existed before and no longer exists anywhere.

One rename is sanctioned by the stage plan: the old More view's wrapper became the Tools section
(#view-more -> #view-tools) - the section is what it is now, and its twelve list ids are still
inside it. Anything else missing is a lost control.

Exit code 0 = nothing lost (or only the rename), 1 = something is unaccounted for.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BEFORE = os.path.join(ROOT, 'design', '_stage1', 'ids_before.json')
AFTER = os.path.join(HERE, 'qa_ia.json')

# the stage plan's one deliberate rename (and the ids the shell itself owns, which live in
# shell.js rather than a page - they are still rendered, they are just not page markup)
RENAMED = {'view-more': 'view-tools'}


def load(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def main():
    if not os.path.exists(AFTER):
        print('no %s yet - run: node design/_stage2/qa_ia.js' % os.path.relpath(AFTER, ROOT))
        return 2
    before = load(BEFORE)
    report = load(AFTER)

    wanted = sorted({i for ids in before.values() for i in ids})
    rendered = set()
    for page in report['pages'].values():
        rendered.update(page['ids'])
    rendered.update(report['ids'].get('extra', []))

    missing = [i for i in wanted if i not in rendered and i not in RENAMED]
    print('ids before        %3d  (%s)' % (len(wanted), ', '.join(sorted(before))))
    print('ids rendered       %3d  across %d fresh pages' % (len(rendered), len(report['pages'])))
    print('sanctioned rename  %s' % ', '.join('%s -> %s' % kv for kv in sorted(RENAMED.items())))
    print('missing            %3d  %s' % (len(missing), missing or '-'))
    if missing:
        print('\nLOST: ' + ', '.join(missing))
        return 1
    print('\nOK - every id from the pre-stage-2 snapshot is still in the rendered DOM.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
