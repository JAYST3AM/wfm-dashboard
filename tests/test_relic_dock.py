"""The docked relic card (Jay, 2026-09-27): *"the ui card that comes up in the relics needs to be
out of the way, perhaps snap it to the left of the inventory card. also add in a resize based off
of the resolution the user is at."*

Source-level pins for what the headless probe measures at 1920 / 1440 / 1100 / 390:
  - the card is a real grid column LEFT of the table (dock before table in the DOM), never a
    pointer-following overlay;
  - the split is viewport-driven in CSS only (360 -> 300 -> stacked), with the stacked card's
    height capped so it cannot push the table off screen;
  - nothing in collection.js reads pointer coordinates for the relic card;
  - a vaulted relic's note never just repeats the header's state word.
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def read(rel):
    with open(os.path.join(ROOT, 'static', rel), encoding='utf-8') as fh:
        return fh.read()


HTML = read('collection.html')
JS = read('collection.js')
DOC = re.sub(r'/\*.*?\*/', '', HTML, flags=re.S)      # markup + CSS, comments stripped
JS_DOC = re.sub(r'/\*.*?\*/', '', JS, flags=re.S)


# ------------------------------------------------------------------ markup: a real left column

def test_dock_is_an_aside_inside_the_relics_view():
    view = DOC.split('id="relicView"', 1)[1]
    assert '<aside class="cl-reldock" id="relDock"' in view.split('</section>', 1)[0]


def test_dock_comes_before_the_table_in_the_dom():
    split = DOC.split('class="cl-relsplit"', 1)[1]
    assert split.index('id="relDock"') < split.index('id="relTable"'), \
        'the card must be the first grid column, not an overlay after the table'


def test_card_and_table_share_the_split_grid():
    assert '.cl-relsplit { display: grid;' in DOC
    assert 'grid-template-columns: 360px minmax(0, 1fr)' in DOC


# ------------------------------------------------------------------ the resolution-driven split

def test_split_narrows_then_stacks_by_viewport_width():
    assert re.search(r'@media \(max-width: 1499px\)\s*\{\s*\.cl-relsplit \{ grid-template-columns: '
                     r'300px minmax\(0, 1fr\)', DOC), 'no 300px step for 1200-1499px'
    narrow = re.search(r'@media \(max-width: 1199px\)\s*\{(.*?)\n  \}', DOC, re.S)
    assert narrow, 'no single-column step below 1200px'
    assert 'grid-template-columns: minmax(0, 1fr)' in narrow.group(1)
    assert '.cl-tip.docked { position: static' in narrow.group(1), \
        'stacked card must stop being sticky'
    assert 'max-height: 220px' in narrow.group(1), \
        'stacked card must be height-capped so the table starts on screen'


def test_dock_is_sticky_and_height_capped_while_wide():
    m = re.search(r'\.cl-tip\.docked \{(.*?)\}', DOC, re.S)
    assert m, '.cl-tip.docked rule missing'
    body = m.group(1)
    assert 'position: sticky' in body and 'top: 10px' in body
    assert 'max-height: calc(100vh - 240px)' in body, 'a tall card must not grow past the fold'


def test_wide_screens_give_the_relics_view_more_room():
    assert re.search(r'@media \(min-width: 1500px\).{0,80}cl-wrap', DOC, re.S), \
        'the 7-column table needs the wider page cap on big screens'


# ------------------------------------------------------------------ never follows the pointer

def test_relic_card_ignores_pointer_coordinates():
    for bad in ('clientX', 'clientY', 'pageX', 'pageY', 'offsetX', 'offsetY', 'movable'):
        assert bad not in JS_DOC, 'collection.js reads %s - the card must not follow the pointer' % bad


def test_dock_is_the_same_tip_shell_flipped_to_docked():
    assert '_rel' in JS and 'fillRelicTip' in JS
    # the dock is the same .cl-tip shell, flipped into 'docked' mode by dockTip()
    assert "classList.add('docked')" in JS or "classList.add(\\'docked\\')" in JS


# ------------------------------------------------------------------ copy: no repeated state word

def test_vaulted_note_does_not_restate_the_header_state():
    m = re.search(r"var note = o\.note \|\| 'no drop location in the store';\s*\n\s*"
                  r"if \(kind === 'vaulted' && note\.toLowerCase\(\) === stateWord\(r\)\)"
                  r" note = 'no active drop';", JS)
    assert m, 'the vaulted note must say what the state means, not repeat it'


def test_the_relic_card_reuses_the_shared_tip_shell():
    assert ".cl-tip" in DOC and 'clt-sect' in JS and 'clt-ref' in JS
