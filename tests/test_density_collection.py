"""Collection page density (Jay 2026-09-27): "more page needs to be condensed, all pages should be
condensed really."

Source-level pins for the layout the headless probe measures (design/_stage6/qa_collection.js):
the item grid spends the horizontal room (12 tiles per row at 1920, 9 at 1440 - it was 8 inside a
1400px column at both), tiles and relic rows stay inside their budgets, and every id / control /
column / filter the page and the other tests hook onto is still there. Nothing here removes an
item, a tab, a count, a filter or a button - only the air between them.

Stage 6 (2026-09-28) consolidated the page around ONE section navigation: the head is now
title + counts + progress hairline + the section row (Collection | Relics | Mastery | Cards), and
the row is the only thing that switches sections. The pins below follow that: the head's own
budget, the row as the single navigation, and the two places the sections used to be duplicated
(the relic tab in the category strip, the blank docked card).

Measured (1920x1080 / 1440x900 / 390x844):
  head (title + counts + bar + row)   79px / 79px   (the completion card alone was 86px)
  section row                         29px / 29px (one line at 1920; the four tabs wrap below
                                      560px only after the narrow-band padding step)
  document scrollHeight  1733 / 2287 / 8744
  tiles with a top edge in the first screen  72 / 45 / 4
  tile height 127-132 - every tile carries its flag row now, so a row of tiles is one height
  relic row 22.5 (805-row table, same seven columns); the docked card 360 / 300 / stacked

The docked relic card keeps its behaviour (it is pinned by tests/test_relic_dock.py); what stage 6
added is what it shows when nothing is hovered: the first row on screen, marked `.sel`. These
tests only guard that the dock's rules stayed in the page while the density layer moved out.
"""
import os
import re

from conftest import shell_js

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


def test_every_tile_reserves_its_flag_row():
    """A tile with no flags used to be 13px shorter than the one beside it; the row is always
    there now, so names, flags and prices sit on the same three lines across the grid."""
    assert 'min-height: 13px' in re.search(r'\.cl-flags \{([^}]*)\}', CSS).group(1)
    assert 'c.appendChild(flags);' in JS


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
    # the strip is 13 categories now, so its tabs are tight enough to keep them on one line at
    # 1920 (1660 -> 1582px) - no orphan tab on a second row
    assert '.cl-tabs .tab { padding: 4px 8px; font-size: 12px; }' in CSS
    assert '.cl-meta { color: var(--muted); font-size: 11.5px; margin: 5px 0 8px;' in CSS


# ------------------------------------------------------------------ the head + the one section row

def test_the_head_is_one_title_row_with_the_section_row_on_its_bottom_edge():
    """Stage 6: the completion card became the page head - the page title and the log's counts on
    one line, a 3px hairline, then the section row flush with the head's bottom border. One border
    style (1px var(--border)), no shadow, no second icon."""
    head = re.search(r'\.cl-overall \{([^}]*)\}', CSS).group(1)
    assert 'border: 1px solid var(--border)' in head
    assert 'box-shadow' not in head
    assert 'padding: 8px 14px 0' in head, "the row has to reach the head's bottom edge"
    assert '<h1 class="cl-title"' in HTML and re.search(r'\.cl-title \{[^}]*font-size: 14px', CSS)
    # the title carries the only mark in the row; the old card's diamond + trophy pair is gone
    assert '.cl-ov-title' not in HTML and '.cl-ov-ico' not in HTML
    for rule in ('#collectionNav .navpill.active {', 'box-shadow: inset 0 -2px 0 var(--accent);',
                 '#collectionNav .navpill::after { display: none; }'):
        assert rule in CSS, rule


def test_the_category_strip_is_the_item_grids_own_control_again():
    """The strip used to carry Relics as a 14th tab. Relics is a section now, so the strip is the
    log's 13 categories and closes with the section - the row is the only section navigation."""
    body = JS[JS.index('function buildTabs'):JS.index('function selectCategory')]
    assert 'state.doc.categories.forEach' in body
    assert "'Relics'" not in body, 'the relic tab must not come back into the category strip'
    assert "tabs.classList.add('hidden')" in JS
    assert '#tabs.hidden { display: none; }' in CSS


def test_the_one_search_box_follows_the_section_it_filters():
    assert "q.placeholder = on === 'relics' ? 'Search relics…' : 'Search this category…';" in JS
    assert "q.setAttribute('aria-label', on === 'relics' ? 'Search relics'" in JS


def test_the_dock_shows_a_row_so_the_left_column_is_never_an_empty_box():
    """Hover still drives the docked card; with nothing hovered it shows the first row on screen
    and marks it, so the dock reads as the table's detail pane instead of a blank hole."""
    for frag in ('function dockRow', 'function dockFirst', 'function markDockRow', 'dockFirst();',
                 "rows[i].classList.toggle('sel'", "dockRow(tr)"):
        assert frag in JS, frag
    assert '.cl-reltab tbody tr.sel {' in HTML
    assert 'No relic selected' in JS      # the only empty state left: nothing matches the filter


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
    """Pages keep every id they own; the shell ids moved to /shell.js in stage 1 (one source for
    all five pages) and are asserted there."""
    for frag in ('id="overall"', 'id="ovPct"', 'id="ovCount"', 'id="ovBar"',
                 'id="ovFoot"', 'id="collectionNav"', 'id="q"', 'id="clearBtn"', 'id="missBtn"',
                 'id="priceBtn"', 'id="tabs"', 'id="meta"', 'id="grid"', 'id="empty"',
                 'id="relicView"', 'id="relPills"', 'id="relDock"', 'id="relTable"',
                 'id="relHead"', 'id="relBody"', 'id="relNote"', 'id="srcLine"'):
        assert frag in HTML, frag
    for frag in ('id="mainnav"', 'id="chips"', 'id="themeBtn"', 'id="themePanel"', 'id="soundBtn"'):
        assert frag in shell_js(), frag


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
    for text in re.findall(r"el\('[a-z-]+', [^,]+, '([^']{25,})'\)", JS):
        assert len(text) <= 100, text
