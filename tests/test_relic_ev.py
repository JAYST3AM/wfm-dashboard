"""scripts/relic_ev.py: EV math + data/relic_ev.json contract.

relic_ev.py has NO env/CLI path override and does its work at import time (it downloads
the WFCD relic table and prices every reward from api.warframe.market), so it can never
be imported by a test. Two offline strategies are used instead:

  1. pure helpers (top_prices) are extracted from the source with ast and executed -
     no module import, no side effects;
  2. the end-to-end run happens in a SUBPROCESS inside tmp_path, where a copy of the
     script finds its own data/ dir and a stub sitecustomize.py replaces
     urllib.request.urlopen with canned relic-table/orderbook payloads. The real source
     is never modified (only copied) and nothing touches api.warframe.market.
"""
import ast
import os
import shutil
import subprocess
import sys

import pytest

from conftest import SCRIPTS, read_json, write_json

RELIC_SRC = os.path.join(SCRIPTS, 'relic_ev.py')
RELIC_SLUG = 'lith_p8_relic'
REWARD_SLUG = 'prime_part_x'
TABLE_ENTRY = {
    'uniqueName': '/Lotus/Types/Game/Projections/T1VoidProjectionB',
    'name': 'Lith P8 Relic',
    'rewards': [
        {'chance': 25.33, 'rarity': 'Rare',
         'item': {'name': 'Prime Part X', 'warframeMarket': {'urlName': REWARD_SLUG, 'id': 'xid'}}},
        {'chance': 74.67, 'rarity': 'Common', 'item': {'name': 'Forma Blueprint'}},   # untradable slot
    ],
}
CANNED = {
    'relics': [TABLE_ENTRY],
    'orders': {
        REWARD_SLUG: {'sell': [{'platinum': 40, 'visible': True}], 'buy': []},
        RELIC_SLUG: {'sell': [{'platinum': 5, 'subtype': 'Radiant', 'visible': True},
                              {'platinum': 6, 'subtype': 'Intact', 'visible': True}],
                     'buy': [{'platinum': 4, 'subtype': 'intact', 'visible': True}]},
    },
}
OWNED_RELICS = [{'slug': RELIC_SLUG, 'name': 'Lith P8 Relic', 'count': 3, 'refinement': 'Intact',
                 'path': TABLE_ENTRY['uniqueName'], 'tags': ['relic', 'refinement']}]
SITECUSTOMIZE = '''\
"""Offline stand-in for the warframe.market API, loaded by Hermes' wfm-dashboard tests.

Imported by `site` at interpreter start (the harness dir is on PYTHONPATH), so the
script under test never reaches the real network. Unmapped URLs return an __error dict,
which relic_ev treats as a transient failure instead of hanging on retries.
"""
import json
import os
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_HERE, 'canned.json'), encoding='utf-8') as _fh:
    _C = json.load(_fh)


class _Resp:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode('utf-8')

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _urlopen(req, timeout=None, **kwargs):
    url = getattr(req, 'full_url', None) or str(req)
    if 'Relics.json' in url:
        return _Resp(_C['relics'])
    if '/orders/item/' in url:
        slug = url.split('/orders/item/', 1)[1].split('/')[0].split('?')[0]
        if slug in _C['orders']:
            return _Resp({'data': _C['orders'][slug]})
    return _Resp({'__error': 'stub: unmapped url %s' % url})


urllib.request.urlopen = _urlopen
'''


# ------------------------------------------------------------------ pure helper (no import)

def _extract_func(name):
    """Compile one function straight out of relic_ev.py's source (never import it)."""
    with open(RELIC_SRC, encoding='utf-8') as fh:
        tree = ast.parse(fh.read())
    node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name), None)
    assert node is not None, 'relic_ev.py no longer defines %s()' % name
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    namespace = {}
    exec(compile(module, '<relic_ev>', 'exec'), namespace)
    return namespace[name]


def test_top_prices_uses_visible_sell_floor_and_buy_ceiling():
    top_prices = _extract_func('top_prices')
    orders = {'sell': [{'platinum': 10, 'visible': True}, {'platinum': 5, 'visible': False}],
              'buy': [{'platinum': 3, 'visible': True}, {'platinum': 9, 'visible': False}]}
    assert top_prices(orders) == (10, 3)
    assert top_prices({}) == (None, None)
    assert top_prices({'sell': [], 'buy': []}) == (None, None)


def test_top_prices_filters_by_subtype_when_orders_carry_one():
    top_prices = _extract_func('top_prices')
    orders = {'sell': [{'platinum': 5, 'subtype': 'Radiant', 'visible': True},
                       {'platinum': 6, 'subtype': 'Intact', 'visible': True}],
              'buy': [{'platinum': 4, 'subtype': 'intact', 'visible': True},
                      {'platinum': 9, 'subtype': 'radiant', 'visible': True}]}
    assert top_prices(orders, 'intact') == (6, 4)         # radiant 5p/no-subtype ignored
    assert top_prices(orders, 'radiant') == (5, 9)
    # plain items carry no subtype: the filter must not discard their orders
    assert top_prices({'sell': [{'platinum': 7, 'visible': True}],
                       'buy': [{'platinum': 2, 'visible': True}]}, 'intact') == (7, 2)


# ------------------------------------------------------------------ subprocess harness

def build_harness(tmp_path, owned):
    root = tmp_path / 'harness'
    (root / 'scripts').mkdir(parents=True)
    (root / 'data').mkdir()
    shutil.copyfile(RELIC_SRC, root / 'scripts' / 'relic_ev.py')   # copy, never modify the source
    write_json(root / 'data' / 'owned.json', owned)
    write_json(root / 'data' / 'prices.json', {})
    write_json(root / 'canned.json', CANNED)
    (root / 'sitecustomize.py').write_text(SITECUSTOMIZE, encoding='utf-8')
    return root


def harness_script(root):
    return root / 'scripts' / 'relic_ev.py'


def run_harness(root):
    env = dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE='1')
    return subprocess.run([sys.executable, str(harness_script(root))], cwd=str(root), env=env,
                          capture_output=True, text=True, timeout=120)


def test_relic_ev_end_to_end_ev_math(tmp_path):
    """chance x price EV, subtype-filtered relic floor, OPEN verdict and totals."""
    root = build_harness(tmp_path, OWNED_RELICS)

    proc = run_harness(root)
    assert proc.returncode == 0, proc.stderr[-2000:]

    doc = read_json(root / 'data' / 'relic_ev.json')
    assert doc['reward_source'].endswith('Relics.json')
    assert doc['relic_snapshot'] == 'data/owned.json'
    assert doc['relics_analyzed'] == 1 and doc['relic_copies'] == 3
    assert doc['unmatched_owned_relics'] == []

    row = doc['rows'][0]
    assert set(row) == {'relic', 'slug', 'refinement', 'count', 'chance_sum', 'table_complete',
                        'ev_unit_wts', 'ev_total_wts', 'ev_unit_wtb', 'relic_wts',
                        'relic_total_value', 'relic_price_missing', 'gain_if_opened_total',
                        'ratio', 'action', 'rewards_priced', 'rewards_total', 'unpriced_rewards',
                        'best_reward'}
    assert (row['relic'], row['slug'], row['refinement'], row['count']) == ('Lith P8 Relic',
                                                                           RELIC_SLUG, 'Intact', 3)
    assert row['chance_sum'] == 100.0 and row['table_complete'] is True
    assert row['rewards_priced'] == 1 and row['rewards_total'] == 2   # Forma slot is untradable
    assert row['unpriced_rewards'] == []
    # 25.33% x 40p = 10.13 EV/unit; the radiant 5p order must not become the relic's floor
    assert row['ev_unit_wts'] == 10.13 and row['ev_total_wts'] == 30.4
    assert row['relic_wts'] == 6 and row['relic_total_value'] == 18.0
    assert row['ratio'] == 1.69 and row['action'] == 'OPEN'           # >= OPEN_RATIO 1.2
    assert row['gain_if_opened_total'] == 12.4
    assert row['best_reward'] == {'name': 'Prime Part X', 'platinum': 40, 'rarity': 'Rare'}

    assert doc['totals'] == {'ev_if_all_opened': 30.4, 'value_if_all_sold_as_is': 18.0,
                             'actions': {'OPEN': 1}, 'live_lookups_this_run': 2}
    assert doc['non_tradable_reward_slots'] == 1
    assert doc['missing_prices'] == {'distinct_reward_slugs': 0, 'slugs': [],
                                     'rows_with_unpriced_rewards': 0, 'one_sided_quotes': 1,
                                     'relics_without_market_price': 0}
    # the resumable price cache is written for the next run
    cache = read_json(root / 'data' / 'relic_prices.json')
    assert set(cache['items']) == {REWARD_SLUG, '%s|intact' % RELIC_SLUG}
    assert cache['items'][REWARD_SLUG]['wts'] == 40
    assert cache['items']['%s|intact' % RELIC_SLUG]['wts'] == 6


def test_relic_ev_fails_fast_without_relic_data(tmp_path):
    """No owned relic stacks -> sys.exit(1) BEFORE any network call is attempted."""
    root = build_harness(tmp_path, [])
    proc = run_harness(root)
    assert proc.returncode == 1
    assert 'no owned relic entries found' in (proc.stderr + proc.stdout)
    assert not (root / 'data' / 'relic_ev.json').exists()


def test_relic_ev_fails_fast_without_owned_json(tmp_path):
    root = tmp_path / 'harness'
    (root / 'scripts').mkdir(parents=True)
    (root / 'data').mkdir()
    shutil.copyfile(RELIC_SRC, harness_script(root))

    proc = run_harness(root)

    assert proc.returncode == 1
    assert 'no owned relic entries found' in (proc.stderr + proc.stdout)


@pytest.mark.parametrize('args,expected', [([], 6.0), (['--refresh'], 0.0),
                                           (['--max-age=2'], 2.0), (['--max-age', '1.5'], 1.5)])
def test_max_age_flags_are_parsed_at_import(tmp_path, args, expected):
    """Documents the CLI contract: --refresh / --max-age H set MAX_AGE before any work."""
    root = build_harness(tmp_path, [])            # empty owned.json -> exits before any fetch
    probe = root / 'probe.py'
    probe.write_text(
        'import sys\n'
        'path = %r\n'
        'sys.argv = [path] + %r\n'
        'ns = {"__name__": "probe", "__file__": path}\n'
        'try:\n'
        '    exec(compile(open(path, encoding="utf-8").read(), path, "exec"), ns)\n'
        'except SystemExit:\n'
        '    pass\n'
        'print("MAX_AGE=%%s" %% ns.get("MAX_AGE"))\n' % (str(harness_script(root)), args),
        encoding='utf-8')

    proc = subprocess.run([sys.executable, str(probe)], cwd=str(root), capture_output=True,
                          text=True, timeout=120,
                          env=dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE='1'))

    assert proc.returncode == 0, proc.stderr[-2000:]
    assert 'MAX_AGE=%s' % expected in proc.stdout
