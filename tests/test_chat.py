"""Chat dock (HOME, right side) - local store first, relay second.

Jay (2026-09-27): *"add a chat that snaps to the right of the home page. look into getting it so
other people can chat with their profiles active."*

These tests pin the server contract (POST /api/chat -> data/chat.json, GET /api/chat -> rows +
relay + your own profile stamp), the honesty rules (the stamp is capped and never invented, a
relayed message keeps the relay's own id so it appears once), and the wiring: home.js loads the
dock, the dock is local-first and posts to /api/chat before anything else.
"""
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(REPO, rel), encoding='utf-8') as fh:
        return fh.read()


def fresh(mod):
    mod._chat_last[0] = 0.0
    return mod


# ------------------------------------------------------------------ the store

def test_a_message_is_stored_and_read_back(server_mod):
    fresh(server_mod)
    code, out = server_mod.chat_post({'name': 'SampleTennoIX', 'mr': 22}, 'gg, thanks for the run')
    assert code == 200 and out['ok'] is True
    rows = server_mod.chat_rows()
    assert len(rows) == 1
    assert rows[0]['text'] == 'gg, thanks for the run'
    assert rows[0]['who'] == {'name': 'SampleTennoIX', 'mr': 22}
    assert isinstance(rows[0]['id'], int) and isinstance(rows[0]['ts'], int)
    # it is a real file next to the other stores, not process memory
    assert os.path.exists(os.path.join(server_mod.DATA, 'chat.json'))


def test_text_is_collapsed_and_capped(server_mod):
    fresh(server_mod)
    _, out = server_mod.chat_post({'name': 'a'}, '  line one \n\t line  two  ')
    assert out['row']['text'] == 'line one line two'
    server_mod._chat_last[0] = 0.0                      # the post gap is not what this test is about
    _, out = server_mod.chat_post({'name': 'a'}, 'x' * 900)
    assert len(out['row']['text']) == 500


def test_empty_and_junk_posts_are_refused(server_mod):
    fresh(server_mod)
    for bad in ('', '   ', '\n\t', None):
        code, out = server_mod.chat_post({'name': 'a'}, bad)
        assert code == 400 and out['ok'] is False, repr(bad)
    assert server_mod.chat_rows() == []


def test_the_post_gap_stops_a_flood(server_mod):
    fresh(server_mod)
    assert server_mod.chat_post({'name': 'a'}, 'one')[0] == 200
    code, out = server_mod.chat_post({'name': 'a'}, 'two')
    assert code == 429 and 'one message at a time' in out['error']
    server_mod._chat_last[0] = 0.0                       # the gap elapses
    assert server_mod.chat_post({'name': 'a'}, 'three')[0] == 200
    assert len(server_mod.chat_rows()) == 2


# ------------------------------------------------------------------ the profile stamp

def test_the_stamp_is_capped_and_never_invented(server_mod):
    fresh(server_mod)
    _, out = server_mod.chat_post(
        {'name': 'n' * 80, 'mr': '22', 'platform': 'p' * 40, 'clan': 'c' * 40,
         'nonsense': 'x', 'level': 5}, 'hi')
    who = out['row']['who']
    assert len(who['name']) == 24 and len(who['platform']) == 12 and len(who['clan']) == 24
    assert who['mr'] == 22, 'a numeric string still lands as a number'
    assert set(who) == {'name', 'mr', 'platform', 'clan'}, 'only known fields survive'


def test_junk_stamps_are_dropped_not_faked(server_mod):
    fresh(server_mod)
    for bad in (None, 'not-a-dict', 42, []):
        server_mod._chat_last[0] = 0.0
        code, out = server_mod.chat_post(bad, 'hi ' + str(bad))
        assert code == 200 and out['row']['who'] == {}, repr(bad)
    fresh(server_mod)
    _, out = server_mod.chat_post({'name': '   ', 'mr': True, 'platform': ''}, 'hi')
    assert out['row']['who'] == {}, 'blank strings and booleans are not a profile'


def test_a_relayed_message_keeps_the_rooms_id(server_mod):
    fresh(server_mod)
    _, out = server_mod.chat_post({'name': 'mate', 'id': 1790493000123}, 'from the room')
    assert out['row']['id'] == 1790493000123, 'so it cannot show twice (local + relay)'
    fresh(server_mod)
    _, out = server_mod.chat_post({'name': 'mate', 'id': 'nope'}, 'local only')
    assert out['row']['id'] != 'nope' and isinstance(out['row']['id'], int)


def test_the_store_is_capped(server_mod):
    for i in range(server_mod.CHAT_CAP + 5):
        server_mod._chat_last[0] = 0.0
        server_mod.chat_post({'name': 'a'}, 'msg %d' % i)
    rows = server_mod.chat_rows()
    assert len(rows) == server_mod.CHAT_CAP
    assert rows[-1]['text'] == 'msg %d' % (server_mod.CHAT_CAP + 4)
    assert rows[0]['text'] == 'msg 5', 'the oldest rows are the ones dropped'


# ------------------------------------------------------------------ payload + relay

def test_payload_carries_rows_relay_and_my_profile(server_mod, monkeypatch):
    import json
    import types
    fresh(server_mod)
    server_mod.chat_post({'name': 'me'}, 'hello')
    with open(os.path.join(server_mod.DATA, 'player.json'), 'w', encoding='utf-8') as fh:
        json.dump({'alias': 'SampleTennoIX', 'platform': 'pc'}, fh)
    with open(os.path.join(server_mod.DATA, 'mastery.json'), 'w', encoding='utf-8') as fh:
        json.dump({'mr': {'rank': 22}}, fh)
    monkeypatch.setattr(server_mod, '_dashcfg',
                        types.SimpleNamespace(read=lambda: {'chat_relay_url': 'https://room.example.workers.dev'}))
    p = server_mod.chat_payload()
    assert p['relay'] == 'https://room.example.workers.dev' and p['cap'] == server_mod.CHAT_CAP
    assert p['count'] == 1 and len(p['rows']) == 1
    assert p['me'] == {'name': 'SampleTennoIX', 'mr': 22, 'platform': 'pc'}


def test_no_relay_configured_means_local_only(server_mod):
    import types
    for stub in (types.SimpleNamespace(read=lambda: {}),
                 types.SimpleNamespace(read=lambda: {'chat_relay_url': '  '}),
                 types.SimpleNamespace(read=lambda: (_ for _ in ()).throw(OSError('boom'))),
                 None):
        server_mod._dashcfg = stub
        assert server_mod.chat_payload()['relay'] == '', repr(stub)


def test_a_broken_save_never_becomes_a_name(server_mod):
    import json
    with open(os.path.join(server_mod.DATA, 'player.json'), 'w', encoding='utf-8') as fh:
        json.dump({'alias': 'signin failed: warframe.market is showing a Cloudflare browser check'}, fh)
    assert server_mod.chat_me()['name'] == '', 'an error string is not an identity'


# ------------------------------------------------------------------ wiring pins

def test_the_routes_and_the_dock_are_wired():
    src = read('server.py')
    assert "if p == '/api/chat': return self._send(200, chat_payload())" in src
    assert re.search(r"if p == '/api/chat':\s*\n\s*ln = int\(self\.headers\.get\('Content-Length'\)", src)
    assert 'def chat_post(who, text):' in src and 'def chat_rows():' in src
    home = read('static/home.js')
    assert "s.src = '/chat.js'" in home and "l.href = '/chat.css'" in home
    assert 'chat_relay_url' in read('scripts/config.py')


def test_the_dock_is_local_first_and_html_safe():
    js = read('static/chat.js')
    assert "jpost('/api/chat'" in js, 'the local store is written before anything else'
    assert 'relay' in js and '/messages?since=' in js, 'the room is pulled by id'
    assert 'innerHTML' not in js, 'rows are built with createElement/textContent'
    assert 'view.hidden' in js, 'no polling while another view is open'


def test_the_dock_layout_matches_the_house_breakpoints():
    css = read('static/chat.css')
    assert '#view-home.chat-docked' in css and 'grid-template-columns' in css
    assert '(min-width: 1500px)' in css and '(min-width: 1200px)' in css and '(max-width: 540px)' in css
    assert 'position: sticky' in css
    assert 'var(--mono)' in css and 'tabular-nums' in css, 'matches the app palette + numerals'


def test_the_rail_runs_to_the_bottom_of_the_viewport():
    """Jay: "the chat isn't going down to the bottom of the screen its only taking the top bit" /
    "chat can go all the way down". A max-height alone left the dock at content height, so the dock
    carries no cap and chat.js measures its own top and fills to the bottom edge (verified at
    1920/1600/1536/1440/1366/1280: 12px below every viewport, list fills, input on the bottom
    edge; under 1200px it is a normal block again)."""
    css = read('static/chat.css')
    js = read('static/chat.js')
    assert 'max-height: calc(100vh - 240px)' not in css, 'the old cap is gone'
    assert "s.style.height" not in css
    assert 'function fit()' in js and "dock.style.height = Math.max(280" in js
    assert 'window.innerWidth < 1200' in js, 'stacked layout clears the measured height'
    assert '[0, 400, 1200, 3000].forEach(function (ms) { setTimeout(fit, ms); })' in js, \
        'the header grows after load (sync status, wrapped chips) so fit() re-runs'
    assert "window.addEventListener('resize'" in js
    assert "min-height: 0; overflow-y: auto; overscroll-behavior: contain" in css, 'the list must scroll, not the page'
