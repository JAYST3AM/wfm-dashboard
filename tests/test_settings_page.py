"""Settings page: the auto-sync picker (Jay, 2026-09-27: "auto sync with settings ie 5m 10m 15m
30m 1hr").

auto_refresh_seconds keeps its key and its save path (the Updates card's Save -> POST /api/config
{pairs}); the row now presents six presets as pills instead of a raw seconds box:

    Manual only 0 | Every 5 minutes 300 | Every 10 minutes 600 | Every 15 minutes 900 |
    Every 30 minutes 1800 | Every hour 3600

Honesty rules pinned here: 0 reads 'Manual only' (never '0 seconds'), and a stored value that is
not a preset is shown raw as Custom (e.g. 'Custom \u00b7 120s') with no pill pressed - never
rounded and never silently preselected. The text rule also runs under node when node is installed
(skipped otherwise - node is never a hard dependency).
"""
import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import REPO

STATIC = os.path.join(REPO, 'static')
NODE = shutil.which('node')

PRESETS = [('Manual only', 0), ('Every 5 minutes', 300), ('Every 10 minutes', 600),
           ('Every 15 minutes', 900), ('Every 30 minutes', 1800), ('Every hour', 3600)]


def read(name):
    with open(os.path.join(STATIC, name), encoding='utf-8') as fh:
        return fh.read()


def picker_table(js=None):
    """The (seconds, label) pairs as written in static/settings.js."""
    js = js if js is not None else read('settings.js')
    block = js.split('const AUTO_SYNC_OPTIONS = [', 1)[1].split('];', 1)[0]
    return re.findall(r"\{\s*seconds:\s*(\d+),\s*label:\s*'([^']+)'\s*\}", block)


def test_the_six_presets_and_their_values_are_pinned():
    table = picker_table()
    assert [sec for sec, _ in table] == ['0', '300', '600', '900', '1800', '3600']
    assert [(label, int(sec)) for sec, label in table] == PRESETS


def test_auto_sync_row_is_labelled_and_unitless():
    row = re.search(r"\{[^{}]*key: 'auto_refresh_seconds'[^{}]*\}", read('settings.js'))
    assert row, 'the auto sync row moved - update this test first'
    assert "label: 'Auto sync'" in row.group(0)
    assert 'unit:' not in row.group(0)                   # no 'seconds' suffix on this row
    assert 'pick: AUTO_SYNC_OPTIONS' in row.group(0)     # the row renders the picker


def test_the_picker_keeps_the_rows_id_and_data_key_plumbing():
    js = read('settings.js')
    fn = js.split('function buildPickControl(', 1)[1].split('\n}', 1)[0]
    assert 'store.id = id;' in fn and 'store.dataset.k = meta.key;' in fn, \
        'the hidden seconds input must keep the row id + data-k'
    assert 'store.value = String(val);' in fn            # the loaded value is what the row posts
    # a Custom value presses no pill; a click stores its seconds and refreshes the value cell
    assert "b.setAttribute('aria-pressed', String(o.seconds === sec))" in fn
    assert 'store.value = String(o.seconds);' in fn
    assert "store.dispatchEvent(new Event('change', { bubbles: true }))" in fn


@pytest.mark.skipif(NODE is None, reason='node is not installed - source pins still run')
def test_zero_reads_manual_only_and_a_non_preset_value_reads_custom():
    js = read('settings.js')
    fn = js.split('function pickText(raw) {', 1)[1].split('\n}', 1)[0]
    opts = re.search(r'const AUTO_SYNC_OPTIONS = \[.*?\n\];', js, re.S)
    assert opts, 'the picker table moved - update this test first'
    script = (opts.group(0) + '\nfunction pickText(raw) {' + fn + '}\n'
              "console.log(JSON.stringify([0, 300, 600, 900, 1800, 3600, 120, 45].map(pickText)));\n")
    proc = subprocess.run([NODE, '-e', script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-500:]
    assert json.loads(proc.stdout) == [
        'Manual only', 'Every 5 minutes', 'Every 10 minutes', 'Every 15 minutes',
        'Every 30 minutes', 'Every hour', 'Custom \u00b7 120s', 'Custom \u00b7 45s',
    ]
