"""Short copy (Jay 2026-09-26):

  "you don't need little explainer text under everything, and wording like this Your rank-9 copy:
   no buy orders at this rank - list just under the lowest ask (15p) = about 14p. doesn't have to be
   so extended, simplify everything, this is a web ui build to help players not confuse them."

The drawer, the item page, the top-picks note and the advisor's own reason lines now carry labels,
values and at most a couple of words - the "how" moved into hover titles. These tests keep it that
way: the extended phrasings are banned outright and the compact forms are pinned.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# the sentences Jay called out, plus their cousins - none may come back
BANNED = [
    '= about ',
    'read it as context',
    'mixes every rank',
    'never counted as sellable',
    'list just under the lowest ask',
    'no standing buy orders',
    'equipped in a loadout',
    'genuinely sellable',
    '48h volume above the 90d rate',
    'recent volume below the 90d rate',
    'see Advanced',                     # the reason overflow line is just '+N more'
    'if every copy sells at',
    'no platinum estimate right now',
    'quick-sell to the top bid for',
    'Estimated value: you own',
]


def norm(s):
    """Compare copy without caring whether it is written as \\uXXXX escapes or real characters."""
    return re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as fh:
        return norm(fh.read())


def has(src, lit):
    return norm(lit) in src


def test_the_extended_sentences_are_gone():
    for rel in ('static/drawer.js', 'static/lookup.js', 'static/app.js', 'static/item.js',
                'scripts/sell_advisor.py'):
        src = read(rel)
        for phrase in BANNED:
            assert phrase not in src, rel + ' still contains the explainer: ' + phrase


def test_drawer_tiles_are_labels_and_values():
    js = read('static/drawer.js')
    assert has(js, "'list ' + fmtInt(Math.max(1, Math.round(Number(ask)) - 1)) + 'p'")
    assert has(js, "'quick-sell'"), 'the bid tile says quick-sell, not a sentence'
    assert has(js, "'no bids'") and has(js, "'no listings'")
    assert has(js, "'48h \\u00b7 all ranks'")
    assert has(js, "'top bid, any rank'") and has(js, "'lowest ask, any rank'")


def test_estimate_is_one_compact_line_with_the_how_in_the_title():
    js = read('static/drawer.js')
    assert has(js, "el('div', 'dw-est-line')")
    assert has(js, "t('List ')") and has(js, "t(hasAsk ? 'bid ' : 'Quick-sell ')")
    assert has(js, "t('No listings at rank ' + it.own_rank)")
    assert has(js, "t(fmt(it.count) + ' \\u00d7 ' + fmt(it.wts) + 'p \\u2248 ')"), 'owned unranked: 74 x 15p = x'
    assert has(js, "p.title = tips.join(' \\u00b7 ')"), 'the how lives in the hover title'
    assert has(js, "' equipped \\u00b7 not sellable'")
    # and the retired lookup page carries the same compact line
    lk = read('static/lookup.js')
    assert has(lk, "line.title = tips.join(' \\u00b7 ')")
    assert has(lk, "document.createTextNode('List ')")


def test_action_box_uses_counts_not_sentences():
    js = read('static/drawer.js')
    assert has(js, "' of ' + it.count + ' safe to list'")
    assert has(js, "'Nothing safe to list'")
    assert has(js, "'\\u00b7 +' + rest + ' more'"), 'reason overflow is +N more'


def test_advisor_reasons_are_short_facts():
    py = read('scripts/sell_advisor.py')
    for short in ("'market %sp'", "'demand rising'", "'demand fading'", "'demand steady'",
                  "'trend +%s%% 30d'", "'trend -%s%% 30d'", "'trend flat 30d'",
                  "'liquidity %s \\u00b7 %d/48h'", "'best window %s%s'", "'sold \\u00d7%d before'",
                  "'keep 1 for collection'", "'all copies equipped'", "'crafting %s'"):
        assert has(py, short), 'missing short reason: ' + short


def test_no_reason_line_grew_back_into_prose():
    py = read('scripts/sell_advisor.py')
    for m in re.finditer(r"reasons\.append\((.*?)\)\n", py, re.S):
        lits = re.findall(r"'([^']{45,})'", m.group(1))
        assert not lits, 'a reason line grew back into prose: ' + lits[0][:70]


def test_top_picks_note_is_one_line():
    js = read('static/app.js')
    assert has(js, 'Sorted by earnings \\u00d7 how fast they sell.</div>')
    assert 'List at = cheapest listing' not in js


def test_item_page_stat_notes_are_badges_not_sentences():
    js = read('static/item.js')
    for short in ("why: 'top bid'", "why: '48h median'", "why: '48h average'", "why: '48h'",
                  "why: 'safe \\u00d7 price'", "why: 'sell - buy'"):
        assert has(js, short), 'missing short note: ' + short
