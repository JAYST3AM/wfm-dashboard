"""Stage 5 (Jay 2026-09-28): Inventory is basic info only.

Jay's brief, verbatim intent: "basic inventory info only, no explanations, no advanced clutter.
Inventory should be Items / Materials, with advanced columns behind a progressive-disclosure
control. Inventory changes / diff history should not occupy a permanent card - reachable from a
button or the item drawer. The Clan Dojo card does NOT belong on Inventory - it moves to Tools.
The item drawer stays."

Source-level pins, in the same style as the other stage tests (the same properties are measured in
a real browser by design/_stage5/qa_inventory.js):

  * the subview control is the page's own `#invViews` (two role=tab buttons, data-v=items/material);
    `#tabs` stays the item-category pill row and is NOT repurposed (collection.js styles its own
    `#tabs.hidden` on the collection page);
  * the advanced columns are ONE disclosure - `details.acc.sub#invAdv` in the tablebar holding the
    same `button#btnCols` and the same `body.show-a` contract; basic columns stay on the surface;
  * the changes live in `details.acc.sub#invDiff` (`#diffCard` > `#diffList`), never a permanent
    card, and `renderDiff()` still reaches `#diffMeta`/`#diffList` by id while collapsed;
  * the Clan Dojo card is the Tools workspace `#tws-dojo` (slug `dojo`), all eleven dojo* ids
    intact, launcher entry in the Warframe group, reachable by click and by `#tools/dojo`;
  * the item drawer stays: `#rows` keeps its delegated click handler.
No test reads the repo's data/ folder - everything here is source-level.
"""
import json
import os

from conftest import REPO

STATIC = os.path.join(REPO, 'static')


def read(name):
    with open(os.path.join(STATIC, name), encoding='utf-8') as fh:
        return fh.read()


def inventory_view():
    html = read('index.html')
    return html.split('id="view-inventory"', 1)[1].split('</section>', 1)[0]


def items_panel():
    view = inventory_view()
    return view.split('id="invItems"', 1)[1].split('id="invMaterials"', 1)[0]


def materials_panel():
    return inventory_view().split('id="invMaterials"', 1)[1]


def dojo_workspace():
    return read('index.html').split('id="tws-dojo"', 1)[1].split('</section>', 1)[0]


# ------------------------------------------------------------------ the ids the snapshot names

def test_the_thirty_inventory_ids_still_ship_verbatim():
    """The stage-1 snapshot's inventory ids may not be renamed - stage 5 sanctions none."""
    path = os.path.join(REPO, 'design', '_stage1', 'ids_before.json')
    if not os.path.isfile(path):
        return                                   # the snapshot is a design artifact
    with open(path, encoding='utf-8') as fh:
        before = json.load(fh)
    blob = '\n'.join(read(n) for n in os.listdir(STATIC)
                     if n.endswith(('.html', '.js', '.css')))
    wanted = [i for i in before.get('index', []) if i in (
        'view-inventory', 'tabs', 'totals', 'invQ', 'btnCols', 'tbl', 'rows', 'status',
        'matCard', 'matMeta', 'matQ', 'matView', 'matSort', 'matTbl', 'matHead', 'matRows',
        'matCap', 'dojoCard', 'dojoTitle', 'dojoMeta', 'dojoTier', 'dojoTbl', 'dojoRows',
        'dojoNote', 'dojoRooms', 'dojoRoomsMeta', 'dojoRoomsList', 'dojoSrc', 'diffMeta',
        'diffList')]
    assert len(wanted) == 30, wanted
    missing = [i for i in wanted if 'id="%s"' % i not in blob]
    assert missing == [], missing


# ------------------------------------------------------------------ Items | Materials subviews

def test_the_subview_control_is_the_pages_own_and_not_the_collection_tabs():
    html = read('index.html')
    inv = inventory_view()
    assert ('<nav id="invViews" class="tabs" role="tablist" aria-label="Inventory sections">' in inv)
    assert '<button class="tab active" role="tab" data-v="items" aria-selected="true">Items</button>' in inv
    assert '<button class="tab" role="tab" data-v="materials" aria-selected="false">Materials</button>' in inv
    # #tabs is unchanged (the item-category pills) and comes AFTER the subview row inside Items
    assert '<nav id="tabs" class="tabs" aria-label="Item categories"></nav>' in inv
    assert inv.index('id="invViews"') < inv.index('id="invItems"') < inv.index('id="tabs"')
    # the collection page's own #tabs harness is untouched (stage 2 contract)
    assert "document.getElementById('tabs')" in read('collection.js')


def test_items_is_the_default_panel_and_materials_ships_hidden():
    inv = inventory_view()
    assert '<div id="invItems" role="tabpanel" aria-label="Items">' in inv
    assert '<div id="invMaterials" role="tabpanel" aria-label="Materials" class="hidden">' in inv


def test_the_switch_swaps_the_panels_and_remembers_the_choice():
    js = read('app.js')
    assert "invView: 'items'," in js                                    # shipped default
    assert 'function switchInvView(v) {' in js
    switch = js.split('function switchInvView(v) {', 1)[1].split('\n}', 1)[0]
    assert "document.querySelectorAll('#invViews [role=\"tab\"]')" in switch
    assert "localStorage.setItem('wfm.invView', v)" in switch
    assert "t.setAttribute('aria-selected', String(on))" in switch
    assert "items.classList.toggle('hidden', v !== 'items')" in switch
    assert "mats.classList.toggle('hidden', v !== 'materials')" in switch
    assert "if (localStorage.getItem('wfm.invView') === 'materials') state.invView = 'materials';" in js
    # the router honours a hash sub-path and re-runs the switch on every entry to the view
    assert "if (view === 'inventory') switchInvView(sub || state.invView);" in js
    assert "if (v === 'inventory') switchInvView(state.invView);" in js


# ------------------------------------------------------------------ the one Columns disclosure

def test_the_advanced_columns_are_one_disclosure_over_the_items_table():
    html = read('index.html')
    js = read('app.js')
    items = items_panel()
    assert '<details class="acc sub" id="invAdv">' in items
    adv = items.split('id="invAdv"', 1)[1].split('</details>', 1)[0]
    assert '<summary data-icon="columns">Columns</summary>' in adv
    assert ('<button class="btn" id="btnCols" aria-pressed="false" aria-controls="tbl" '
            'title="Show or hide the advanced columns" data-icon="columns">Show advanced columns</button>') in adv
    # collapsed by default, and the switch lives in the tablebar (never inside the scroller)
    assert '<details class="acc sub" id="invAdv" open' not in items
    assert items.index('id="invAdv"') < items.index('id="tbl"')
    # 10 of the 14 columns are advanced, and the header and the row template hide the same 10
    head = items.split('<thead>', 1)[1].split('</thead>', 1)[0]
    assert head.count('hide-a') == 10, head.count('hide-a')
    for col in ('equipped', 'safe', 'cat', 'ducats', 'wtb', 'spread', 'vol48', 'median', 'reserved'):
        assert 'data-k="%s" class="num hide-a"' % col in head, col
    assert 'class="spark hide-a"' in head                       # Trend
    row = js.split('<tr class="inv-row"', 1)[1].split('</tr>', 1)[0]
    assert row.count('hide-a') == 10, row.count('hide-a')
    assert 'class="spark hide-a"' in row
    assert 'colspan="14"' in js and 'colspan="13"' not in js    # cells stay in the DOM
    # the four basic columns that remain: Item, Qty, Sell price, Value
    for col in ('data-k="name"', 'data-k="count"', 'data-k="wts"', 'data-k="value"'):
        assert col in head, col
    for col in ('class="num hide-a" scope="col" title="Copies slotted in a build - never listed"',):
        assert col in head


def test_the_columns_disclosure_keeps_the_show_a_contract():
    css = read('style.css')
    assert '.hide-a { display: none; }' in css
    assert 'body.show-a .hide-a { display: table-cell; }' in css
    js = read('app.js')
    switch = js.split("const btnCols = document.getElementById('btnCols');", 1)[1].split('});', 1)[0]
    assert "document.body.classList.toggle('show-a')" in switch
    assert "btnCols.setAttribute('aria-pressed', String(on))" in switch
    assert "iconRepaint(btnCols)" in switch


# ------------------------------------------------------------------ changes behind a disclosure

def test_inventory_changes_is_a_disclosure_not_a_permanent_card():
    items = items_panel()
    assert '<details class="acc sub" id="invDiff">' in items
    assert '<summary>Inventory changes <span class="dim small" id="diffMeta"></span></summary>' in items
    assert '<div class="card" id="diffCard">' in items
    assert '<div class="picks" id="diffList"></div>' in items
    # collapsed by default, below the status line, inside the Items subview
    assert '<details class="acc sub" id="invDiff" open' not in items
    assert items.index('id="status"') < items.index('id="invDiff"') < items.index('id="diffList"')
    # the renderer is untouched: it still reaches both ids by getElementById
    js = read('app.js')
    render = js.split('function renderDiff() {', 1)[1].split('\n}', 1)[0]
    assert "document.getElementById('diffList')" in render
    assert "document.getElementById('diffMeta')" in render
    # one fetch, on the shared feature fan-out, still read as FEAT.invdiff
    assert "'invdiff'" in js and js.count("FEAT.invdiff") >= 1
    assert js.count("'/api/feature/invdiff'") == 0, 'no second fetch site was added'


# ------------------------------------------------------------------ the dojo moved to Tools

def test_the_clan_dojo_is_the_tools_dojo_workspace():
    html = read('index.html')
    ws = dojo_workspace()
    assert '<div class="tws hidden" id="tws-dojo" data-tool="dojo" role="region" aria-label="Clan Dojo">' in html
    assert '<a class="tws-back" href="#tools" data-icon="arrow-left">All tools</a>' in ws
    assert '<span class="tws-name">Clan Dojo</span>' in ws
    for dojo_id in ('dojoCard', 'dojoTitle', 'dojoMeta', 'dojoTier', 'dojoTbl', 'dojoRows',
                    'dojoNote', 'dojoRooms', 'dojoRoomsMeta', 'dojoRoomsList', 'dojoSrc'):
        assert 'id="%s"' % dojo_id in ws, dojo_id
        assert 'id="%s"' % dojo_id not in inventory_view(), dojo_id
    # the launcher entry: the Warframe group, last, with the card's own icon and a short sub
    launcher = html.split('id="toolsLauncher"', 1)[1].split('id="toolsWs"', 1)[0]
    assert ('<a class="tool" href="#tools/dojo" data-tool="dojo">' in launcher)
    assert '<span class="tool-name" data-icon="castle-turret">Clan Dojo</span>' in launcher
    warframe = launcher.split('>Warframe</div>', 1)[1]
    assert warframe.index('data-tool="player"') < warframe.index('data-tool="dojo"')
    assert launcher.count('class="tool"') == 13
    # the renderer moved with the markup - no change to renderDojo/paintDojoTier
    js = read('app.js')
    assert "'baro', 'meta', 'news', 'player', 'dojo'];" in js
    assert 'function renderDojo() {' in js and 'const paintDojoTier = () => {' in js
    assert "if (slug === 'dojo') markScrollers();" in js


# ------------------------------------------------------------------ scroller cues + the drawer

def test_a_panel_becoming_visible_remeasures_its_scroller_cue():
    """A hidden panel measures 0: the switch and the dojo workspace re-run markScrollers(), or the
    soft bottom edge appears only after a resize."""
    js = read('app.js')
    switch = js.split('function switchInvView(v) {', 1)[1].split('\n}', 1)[0]
    assert 'markScrollers();' in switch
    show = js.split('function showView(v, sub) {', 1)[1].split('\n}', 1)[0]
    assert "if (v === 'inventory') switchInvView(state.invView);" in show
    tool = js.split('function showTool(slug) {', 1)[1].split('\n}', 1)[0]
    assert "if (slug === 'dojo') markScrollers();" in tool
    assert 'function markScrollers()' in js


def test_the_item_drawer_still_opens_from_a_row():
    js = read('app.js')
    handler = js.split("document.getElementById('rows').addEventListener('click'", 1)[1].split('});', 1)[0]
    assert "closest('tr.inv-row')" in handler
    assert 'wfmOpenItem(tr.dataset.slug)' in handler
    # the row anatomy the handler reads is unchanged: one tr.inv-row[data-slug] per stack
    row = js.split('<tr class="inv-row"', 1)[1].split('>', 1)[0]
    assert 'data-slug="${escHtml(r.slug)}"' in row
