"""Collection page density (Jay 2026-09-27): "more page needs to be condensed, all pages should be
condensed really."

Source-level pins for the layout the headless probe measures (qa_collection_density.js):
the item grid spends the horizontal room (12 tiles per row at 1920, 11 at 1440 - it was 8 inside a
1400px column at both), tiles and relic rows stay inside their budgets, and every id / control /
column / filter the page and the other tests hook onto is still there. Nothing here removes an
item, a tab, a count, a filter or a button - only the air between them.

Measured (qa_collection_density.js, 1920x1080 / 1440x900):
  document scrollHeight  2918 / 2918  ->  1680 / 1942
  tiles with a top edge in the first screen  32 / 24  ->  72 / 50
  tile height 147 -> 134 worst case (110 when a tile carries no flag row)
  relic row 26 -> 23 (805-row table, same seven columns)

The docked relic card is untouched in behaviour and still pinned by tests/test_relic_dock.py;
these tests only guard that its rules stayed in the page while the density layer moved out.
"""
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(REPO, rel), encoding='utf-8') as fh:
        return fh.read()


HTML = read('static/collection.html')
CSS = read('static/collection.css')
JS = read('static/collection.js')


def px(pattern, text):
    m = re.search(pattern, text)
    assert m, 'missing: ' + pattern
    return int(m.group(1))


def grid_minmax(text, band=None):
    """The `minmax(Npx, 1fr)` the grid uses in the default rule or inside a media band."""
    if band is None:
        block = re.search(r'\.cl-grid \{([^}]*)\}', text).group(1)
    else:
        block = re.search(r'@media \(%s\) \{ \.cl-grid \{([^}]*)\} \}' % re.escape(band),
                          text).group(1)
    return px(r'minmax\((\d+)px, 1fr\)', block)


# ------------------------------------------------------------------ the density layer is linked first

def test_the_density_layer_is_linked_after_style_css():
    assert '<link rel="stylesheet" href="/collection.css">' in HTML
    assert HTML.index('/style.css') < HTML.index('/collection.css') < HTML.index('</head>')
    # and the page's own <style> still carries what other tests read out of THIS file
    assert '.cl-tip {' in HTML and '.cl-relsplit { display: grid;' in HTML


def test_the_density_values_live_in_exactly_one_file():
    for gone in ('repeat(auto-fill, minmax(146px, 1fr))', 'width: 68px; height: 68px',
                 'padding: 13px 16px 14px'):
        assert gone not in HTML, gone + ' is still in the page as well as the stylesheet'
    assert 'repeat(auto-fill, minmax(146px, 1fr))' not in CSS


# ------------------------------------------------------------------ the sideways bands

def test_the_item_grid_spends_the_room_on_wide_screens():
    assert '.cl-grid { display: grid; gap: 8px; grid-template-columns: ' \
           'repeat(auto-fill, minmax(126px, 1fr)); }' in CSS
    assert '@media (min-width: 1200px) { .cl-grid { grid-template-columns: ' \
           'repeat(auto-fill, minmax(120px, 1fr)); } }' in CSS
    # wider viewport, smaller minimum, more columns per row - never the other way round
    assert grid_minmax(CSS, 'min-width: 1200px') < grid_minmax(CSS)


def test_the_wide_band_raises_the_page_cap_to_the_relic_views_1680():
    assert '@media (min-width: 1500px) { .cl-wrap { max-width: 1680px; } }' in CSS
    assert '@media (min-width: 1500px) { .cl-foot { max-width: 1680px; } }' in CSS
    assert '.cl-wrap { padding: 10px 16px 26px; max-width: 1400px; margin: 0 auto; }' in CSS


def test_a_390px_phone_still_gets_two_tiles_per_row():
    """Same two columns as before: 358px of content fits 2 x 126 + gap, never a third."""
    min_w, gap = grid_minmax(CSS), px(r'\.cl-grid \{[^}]*gap: (\d+)px', CSS)
    content = 390 - 2 * 16                      # .cl-wrap's own padding, pinned above
    assert (content + gap) // (min_w + gap) == 2


# ------------------------------------------------------------------ the budgets

def test_one_tile_stays_inside_the_136px_budget():
    """padding + art + 3 gaps + a 2-line name + the flag row + the price pill."""
    card = re.search(r'\.cl-card \{([^}]*)\}', CSS).group(1)
    pad = px(r'padding: (\d+)px', card)
    gap = px(r'gap: (\d+)px', card)
    thumb = px(r'\.cl-thumb \{\s*width: (\d+)px; height: \d+px', CSS)
    name_min = px(r'\.cl-name \{[^}]*min-height: (\d+)px', CSS)
    labels = 30                                  # flag row 13 + price pill 17, measured at 1920
    assert 2 * pad + thumb + 3 * gap + name_min + labels <= 136, 'tile grew past its budget'


def test_one_relic_row_stays_inside_the_28px_budget():
    line = '.cl-reltab tbody td { padding: 3px 9px; font-size: 11.5px; line-height: 1.35; }'
    assert line in HTML
    size = float(re.search(r'font-size: ([\d.]+)px', line).group(1))
    lh = float(re.search(r'line-height: ([\d.]+)', line).group(1))
    pad = float(re.search(r'padding: ([\d.]+)px', line).group(1))
    row = size * lh + 2 * pad + 1                     # + the row's own 1px border
    assert row <= 28, row


def test_the_toolbar_and_tab_strip_are_one_size_down():
    assert '.cl-controls .btn { padding: 4px 12px; font-size: 11.5px; }' in CSS
    assert '.cl-tabs .tab { padding: 4px 11px; font-size: 12px; }' in CSS
    assert '.cl-meta { color: var(--muted); font-size: 11.5px; margin: 5px 2px 8px;' in CSS


# ------------------------------------------------------------------ the dock stays where it was

def test_the_docked_relic_card_did_not_move_to_the_stylesheet():
    """The dock's split, stickiness and phone cap are pinned in this very file by
    tests/test_relic_dock.py - they must stay here, not drift into collection.css."""
    for rule in ('.cl-relsplit { display: grid; grid-template-columns: 360px minmax(0, 1fr);',
                 '.cl-tip.docked {', 'position: sticky; top: 10px',
                 'max-height: calc(100vh - 240px)', 'max-height: 220px'):
        assert rule in HTML, rule
    assert 'cl-relsplit' not in CSS


# ------------------------------------------------------------------ nothing lost

def test_every_id_and_control_is_still_on_the_page():
    for frag in ('id="mainnav"', 'id="overall"', 'id="ovPct"', 'id="ovCount"', 'id="ovBar"',
                 'id="ovFoot"', 'id="chips"', 'id="q"', 'id="clearBtn"', 'id="missBtn"',
                 'id="priceBtn"', 'id="tabs"', 'id="meta"', 'id="grid"', 'id="empty"',
                 'id="relicView"', 'id="relPills"', 'id="relDock"', 'id="relTable"',
                 'id="relHead"', 'id="relBody"', 'id="relNote"', 'id="srcLine"',
                 'id="themeBtn"', 'id="themePanel"', 'id="soundBtn"'):
        assert frag in HTML, frag


def test_the_relic_table_keeps_its_seven_columns_and_four_pills():
    for col in ("{ key: 'name', label: 'Relic' }", "{ key: 'tier', label: 'Tier' }",
                "{ key: '', label: 'State' }", "{ key: 'owned', label: 'Owned' }",
                "{ key: '', label: 'Best reward' }", "{ key: 'ev', label: 'EV', cls: 'num' }",
                "{ key: '', label: 'Where' }"):
        assert col in JS, col
    for pill in ("{ key: 'all', label: 'All' }", "{ key: 'drop', label: 'Dropping now' }",
                 "{ key: 'owned', label: 'Owned' }", "{ key: 'vaulted', label: 'Vaulted' }"):
        assert pill in JS, pill


def test_the_tile_still_carries_art_name_flags_and_the_price_pill():
    for frag in ("el('img', 'cl-thumb')", "el('div', 'cl-name', it.name)", "'cl-flag mastered'",
                 "'cl-flag owned'", "'cl-flag mr'", "el('a', 'cl-floor')", "'▲ ' + fmtInt(it.floor) + 'p'",
                 "el('div', 'cl-noprice', '—')"):
        assert frag in JS, frag


def test_the_toolbar_wiring_is_untouched():
    for frag in ("toggleBtn('missBtn', 'missingOnly')", "toggleBtn('priceBtn', 'buyable')",
                 "document.getElementById('clearBtn')", 'window.wfmOpenItem',
                 'function wireObtainTip()', 'function wireRelicTip()', 'fillRelicTip',
                 'function dockTip()', 'function undockTip()'):
        assert frag in JS, frag


def test_the_copy_diet_rules_hold_in_the_page_block():
    """No sentence came back with the density pass: the page's own strings stay labels."""
    for text in re.findall(r'el\(\'[a-z-]+\', [^,]+, \'([^\']{25,})\'\)', JS):
        assert len(text) <= 100, text
