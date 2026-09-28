"""Stage 2 (2026-09-28): every feature is still reachable from the new primary navigation.

Jay's brief: "primary nav becomes Home, Trade, Inventory, Collection; separated lower in the
sidebar: Tools, Settings. Remove Mastery, Player and More from primary navigation - do not delete
their features. Re-home them properly."

The site is static, so these are source-level contracts on the shipped files. The same properties
are measured in a real browser by design/_stage2/qa_ia.js (the rail on every page, a click-through
of every Tools workspace, the mastery tab, the legacy hashes, and the rendered id union
against design/_stage1/ids_before.json - 0 missing). Reachability is pinned here so a later edit
cannot quietly orphan a feature:

  * the rail is exactly the six destinations, in order, in two groups;
  * every Tools slug in app.js's TOOL_SLUGS has a launcher entry AND a workspace in index.html;
  * all twelve list ids that lived on the old More page are still rendered by their workspace,
    and the Clan Dojo card that stage 5 moved off Inventory renders in the `dojo` workspace;
  * Mastery is a tab of collection.html's section row, with its ids and its renderer;
  * the Player profile is the `player` workspace (pc* ids) reached from the launcher;
  * the legacy hashes resolve (#more/#market -> tools, #player -> tools/player,
    #mastery -> collection.html#mastery, #history/#trader -> trade);
  * no id from the stage 1 snapshot disappeared (one sanctioned rename: view-more -> view-tools);
  * the Trade engine internals stay one click from the Sell surface (stage 4's Advanced tab).
"""
import json
import os
import re

import pytest

from conftest import REPO, rail_rows, read_static, shell_js

STATIC = os.path.join(REPO, 'static')
INDEX = read_static('index.html')
COLLECTION = read_static('collection.html')
APP_JS = read_static('app.js')
COLLECTION_JS = read_static('collection.js')
SHELL = shell_js()

# slug -> the list (or card) ids its workspace owns. The old More page's four groups, split into
# the launcher's three, plus the moved player profile. tests/test_density_views.py measures the
# row budgets of the same ids.
WORKSPACES = [
    ('deals', ['dealsList']),
    ('trends', ['moversList', 'trendsList']),          # merged: movers + demand trends
    ('rivens', ['rivensList']),
    ('wl', ['wlList']),
    ('ducats', ['ducatsList']),
    ('craft', ['craftList']),
    ('relicev', ['relicsList']),
    ('sets', ['setsList', 'nudgesList']),              # merged: completion + near misses
    ('baro', ['baroList']),
    ('meta', ['metaList']),
    ('news', ['newsList']),                            # moved off Home in stage 3 (its old card id)
    ('player', ['pcHead', 'pcStats', 'pcTop', 'pcSyn', 'pcInt', 'pcFocus', 'pcMarket', 'pcClan']),
    ('dojo', ['dojoTbl', 'dojoRows']),                 # moved off Inventory in stage 5
]
SLUGS = [slug for slug, _lists in WORKSPACES]
GROUPS = {'Trading': ['deals', 'trends', 'rivens', 'wl'],
          'Planning': ['ducats', 'craft', 'relicev', 'sets'],
          'Warframe': ['baro', 'meta', 'news', 'player', 'dojo']}


def tool_slugs_from_app():
    return re.search(r'const TOOL_SLUGS = \[(.*?)\];', APP_JS, re.S).group(1)


def launcher_block():
    return INDEX.split('id="toolsLauncher"', 1)[1].split('id="toolsWs"', 1)[0]


def workspaces():
    """slug -> the workspace's own markup, from its wrapper tag up to the next workspace."""
    ws = INDEX.split('id="toolsWs"', 1)[1]
    out = {}
    for chunk in ws.split('<div class="tws hidden" id=')[1:]:
        slug = re.search(r'data-tool="([a-z]+)"', chunk).group(1)
        out[slug] = '<div class="tws hidden" id=' + chunk
    return out


def workspace_block(slug):
    block = workspaces()
    assert slug in block, (slug, sorted(block))
    return block[slug]


# ------------------------------------------------------------------ the rail itself

def test_the_rail_is_exactly_six_destinations_in_order():
    rows = rail_rows()
    assert [(r[0], r[1], r[3]) for r in rows] == [
        ('home', '#home', 'Home'),
        ('trade', '#trade', 'Trade'),
        ('inventory', '#inventory', 'Inventory'),
        ('collection', '/collection.html', 'Collection'),
        ('tools', '#tools', 'Tools'),
        ('settings', '/settings.html', 'Settings'),
    ]
    # every pill keeps the stage 1 conventions: data-v (app.js routes on it), data-icon, .navpill
    assert "data-v=\"' + v + '\"" in SHELL and 'data-icon="' in SHELL
    assert "'<nav class=\"mainnav sidenav\" id=\"mainnav\" aria-label=\"Primary\">'" in SHELL


def test_the_rail_is_two_groups_primary_then_secondary():
    groups = SHELL.split('var RAIL_GROUPS = [', 1)[1].split('];', 1)[0]
    assert "['home', 'trade', 'inventory', 'collection']," in groups
    assert "['tools', 'settings']," in groups
    # the second group is marked so shell.css holds it under a gap + hairline - and only its
    # first pill carries the mark (a second hairline under Tools would cut Settings loose again)
    assert 'secOpener' in SHELL and 'sec = v === secOpener;' in SHELL
    assert '.navsec' in read_static('shell.css')
    css = read_static('shell.css')
    assert '.side .navpill.navsec { margin-top: 18px; }' in css
    assert '.side .navpill.navsec::before {' in css
    # and the fold still turns the rail into a row without a gap
    fold = css.split('@media (max-width: 900px)', 1)[1]
    assert '.side .navpill.navsec { margin-top: 0; }' in fold
    assert '.side .navpill.navsec::before { display: none; }' in fold


def test_mastery_player_and_more_are_not_primary_destinations():
    keys = [r[0] for r in rail_rows()]
    hrefs = [r[1] for r in rail_rows()]
    for gone in ('mastery', 'player', 'more'):
        assert gone not in keys, gone
    for gone in ('#mastery', '#player', '#more'):
        assert gone not in hrefs, gone
    # their features are sections now, not pills - the homes are pinned below
    assert 'href="#tools/player"' in INDEX
    assert 'id="view-mastery"' in COLLECTION


def test_the_spa_router_keeps_aria_current_on_the_active_pill():
    """Audit M1 (2026-09-28): on the SPA the rail's .active followed the router while
    aria-current="page" stayed on Home - shell.js writes it once, at mount, and showView() only
    toggled .active. showView() now writes both from the same fact (trade / inventory / tools and
    the workspace hashes all route through it), so the announcement can never disagree with the
    painted pill. The multi-document pages keep the shell's mount-time mark, and their own subnav
    setters move it the same way (collection.js / settings.js)."""
    block = APP_JS.split('function showView(v, sub) {', 1)[1].split('if (window.PlatChart)', 1)[0]
    assert "document.querySelectorAll('#mainnav .navpill')" in block
    assert "const on = el2.dataset.v === v;" in block
    assert "el2.classList.toggle('active', on);" in block
    assert "if (on) el2.setAttribute('aria-current', 'page');" in block
    assert 'else el2.removeAttribute(\'aria-current\');' in block
    # one entry point: the initial route AND every hash change go through showView()
    assert 'applyHash();' in APP_JS and "window.addEventListener('hashchange', applyHash);" in APP_JS
    # the static pages are the shell's job, and they keep their own setters
    assert 'aria-current="page"' in SHELL
    assert "setAttribute('aria-current', 'page')" in read_static('collection.js')
    assert "setAttribute('aria-current', 'page')" in read_static('settings.js')


def test_settings_is_reachable_from_the_rail_and_links_back():
    assert ('settings', '/settings.html', 'Settings') in [(r[0], r[1], r[3]) for r in rail_rows()]
    assert "active: 'settings'" in SHELL.split('settings: {', 1)[1].split('},', 1)[0]
    settings = read_static('settings.html')
    assert 'href="/#tools" class="navpill"' in settings
    assert 'shell.js' in settings and 'data-shell="settings"' in settings


# ------------------------------------------------------------------ the Tools launcher

def test_every_tool_slug_has_a_launcher_entry_and_a_workspace():
    slugs = re.findall(r"'([a-z]+)'", tool_slugs_from_app())
    assert slugs == SLUGS, slugs
    launcher, ws = launcher_block(), INDEX.split('id="toolsWs"', 1)[1]
    for slug in SLUGS:
        assert 'class="tool" href="#tools/%s" data-tool="%s"' % (slug, slug) in launcher, slug
        assert 'class="tws hidden" id="' in ws, 'every workspace starts hidden'
        assert 'data-tool="%s"' % slug in ws, slug
    assert INDEX.count('data-tool="player"') == 2, 'launcher entry + workspace wrapper'
    assert INDEX.count('data-tool="dojo"') == 2, 'launcher entry + workspace wrapper (stage 5)'
    assert 'id="tws-player"' not in INDEX, 'the player workspace keeps the moved #view-player id'


def test_the_launcher_groups_the_tools_trading_planning_warframe():
    launcher = launcher_block()
    heads = re.findall(r'<div class="tl-ghead"[^>]*>([A-Za-z]+)</div>', launcher)
    assert heads == list(GROUPS), heads
    for group, slugs in GROUPS.items():
        chunk = launcher.split('>%s</div>' % group, 1)[1].split('tl-group', 1)[0]
        assert re.findall(r'data-tool="([a-z]+)"', chunk) == slugs, group
    # 13 entries in three groups, and the launcher is a list, not a wall of live lists: no data
    # list renders up here (they are all inside the workspaces below)
    assert launcher.count('class="tool"') == len(SLUGS)
    assert 'id="dojoCard"' not in launcher, 'the launcher entry links the dojo - the card stays in its workspace'
    for _slug, lists in WORKSPACES:
        for list_id in lists:
            assert 'id="%s"' % list_id not in launcher, list_id


def test_the_workspaces_are_one_at_a_time_not_all_at_once():
    """The default is the launcher; opening a tool hides it and shows exactly that workspace."""
    for frag in ("launcher.classList.toggle('hidden', !!slug)",
                 "el.classList.toggle('hidden', s !== slug)",
                 "if (slug === 'player') renderPlayerPage()"):
        assert frag in APP_JS, frag
    assert "if (v === 'tools') showTool(sub || '')" in APP_JS
    section = INDEX.split('id="view-tools"', 1)[1]
    assert section.count('class="tws hidden"') >= len(SLUGS), 'each workspace ships hidden'
    assert 'id="toolsLauncher"' in section, 'the launcher is the default surface'


def test_every_tool_list_id_is_still_rendered_by_its_workspace():
    for slug, lists in WORKSPACES:
        block = workspace_block(slug)
        for list_id in lists:
            assert 'id="%s"' % list_id in block, (slug, list_id)
    # stage 5: the Clan Dojo ids travelled with the card - inside #tws-dojo, out of Inventory
    inv = INDEX.split('id="view-inventory"', 1)[1].split('</section>', 1)[0]
    for dojo_id in ('dojoCard', 'dojoTitle', 'dojoMeta', 'dojoTier', 'dojoTbl', 'dojoRows',
                    'dojoNote', 'dojoRooms', 'dojoRoomsMeta', 'dojoRoomsList', 'dojoSrc'):
        assert 'id="%s"' % dojo_id not in inv, dojo_id
        assert 'id="%s"' % dojo_id in workspace_block('dojo'), dojo_id
    # and each workspace has its own way back to the launcher
    assert INDEX.count('class="tws-back" href="#tools"') == len(SLUGS)


def test_the_merged_workspaces_carry_both_lists():
    trends = workspace_block('trends')
    assert 'id="moversList"' in trends and 'id="trendsList"' in trends
    assert 'Movers' in trends and 'Demand trends' in trends
    sets = workspace_block('sets')
    assert 'id="setsList"' in sets and 'id="nudgesList"' in sets
    assert 'Set completion' in sets and 'Almost complete' in sets


def test_the_page_foot_and_setup_links_stay_at_the_launcher_bottom():
    launcher = launcher_block()
    assert 'id="foot"' in INDEX
    assert 'id="setupCard"' in launcher
    for href in ('/settings.html', '/collection.html', '/#search'):
        assert 'href="%s"' % href in launcher, href
    # the foot element itself is the page's own footer, still reachable while the launcher shows
    assert INDEX.index('id="foot"') > INDEX.index('id="toolsWs"')
    # the settings page's own sub-nav points back at the launcher
    settings = read_static('settings.html')
    assert 'href="/#tools" class="navpill"' in settings


# ------------------------------------------------------------------ Mastery -> Collection

def test_mastery_is_a_tab_of_the_collection_section_row():
    """Stage 6: the row is the page's ONE section navigation - four entries, one anatomy (icon +
    label), one active mark, deep-linkable hrefs. It sits inside the page head, under the title
    and the log's counts."""
    row = COLLECTION.split('id="collectionNav"', 1)[1].split('</nav>', 1)[0]
    assert re.findall(r'data-v="([a-z]+)"', row) == ['collection', 'relics', 'mastery', 'cards']
    # same anatomy on all four: one Phosphor mark each, then the label
    assert re.findall(r'data-v="[a-z]+" data-icon="([a-z-]+)"',
                      row) == ['squares-four', 'tray', 'trophy', 'stack']
    assert row.count('class="navpill') == 4
    assert 'href="/collection.html#mastery" class="navpill" data-v="mastery"' in row
    assert 'href="/cards.html" class="navpill" data-v="cards"' in row, 'Cards stays a page'
    for href in ('href="/collection.html" class="navpill active" data-v="collection"',
                 'href="/collection.html#relics" class="navpill" data-v="relics"'):
        assert href in row, href
    assert 'aria-current="page"' in row
    assert ' aria-label="Collection sections"' in row
    # the head carries the page title and the log's counts; the row is the last thing in it
    head = COLLECTION.split('id="overall"', 1)[1].split('</nav>', 1)[0]
    for frag in ('<h1 class="cl-title"', 'id="ovPct"', 'id="ovCount"', 'id="ovBar"', 'id="ovFoot"'):
        assert frag in head, frag
    assert COLLECTION.index('id="overall"') < COLLECTION.index('id="collectionNav"') \
        < COLLECTION.index('</main>')


def test_the_mastery_markup_moved_whole_and_left_nothing_behind():
    assert 'id="view-mastery"' not in INDEX, 'the view left the dashboard'
    section = COLLECTION.split('id="view-mastery"', 1)[1].split('</section>', 1)[0]
    for mh_id in ('mhCard', 'mhMeta', 'mhHead', 'mhStats', 'mhNextCard', 'mhNextMeta',
                  'mhFilters', 'mhNext', 'mhCap', 'mhCatsCard', 'mhCatsMeta', 'mhCats'):
        assert 'id="%s"' % mh_id in section, mh_id
    assert '<section class="cl-mhview hidden" id="view-mastery"' in COLLECTION


def test_the_mastery_renderer_moved_with_it_and_keeps_its_contract():
    """Same endpoint, same ids, same behaviour (filters / categories / cap) - only the file."""
    assert "var MASTERY_SRC = '/api/feature/mastery';" in COLLECTION_JS
    assert 'api/feature/mastery' not in APP_JS, 'the dashboard no longer fetches it'
    for frag in ("document.getElementById('mhHead')", "document.getElementById('mhStats')",
                 "document.getElementById('mhNext')", "document.getElementById('mhCats')",
                 "document.getElementById('mhFilters')", "document.getElementById('mhNextMeta')",
                 "document.getElementById('mhCatsMeta')", "document.getElementById('mhMeta')",
                 'function renderMasteryPage', 'function renderMasteryHead',
                 'function renderMasteryNext', 'MH_FILTERS'):
        assert frag in COLLECTION_JS, frag
    assert "state.mhFilter" in COLLECTION_JS, 'the filter state survives'
    assert "'showing '" in COLLECTION_JS, 'the row cap keeps its caption'
    assert 'mhEmpty' in COLLECTION_JS, 'a missing payload still renders a note, not a blank card'


def test_the_collection_hash_opens_the_mastery_tab():
    js = COLLECTION_JS
    assert 'function sectionFromHash' in js and "raw === 'mastery'" in js
    assert 'paintNav(sectionFromHash())' in js, 'a deep link opens its section on load'
    assert "location.hash = want" in js and "'#' + name" in js
    assert "state.view = 'mastery'" in js
    # the item grid / relic view / mastery panel are mutually exclusive
    for frag in ("function hideMastery", "classList.remove('hidden')",
                 "document.getElementById('grid').classList.add('hidden')"):
        assert frag in js, frag
    css = read_static('collection.css')
    assert '.cl-controls.mh { display: none; }' in css
    assert '#tabs.hidden { display: none; }' in css


# ------------------------------------------------------------------ Player -> Tools

def test_the_player_profile_is_the_tools_player_workspace():
    block = workspace_block('player')
    assert 'id="view-player" data-tool="player"' in block
    for pc_id in ('pcHead', 'pcStats', 'pcTop', 'pcSyn', 'pcInt', 'pcFocus', 'pcMarket', 'pcClan'):
        assert 'id="%s"' % pc_id in block, pc_id
    assert 'href="#tools/player" data-tool="player"' in launcher_block()
    assert "'player'" in tool_slugs_from_app()
    # its renderer stayed in app.js (the tools page IS index.html) and the router calls it
    assert 'function renderPlayerPage' in APP_JS
    assert "'/api/feature/player'" in APP_JS


# ------------------------------------------------------------------ Trade internals (stage 4)

def test_the_trade_internals_are_one_click_from_the_sell_surface():
    """Stage 4 (2026-09-28): Trade is Sell / Buy / History + ONE Safety & advanced tab. This file's
    watch-list item ("Trade engine internals once behind Safety/Advanced - must stay 1 tap from
    Sell") is pinned here: the advanced tab sits in #tradeTabs beside Sell (Orders joined the strip
    ahead of Sell later that day - see tests/test_trade_orders_tab.py), the panel it controls
    holds every internal id, the kill switch and the trade limit are plain cards (the hygiene plan
    keeps the layer's only <details>), and nothing engine-side sits on the Sell surface."""
    trade = INDEX.split('id="view-trade"', 1)[1].split('</section>', 1)[0]
    tabs = trade.split('<nav id="tradeTabs"', 1)[1].split('</nav>', 1)[0]
    assert 'id="tt-advanced"' in tabs and 'aria-controls="tp-advanced"' in tabs, 'one click from Sell'
    adv = trade.split('id="tp-advanced"', 1)[1]
    for internals in ('limMeta', 'limList', 'killMeta', 'btnKill', 'killNote', 'killList',
                      'notifyMeta', 'btnNotify', 'notifyList', 'runqMeta', 'btnRunq', 'runqList',
                      'hygieneAcc', 'hygieneMeta', 'btnHygiene', 'hygieneList'):
        assert 'id="%s"' % internals in adv, internals
    assert adv.count('<details') == 1 and 'id="hygieneAcc"' in adv, \
        'the hygiene plan is the layer\'s only disclosure'
    sell = trade.split('id="tp-sell"', 1)[1].split('id="tp-buy"', 1)[0]
    for gone in ('limList', 'killList', 'notifyList', 'runqList', 'hygieneList', 'hygieneAcc'):
        assert 'id="%s"' % gone not in sell, gone


# ------------------------------------------------------------------ legacy addresses

def test_legacy_hashes_resolve_to_the_new_destinations():
    for alias in ("more: 'tools'", "market: 'tools'", "player: 'tools'", "history: 'trade'",
                  "trader: 'trade'"):
        assert alias in APP_JS, alias
    assert "location.replace('#tools')" in APP_JS               # #more / #market
    assert "location.replace('#tools/player')" in APP_JS        # #player
    assert "location.replace('/collection.html#mastery')" in APP_JS   # #mastery
    assert "if (v === 'collection' || v === 'cards')" in APP_JS, 'the old page hashes still forward'
    # the rail marks the pill the router will show (keep the two tables in step)
    alias_table = SHELL.split('var ALIAS = {', 1)[1].split('};', 1)[0]
    for pair in ("more: 'tools'", "market: 'tools'", "player: 'tools'", "mastery: 'collection'",
                 "history: 'trade'", "trader: 'trade'"):
        assert pair in alias_table, pair


def test_legacy_hashes_cannot_land_blank():
    """"Nothing that resolved before may 404 or land blank": every alias target and every rail
    href names a section that exists (or a page that ships)."""
    views = re.search(r'const VIEWS = \[(.*?)\];', APP_JS, re.S).group(1)
    names = re.findall(r"'([a-z]+)'", views)
    for v in names:
        assert 'id="view-%s"' % v in INDEX, v
    for slug in SLUGS:
        assert 'data-tool="%s"' % slug in INDEX, slug
    for page in ('collection.html', 'cards.html', 'settings.html', 'item.html'):
        assert os.path.isfile(os.path.join(STATIC, page)), page
    for href in ('/collection.html', '/settings.html', '/#search', '#tools'):
        assert href in INDEX or href in SHELL, href


# ------------------------------------------------------------------ nothing lost

pytestmark_optional_snapshot = pytest.mark.skipif(
    not os.path.isfile(os.path.join(REPO, 'design', '_stage1', 'ids_before.json')),
    reason='the stage 1 id snapshot is a design artifact')


@pytestmark_optional_snapshot
def test_no_id_from_the_stage1_snapshot_disappeared():
    """The acceptance criterion, source-level: every id that existed before stage 2 is still in a
    shipped file. One sanctioned rename: the old More view's wrapper became the Tools section
    (#view-more -> #view-tools), because that section is what it is now.

    Stage 3 (Jay 2026-09-28, "make Home a clean action surface with no duplicated values") retired
    four Home ids whose values merged into the one Today strip. Each one is listed here with the
    duplicate it stood for; this is the whole sanctioned removal set, and nothing else may go:
      heroCard   the hero band: platinum now + trades left, both now in #kpis (the strip)
      heroMeta   the hero's date line, a copy of #homeSub (the page header's own date)
      homeSync   the sync state, a copy of #syncState in the header (and the footer line)
      kpiCard    the six-cell grid, merged into #kpis
    The data those ids carried did not leave the app: the six readings are the strip's four cells
    and its detail disclosure, and the sync state still renders in the header + footer.
    """
    with open(os.path.join(REPO, 'design', '_stage1', 'ids_before.json'), encoding='utf-8') as fh:
        before = json.load(fh)
    removed = {'heroCard': 'duplicate of the Today strip (#kpis) + #chartCard',
               'heroMeta': 'duplicate of #homeSub (the page date line)',
               'homeSync': 'duplicate of #syncState (the header clock)',
               'kpiCard': 'merged into the Today strip (#kpis)'}
    wanted = sorted({i for ids in before.values() for i in ids} - set(removed))
    sources = []
    for name in sorted(os.listdir(STATIC)):
        if name.endswith(('.html', '.js', '.css', '.svg')):
            sources.append(os.path.join(STATIC, name))
    sources.append(os.path.join(REPO, 'server.py'))
    blob = '\n'.join(open(p, encoding='utf-8', errors='replace').read() for p in sources)
    renamed = {'view-more': 'view-tools'}
    missing = [i for i in wanted if i not in renamed and
               not re.search(r'id="%s"|\b%s\b' % (re.escape(i), re.escape(i)), blob)]
    assert missing == [], missing
    for gone in removed:
        assert not re.search(r'id="%s"' % re.escape(gone), INDEX), gone
    for old, new in renamed.items():
        assert 'id="%s"' % new in blob, new
