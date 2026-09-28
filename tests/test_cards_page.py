"""Cards page clean pass (Jay 2026-09-28): same controls, same grid, same features - new chrome.

This is the TCG / mod-card workspace reached from Collection (its tab row links Collection |
Relics | Mastery | Cards). The clean pass gave it the anatomy the rest of the app already has:
page title + count meta, ONE toolbar row, then the card grid; one card treatment; and local-only
art with the shared drawer's letter tile as the fallback - the warframe.market CDN is blocked on
this PC, so the grid never asks it for an image (no broken-image icons, no console noise).

Source-level pins here; the behaviour (filters move the grid count, a card click opens the
inspect panel, Escape closes it, 0 console errors) is measured headlessly by
design/_cards_clean/probe_after.js against 1920x1080.
"""
import os

from conftest import REPO, read_static

PAGE = 'cards.html'
CSS = 'cards.css'
JS = 'cards.js'

# the warframe.market hosts the grid must never ask for artwork
CDN_MARKERS = ('warframe.market/static', 'cdn.warframestat.us', 'api.warframe.market')


def cards_js():
    return read_static(JS)


def cards_css():
    return read_static(CSS)


def cards_html():
    return read_static(PAGE)


# ------------------------------------------------------------------ anatomy

def test_head_holds_the_count_meta_and_no_explainer():
    html = cards_html()
    main = html.split('<main class="mcd-wrap">', 1)[1].split('</main>', 1)[0]
    assert '<h1 class="mcd-title" data-icon="stack">Mod Cards</h1>' in main
    assert '<div class="mcd-meta" id="meta">Loading mod cards…</div>' in main
    assert 'class="mcd-head"' in main
    # label + value only: the page carries no lead paragraph and no rarity-coverage block
    assert '<p ' not in main and '<p>' not in main
    js = cards_js()
    assert "help.push('rarity coverage (owned/total): '" in js, 'the coverage string moved into title='
    assert 'meta.title = help.join' in js, 'build notes + coverage ride the title attribute'


def test_one_toolbar_row_is_the_only_control_block():
    html = cards_html()
    main = html.split('<main class="mcd-wrap">', 1)[1].split('</main>', 1)[0]
    assert main.count('class="mcd-tools"') == 1
    for gone in ('mcd-bar', 'mcd-filters', 'mcd-sep'):
        assert gone not in html, gone + ' is the retired two-block placement'
    # the state buttons + reset are labelled for a human: no "×N" placeholder token
    assert '>Dupes</button>' in html and '×N' not in html
    assert 'title="Mods you own more than one copy of"' in html
    assert '>Reset</button>' in html and 'title="Back to the default filters"' in html


def test_meta_line_reads_shown_then_the_collection_counts():
    js = cards_js()
    # one line: "Showing <b>N / M</b> mods · owned N · missing N · dupes N · quoted N"
    for frag in ("'Showing '", "' mods'", "' · filters: '", "' · owned '", "' · missing '",
                 "' · dupes '", "' · quoted '"):
        assert frag in js, frag
    assert "' of ' + state.all.length + ' mods'" not in js, 'the meta lost its third count'
    assert "state.shown + ' / ' + state.filtered.length" in js


# ------------------------------------------------------------------ local-only art

def test_grid_art_never_asks_a_remote_host():
    """Pre-existing design: the CDN refuses cross-origin embeds on this PC
    (ERR_BLOCKED_BY_RESPONSE), which filled the console. Art is the local 4x set only."""
    js = cards_js()
    for marker in CDN_MARKERS:
        assert marker not in js, marker + ' must not be requested by the cards grid'
    for dead in ('artState', 'probeArt', 'upgradeArt', 'new Image()'):
        assert dead not in js, dead + ' belongs to the retired CDN probe'
    # artSrc answers from the local manifest or nothing at all - never card.icon
    assert "return (state.hi && state.hi[card.slug]) ? '/hi/' + card.slug + '.webp' : null;" in js
    assert "fetch('hi/index.json'" in js


def test_missing_local_art_falls_back_to_the_drawers_letter_tile():
    """No /hi file -> the shared drawer's letter tile (its .dw-avatar recipe), so a card can
    never show a broken-image icon."""
    js = cards_js()
    css = cards_css()
    drawer = read_static('drawer.js')
    # same initial rule in both files (the drawer's own helper)
    assert "replace(/[^A-Za-z0-9]/g, '')" in js
    assert "replace(/[^A-Za-z0-9]/g, '')" in drawer
    assert 'function addTile(art, card)' in js
    assert 'var tile = el(\'span\', \'mcd-tile\', initial(card.name, card.slug));' in js
    assert "if (!src) { addTile(art, card); return; }" in js
    # a local file that will not decode swaps the image for the tile as well
    assert "img.remove();\n      art.classList.remove('has-art');\n      addTile(art, card);" in js
    # the tile is the drawer avatar's palette, and it takes the art slot on the face
    assert '.mcd-tile {' in css
    tile = css.split('.mcd-tile {', 1)[1].split('}', 1)[0]
    for token in ('background: var(--panel2)', 'border: 1px solid var(--border)',
                  'color: var(--accent)', 'border-radius: 12px'):
        assert token in tile, token
    assert '.mcd-art.has-tile .mcd-pol { font-size: 15px; opacity: .8; }' in css
    # the art-less face fills its plate with the mod's own text instead of an empty box
    assert "if ((fa || !artSrc(card)) && card.stats_text)" in js


def test_full_art_and_baked_faces_still_win():
    """The local art tile must not fight the cardart manifest: full-art/baked faces are
    painted from their own file and never take an <img>."""
    js = cards_js()
    html = cards_html()
    assert 'if (artEntry(card)) return;' in js
    assert 'if (!fa) addArt(art, card);' in js
    assert '.mcd-front.has-fullart.art-baked {' in html
    assert '.mcd-front .mcd-art.has-art ~ .mcd-body { display: none; }' in html


# ------------------------------------------------------------------ features kept

def test_the_inspect_panel_keeps_every_row_and_action():
    js = cards_js()
    for frag in ("insRow('Type'", "insRow('Polarity'", "insRow('Base drain'", "insRow('Max rank'",
                 "insRow('Best copy'", "insRow('Median (48h · all ranks)'", "insRow('Slug'",
                 "'Flip card'", "'Reset view'", "el('a', 'mcd-btn ins-market'",
                 "I.info.appendChild(gradeLine(card))"):
        assert frag in js, frag
    assert 'MARKET + encodeURIComponent(card.slug)' in js


def test_filters_search_sort_and_paging_are_untouched():
    js = cards_js()
    html = cards_html()
    for frag in ("state.rarity", "state.type", "state.dupes", "state.owned", "state.missing",
                 "state.sort", "state.q", 'function matches(card)', 'function sorted(list)',
                 'function score(c, q)', 'BATCH = 180'):
        assert frag in js, frag
    # every control the page declares is wired in the DOMContentLoaded block
    for frag in ("document.getElementById('q')", "q.addEventListener('input'",
                 "document.getElementById('clearBtn').addEventListener",
                 "document.getElementById('typeSel').addEventListener",
                 "document.getElementById('sortSel').addEventListener",
                 "document.getElementById('resetBtn').addEventListener",
                 "document.getElementById('moreBtn').addEventListener",
                 "document.getElementById('stateRow')"):
        assert frag in js, frag
    assert "getElementById('rarityRow')" in js          # rarity buttons are built + wired there
    for mode in ('owned', 'name', 'rarity', 'copies', 'value'):
        assert '<option value="%s"' % mode in html, mode


def test_the_failed_load_path_keeps_the_file_picker():
    js = cards_js()
    assert 'function showLoadError(err)' in js
    assert "input.type = 'file';" in js and "input.accept = '.json,application/json';" in js
    assert 'Run scripts/mod_cards.py, then reload.' in js
    assert 'box.title = ' in js, 'the failed sources are one hover away, not a paragraph'
