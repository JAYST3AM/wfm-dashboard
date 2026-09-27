"""Copy diet (Jay, 2026-09-27): "really need to clean up the text bs it needs to be just simple
wording, you have explanations everywhere its just bloat."

The rule this test enforces, in his words: labels and values, nothing else.

  * every user-visible string is at most 8 words and 90 characters
  * no visible string may carry more than one sentence-ending period
  * a paragraph is never a UI string - if it does not fit, the drawer/card loses the line,
    or the detail moves into an existing value's title= (which is also capped, at 8 words)

The scan is deliberately dumb-but-honest: quoted strings and HTML text nodes that contain a
space and a lowercase letter, minus anything that is obviously code (selectors, URLs, template
expressions, concatenations).  It over-reports rather than under-reports, so the fix is always
to shorten or delete the copy - never to widen the rule.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, 'static')

MAX_WORDS = 8
MAX_CHARS = 90
MAX_PERIODS = 1

CANDS = re.compile(r"'([^'\n]{16,})'|\"([^\"\n]{16,})\"|>([^<>{}\n]{16,})<")
# things that are code, not copy (URLs, selectors, template/concatenation fragments, entities)
CODEY = re.compile(r'[{}<>$]|://|\bpx\b|\bvar\b|url\(|\.js\b|\.json\b|\.css\b|function|=>|\\u|'
                   r'data-|class=|id=|/[a-z_]+/|\+|\?|\bnoopener\b|\bnoreferrer\b|\bpx\b')

# strings that are legitimately long: file formats, licence/credit lines, legend separators
ALLOW = {
    'collection.js': ('Intact/Exceptional/Flawless/Radiant',),
    'cards.js': ('Mint',),
    'settings.js': ('WFM_HOST', 'WFM_PORT'),
}

def candidates(text):
    for m in CANDS.finditer(text):
        x = next(g for g in m.groups() if g)
        if not (re.search(r'[a-z]', x) and ' ' in x):
            continue
        if CODEY.search(x):
            continue
        yield x


def offenders():
    bad = []
    for name in sorted(os.listdir(STATIC)):
        if not name.endswith(('.js', '.html')):
            continue
        text = open(os.path.join(STATIC, name), encoding='utf-8').read()
        for x in candidates(text):
            if any(a in x for a in ALLOW.get(name, ())):
                continue
            words = len(x.split())
            periods = x.count('. ') + (1 if x.rstrip().endswith('.') else 0)
            if words > MAX_WORDS or len(x) > MAX_CHARS or periods > MAX_PERIODS:
                bad.append((name, words, len(x), x.strip()))
    return bad


def test_no_visible_string_is_a_sentence():
    bad = offenders()
    assert not bad, 'visible copy must stay label + value (<= %d words):\n%s' % (
        MAX_WORDS, '\n'.join('%s [%dw %dc] %s' % b for b in bad[:40]))
