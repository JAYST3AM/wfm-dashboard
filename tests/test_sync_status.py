"""Header auto-sync status (2026-09-27).

The SERVER runs the sync pipeline on the dashboard cadence (`auto_refresh_seconds`; see
tests/test_autosync.py for the loop and the GET /api/sync contract). This file pins the UI half:

  * the host span sits beside the header Refresh button, icon on the host (sprite picks it up);
  * the five labels are label-only (copy diet): 'Synced 12:04' / 'Sync failed' / 'Syncing…' /
    'Auto sync off' / 'Auto sync —' before the first sync lands;
  * the hover title carries the cadence + the next run ('manual only' when off);
  * the page polls /api/sync every 60s, once on load;
  * the store poll (`syncAutoRefresh`) is capped at 60s, so a 1-hour cadence still shows fresh
    data - the data itself is refreshed server side.

The five labels are also run: the shipped syncText() is extracted and evaluated in node, so the
mapping is asserted against the function that renders, not a copy of it.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import shell_decl, shell_js

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which('node')


def read(rel):
    with open(os.path.join(REPO, rel), encoding='utf-8') as fh:
        return fh.read()


# ------------------------------------------------------------------ the host

def test_the_header_host_is_beside_the_refresh_button():
    """Stage 1: the header is shell chrome. The sync host is still one compact span inside the
    action cluster, still before the Refresh button - now pinned at the shell that renders it."""
    shell = shell_js()
    assert '<span id="syncState" class="dim small" data-icon="arrows-clockwise"></span>' in shell, \
        'a compact status, icon on the host span'
    assert shell.index('id="syncState"') < shell.index('id="refresh"')
    # it is not a block of its own: one line in the header action cluster
    actions = shell.split('<div class="actions">', 1)[1].split('</header>', 1)[0]
    assert 'id="syncState"' in actions
    # and index.html is the page that asks for it (the sub-pages have no sync state today)
    assert 'syncState' in shell_decl('index.html')[1]
    assert 'syncState' not in shell_decl('collection.html')[1]


# ------------------------------------------------------------------ the labels

def test_the_five_status_labels_are_in_the_shipped_source():
    js = read('static/app.js')
    for label in ("'Auto sync off'", "'Syncing…'", "'Sync failed'", "'Synced '", "'Auto sync —'"):
        assert label in js, label
    body = js.split('function syncText(s) {', 1)[1].split('\n}', 1)[0]
    order = [body.index(x) for x in ("'Auto sync off'", "'Syncing…'", "'Sync failed'", "'Synced '", "'Auto sync —'")]
    assert order == sorted(order), 'off beats running beats failed beats last-sync beats blank'


def test_the_hover_title_carries_the_cadence_and_the_next_run():
    js = read('static/app.js')
    assert "'manual only'" in js, 'auto sync off reads as manual only'
    assert 'auto sync every ${mins} minutes${next}' in js
    assert "Math.round((Number(s.seconds) || 0) / 60)" in js, 'minutes derive from seconds'
    assert "const next = (s.next_in == null) ? '' : ' · next ' + syncClock(" in js


@pytest.mark.skipif(NODE is None, reason='node is not installed')
def test_the_shipped_syncText_maps_the_five_states(tmp_path):
    js = read('static/app.js')
    clock = re.search(r'function syncClock\(ts\) \{.*?\n\}', js, re.S).group(0)
    text = re.search(r'function syncText\(s\) \{.*?\n\}', js, re.S).group(0)
    probe = tmp_path / 'sync_text.js'
    probe.write_text(
        clock + '\n' + text + '\n' + """
const cases = {
  off:     {enabled: false, seconds: 0},
  running: {enabled: true, running: true, last_ok: true, last_sync: 1758960000},
  failed:  {enabled: true, last_ok: false, last_sync: 1758960000},
  synced:  {enabled: true, last_ok: true, last_sync: 1758960000},
  blank:   {enabled: true, last_sync: null, last_ok: null},
};
const out = {};
for (const [k, v] of Object.entries(cases)) out[k] = syncText(v);
console.log(JSON.stringify(out));
""", encoding='utf-8')
    res = subprocess.run([NODE, str(probe)], capture_output=True, text=True,
                         encoding='utf-8', timeout=60)
    assert res.returncode == 0, res.stderr
    got = json.loads(res.stdout)
    assert got['off'] == 'Auto sync off'
    assert got['running'] == 'Syncing…'
    assert got['failed'] == 'Sync failed'
    assert got['blank'] == 'Auto sync —'
    assert re.fullmatch(r'Synced \d{2}:\d{2}', got['synced']), got['synced']


# ------------------------------------------------------------------ the cadence

def test_the_status_is_fetched_once_on_load_then_every_60s():
    js = read('static/app.js')
    assert "fetch('/api/sync')" in js
    assert 'const SYNC_POLL_MS = 60000;' in js
    assert 'setInterval(loadSyncState, SYNC_POLL_MS);' in js
    assert js.count('loadSyncState()') >= 2, 'definition + the once-on-load call'


def test_the_store_poll_is_capped_at_60_seconds():
    """A 1-hour sync cadence must still show fresh data: the knob drives the SERVER loop, so the
    page's own re-read is Math.min(knob, 60)."""
    js = read('static/app.js')
    body = js.split('function syncAutoRefresh(values) {', 1)[1].split('\n}', 1)[0]
    assert 'const secs = Math.min(knob, 60);' in body
    assert 'setInterval(load, secs * 1000);' in body
