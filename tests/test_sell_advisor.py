"""scripts/sell_advisor.py: the integration layer over every other data source.

Fixture-driven: each test writes its own data/ documents into tmp_path and points the
module's DATA/OUT globals there, so no repo data is read and nothing is written to the
repo. Every existing input file is optional by design - the advisor must degrade to
fewer factors, never guess, so the "missing inputs" tests are as important as the rest.
"""
import os

from conftest import load_script, read_json, write_json


def owned_row(slug, name, count, tags, ducats=None, refinement=None):
    return {'slug': slug, 'name': name, 'count': count, 'tags': tags, 'ducats': ducats,
            'section': 'RawUpgrades', 'path': '/x/' + slug, 'match': 'by_name',
            'refinement': refinement}


def make_ctx(sa, data_dir, monkeypatch, *, owned, prices=None, stats=None, inuse=None,
             mods=None, collection=None, trends=None, ducats=None, sets=None, craft=None,
             relics=None, timing=None, plan=None, orders=None, baro=None, history=None):
    """Write the fixture documents and return a fresh context."""
    write_json(os.path.join(data_dir, 'owned.json'), owned)
    docs = {'prices.json': prices or {}, 'stats.json': stats or {},
            'inuse.json': inuse or {'items': []},
            'mod_cards.json': {'cards': [{'slug': s} for s in (mods or [])]},
            'collection_log.json': {'categories': [{'key': 'w', 'items': collection or []}]},
            'trends.json': {'rows': trends or []},
            'ducats.json': {'rows': ducats or []},
            'sets.json': sets or {'sets': [], 'cash_out_parts': []},
            'craft.json': {'rows': craft or []},
            'relic_ev.json': {'rows': relics or []},
            'sell_timing.json': timing or {},
            'trade_log.json': [],
            'trader_plan.json': plan or {'plan': []},
            'self_orders.json': orders or [],
            'baro.json': baro or {}}
    if history is not None:
        docs['price_history.json'] = history
    for name, doc in docs.items():
        write_json(os.path.join(data_dir, name), doc)
    monkeypatch.setattr(sa, 'DATA', str(data_dir))
    monkeypatch.setattr(sa, 'OUT', os.path.join(str(data_dir), 'sell_advisor.json'))
    return sa.build_context()


def test_equipped_copies_are_never_sellable(data_dir, monkeypatch):
    sa = load_script('sell_advisor')
    ctx = make_ctx(sa, data_dir, monkeypatch,
                   owned=[owned_row('some_prime_barrel', 'Some Prime Barrel', 2, ['prime', 'component']),
                          owned_row('some_prime_barrel', 'Some Prime Barrel', 2, ['prime', 'component'])],
                   inuse={'items': [{'item_id': 'a', 'slug': 'some_prime_barrel', 'rank': 0},
                                    {'item_id': 'b', 'slug': 'some_prime_barrel', 'rank': 0}]},
                   prices={'some_prime_barrel': {'wts': 30}})
    rec = sa.advise('some_prime_barrel', ctx)
    assert (rec['owned'], rec['equipped'], rec['reserved'], rec['sellable']) == (4, 2, 0, 2)
    assert '2 safe to sell.' in rec['text']
    assert '2 equipped.' in rec['text']


def test_mod_keeps_one_copy_for_the_collection(data_dir, monkeypatch):
    """Jay's example: owns 4, 1 equipped, 1 kept for the collection -> 2 sellable."""
    sa = load_script('sell_advisor')
    ctx = make_ctx(sa, data_dir, monkeypatch,
                   owned=[owned_row('archon_flow', 'Archon Flow', 4, ['mod'])],
                   inuse={'items': [{'item_id': 'a', 'slug': 'archon_flow', 'rank': 10}]},
                   mods=['archon_flow'],
                   prices={'archon_flow': {'wts': 18}},
                   stats={'archon_flow': {'vol48': 40, 'volday90': 12.0, 'med48': 20}})
    rec = sa.advise('archon_flow', ctx)
    assert (rec['owned'], rec['equipped'], rec['reserved'], rec['sellable']) == (4, 1, 1, 2)
    assert rec['recommendation'] == 'list'
    assert rec['recommended_quantity'] == 2
    assert rec['recommended_price'] == 18
    assert 'keep 1 for collection' in rec['reasons']
    assert 'Recommendation: list 2' in rec['text'] and 'around 18p' in rec['text']


def test_equipped_mod_with_no_spare_is_kept(data_dir, monkeypatch):
    sa = load_script('sell_advisor')
    ctx = make_ctx(sa, data_dir, monkeypatch,
                   owned=[owned_row('primed_continuity', 'Primed Continuity', 1, ['mod'])],
                   inuse={'items': [{'item_id': 'a', 'slug': 'primed_continuity', 'rank': 10}]},
                   mods=['primed_continuity'], prices={'primed_continuity': {'wts': 47}})
    rec = sa.advise('primed_continuity', ctx)
    assert rec['sellable'] == 0 and rec['recommendation'] == 'keep'
    assert 'all copies equipped' in rec['reasons']


def test_craft_and_near_set_parts_are_reserved(data_dir, monkeypatch):
    sa = load_script('sell_advisor')
    ctx = make_ctx(sa, data_dir, monkeypatch,
                   owned=[owned_row('hydroid_prime_chassis_blueprint', 'Hydroid Prime Chassis Blueprint', 1,
                                    ['prime', 'blueprint']),
                          owned_row('boar_prime_stock', 'Boar Prime Stock', 1, ['prime', 'component']),
                          owned_row('plain_part', 'Plain Part', 3, ['prime', 'component'])],
                   prices={'hydroid_prime_chassis_blueprint': {'wts': 25},
                           'boar_prime_stock': {'wts': 45},
                           'plain_part': {'wts': 10}},
                   craft=[{'result_name': 'Hydroid Prime Set', 'verdict': 'CRAFT',
                           'owned_parts': ['hydroid_prime_chassis_blueprint'], 'missing_parts': []}],
                   sets={'cash_out_parts': [], 'sets': [
                       {'slug': 'boar_prime_set', 'name': 'Boar Prime Set', 'units_needed': 4,
                        'units_have': 3, 'units_missing': 1, 'roi': 0.8, 'set_value': 90,
                        'cost_missing': 12,
                        'missing': [{'slug': 'boar_prime_barrel', 'name': 'Boar Prime Barrel'}],
                        'got': [{'slug': 'boar_prime_stock'}]}]})
    craft_rec = sa.advise('hydroid_prime_chassis_blueprint', ctx)
    assert craft_rec['sellable'] == 0 and craft_rec['recommendation'] == 'keep'
    assert any('hydroid prime set' in r.lower() for r in craft_rec['reasons'])
    set_rec = sa.advise('boar_prime_stock', ctx)
    assert set_rec['sellable'] == 0 and set_rec['recommendation'] == 'finish_set'
    assert set_rec['recommended_quantity'] == 1 and '~12p' in set_rec['text']
    spare = sa.advise('plain_part', ctx)
    assert spare['sellable'] == 3 and spare['recommendation'] == 'list'


def test_factors_without_data_are_omitted_not_guessed(data_dir, monkeypatch):
    sa = load_script('sell_advisor')
    ctx = make_ctx(sa, data_dir, monkeypatch,
                   owned=[owned_row('plain_part', 'Plain Part', 4, ['prime', 'component'])],
                   prices={'plain_part': {'wts': 10}})
    rec = sa.advise('plain_part', ctx)
    assert rec['trend'] is None and rec['best_sell_window'] is None
    for absent in ('Demand', 'Price trend', 'Baro', 'fastest'):
        assert absent not in rec['text'], absent
    assert 'market 10p.' in rec['text']


def test_demand_and_trend_lines_come_from_trends_json(data_dir, monkeypatch):
    sa = load_script('sell_advisor')
    ctx = make_ctx(sa, data_dir, monkeypatch,
                   owned=[owned_row('plain_part', 'Plain Part', 4, ['prime', 'component'])],
                   prices={'plain_part': {'wts': 10}},
                   stats={'plain_part': {'vol48': 25, 'volday90': 9.0}},
                   trends=[{'slug': 'plain_part', 'badge': 'spike', 'price_trend_pct': 12.0}])
    rec = sa.advise('plain_part', ctx)
    assert rec['trend'] == 'rising' and rec['demand_badge'] == 'spike'
    assert 'Demand is rising.' in rec['text']
    assert 'Recent price trend is up.' in rec['text']
    assert rec['liquidity'] == 'medium'          # nudges.liquidity_conf(25)


def test_sell_window_uses_own_sale_history(data_dir, monkeypatch):
    sa = load_script('sell_advisor')
    timing = {'hours': [{'hour': h, 'sales': 0, 'plat': 0} for h in range(24)],
              'by_kind': {'mod': {'sales': 12, 'plat': 300, 'best_hours': [
                  {'hour': 20, 'sales': 6, 'plat': 200}, {'hour': 21, 'sales': 4, 'plat': 80}]}}}
    ctx = make_ctx(sa, data_dir, monkeypatch,
                   owned=[owned_row('plain_mod', 'Plain Mod', 2, ['mod'])],
                   mods=['plain_mod'], prices={'plain_mod': {'wts': 10}}, timing=timing)
    rec = sa.advise('plain_mod', ctx)
    assert rec['best_sell_window'] == '20:00-22:00'
    assert any('20:00-22:00' in r for r in rec['reasons'])


def test_ducat_burn_beats_a_cheap_sale(data_dir, monkeypatch):
    sa = load_script('sell_advisor')
    ctx = make_ctx(sa, data_dir, monkeypatch,
                   owned=[owned_row('orthos_prime_blade', 'Orthos Prime Blade', 1, ['prime', 'component'])],
                   prices={'orthos_prime_blade': {'wts': 2}},
                   ducats=[{'slug': 'orthos_prime_blade', 'count': 1, 'verdict': 'BURN',
                            'reason': 'ducat-dense 22.5 d/p', 'ducats_per_plat': 22.5}])
    rec = sa.advise('orthos_prime_blade', ctx)
    assert rec['recommendation'] == 'burn_ducats'
    assert 'Recommendation: burn 1 for ducats.' in rec['text']


def test_relic_open_verdict_and_ev_fallback(data_dir, monkeypatch):
    sa = load_script('sell_advisor')
    ctx = make_ctx(sa, data_dir, monkeypatch,
                   owned=[owned_row('lith_a1_relic', 'Lith A1 Relic', 5, ['relic']),
                          owned_row('neo_d3_relic', 'Neo D3 Relic', 5, ['relic'])],
                   prices={'lith_a1_relic': {'wts': 12}, 'neo_d3_relic': {'wts': 30}},
                   relics=[{'slug': 'lith_a1_relic', 'refinement': 'Intact', 'verdict': 'OPEN',
                            'ev_unit_wts': 25, 'relic_wts': 12},
                           {'slug': 'neo_d3_relic', 'refinement': 'Intact',
                            'ev_unit_wts': 8, 'relic_wts': 30}])
    open_rec = sa.advise('lith_a1_relic', ctx)
    sell_rec = sa.advise('neo_d3_relic', ctx)
    assert open_rec['recommendation'] == 'open_relic'
    assert sell_rec['recommendation'] == 'list' and sell_rec['sellable'] == 5


def test_queued_rows_are_never_relisted(data_dir, monkeypatch):
    sa = load_script('sell_advisor')
    ctx = make_ctx(sa, data_dir, monkeypatch,
                   owned=[owned_row('plain_part', 'Plain Part', 4, ['prime', 'component'])],
                   prices={'plain_part': {'wts': 30}},
                   plan={'plan': [{'slug': 'plain_part', 'qty': 1, 'price': 33, 'lane': 'sell'}]})
    rec = sa.advise('plain_part', ctx)
    assert rec['recommendation'] == 'already_listed'
    assert 'queued in the trader plan (qty 1 @ 33p)' in rec['text']


def test_live_orders_win_and_missing_price_holds(data_dir, monkeypatch):
    sa = load_script('sell_advisor')
    ctx = make_ctx(sa, data_dir, monkeypatch,
                   owned=[owned_row('plain_part', 'Plain Part', 4, ['prime', 'component']),
                          owned_row('no_price_part', 'No Price Part', 2, ['prime', 'component'])],
                   prices={'plain_part': {'wts': 30}},
                   orders=[{'type': 'sell', 'quantity': 3, 'platinum': 31,
                            'item': {'slug': 'plain_part'}}])
    live = sa.advise('plain_part', ctx)
    assert live['recommendation'] == 'already_listed' and live['recommended_quantity'] == 3
    assert 'live sell order' in live['text']
    quiet = sa.advise('no_price_part', ctx)
    assert quiet['recommendation'] == 'hold'
    assert 'no local price data' in quiet['text']


def test_document_is_deterministic_and_hash_stable(data_dir, monkeypatch):
    sa = load_script('sell_advisor')
    ctx = make_ctx(sa, data_dir, monkeypatch,
                   owned=[owned_row('plain_part', 'Plain Part', 4, ['prime', 'component'])],
                   prices={'plain_part': {'wts': 30}})
    first = sa.build_doc(ctx)
    second = sa.build_doc(ctx)
    assert first['content_hash'] == second['content_hash']
    assert first['items']['plain_part']['item'] == 'plain_part'
    assert 'text' in first['items']['plain_part']
    sa.atomic_write(sa.OUT, first)
    third = sa.build_doc(ctx)
    assert third['generated'] == first['generated']       # stamp reused, file byte-stable
    assert read_json(sa.OUT)['content_hash'] == first['content_hash']


def test_ranked_puts_actionable_before_keeps(data_dir, monkeypatch):
    sa = load_script('sell_advisor')
    ctx = make_ctx(sa, data_dir, monkeypatch,
                   owned=[owned_row('cheap_keep', 'Cheap Keep', 1, ['mod']),
                          owned_row('big_list', 'Big List', 3, ['prime', 'component'])],
                   mods=['cheap_keep'],
                   prices={'cheap_keep': {'wts': 900}, 'big_list': {'wts': 5}})
    doc = sa.build_doc(ctx)
    assert doc['ranked'][0] == 'big_list'                  # a keep never outranks a list
    assert doc['counts'].get('keep') == 1 and doc['counts'].get('list') == 1
