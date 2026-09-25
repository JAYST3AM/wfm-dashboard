"""server.py payload contract tests: trimming rules, trade totals, plat history math.

server.py is imported as a module (never started): DATA/ROOT point at tmp_path, so
these tests are pure functions over data/ JSON files.
"""
import time

from conftest import write_json


# ------------------------------------------------------------------ feature_payload

def test_deals_trimmed_to_first_60(server_mod, data_dir):
    deals = [{'slug': 'k%03d' % i, 'score': float(i)} for i in range(70)]
    write_json(data_dir / 'deals.json', {'version': 1, 'counts': {'total': 70}, 'deals': deals})

    payload = server_mod.feature_payload('deals')

    assert len(payload['deals']) == 60
    assert [d['slug'] for d in payload['deals']] == ['k%03d' % i for i in range(60)]
    assert payload['counts'] == {'total': 70}          # every other key survives


def test_ducats_keeps_summary_and_splits_top_25_burn_25_sell(server_mod, data_dir):
    rows = ([{'slug': 'b%d' % i, 'verdict': 'BURN', 'ducats_per_plat': i, 'sell_total': 1000 - i}
             for i in range(1, 31)]
            + [{'slug': 'b_none', 'verdict': 'BURN'}]                      # missing rank key
            + [{'slug': 's%d' % i, 'verdict': 'SELL', 'ducats_per_plat': 1.0, 'sell_total': i}
               for i in range(0, 26)]
            + [{'slug': 'h%d' % i, 'verdict': 'HOLD', 'ducats_per_plat': 99} for i in range(5)])
    write_json(data_dir / 'ducats.json',
               {'generated': 'now', 'summary': {'sell_count': 26}, 'account': {'mr': 30},
                'buckets': {'sell': ['s0'], 'burn': ['b1']}, 'rows': rows})

    payload = server_mod.feature_payload('ducats')

    assert payload['summary'] == {'sell_count': 26}
    assert payload['account'] == {'mr': 30}
    assert 'buckets' not in payload                                     # heavy key dropped
    assert len(payload['rows']) == 50
    burn, sell = payload['rows'][:25], payload['rows'][25:]
    assert {r['verdict'] for r in burn} == {'BURN'}
    assert {r['verdict'] for r in sell} == {'SELL'}                     # HOLD rows dropped
    assert [r['ducats_per_plat'] for r in burn] == list(range(30, 5, -1))   # desc, top 25
    assert [r['sell_total'] for r in sell] == list(range(25, 0, -1))        # desc, top 25
    assert 'b_none' not in [r['slug'] for r in burn]                    # None ranks last


def test_ducats_with_fewer_than_25_rows_keeps_them_all(server_mod, data_dir):
    rows = [{'slug': 'b1', 'verdict': 'BURN', 'ducats_per_plat': 9},
            {'slug': 's1', 'verdict': 'SELL', 'sell_total': 9},
            {'slug': 'h1', 'verdict': 'HOLD'}]
    write_json(data_dir / 'ducats.json', {'rows': rows, 'buckets': {}})

    payload = server_mod.feature_payload('ducats')

    assert [r['slug'] for r in payload['rows']] == ['b1', 's1']
    assert 'buckets' not in payload


def test_sets_drops_full_rows_but_keeps_ui_keys(server_mod, data_dir):
    write_json(data_dir / 'sets.json', {
        'generated': 'now', 'summary': {'sets_total': 2}, 'top_targets': [{'slug': 'a'}],
        'cash_out_parts': [{'part': 'p'}], 'self_check': {'rows_match_sets': True},
        'model': {'thresholds': {}}, 'sets': [{'slug': 'a', 'parts_total': 3}] * 2})

    payload = server_mod.feature_payload('sets')

    assert 'sets' not in payload                       # ~350KB of rows never shipped
    assert payload['summary'] == {'sets_total': 2}
    assert payload['top_targets'] == [{'slug': 'a'}]
    assert payload['cash_out_parts'] == [{'part': 'p'}]
    assert payload['self_check'] == {'rows_match_sets': True}
    assert payload['model'] == {'thresholds': {}}


def test_sessions_trimmed_to_first_12(server_mod, data_dir):
    sessions = [{'start': 1000 - i, 'start_at': 'x%d' % i} for i in range(20)]
    write_json(data_dir / 'session_stats.json',
               {'generated': 'now', 'gap_min': 45, 'totals': {'sessions': 20},
                'sessions': sessions, 'shown': 50})

    payload = server_mod.feature_payload('sessions')

    assert len(payload['sessions']) == 12
    assert [s['start_at'] for s in payload['sessions']] == ['x%d' % i for i in range(12)]
    assert payload['totals'] == {'sessions': 20}
    assert payload['shown'] == 50


def test_feature_payload_survives_missing_files(server_mod, data_dir):
    """A fresh/partial data dir must not crash any feature endpoint."""
    for name in server_mod.FEATURES:
        assert isinstance(server_mod.feature_payload(name), dict), name
    # the trimmed features expose an empty list rather than None/KeyError
    assert server_mod.feature_payload('deals') == {'deals': []}
    assert server_mod.feature_payload('sessions') == {'sessions': []}
    assert server_mod.feature_payload('ducats') == {'rows': []}
    assert server_mod.feature_payload('sets') == {}
    assert server_mod.feature_payload('relics') == {}


def test_relics_limits_movers_invdiff_pass_through_untouched(server_mod, data_dir):
    """These four features are shipped verbatim - no trimming rules apply."""
    payloads = {
        'relics': {'relics_analyzed': 1, 'rows': [{'relic': 'Lith P8', 'action': 'OPEN'}]},
        'limits': {'plan': {'x': 1}},
        'movers': {'mode': '24h-movers', 'movers': [{'slug': 'a'}]},
        'invdiff': {'status': 'baseline', 'added': []},
    }
    for name, body in payloads.items():
        write_json(data_dir / server_mod.FEATURES[name], body)
        assert server_mod.feature_payload(name) == body, name


# ------------------------------------------------------------------ trades_payload

def test_trades_totals_and_reversed_events(server_mod, data_dir):
    events = [
        {'ts': 1, 'kind': 'sale', 'name': 'A', 'qty': 2, 'total': 12},
        {'ts': 2, 'kind': 'purchase', 'name': 'B', 'qty': 1, 'total': 5},
        {'ts': 3, 'kind': 'listing', 'name': 'C', 'qty': 9, 'total': 99},
        {'ts': 4, 'kind': 'note', 'name': 'D'},
    ]
    write_json(data_dir / 'trade_log.json', events)

    payload = server_mod.trades_payload()

    assert payload['n'] == 4
    assert payload['totals'] == {'earned': 12, 'spent': 5, 'net': 7,
                                 'sales': 1, 'purchases': 1, 'items': 3}
    assert [e['ts'] for e in payload['events']] == [4, 3, 2, 1]     # newest first for the UI


def test_trades_payload_empty_without_log(server_mod, data_dir):
    payload = server_mod.trades_payload()
    assert payload['n'] == 0 and payload['events'] == []
    assert payload['totals'] == {'earned': 0, 'spent': 0, 'net': 0,
                                 'sales': 0, 'purchases': 0, 'items': 0}


def test_trades_totals_tolerate_missing_fields(server_mod, data_dir):
    write_json(data_dir / 'trade_log.json', [{'kind': 'sale', 'name': 'A'}, {'kind': 'purchase'}])
    totals = server_mod.trades_payload()['totals']
    assert totals['sales'] == 1 and totals['purchases'] == 1
    assert totals['earned'] == 0 and totals['spent'] == 0 and totals['items'] == 0


# ------------------------------------------------------------------ plat_history_payload

def test_plat_history_deltas(server_mod, data_dir):
    now = int(time.time())
    hist = [
        {'ts': now - 10 * 86400, 'plat': 1000, 'credits': 5},                 # > 7d back
        {'ts': now - 2 * 86400, 'plat': 1100},                                # 24h..7d back
        {'ts': now - 12 * 3600, 'plat': 1200, 'mr': 20, 'src': 'alecaframe'},  # < 24h back
        {'ts': now - 3600, 'plat': 1250, 'credits': 7},
    ]
    write_json(data_dir / 'plat_history.json', hist)

    payload = server_mod.plat_history_payload()

    assert payload['points'] == hist                     # shipped verbatim to the chart
    assert payload['now'] == 1250                        # last point wins
    assert payload['d24'] == 150                         # 1250 - 1100 (latest point <= now-24h)
    assert payload['d7'] == 250                          # 1250 - 1000 (latest point <= now-7d)
    assert payload['first_ts'] == now - 10 * 86400
    assert payload['first_plat'] == 1000
    assert payload['n'] == 4


def test_plat_history_empty_and_young(server_mod, data_dir):
    empty = server_mod.plat_history_payload()
    assert empty == {'points': [], 'now': None, 'd24': None, 'd7': None,
                     'first_ts': None, 'first_plat': None, 'n': 0}

    now = int(time.time())
    write_json(data_dir / 'plat_history.json', [{'ts': now, 'plat': 42}])
    young = server_mod.plat_history_payload()
    assert young['now'] == 42 and young['n'] == 1
    assert young['d24'] is None and young['d7'] is None   # no baseline old enough yet


# ------------------------------------------------------------------ items_payload

def test_items_payload_categories_counts_and_value(server_mod, data_dir):
    owned = [
        {'slug': 'a', 'name': 'A', 'count': 2, 'tags': ['prime', 'component'], 'section': 'Primary', 'ducats': 15},
        {'slug': 'a', 'name': 'A', 'tags': ['prime', 'component'], 'section': 'Secondary'},   # count defaults to 1
        {'slug': 'b', 'name': 'B', 'tags': ['mod'], 'section': 'Mods'},
        {'slug': 'c', 'name': 'C', 'tags': ['prime', 'set'], 'section': 'Primary'},
        {'slug': 'd', 'name': 'D', 'tags': ['set'], 'section': 'Suits'},                       # prime-less dup: skipped
    ]
    write_json(data_dir / 'owned.json', owned)
    write_json(data_dir / 'prices.json', {'a': {'wts': 10, 'wtb': 4}, 'b': {'wtb': 3}})
    write_json(data_dir / 'stats.json', {'a': {'vol48': 5, 'median': 11, 'avg48': 12}})

    items = server_mod.items_payload()

    by_slug = {r['slug']: r for r in items}
    assert set(by_slug) == {'a', 'b', 'c'}                       # 'd' dropped
    a = by_slug['a']
    assert a['cat'] == 'prime_part' and a['count'] == 3
    assert a['ducats'] == 15
    assert a['wts'] == 10 and a['wtb'] == 4 and a['vol48'] == 5
    assert a['value'] == 30 and a['spread'] == 6
    assert a['sections'] == 'Primary,Secondary'
    b = by_slug['b']
    assert b['cat'] == 'mod' and b['wts'] is None
    assert b['value'] == 0 and b['spread'] is None                # wtb alone gives no spread
    assert by_slug['c']['cat'] == 'prime_set'
