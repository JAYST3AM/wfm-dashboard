"""PLAYER page (#player): nav slot, view section, loader, payload contract, copy budget.

A sibling script writes data/player.json; the page reads it through the read-only
/api/feature/player route. Nothing here reads the repo's data/ folder - the server_mod
fixture points DATA at tmp_path and the fixtures below are the page's own stand-in.

Contracts kept here (source-level, like tests/test_redesign_ia.py):
  * the Player pill sits between Collection and More and is the fifth hash view;
  * #player opens the section through the same VIEWS / VIEW_ALIAS path as the others;
  * the payload is fetched once and cached on state - no polling, no second request;
  * every number the page prints goes through pnum(), so a missing field is a dash;
  * >60 chars of user copy must sit in an element marked .explain (Advanced switch).
"""
import os
import re

from conftest import REPO, write_json

STATIC = os.path.join(REPO, 'static')

PLAYER = {
    'schema': 1, 'updated': 1758800000, 'updated_iso': '2026-09-26T02:00:00Z', 'alias': 'Tenno',
    'mastery': {'rank': 30, 'items_tracked': 612,
                'top_items': [{'name': 'Kuva Bramma', 'xp': 2400000}, {'name': None, 'xp': 1}]},
    'clan': {'id': 'abcdef0123456789', 'name_source': 'config', 'research_blueprints': 411,
             'vault_bonus': {'progress': 399, 'week_count': 658}},
    'syndicates': [{'tag': 'SM', 'name': 'Steel Meridian', 'standing': -22000, 'title': 5, 'next_at': None},
                   {'tag': 'SU', 'name': 'Cephalon Suda', 'standing': 132000, 'title': 3, 'next_at': 132000}],
    'intrinsics': {'railjack': {'pilotting': 5, 'gunnery': 4, 'engineering': 3, 'tactical': 2,
                                'command': 1, 'xp': 111213},
                   'drifter': {'riding': 5, 'combat': 5, 'opportunity': 4, 'xp': 22222}},
    'focus': [{'tag': 'ZEN', 'name': 'Zenurik', 'xp': 1234567},
              {'tag': 'MAD', 'name': 'Madurai', 'xp': 76543}],
    'stats': {'achievements_tracked': 137, 'last_region': 'Cambion Drift', 'items_tracked': 612,
              'railjack_owned': True, 'necramech_owned': False, 'daily_focus': 26000},
}


def read(name, root=STATIC):
    with open(os.path.join(root, name), encoding='utf-8') as fh:
        return fh.read()


def nav_block():
    return read('index.html').split('id="mainnav"', 1)[1].split('</nav>', 1)[0]


def player_section():
    return read('index.html').split('id="view-player"', 1)[1].split('</section>', 1)[0]


def player_js():
    js = read('app.js')
    start = js.index('/* ---------- player page')
    end = js.index('/* ---------- /player page ---------- */')
    return js[start:end]


# ------------------------------------------------------------------ nav + view shell

def test_player_pill_sits_between_collection_and_more():
    nav = nav_block()
    collection, player, more = (nav.index('data-v="collection"'),
                                nav.index('data-v="player"'),
                                nav.index('data-v="more"'))
    assert collection < player < more
    pill = re.search(r'<a\b[^>]*data-v="player"[^>]*>([^<]+)</a>', nav)
    assert pill, 'no Player pill in the primary nav'
    assert pill.group(1) == 'Player'
    assert 'href="#player"' in pill.group(0)


def test_the_original_pills_survive_and_collection_stays_a_page():
    nav = nav_block()
    for href in ('#home', '#inventory', '#trade', '#more'):
        assert 'href="%s"' % href in nav, href
    assert 'href="/collection.html" class="navpill" data-v="collection"' in nav
    assert 'href="#collection"' not in nav                    # still a sub-page, not a view


def test_player_view_section_exists_and_is_hidden_by_default():
    html = read('index.html')
    assert 'id="view-player" class="hidden"' in html
    section = player_section()
    for node in ('pcHead', 'pcStats', 'pcTop', 'pcClan', 'pcSyn', 'pcInt', 'pcFocus', 'pcMarket'):
        assert 'id="%s"' % node in section, node
    assert section.count('class="card"') >= 6                 # player, clan, syndicates, intrinsics, focus, market


def test_every_container_the_page_renders_into_exists_in_the_markup():
    section = player_section()
    js = player_js()
    for node in re.findall(r'id="([^"]+)"', section):
        assert node in js, node


# ------------------------------------------------------------------ hash routing + loader

def test_player_hash_routes_like_the_other_views():
    js = read('app.js')
    views = re.search(r'const VIEWS = \[([^\]]*)\]', js).group(1)
    assert "'player'" in views, 'showView() must accept the player view'
    alias = re.search(r'const VIEW_ALIAS = \{(.*?)\};', js, re.S).group(1)
    assert "player: 'player'" in alias, '#player must resolve through VIEW_ALIAS'
    router = js.split('function applyHash()', 1)[1].split('\n}', 1)[0]
    assert 'VIEW_ALIAS[v]' in router and 'showView(view)' in router
    show = js.split('function showView(v) {', 1)[1].split('\n}', 1)[0]
    assert "v === 'player'" in show and 'renderPlayerPage()' in show


def test_loader_fetches_the_player_feature_once_and_caches_it():
    js = read('app.js')
    assert js.count('/api/feature/player') == 1, 'one fetch site - the page must not poll'
    block = player_js()
    assert "fetch('/api/feature/player')" in block
    loader = block.split('function loadPlayer()', 1)[1].split('\n}', 1)[0]
    assert 'state.player' in loader, 'the payload is cached on state'
    assert block.count('state.player') >= 2
    assert ".catch(() => ({}))" in loader                     # a dead endpoint renders dashes
    assert '!Array.isArray(j)' in loader                      # a non-object payload degrades too


def test_the_clan_card_writes_the_name_through_the_config_route():
    block = player_js()
    assert "fetch('/api/config'" in block
    assert "JSON.stringify({ pairs: { clan_name: name } })" in block
    assert 'id="pcClanName"' in block and "for=\"pcClanName\"" in block   # labelled inline input
    assert '>Dojo materials →</a>' in block and 'href="#inventory"' in block


# ------------------------------------------------------------------ payload contract

def test_player_feature_is_registered_on_the_read_only_route():
    src = read('server.py', REPO)
    assert "'player': 'player.json'," in src
    assert 'if name in FEATURES:' in src                      # the generic /api/feature/<name> branch


def test_player_payload_passes_through_with_every_schema_key(server_mod, data_dir):
    write_json(data_dir / server_mod.FEATURES['player'], PLAYER)

    payload = server_mod.feature_payload('player')

    assert payload == PLAYER                                 # read-only store, shipped as-is
    for key in ('schema', 'updated', 'updated_iso', 'alias', 'mastery', 'clan',
                'syndicates', 'intrinsics', 'focus', 'stats'):
        assert key in payload, key
    assert {'rank', 'items_tracked', 'top_items'} <= set(payload['mastery'])
    assert {'id', 'name_source', 'research_blueprints', 'vault_bonus'} <= set(payload['clan'])
    assert {'progress', 'week_count'} <= set(payload['clan']['vault_bonus'])
    assert {'tag', 'name', 'standing', 'title', 'next_at'} <= set(payload['syndicates'][0])
    assert {'railjack', 'drifter'} <= set(payload['intrinsics'])
    assert {'pilotting', 'gunnery', 'engineering', 'tactical', 'command', 'xp'} <= set(payload['intrinsics']['railjack'])
    assert {'riding', 'combat', 'opportunity', 'xp'} <= set(payload['intrinsics']['drifter'])
    assert {'tag', 'name', 'xp'} <= set(payload['focus'][0])
    assert {'achievements_tracked', 'last_region', 'items_tracked', 'railjack_owned',
            'necramech_owned', 'daily_focus'} <= set(payload['stats'])


def test_the_page_reads_the_keys_the_payload_ships():
    """The renderers stay in step with data/player.json (the version marker 'schema' is the
    payload test's business - the page ignores keys it does not know)."""
    block = player_js()
    for key in ('alias', 'mastery', 'rank', 'items_tracked', 'top_items', 'clan',
                'research_blueprints', 'vault_bonus', 'progress', 'week_count', 'syndicates',
                'standing', 'next_at', 'title', 'intrinsics', 'railjack', 'drifter',
                'pilotting', 'gunnery', 'engineering', 'tactical', 'command', 'riding',
                'combat', 'opportunity', 'focus', 'achievements_tracked', 'last_region',
                'railjack_owned', 'necramech_owned', 'daily_focus'):
        assert key in block, key


def test_missing_file_answers_an_empty_object(server_mod, data_dir):
    """data/player.json does not exist yet - the route still answers 200 with this body."""
    assert not os.path.exists(os.path.join(str(data_dir), 'player.json'))

    payload = server_mod.feature_payload('player')

    assert payload == {} and isinstance(payload, dict)


def test_corrupt_or_non_object_files_degrade_instead_of_raising(server_mod, data_dir):
    path = os.path.join(str(data_dir), 'player.json')
    for blob in ('{ not json at all', '[]', '"a string"', 'null', ''):
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(blob)
        payload = server_mod.feature_payload('player')
        assert isinstance(payload, dict), blob
        assert payload == {}, blob


def test_missing_pieces_render_a_dash_and_the_market_card_skips_absent_keys():
    block = player_js()
    assert block.count("'—'") >= 4                            # pnum/pyes/pcVal dash fallbacks
    assert 'Object.keys(M)' in block                          # market rows come from the payload
    for word in ('undefined', 'NaN', 'nan'):
        assert ("'" + word + "'") not in block, word
        assert ('"' + word + '"') not in block, word
    assert 'function pnum(v)' in block and 'function pcVal(v)' in block
    assert block.count('Number.isFinite') >= 4                 # non-numbers never reach toLocaleString


# ------------------------------------------------------------------ copy budget
TECHY = ('#', '/', 'http', 'data:', 'url', '.', 'function', 'var(', 'px ', 'cubic-bezier')
ALLOWED = re.compile(r"^[\w\s.,!?%:;—’“”'+\-()×·→]+$")


def visible_strings(src):
    """Quoted strings a user could read - the same filter tests/test_ui_polish.py applies."""
    for m in re.finditer(r"['\"]([^'\"\n]{60,})['\"]", src):
        s = m.group(1)
        if s.startswith(TECHY) or 'function' in s or '{' in s or ';' in s or '\\u25' in s:
            continue
        if ALLOWED.match(s) is None:
            continue
        yield s


def test_no_player_copy_over_a_hundred_chars():
    for name, src in (('index.html', player_section()), ('app.js', player_js())):
        for s in visible_strings(src):
            assert len(s) <= 100, (name, len(s), s)


def test_long_copy_lives_in_an_explanation():
    """>60 chars of user copy is an explanation: it must sit inside class="explain"."""
    for name, src in (('index.html', player_section()), ('app.js', player_js())):
        for m in re.finditer(r"['\"]([^'\"\n]{61,})['\"]", src):
            s = m.group(1)
            if s.startswith(TECHY) or ALLOWED.match(s) is None:
                continue
            line = src[src.rfind('\n', 0, m.start()) + 1: src.find('\n', m.start())]
            assert 'explain' in line, (name, s[:60])


def test_the_page_is_labels_and_values_only():
    """No explainer sentences in the markup: every static line is a short label or value."""
    for line in player_section().splitlines():
        text = re.sub(r'<[^>]+>', ' ', line)
        text = re.sub(r'&[a-z]+;', ' ', text).strip()
        assert len(text.split()) <= 5, line.strip()
