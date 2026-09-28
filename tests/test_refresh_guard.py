"""scripts/refresh.py: the empty-decode guard and the atomic write - in a hermetic sandbox.

Every run here is a real subprocess: tmp/scripts/refresh.py (a copy, so ROOT/DATA resolve
inside tmp) + tmp/scripts/saveio.py (the module refresh imports for decrypt/normalise) run
against a fake %LOCALAPPDATA% (tmp/AlecaFrame).  The save is a plaintext b'{}' - the
decryptor's documented plaintext branch - and the cached catalogs + wfm_items_v2 fixture
are all present, so the run is offline and deterministic.

Pinned:
  * a decode that produces 0 items must NEVER replace a non-empty owned.json - including
    when the previous rollup is real (rc=3, a 'skipped' line the UI surfaces, file intact);
  * an empty rollup over an EMPTY previous file is a legitimate fresh start (rc=0, []);
  * a save carrying its inventory inside InventoryJson hoists end-to-end: the summary
    line reports mr/trades/credits and owned.json is built from the inner sections.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import read_json, write_json

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, 'scripts')
REFRESH = os.path.join(SCRIPTS, 'refresh.py')


def sandbox(tmp_path, save=b'{}', basic=None, wfm=None):
    """tmp/{scripts,data,AlecaFrame}: the copy + fixtures one refresh run needs."""
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    shutil.copy(REFRESH, str(scripts / 'refresh.py'))
    shutil.copy(os.path.join(SCRIPTS, 'saveio.py'), str(scripts / 'saveio.py'))
    data = tmp_path / 'data'
    data.mkdir()
    af = tmp_path / 'AlecaFrame'
    (af / 'cachedData' / 'custom').mkdir(parents=True)
    (af / 'cachedData' / 'json').mkdir(parents=True)
    (af / 'lastData.dat').write_bytes(save)
    write_json(af / 'cachedData' / 'custom' / 'basic.json', {'items': basic or {}})
    write_json(af / 'cachedData' / 'json' / 'Relics.json', [])
    write_json(data / 'wfm_items_v2.json', wfm or {'data': []})    # never the network
    return tmp_path, data


def run_refresh(tmp_path):
    """The copied refresh.py as a real process, with %LOCALAPPDATA% faked at tmp."""
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path))
    return subprocess.run([sys.executable, str(tmp_path / 'scripts' / 'refresh.py')],
                          cwd=str(tmp_path), env=env, capture_output=True, text=True,
                          timeout=180)


PREV = [{'slug': 'ferrite', 'name': 'Ferrite', 'count': 1200, 'section': 'MiscItems'},
        {'slug': 'ash_prime_set', 'name': 'Ash Prime Set', 'count': 2, 'section': 'Recipes'}]


def test_empty_decode_never_replaces_a_non_empty_owned(tmp_path):
    root, data = sandbox(tmp_path)                       # b'{}' -> a 0-item decode
    write_json(data / 'owned.json', PREV)
    r = run_refresh(tmp_path)
    assert r.returncode == 3, r.stdout + r.stderr
    assert 'skipped' in r.stdout
    assert read_json(data / 'owned.json') == PREV        # the live rollup survived intact
    assert not os.path.exists(str(data / 'owned.json.tmp'))   # and no half-written file


@pytest.mark.parametrize('empty', ['list', 'file'], ids=['empty-list', 'empty-file'])
def test_empty_rollup_with_an_empty_previous_file_is_a_legitimate_fresh_start(tmp_path, empty):
    root, data = sandbox(tmp_path)
    if empty == 'list':
        write_json(data / 'owned.json', [])
    else:
        (data / 'owned.json').write_bytes(b'')           # a torn/never-written prev file
    r = run_refresh(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_json(data / 'owned.json') == []          # a fresh start is allowed
    assert json.loads(r.stdout.strip().splitlines()[-1])['owned'] == 0


def test_inventory_json_hoists_through_refresh(tmp_path):
    """The end-to-end shape fix: sections inside InventoryJson still build owned.json and
    feed the summary line - this is the regression that emptied the store."""
    save = json.dumps({
        'FusionPoints': 5,
        'InventoryJson': json.dumps({
            'PlayerLevel': 22, 'TradesRemaining': 22, 'RegularCredits': 4606665,
            'MiscItems': [{'ItemType': '/Lotus/X', 'ItemCount': 3}]})}).encode('utf-8')
    wfm = {'data': [{'slug': 'x', 'gameRef': '/Lotus/X', 'tags': ['prime'],
                     'i18n': {'en': {'name': 'X'}}}]}
    root, data = sandbox(tmp_path, save=save, basic={'/Lotus/X': {'name': 'X'}}, wfm=wfm)
    r = run_refresh(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout.strip().splitlines()[-1]) == {
        'mr': 22, 'trades': 22, 'credits': 4606665, 'owned': 1}
    owned = read_json(data / 'owned.json')
    assert [(row['slug'], row['count'], row['section'], row['match']) for row in owned] == [
        ('x', 3, 'MiscItems', 'ref')]
    # and the decrypted copy every other reader uses is the classic flat shape already
    dec = read_json(data / 'lastData.dec.json')
    assert dec['MiscItems'] == [{'ItemType': '/Lotus/X', 'ItemCount': 3}]
    assert dec['PlayerLevel'] == 22 and dec['TradesRemaining'] == 22
