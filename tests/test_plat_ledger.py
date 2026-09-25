"""scripts/plat_ledger.py: window math, the reconciliation verdict and the JSON contract.

Everything runs against synthetic fixtures under tmp_path: the module takes --root DIR,
so no repo data/ file is read and no repo file is written. The EE.log probe is fed a
synthetic log; nothing here touches the real Warframe install or the network.
"""
import time
from datetime import datetime, timedelta, timezone

import pytest

from conftest import load_script, read_json, write_json

TZ = timezone(timedelta(hours=10))          # fixed UTC+10 so fixtures do not need tzdata


@pytest.fixture
def pl(monkeypatch):
    return load_script('plat_ledger', monkeypatch=monkeypatch)


def ts(y, mo, d, h=12, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp())


def ev(t, kind, total, name='Item'):
    return {'ts': t, 'kind': kind, 'total': total, 'name': name}


def write_inputs(root, readings, events):
    write_json(root / 'data' / 'plat_history.json', readings)
    write_json(root / 'data' / 'trade_log.json', events)


def run(pl, root, *extra):
    return pl.main(['plat_ledger.py', '--root', str(root), *extra])


# ------------------------------------------------------------------ pure logic

def test_norm_points_sorts_skips_junk_and_defaults_source(pl):
    pts = pl.norm_points([{'ts': 300, 'plat': 5}, {'ts': 100, 'plat': 1, 'src': 'alecaframe'},
                          {'ts': 200}, {'plat': 9}, 'nonsense', {'ts': '400', 'plat': '7'}], TZ)
    assert [(p['ts'], p['plat'], p['src']) for p in pts] == [
        (100, 1, 'alecaframe'), (300, 5, 'tracker'), (400, 7, 'tracker')]


def test_balance_anchors_collapse_a_day_and_keep_the_newest_reading(pl):
    readings = pl.norm_points([{'ts': ts(2026, 9, 10, 8), 'plat': 100},
                               {'ts': ts(2026, 9, 10, 9), 'plat': 100},      # heartbeat, same
                               {'ts': ts(2026, 9, 10, 20), 'plat': 140},     # day moves
                               {'ts': ts(2026, 9, 11, 1), 'plat': 120}], TZ)

    anchors = pl.balance_anchors(readings, TZ)

    assert [a['date'] for a in anchors] == ['2026-09-10', '2026-09-11']
    assert [a['plat'] for a in anchors] == [140, 120]
    assert anchors[0]['readings'] == 3 and anchors[0]['first_plat'] == 100
    assert anchors[0]['intraday_swing'] == 40


def test_window_trades_is_half_open_on_the_left_edge(pl):
    events = [ev(100, 'sale', 5), ev(150, 'sale', 10), ev(200, 'purchase', 4),
              ev(250, 'note', 0), ev(250, 'sale', 1), ev(300, 'sale', 99)]

    assert pl.window_trades(events, 100, 250) == (3, 11, 4)     # 100 excluded, 250 included
    assert pl.window_trades(events, 0, 99) == (0, 0, 0)
    assert pl.window_trades(events, 300, 500) == (0, 0, 0)      # boundary, not after it


def test_window_rows_reconcile_delta_into_trades_plus_other(pl):
    readings = pl.norm_points([{'ts': ts(2026, 9, 10), 'plat': 1000},
                               {'ts': ts(2026, 9, 11), 'plat': 1300},
                               {'ts': ts(2026, 9, 12), 'plat': 700}], TZ)
    events = [ev(ts(2026, 9, 11, 9), 'sale', 300),              # fully explains +300
              ev(ts(2026, 9, 12, 9), 'sale', 100),
              ev(ts(2026, 9, 12, 10), 'purchase', 150)]         # 700-1300 = -600 vs -50

    shown, all_rows = pl.window_rows(pl.balance_anchors(readings, TZ), events, TZ)

    assert [r['date'] for r in shown] == ['2026-09-12', '2026-09-11']   # newest first
    clean = {r['date']: r for r in all_rows}['2026-09-11']
    assert (clean['delta'], clean['trades_net'], clean['other_net'], clean['inferred_spend']) \
        == (300, 300, 0, 0)
    dirty = {r['date']: r for r in all_rows}['2026-09-12']
    assert (dirty['delta'], dirty['trades_net'], dirty['other_net'], dirty['inferred_spend']) \
        == (-600, -50, -550, 550)
    assert dirty['window_from'] == '2026-09-11' and dirty['window_days'] == 1
    assert dirty['trades'] == 2 and dirty['earned'] == 100 and dirty['spent'] == 150


def test_window_rows_skip_dead_windows_unless_asked(pl):
    readings = pl.norm_points([{'ts': ts(2026, 9, 1), 'plat': 500},
                               {'ts': ts(2026, 9, 2), 'plat': 500}], TZ)
    anchors = pl.balance_anchors(readings, TZ)

    shown, all_rows = pl.window_rows(anchors, [], TZ)
    assert (len(shown), len(all_rows)) == (0, 1)

    shown, _ = pl.window_rows(anchors, [], TZ, include_zero=True)
    assert len(shown) == 1 and shown[0]['delta'] == 0

    # a zero-trade day that still carries balance movement is always listed
    moving = pl.norm_points([{'ts': ts(2026, 9, 1), 'plat': 500},
                             {'ts': ts(2026, 9, 2), 'plat': 400}], TZ)
    shown, _ = pl.window_rows(pl.balance_anchors(moving, TZ), [], TZ)
    assert [(r['date'], r['trades'], r['inferred_spend']) for r in shown] == \
        [('2026-09-02', 0, 100)]


def test_check_reconciliation_passes_on_clean_rows_and_names_every_failure(pl):
    readings = pl.norm_points([{'ts': ts(2026, 9, 10), 'plat': 100},
                               {'ts': ts(2026, 9, 11), 'plat': 160},
                               {'ts': ts(2026, 9, 12), 'plat': 90}], TZ)
    events = [ev(ts(2026, 9, 11, 5), 'sale', 60), ev(ts(2026, 9, 12, 5), 'purchase', 70)]
    anchors = pl.balance_anchors(readings, TZ)
    _, rows = pl.window_rows(anchors, events, TZ)

    verdict = pl.check_reconciliation(rows, anchors, events, 0.0)
    assert verdict['reconciles'] is True and verdict['failures'] == []
    assert set(verdict['checks']) == {'window_identity', 'balance_chain', 'trade_coverage',
                                      'day_uniqueness', 'reading_integrity'}
    assert verdict['tolerance'] == 0.0 and 'reconciles' in verdict['note']

    # a tampered residual must fail window_identity and say so, not be smoothed over
    broken = [dict(rows[0], other_net=rows[0]['other_net'] + 1)] + rows[1:]
    bad = pl.check_reconciliation(broken, anchors, events, 0.0)
    assert bad['reconciles'] is False and bad['failures'] == ['window_identity']
    assert 'NOT RECONCILED' in bad['note'] and 'delta - (trades_net + other_net)' in bad['note']

    # a row that tallies more events than the log holds is a coverage failure
    mismatch = [dict(rows[0], trades=rows[0]['trades'] + 1)] + rows[1:]
    covered = pl.check_reconciliation(mismatch, anchors, events, 0.0)
    assert covered['failures'] == ['trade_coverage']
    assert 'tallied them' in covered['checks']['trade_coverage']['detail']

    # a duplicated window day breaks the day list (and is reported as such)
    dupe = pl.check_reconciliation(rows + [dict(rows[0], date=rows[1]['date'])], anchors,
                                   events, 0.0)
    assert dupe['reconciles'] is False and 'day_uniqueness' in dupe['failures']


def test_check_reconciliation_tolerance_is_honoured(pl):
    readings = pl.norm_points([{'ts': ts(2026, 9, 10), 'plat': 100},
                               {'ts': ts(2026, 9, 11), 'plat': 175}], TZ)
    anchors = pl.balance_anchors(readings, TZ)
    _, rows = pl.window_rows(anchors, [], TZ)
    tampered = [dict(rows[0], other_net=rows[0]['other_net'] - 5)]

    assert pl.check_reconciliation(tampered, anchors, [], 0.0)['reconciles'] is False
    loose = pl.check_reconciliation(tampered, anchors, [], 5.0)
    assert loose['reconciles'] is True and loose['tolerance'] == 5.0


def test_probe_ee_log_reads_real_style_lines_without_parsing_them(pl, tmp_path):
    log = tmp_path / 'EE.log'
    log.write_text(
        '0.080 Sys [Diag]: Build Label: 2026.09.24.13.29 Retail Windows x64 [Stripped]\n'
        '8359.099 Script [Info]: ThemedDetailedPurchaseDialog.lua: DBG: HudVis 1\n'
        '8359.317 Script [Info]: ThemedDetailedPurchaseDialog.lua: '
        'PopulateInfo->/Lotus/Types/StoreItems/Packages/WarframeBundles/NarinItemsBundle\n'
        '10346.877 Script [Info]: Dialog.lua: Dialog::CreateOkCancel('
        'description=/Lotus/Language/Menu/PurchaseInProgress, title= leftItem=nil)\n'
        '10347.119 Sys [Info]: Created /Lotus/Interface/PurchaseCelebration.swf\n'
        '12790.873 Script [Info]: CheckInventoryOwnership.lua: [CheckInventoryOwnership] '
        '/Lotus/Types/StoreItems/AvatarImages/AvatarImageAmirAccoladeGlyph is not there. Fail\n'
        '12584.090 Net [Info]: Reusing id=15898, previously had RusherSuit, new object: X\n'
        '12816.340 Sys [Info]: Spot-building /Lotus/Types/StoreItems/Consumables/CipherBlueprint\n'
        '8359.116 Sys [Info]: ResourceLoader 0x401 (/Lotus/Levels/Episodes/'
        'MarketBundleNarinSupporterPack.level) Found 9,319 items to load\n',
        encoding='utf-8')

    ee = pl.probe_ee_log(str(log), tail_bytes=65536)

    assert ee['found'] is True and ee['size'] == log.stat().st_size
    assert ee['keywords']['purchase'] == 4 and ee['keywords']['storeitems'] == 3
    assert ee['keywords']['rush'] == 1 and ee['keywords']['market'] == 1
    assert ee['tail_keywords'] == ee['keywords']                # everything is in the tail
    assert ee['buckets']['ui_dialog'] == 4                      # 4 purchase lines, all dialog
    assert ee['buckets']['entity_noise'] == 1
    assert ee['parsed'] is False and ee['records'] == [] and ee['candidates'] == 0
    assert 'no stable purchase format' in ee['format_note']
    assert ee['coverage'].startswith('0 of the ledger totals')
    assert len(ee['samples']['purchase']) == 3                  # newest samples only
    assert ee['samples']['purchase'][-1].startswith('10347.119 Sys')


def test_probe_ee_log_separates_tail_counts_and_parses_a_stable_shape(pl, tmp_path):
    log = tmp_path / 'EE.log'
    # the purchase-shaped lines sit at the TOP: the tail window below must not see them
    lines = ['999.001 Script [Info]: Shop: purchased item 11 for platinum 101\n',
             '999.002 Script [Info]: Shop: purchased item 12 for platinum 102\n',
             '999.003 Script [Info]: Shop: purchased item 13 for platinum 103\n']
    lines += ['%d.001 Sys [Info]: filler line %d\n' % (n, n) for n in range(1, 40)]
    log.write_text(''.join(lines), encoding='utf-8')

    whole = pl.probe_ee_log(str(log), tail_bytes=10_000_000)
    assert (whole['parsed'], len(whole['records'])) == (True, 3)
    assert sorted(r['plat'] for r in whole['records']) == [101, 102, 103]
    assert 'stable item+platinum line shape found' in whole['format_note']
    assert whole['tail_keywords']['purchase'] == 3

    tail = pl.probe_ee_log(str(log), tail_bytes=100)             # same log, tiny tail window
    assert tail['keywords']['purchase'] == 3 and tail['tail_keywords']['purchase'] == 0
    assert tail['parsed'] is True                               # parsing scans the whole file


def test_probe_ee_log_missing_file_and_off(pl):
    missing = pl.probe_ee_log(str('C:/definitely/not/here/EE.log'))
    assert (missing['found'], missing['size'], missing['parsed']) == (False, None, False)
    assert 'nothing to parse' in missing['format_note']

    off = pl.probe_ee_log('')
    assert (off['found'], off['parsed']) == (False, False)
    assert 'not probed' in off['format_note']


def test_export_inventory_reports_every_array_and_cross_checks_trades(pl, tmp_path):
    path = write_json(tmp_path / 'exp.json', {
        'trades': [{'ts': '2026-09-01T00:00:00.000Z', 'tx': [], 'rx': [], 'totalPlat': 9},
                   {'ts': '2026-09-02T00:00:00.000Z', 'tx': [], 'rx': [], 'totalPlat': 4}],
        'generalDataPoints': [{'ts': '2026-09-01T00:00:00.000Z', 'plat': 100, 'credits': 5,
                               'endo': 1, 'platGain': 3}],
        'primeResurgenceVaults': [{'name': 'Nezha', 'ts': 'x'}],
        'userHash': 'abc', 'publicParts': 0, 'usernameWhenPublic': None,
    })

    arrays, scalars, points, note = pl.export_inventory(path, {'earned': 7, 'spent': 6,
                                                               'net': 1, 'kinds': {}, 'events': 2})

    assert [a['name'] for a in arrays] == ['trades', 'generalDataPoints', 'primeResurgenceVaults']
    assert [a['beyond_known'] for a in arrays] == [False, False, True]
    assert [a['rows'] for a in arrays] == [2, 1, 1]
    assert [a['type'] for a in arrays] == ['list', 'list', 'list']
    assert 'endo' in arrays[1]['fields'] and 'platGain' in arrays[1]['fields']
    assert 'match' in arrays[0]['note']                        # 13 totalPlat == 7 + 6
    assert 'not imported' in arrays[2]['note']
    assert len(points) == 1 and 'primeResurgenceVaults' in note
    assert sorted(s['name'] for s in scalars) == ['publicParts', 'userHash', 'usernameWhenPublic']

    # an object (dict) at top level is an array-shaped entry too: report, never import
    obj_arrays, _, _, _ = pl.export_inventory(
        write_json(tmp_path / 'obj.json', {'miscBlob': {'a': 1, 'b': 2}}), {'earned': 0, 'spent': 0})
    assert obj_arrays[0]['type'] == 'object' and obj_arrays[0]['fields'] == ['a', 'b']


# ------------------------------------------------------------------ CLI contract

def test_main_writes_the_plat_ledger_contract(pl, tmp_path, capsys):
    write_inputs(
        tmp_path,
        readings=[{'ts': ts(2026, 9, 10, 10), 'plat': 1000, 'credits': 1, 'src': 'alecaframe'},
                  {'ts': ts(2026, 9, 11, 10), 'plat': 1150, 'credits': 2, 'src': 'alecaframe'},
                  {'ts': ts(2026, 9, 11, 22), 'plat': 1150, 'credits': 2},          # heartbeat
                  {'ts': ts(2026, 9, 12, 10), 'plat': 900, 'credits': 3, 'src': 'alecaframe'}],
        events=[ev(ts(2026, 9, 11, 5), 'sale', 150),
                ev(ts(2026, 9, 12, 5), 'sale', 50),
                ev(ts(2026, 9, 12, 6), 'purchase', 25),
                ev(ts(2026, 9, 12, 7), 'note', 0, 'swap')])

    assert run(pl, tmp_path) == 0

    doc = read_json(tmp_path / 'data' / 'plat_ledger.json')
    assert set(doc) == {'generated', 'sources', 'totals', 'days', 'shown', 'all_days',
                        'self_check', 'notes'}
    assert doc['all_days'] is False and doc['shown'] == 2 == len(doc['days'])
    assert doc['generated'].startswith(time.strftime('%Y-%m-%d'))

    assert set(doc['sources']) == {'plat_history', 'trade_log', 'export_arrays', 'export_note',
                                   'ee_log'}
    assert doc['sources']['plat_history']['readings'] == 4
    assert doc['sources']['plat_history']['by_source'] == {'alecaframe': 3, 'tracker': 1}
    assert doc['sources']['plat_history']['duplicate_ts_conflicts'] == []
    assert doc['sources']['trade_log']['kinds'] == {'sale': 2, 'purchase': 1, 'note': 1}
    assert doc['sources']['export_arrays'] == []
    assert doc['sources']['ee_log']['found'] is False               # off unless asked

    assert doc['days'][0]['date'] == '2026-09-12'
    assert set(doc['days'][0]) >= {'date', 'balance', 'delta', 'trades_net', 'other_net',
                                   'inferred_spend'}
    assert (doc['days'][0]['balance'], doc['days'][0]['delta'], doc['days'][0]['trades_net'],
            doc['days'][0]['other_net'], doc['days'][0]['inferred_spend']) == \
        (900, -250, 25, -275, 275)
    assert doc['days'][0]['readings'] == 1 and doc['days'][0]['window_days'] == 1
    assert doc['days'][1]['date'] == '2026-09-11'
    assert (doc['days'][1]['delta'], doc['days'][1]['trades_net'], doc['days'][1]['other_net']) \
        == (150, 150, 0)

    t = doc['totals']
    assert (t['trades_earned_plat'], t['trades_spent_plat']) == (200, 25)
    assert t['in_game_spent_inferred_plat'] == 275 and t['other_net_plat'] == -275
    assert t['current_balance'] == 900 and t['first_balance'] == 1000
    assert t['balance_change_plat'] == -100 and t['windows'] == 2
    assert t['inferred_windows'] == 1 and t['trades_net_covered_plat'] == 175

    assert doc['self_check']['reconciles'] is True and doc['self_check']['tolerance'] == 0.0
    assert doc['self_check']['failures'] == []
    assert 'reconciles: 5/5 checks pass' in doc['self_check']['note']
    assert any('RESIDUAL' in n for n in doc['notes'])

    out = capsys.readouterr().out
    assert 'plat ledger: 4 readings over 3 day(s)' in out
    assert 'inferred in-game spend 275p' in out
    assert 'wrote data/plat_ledger.json' in out


def test_main_all_flag_lists_dead_windows_and_last_caps_rows(pl, tmp_path):
    write_inputs(tmp_path,
                 readings=[{'ts': ts(2026, 9, 1), 'plat': 500}, {'ts': ts(2026, 9, 2), 'plat': 500},
                           {'ts': ts(2026, 9, 3), 'plat': 400}, {'ts': ts(2026, 9, 4), 'plat': 350}],
                 events=[])
    assert run(pl, tmp_path, '--all', '--last', '2') == 0

    doc = read_json(tmp_path / 'data' / 'plat_ledger.json')
    assert doc['all_days'] is True and doc['totals']['windows'] == 3 and doc['shown'] == 2
    assert [d['date'] for d in doc['days']] == ['2026-09-04', '2026-09-03']
    assert doc['totals']['windows_without_movement'] == 1
    assert doc['days'][1]['inferred_spend'] == 100


def test_main_reports_outside_span_trades_and_missing_trade_log(pl, tmp_path, capsys):
    write_inputs(tmp_path,
                 readings=[{'ts': ts(2026, 9, 10), 'plat': 100}, {'ts': ts(2026, 9, 11), 'plat': 70}],
                 events=[ev(ts(2026, 9, 1), 'sale', 30)])            # before the first reading
    assert run(pl, tmp_path) == 0

    doc = read_json(tmp_path / 'data' / 'plat_ledger.json')
    assert doc['totals']['trades_net_covered_plat'] == 0
    assert doc['totals']['trades_net_outside_windows_plat'] == 30
    assert doc['totals']['trades_outside_windows'] == 1
    assert doc['totals']['in_game_spent_inferred_plat'] == 30
    assert doc['self_check']['reconciles'] is True

    (tmp_path / 'data' / 'trade_log.json').write_text('[]', encoding='utf-8')
    assert run(pl, tmp_path) == 0
    assert 'trade_log.json is empty' in capsys.readouterr().out


def test_main_flags_a_reconciliation_failure_instead_of_hiding_it(pl, tmp_path, capsys):
    write_inputs(tmp_path,
                 readings=[{'ts': ts(2026, 9, 10), 'plat': 100}, {'ts': ts(2026, 9, 11), 'plat': 90},
                           {'ts': ts(2026, 9, 11), 'plat': 85}],     # same ts, two balances
                 events=[])

    assert run(pl, tmp_path) == 0

    doc = read_json(tmp_path / 'data' / 'plat_ledger.json')
    assert doc['self_check']['reconciles'] is False
    assert doc['self_check']['failures'] == ['reading_integrity']
    assert doc['self_check']['note'].startswith('NOT RECONCILED')
    assert doc['notes'][0].startswith('RECONCILIATION FAILED')
    assert doc['sources']['plat_history']['duplicate_ts_conflicts'] == \
        [{'ts': ts(2026, 9, 11), 'plat': 90, 'other': 85}]
    out = capsys.readouterr().out
    assert 'self_check: NOT RECONCILED' in out and 'reading_integrity' in out


def test_main_merges_export_daily_points_without_duplicating_readings(pl, tmp_path):
    write_inputs(tmp_path,
                 readings=[{'ts': ts(2026, 9, 10), 'plat': 100, 'src': 'alecaframe'}],
                 events=[])
    export = write_json(tmp_path / 'export.json', {
        'trades': [], 'publicParts': 0,
        'generalDataPoints': [{'ts': '2026-09-10T02:00:00.000Z', 'plat': 100, 'credits': 1},
                              {'ts': '2026-09-12T02:00:00.000Z', 'plat': 60, 'credits': 2}],
        'relicLog': [],
    })

    assert run(pl, tmp_path, '--export', export) == 0

    doc = read_json(tmp_path / 'data' / 'plat_ledger.json')
    # the 2026-09-10 point duplicates a reading (same ts) and is not merged twice
    assert doc['sources']['plat_history']['readings'] == 2
    assert doc['sources']['plat_history']['by_source'] == {'alecaframe': 1, 'export': 1}
    assert [a['beyond_known'] for a in doc['sources']['export_arrays']] == [False, False, True]
    assert 'merged 1 new reading' in doc['sources']['export_note']
    assert any(n.startswith('AlecaFrame export:') for n in doc['notes'])


def test_main_probes_ee_log_only_when_asked_and_keeps_it_out_of_totals(pl, tmp_path):
    write_inputs(tmp_path, readings=[{'ts': ts(2026, 9, 10), 'plat': 100}], events=[])
    log = tmp_path / 'EE.log'
    log.write_text('1.0 Script [Info]: ThemedDetailedPurchaseDialog.lua: DBG: HudVis 1\n'
                   '2.0 Script [Info]: Shop: purchased item A for platinum 55\n',
                   encoding='utf-8')

    assert run(pl, tmp_path, '--ee-log', str(log)) == 0

    doc = read_json(tmp_path / 'data' / 'plat_ledger.json')
    ee = doc['sources']['ee_log']
    assert (ee['found'], ee['parsed']) == (True, False)        # 1 line, below EE_STABLE_MIN
    assert ee['keywords']['purchase'] == 2 and ee['candidates'] == 1
    assert ee['records'] == [] and ee['coverage'].startswith('0 of the ledger totals')
    assert doc['totals']['in_game_spent_inferred_plat'] == 0    # nothing invented from the log
    assert any(n.startswith('EE.log: no stable purchase format') for n in doc['notes'])


def test_main_no_readings_returns_1_and_writes_nothing(pl, tmp_path):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / 'plat_history.json').write_text('[]', encoding='utf-8')

    assert run(pl, tmp_path) == 1
    assert not (tmp_path / 'data' / 'plat_ledger.json').exists()


def test_main_bad_flag_exits_2(pl):
    with pytest.raises(SystemExit) as exc:
        pl.main(['plat_ledger.py', '--nope'])
    assert exc.value.code == 2


def test_selftest_is_offline_and_leaves_no_files(pl, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pl, 'ROOT', str(tmp_path / 'ghost'))    # proves it needs no data/

    assert pl.main(['plat_ledger.py', '--selftest']) == 0

    out = capsys.readouterr().out
    assert 'selftest OK' in out and 'checks' in out
    assert not (tmp_path / 'ghost').exists() and not (tmp_path / 'data').exists()
