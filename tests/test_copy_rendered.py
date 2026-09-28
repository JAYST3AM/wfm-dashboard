"""Rendered copy-diet: every visible string the harness saw must be label + value
(<= 8 words / <= 90 chars).

tests/test_copy_diet.py scans the *source* (string literals in static/*.js|html); it cannot see
sentences joined from data at render time. This test reads what actually rendered:
design/_stage10/gate-raw.json, written by design/_stage10/gate.js. Skip cleanly when that file is
absent (the harness only runs on demand).
"""
import json
import os

import pytest

RAW = os.path.join(os.path.dirname(__file__), '..', 'design', '_stage10', 'gate-raw.json')
MAX_WORDS = 8
MAX_CHARS = 90

# Rendered-copy exemptions. Keep this list tiny; every entry names its owner and the reason it is
# out of this pass's scope. Nothing this pass owns may live here, and deleting an entry must be
# part of landing its owner's fix.
# Key: (page or '*', css class on the element) -> why.
EXEMPT_RENDERED = {
    # static/home.js prints the feature payload's alert rows and the recent-materials line as one
    # data sentence (2-4 facts joined). home.js/chart.js are frozen during the gate-fix pass (the
    # Home/chart workstream owns them, including trimming these lines). Matched on page + stable
    # class because the counts inside the text are live data.
    ('*', 'h-alert-t'): 'home.js alert title - payload sentence, Home/chart workstream owns',
    ('*', 'h-alert-d'): 'home.js alert detail - payload sentence, Home/chart workstream owns',
    ('*', 'h-l2'): 'home.js recent-materials line - payload data, Home/chart workstream owns',
}


def _exempt(page, cls):
    classes = (cls or '').split()
    for (pg, kls), why in EXEMPT_RENDERED.items():
        if pg in ('*', page) and kls in classes:
            return why
    return None


@pytest.mark.skipif(not os.path.exists(RAW), reason='no gate-raw.json yet - run node design/_stage10/gate.js')
def test_rendered_copy_stays_inside_budget():
    with open(RAW, encoding='utf-8') as fh:
        raw = json.load(fh)
    rows = raw.get('copy') or []
    bad = []
    for r in rows:
        text = str(r.get('text') or '')
        words, chars = int(r.get('words') or 0), int(r.get('chars') or 0)
        if words <= MAX_WORDS and chars <= MAX_CHARS:
            continue                      # recorded only as a courtesy; inside budget
        if _exempt(str(r.get('page') or ''), str(r.get('cls') or '')):
            continue
        bad.append('%s/%s [%dw %dc] cls=%s :: %s' % (
            r.get('page'), r.get('state'), words, chars, r.get('cls'), text[:120]))
    assert not bad, ('rendered copy must stay label + value (<= %d words / %d chars); '
                     'fix at the render site, keep the full text in the title:\n%s'
                     % (MAX_WORDS, MAX_CHARS, '\n'.join(bad[:40])))


@pytest.mark.skipif(not os.path.exists(RAW), reason='no gate-raw.json yet - run node design/_stage10/gate.js')
def test_rendered_copy_exemptions_stay_short():
    """The exemption list is a temporary carve-out for strings other workstreams own, not a dumping
    ground: if it grows past a handful of rows, the right fix is at the render site."""
    assert len(EXEMPT_RENDERED) <= 4, 'trim the rendered-copy exemption list (currently %d rows)' % len(EXEMPT_RENDERED)
