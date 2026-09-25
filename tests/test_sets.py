"""scripts/sets.py: tier/median helpers + the data/sets.json contract.

sets.py has no CLI override, so module.DATA is monkeypatched to tmp_path before main().
The synthetic catalogue is tiny on purpose: two prime sets, one fully owned (-> ASSEMBLE_SELL)
and one one-part-away with real quotes (-> COMPLETE).
"""
from types import SimpleNamespace

import pytest

from conftest import load_script, read_json, write_json

CATALOG = {'data': [
    {'slug': 'akstiletto_prime_set', 'tags': ['prime', 'set'], 'ducats': 0,
     'i18n': {'en': {'name': 'Akstiletto Prime Set'}}},
    {'slug': 'akstiletto_prime_barrel', 'tags': ['prime', 'component'], 'ducats': 15,
     'i18n': {'en': {'name': 'Akstiletto Prime Barrel'}}},
    {'slug': 'akstiletto_prime_receiver', 'tags': ['prime', 'component'], 'ducats': 30,
     'i18n': {'en': {'name': 'Akstiletto Prime Receiver'}}},
    {'slug': 'braton_prime_set', 'tags': ['prime', 'set'], 'ducats': 0,
     'i18n': {'en': {'name': 'Braton Prime Set'}}},
    {'slug': 'braton_prime_barrel', 'tags': ['prime', 'component'], 'ducats': 15,
     'i18n': {'en': {'name': 'Braton Prime Barrel'}}},
    {'slug': 'braton_prime_receiver', 'tags': ['prime', 'component'], 'ducats': 15,
     'i18n': {'en': {'name': 'Braton Prime Receiver'}}},
]}
OWNED = [{'slug': 'akstiletto_prime_barrel', 'name': 'Akstiletto Prime Barrel', 'count': 1},
         {'slug': 'akstiletto_prime_receiver', 'name': 'Akstiletto Prime Receiver', 'count': 1},
         {'slug': 'braton_prime_barrel', 'name': 'Braton Prime Barrel', 'count': 1}]
PRICES = {'akstiletto_prime_barrel': {'wts': 20}, 'akstiletto_prime_receiver': {'wts': 30},
          'braton_prime_barrel': {'wts': 40}, 'braton_prime_receiver': {'wts': 10}}


@pytest.fixture
def sets_mod(monkeypatch):
    return load_script('sets', monkeypatch=monkeypatch)


@pytest.fixture
def sets_run(monkeypatch, data_dir, sets_mod):
    monkeypatch.setattr(sets_mod, 'DATA', str(data_dir))
    write_json(data_dir / 'wfm_items_v2.json', CATALOG)
    write_json(data_dir / 'owned.json', OWNED)
    write_json(data_dir / 'prices.json', PRICES)
    write_json(data_dir / 'stats.json', {})
    sets_mod.main()
    return SimpleNamespace(doc=read_json(data_dir / 'sets.json'), mod=sets_mod)


def test_median_helper(sets_mod):
    assert sets_mod.median([]) is None
    assert sets_mod.median([5]) == 5
    assert sets_mod.median([1, 3, 9]) == 3
    assert sets_mod.median([1, 2, 3, 4]) == 2.5


def test_sets_json_top_level_contract(sets_run):
    doc = sets_run.doc
    assert set(doc) == {'generated', 'source', 'model', 'assumptions', 'summary',
                        'top_targets', 'cash_out_parts', 'self_check', 'sets'}
    assert doc['source'].startswith('wfm catalog + owned inventory')
    assert doc['model']['thresholds'] == {'roi_complete': 0.25, 'roi_maybe': 0.12,
                                          'min_profit_complete': 10.0, 'min_profit_maybe': 5.0}
    assert doc['model']['multi_parts'] == sets_run.mod.MULTI
    assert doc['model']['tier_medians'] == {}            # no priced prime parts in the fixture
    assert doc['model']['fit'] == {'a': 5.0, 'b': 1.0}   # documented no-data fallback p = 5*d^1
    assert len(doc['assumptions']) >= 4


def test_sets_self_check_all_pass(sets_run):
    checks = sets_run.doc['self_check']
    assert set(checks) == {'rows_match_sets', 'units_balance', 'cost_matches_parts',
                           'actions_known', 'every_set_has_parts', 'target_actions_real'}
    assert all(checks.values()), checks


def test_sets_rows_and_summary_are_consistent(sets_run):
    doc = sets_run.doc
    rows = doc['sets']
    by_slug = {r['slug']: r for r in rows}

    assert doc['summary']['sets_total'] == len(rows) == 2
    assert doc['summary']['parts_total'] == 4
    assert doc['summary']['complete'] == 1 and doc['summary']['near_1_missing'] == 1
    assert doc['summary']['complete_or_near'] == 2 and doc['summary']['two_missing'] == 0
    assert doc['summary']['targets'] == 2
    assert doc['summary']['actions'] == {'ASSEMBLE_SELL': 1, 'COMPLETE': 1}
    assert doc['summary']['held_parts_value_incomplete'] == 40.0
    assert doc['summary']['held_parts_value_near'] == 40.0
    assert doc['summary']['dupes_value'] == 0.0
    assert doc['summary']['net_profit_build_targets'] == 40.0
    assert doc['summary']['gross_value_ready_to_sell'] == 50.0
    assert all(r['action'] in sets_run.mod.ACTIONS for r in rows)

    assemble = by_slug['akstiletto_prime_set']
    assert assemble['action'] == 'ASSEMBLE_SELL'
    assert (assemble['units_have'], assemble['units_needed'], assemble['units_missing']) == (2, 2, 0)
    assert assemble['held_value'] == 50.0 and assemble['set_value'] == 50.0
    assert assemble['profit'] == 50.0 and assemble['roi'] is None       # nothing left to buy
    assert assemble['cost_basis'] == 'none' and assemble['profit_basis'] == 'gross'
    assert assemble['set_price'] is None and assemble['set_price_src'] == 'no_data'
    assert assemble['set_price_real'] is False and assemble['value_src'] == 'parts_sum_real'
    assert assemble['confidence'] == 'high' and assemble['price_coverage'] == 1.0
    assert assemble['own_set'] == 0 and assemble['duplicate_build'] is False
    assert assemble['trades_to_complete'] == 0 and assemble['score'] == 105.0

    build = by_slug['braton_prime_set']
    assert build['action'] == 'COMPLETE'
    assert build['missing_count'] == 1 and build['missing'][0]['slug'] == 'braton_prime_receiver'
    assert build['cost_missing'] == 10.0 and build['held_value'] == 40.0
    assert build['set_value'] == 50.0 and build['profit'] == 40.0 and build['roi'] == 4.0
    assert build['cost_basis'] == 'real' and build['profit_basis'] == 'net'
    assert build['confidence'] == 'medium'          # 50 real-backed of 60 exposure
    assert build['trades_to_complete'] == 1 and build['score'] == 54.0
    assert build['parts_have'] == 1 and build['got'][0]['slug'] == 'braton_prime_barrel'


def test_sets_top_targets_are_target_rows(sets_run):
    doc, mod = sets_run.doc, sets_run.mod
    assert [t['slug'] for t in doc['top_targets']] == ['akstiletto_prime_set', 'braton_prime_set']
    for brief in doc['top_targets']:
        row = next(r for r in doc['sets'] if r['slug'] == brief['slug'])
        assert brief['action'] in ('COMPLETE', 'COMPLETE_MAYBE', 'ASSEMBLE_SELL')
        assert row['parts_have'] >= 1
        assert set(brief) == {'slug', 'name', 'parts', 'need', 'cost_est', 'cost_basis',
                              'set_value', 'value_src', 'profit', 'roi', 'held_value', 'action',
                              'confidence', 'score'}
    assert doc['top_targets'][0]['parts'] == '2/2'
    assert doc['top_targets'][1]['need'] == ['braton_prime_receiver']


def test_sets_cash_out_parts_skip_target_sets(sets_run):
    # every held part here sits in a set that is worth assembling, so nothing to cash out
    assert sets_run.doc['cash_out_parts'] == []


def test_sets_row_key_contract(sets_run):
    row = sets_run.doc['sets'][0]
    for key in ('slug', 'name', 'tags', 'parts_total', 'units_needed', 'units_have', 'units_missing',
                'partial_parts', 'parts_have', 'missing_count', 'missing', 'got', 'cost_missing',
                'held_value', 'dupes_value', 'parts_sum', 'set_price', 'set_price_src',
                'set_price_real', 'set_value', 'value_src', 'profit', 'roi', 'profit_basis',
                'cost_basis', 'real_share', 'confidence', 'own_set', 'duplicate_build',
                'trades_to_complete', 'price_coverage', 'score', 'action'):
        assert key in row, key
    assert set(row['got'][0]) == {'slug', 'name', 'have', 'need', 'got', 'missing', 'partial',
                                  'ducats', 'unit_price', 'price_src', 'price_real', 'vol48', 'value'}
