"""Cards page density (Jay 2026-09-27): "more page needs to be condensed, all pages should be
condensed really."

Source-level pins for the layout the QA probe measures headlessly (qa_cards_density.js):
the wrap uses the whole window from 1500px, the two filter rows share one line there, the tile
grid packs ~130px columns at a 10px gap (13 across at 1920, was 8 at 173px), every tile keeps
its text at >= 8.5px and every id/control other tests and the probe hook onto is still on the
page. Nothing here removes a card, a field, a filter or a button - only the air between them.
Measured: docScroll 6364 -> 3062 @1920x1080, 6122 -> 3924 @1440x900, no horizontal scroll at
1920/1440/1100/390, same 3 by-design CDN icon errors.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(REPO, rel), encoding='utf-8') as fh:
        return fh.read()


# ------------------------------------------------------------------ load order + the sideways layout

def test_cards_css_is_linked_right_after_style_css():
    """The density layer must be parsed after the shell theme but before the page's own
    <style> (which now carries only face art/foil/inspect visuals)."""
    html = read('static/cards.html')
    assert '<link rel="stylesheet" href="/cards.css">' in html
    assert html.index('/style.css') < html.index('/cards.css') < html.index('<style>')


def media_blocks(css, query):
    return [b.split('\n}', 1)[0] for b in css.split('@media (%s) {' % query)[1:]]


def test_the_wrap_uses_the_whole_window_from_1500px():
    css = read('static/cards.css')
    assert '.mcd-wrap { padding: 10px 14px 18px; max-width: 1500px; margin: 0 auto; }' in css
    assert any('.mcd-wrap { max-width: 1840px; }' in b for b in media_blocks(css, 'min-width: 1500px'))


def test_the_two_filter_rows_share_one_line_from_1500px():
    css = read('static/cards.css')
    assert ('.mcd-filters { display: grid; grid-template-columns: minmax(0, 1fr); gap: 2px 12px; '
            'align-items: start; margin-top: 6px; }') in css, 'single column is the default'
    assert any('.mcd-filters { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }' in b
               for b in media_blocks(css, 'min-width: 1500px'))


def test_rarity_and_state_rows_are_wrapped_by_the_band():
    html = read('static/cards.html')
    band = html.split('<div class="mcd-filters">', 1)[1].split('\n  </div>', 1)[0]
    for frag in ('id="rarityRow"', 'id="stateRow"', 'id="resetBtn"'):
        assert frag in band, frag
    assert '<summary' not in band, 'no filter sits in a <details>'


# ------------------------------------------------------------------ the tile budget

def test_the_grid_packs_tiles_at_a_10px_gap_and_130px_columns():
    css = read('static/cards.css')
    assert 'gap: 10px' in css.split('.mcd-grid {', 1)[1].split('}', 1)[0]
    assert 'grid-template-columns: repeat(auto-fill, minmax(122px, 1fr));' in css
    assert 'minmax(158px, 1fr)' not in read('static/cards.html'), 'the old 8-across grid is gone'


def test_the_tile_keeps_its_text_at_a_readable_size():
    """The card face (5:7 art) scales with the column; the drawn text may not go below 8.5px
    and the name keeps two lines so no title is cut to one clipped line."""
    css = read('static/cards.css')
    assert '.mcd-name' in css and 'font-size: 11.5px' in css and 'min-height: 24px' in css
    assert '-webkit-line-clamp: 2' in css
    assert 'font: 8.5px/1.3 var(--sans)' in css          # .mcd-desc floor
    assert 'font: 700 26px var(--mono)' in css           # .mcd-pol
    assert 'font: 9px var(--mono)' in css                # .mcd-type / .mcd-pol-name
    assert '.mcd-body { padding: 5px 6px 6px;' in css


def test_toolbar_rows_and_the_meta_line_stay_in_the_dense_budget():
    """Toolbar/filter rows measured 23px each (was 28) and the meta line 11.5px/1.45: the
    same controls, only tighter padding - nothing hides behind a click."""
    css = read('static/cards.css')
    assert 'padding: 3px 11px; cursor: pointer; font: 600 11.5px var(--sans);' in css   # .mcd-btn
    assert '.mcd-meta { color: var(--muted); font-size: 11.5px; margin: 5px 2px 6px; line-height: 1.45; }' in css
    assert '.mcd-meta b { color: var(--text); font-family: var(--mono); }' in css      # counts stay mono
    assert '.mcd-sep { width: 1px; height: 18px;' in css


def test_the_tail_gives_its_margins_back():
    css = read('static/cards.css')
    assert '.mcd-more { display: flex; justify-content: center; gap: 10px; margin: 8px 0 2px; }' in css
    assert '.mcd-foot { color: var(--muted); font-size: 11px; padding: 4px 14px 12px;' in css


# ------------------------------------------------------------------ phones

def test_phones_keep_a_two_column_grid_and_no_sideways_scroll():
    css = read('static/cards.css')
    block = css.split('@media (max-width: 460px) {', 1)[1].split('\n}', 1)[0]
    assert 'grid-template-columns: repeat(auto-fill, minmax(136px, 1fr)); gap: 9px;' in block
    assert '.mcd-sep { display: none; }' in block, 'no stray divider at a wrap point'
    assert '.mcd-bar .mcd-lbl { display: none; }' in css.split('@media (max-width: 560px) {', 1)[1]
    # the band is one column below 1500px - the phone layout is the stacked one
    assert '.mcd-filters { display: grid; grid-template-columns: minmax(0, 1fr);' in css


# ------------------------------------------------------------------ the hooks other tests pin

def test_every_card_id_and_control_is_still_on_the_page():
    html = read('static/cards.html')
    for frag in ('id="q"', 'id="clearBtn"', 'id="typeSel"', 'id="sortSel"', 'id="rarityRow"',
                 'id="stateRow"', 'id="resetBtn"', 'id="meta"', 'id="grid"', 'id="moreBtn"',
                 'id="empty"', 'id="moreWrap"', 'class="mcd-grid"'):
        assert frag in html, frag
    for mode in ('owned', 'name', 'rarity', 'copies', 'value'):
        assert '<option value="%s"' % mode in html, mode
    assert '<summary' not in html.split('<main class="mcd-wrap">', 1)[1].split('</main>', 1)[0]
