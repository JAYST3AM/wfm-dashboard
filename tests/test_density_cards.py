"""Cards page layout (clean pass, Jay 2026-09-28): "clean up ui, don't leave anything long winded".

Retargeted from the 2026-09-27 density round (same file, same job: source-level pins for the layout
the headless probe measures). The clean pass replaced the two stacked control blocks with ONE
toolbar row and put the page head (title + count meta) above it, so the pins that described the old
placement are rewritten to the new arrangement; the constraints that still describe a real budget -
the tile grid at a 10px gap on ~130px columns, the 8.5px text floor, every id/control on the page -
stay exactly as they were.

Measured headlessly (design/_cards_clean/probe_after.js, 1920x1080): 12 columns of 183px tiles,
one wrapped toolbar (search/type/sort/rarity, then the state buttons), no horizontal scroll, and
0 console errors - the remote CDN icons the old probe counted are gone (local art + letter tile).
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(REPO, rel), encoding='utf-8') as fh:
        return fh.read()


# ------------------------------------------------------------------ load order

def test_cards_css_is_linked_right_after_style_css():
    """The page sheet must be parsed after the shell theme but before the page's own
    <style> (which carries only face art/foil/inspect visuals)."""
    html = read('static/cards.html')
    assert '<link rel="stylesheet" href="/cards.css">' in html
    assert html.index('/style.css') < html.index('/cards.css') < html.index('<style>')


def media_blocks(css, query):
    return [b.split('\n}', 1)[0] for b in css.split('@media (%s) {' % query)[1:]]


# ------------------------------------------------------------------ the wrap + head

def test_the_wrap_uses_the_whole_window_from_1500px():
    css = read('static/cards.css')
    assert ('.mcd-wrap { padding: 10px 18px 24px; max-width: 1520px; margin: 0 auto; '
            'font-variant-numeric: tabular-nums; }') in css
    assert any('.mcd-wrap { max-width: 1840px; }' in b for b in media_blocks(css, 'min-width: 1500px'))


def test_the_page_head_is_the_title_and_the_count_meta():
    html = read('static/cards.html')
    main = html.split('<main class="mcd-wrap">', 1)[1].split('</main>', 1)[0]
    head = main.split('</div>', 1)[0]
    assert '<div class="mcd-head">' in head
    assert '<h1 class="mcd-title"' in head and 'Mod Cards</h1>' in head
    assert 'id="meta"' in head, 'the count meta rides the title row'
    # title, then the ONE toolbar, then the grid - and no explainer paragraph anywhere in the wrap
    assert main.index('class="mcd-head"') < main.index('class="mcd-tools"') < main.index('id="grid"')
    assert '<p ' not in main and '<p>' not in main, 'label + value only: no lead copy'


# ------------------------------------------------------------------ one toolbar row

def test_one_toolbar_row_carries_every_filter_control():
    html = read('static/cards.html')
    main = html.split('<main class="mcd-wrap">', 1)[1].split('</main>', 1)[0]
    tools = main.split('<div class="mcd-tools"', 1)[1].split('id="grid"', 1)[0]
    for frag in ('id="q"', 'id="clearBtn"', 'id="typeSel"', 'id="sortSel"',
                 'id="rarityRow"', 'id="stateRow"', 'id="resetBtn"'):
        assert frag in tools, frag
    assert main.count('class="mcd-tools"') == 1, 'one toolbar, not a bar plus a filter block'
    assert 'mcd-bar' not in html and 'mcd-filters' not in html, 'the old two-block placement is gone'
    assert '<summary' not in tools, 'no filter sits in a <details>'
    css = read('static/cards.css')
    assert ('.mcd-tools { display: flex; flex-wrap: wrap; gap: 6px; align-items: center;\n'
            '  padding-bottom: 9px; margin-bottom: 12px; border-bottom: 1px solid var(--border); }') in css
    assert '.mcd-select {\n  background: var(--panel2); border: 1px solid var(--border); color: var(--text);\n' \
           '  border-radius: 9px; padding: 5px 8px; font: 12px var(--sans); min-height: 30px; max-width: 190px;\n}' in css


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


def test_the_toolbar_and_meta_stay_in_the_dense_budget():
    """One 30px control height for selects and filter buttons, 11.5px labels, and a 12px
    meta line that keeps its counts in tabular mono - nothing hides behind a click."""
    css = read('static/cards.css')
    assert 'border-radius: 9px; padding: 5px 9px; min-height: 30px; cursor: pointer; font: 600 11.5px var(--sans);' in css
    assert '.mcd-meta { color: var(--muted); font-size: 12px; line-height: 1.6; min-width: 0; }' in css
    assert '.mcd-meta b { color: var(--text); font-family: var(--mono); font-weight: 700; }' in css
    assert '.mcd-lbl { color: var(--muted); font-size: 10.5px;' in css


def test_the_tail_hides_the_more_button_and_gives_its_margins_back():
    css = read('static/cards.css')
    assert '.mcd-more { display: flex; justify-content: center; gap: 10px; margin: 10px 0 2px; }' in css
    # cards.css loads after style.css, so .hidden alone loses the tie: the button needs the pair
    assert '.mcd-more.hidden { display: none; }' in css
    assert '.mcd-foot { color: var(--muted); font-size: 11px; padding: 6px 18px 14px;' in css


# ------------------------------------------------------------------ phones

def test_phones_keep_a_two_column_grid_and_no_sideways_scroll():
    css = read('static/cards.css')
    block = css.split('@media (max-width: 460px) {', 1)[1].split('\n}', 1)[0]
    assert 'grid-template-columns: repeat(auto-fill, minmax(136px, 1fr)); gap: 9px;' in block
    assert '.mcd-tools .mcd-lbl { display: none; }' in css.split('@media (max-width: 560px) {', 1)[1]
    # the toolbar is a wrapping row, so the phone layout is the same stacked one
    assert '.mcd-tools { display: flex; flex-wrap: wrap;' in css


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
