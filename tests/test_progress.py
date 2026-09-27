"""scripts/progress.py: the progress store contract + the session/day maths.

Offline by construction: WFM_DATA_DIR / WFM_STATIC_DIR are redirected into tmp_path before the
module is exec'd (conftest.load_script(env=...)) and the clock is pinned via mod.now_ts, so no
repo file is read or written and nothing touches the network.

Fixed fixture clock: Wednesday 2026-06-17 20:00 local -> the week starts Mon 2026-06-15, and
the two fixture snapshots are the 16th (reference) and the 17th (today).
"""
import re
from datetime import date, datetime, timedelta

import pytest

from conftest import load_script, read_json, write_json

D13, D15, D16, D17 = (date(2026, 6, 13), date(2026, 6, 15),
                      date(2026, 6, 16), date(2026, 6, 17))
BASE = D17                                              # a Wednesday: week starts Mon D15


def at(d, hh, mm):
    return int(datetime(d.year, d.month, d.day, hh, mm).timestamp())


NOW = at(BASE, 20, 0)

POINTS = [
    {'ts': at(D13, 10, 0), 'plat': 100, 'credits': 1000, 'mr': 10},    # closed session
    {'ts': at(D13, 10, 10), 'plat': 130, 'credits': 900},              # +30 lands on the 13th
    {'ts': at(D15, 9, 0), 'plat': 130, 'credits': 900},                # Monday, this week
    {'ts': at(D16, 23, 50), 'plat': 130, 'credits': 900},              # crosses midnight
    {'ts': at(D17, 0, 5), 'plat': 230, 'credits': 850},                # +100 lands TODAY
    {'ts': at(D17, 19, 50), 'plat': 230, 'credits': 850},              # current session
    {'ts': at(D17, 19, 58), 'plat': 230, 'credits': 850},
]
EVENTS = [
    {'ts': at(D13, 10, 5), 'kind': 'sale', 'name': 'Old Mod', 'qty': 1, 'plat': 7, 'total': 7},
    {'ts': at(D15, 9, 30), 'kind': 'sale', 'name': 'Week Mod', 'qty': 2, 'plat': 10, 'total': 20},
    {'ts': at(D17, 0, 5), 'kind': 'purchase', 'name': 'Today Part', 'qty': 1, 'plat': 5,
     'total': 5},
]
SNAP16 = [{'slug': 'a', 'name': 'A', 'count': 1},
          {'slug': 'b', 'name': 'B', 'count': 1},
          {'slug': 'c', 'name': 'C', 'count': 1}]
SNAP17 = [{'slug': 'a', 'name': 'A', 'count': 1},
          {'slug': 'c', 'name': 'C', 'count': 2},
          {'slug': 'd', 'name': 'D', 'count': 1}]
INVDIFF = dict(generated='2026-06-17 20:00', status='ok',
               snapshot='data/inventory_snapshots/owned_2026-06-17.json',
               reference='data/inventory_snapshots/owned_2026-06-16.json',
               summary=dict(added=1, removed=1, changed=1),
               totals=dict(now=dict(items=3, stacks=4, value=0),
                           previous=dict(items=3, stacks=3, value=0)))
ITEMS = {'schema': 1, 'items': {
    'ferrite_mod': {'name': 'Ferrite Mod',
                    'points': [[at(D17, 19, 45), 1], [at(D17, 19, 55), 3]]},   # gained now
    'shrinking': {'name': 'Shrinking',
                  'points': [[at(D17, 19, 45), 5], [at(D17, 19, 55), 4]]},     # decrease
    'monday_gain': {'name': 'Monday Gain',
                    'points': [[at(D15, 9, 10), 1], [at(D15, 9, 20), 2]]}}}    # gained Monday
MATERIALS = {'schema': 1, 'updated': NOW, 'materials': [
    {'slug': 'ferrite', 'name': 'Ferrite', 'count': 1300},
    {'slug': 'nano_spores', 'name': 'Nano Spores', 'count': 100}]}
MATERIALS_PREV = {'updated': NOW - 3600, 'materials': [
    {'slug': 'ferrite', 'name': 'Ferrite', 'count': 1000},
    {'slug': 'nano_spores', 'name': 'Nano Spores', 'count': 150}]}


def prog(tmp_path, monkeypatch):
    """Module with tmp data/static dirs and the fixture clock pinned."""
    data, static = tmp_path / 'data', tmp_path / 'static'
    data.mkdir()
    mod = load_script('progress', monkeypatch=monkeypatch,
                      env={'WFM_DATA_DIR': str(data), 'WFM_STATIC_DIR': str(static)})
    monkeypatch.setattr(mod, 'now_ts', lambda: NOW)
    return mod, data, static


def write_core(data, points=POINTS, events=EVENTS, gap=45):
    write_json(data / 'plat_history.json', points)
    if events is not None:
        write_json(data / 'trade_log.json', events)
    if gap is not None:
        write_json(data / 'session_stats.json', {'gap_min': gap})


def write_inventory(data, invdiff=INVDIFF):
    write_json(data / 'inventory_snapshots' / 'owned_2026-06-16.json', SNAP16)
    write_json(data / 'inventory_snapshots' / 'owned_2026-06-17.json', SNAP17)
    if invdiff is not None:
        write_json(data / 'invdiff.json', invdiff)


def write_all(data):
    write_core(data)
    write_inventory(data)
    write_json(data / 'item_history.json', ITEMS)
    write_json(data / 'materials.json', MATERIALS)
    write_json(data / 'materials_prev.json', MATERIALS_PREV)


def run(mod, *argv):
    return mod.main(list(argv) if argv else ['--once'])


# ------------------------------------------------------------------ offline fixtures

def test_selftest_passes(tmp_path, monkeypatch):
    mod, _, _ = prog(tmp_path, monkeypatch)
    assert mod.selftest() == 0


def test_main_writes_store_and_static_copy(tmp_path, monkeypatch, capsys):
    mod, data, static = prog(tmp_path, monkeypatch)
    write_all(data)

    assert run(mod) == 0

    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith('progress: today +1 items, +100p, 1 trade, '
                                          '2 sessions (current) | 4 active days | week +100p')
    assert read_json(data / 'progress.json') == read_json(static / 'progress.json')
    assert not (data / 'progress.json.tmp').exists()


def test_store_schema_keys(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    write_all(data)
    run(mod)
    doc = read_json(data / 'progress.json')

    assert list(doc) == ['schema', 'updated', 'updated_iso', 'source', 'notes', 'today',
                         'sessions', 'days', 'streaks']
    assert doc['schema'] == 1 and doc['updated'] == NOW
    assert list(doc['today']) == ['date', 'first_ts', 'last_ts', 'plat_start', 'plat_now',
                                  'plat_delta', 'credits_delta', 'mr', 'items_added',
                                  'items_removed', 'items_total', 'trades', 'sessions',
                                  'materials_gained', 'material_delta_total']
    assert list(doc['today']['trades']) == ['count', 'sales', 'purchases', 'plat_in',
                                            'plat_out']
    assert list(doc['today']['sessions']) == ['count', 'minutes', 'current']
    assert list(doc['sessions'][0]) == ['start_ts', 'start_iso', 'end_ts', 'end_iso',
                                        'minutes', 'current', 'events', 'trades', 'sales',
                                        'plat_start', 'plat_end', 'plat_delta',
                                        'items_gained', 'headline']
    assert list(doc['days'][0]) == ['date', 'plat_delta', 'credits_delta', 'mr', 'trades',
                                    'plat_in', 'plat_out', 'items_added', 'sessions']
    assert list(doc['streaks']) == ['days_active', 'last_active_date', 'hours_this_week',
                                    'trades_this_week', 'plat_this_week']
    assert re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$',
                    doc['updated_iso'])
    assert doc['source'] == ('plat_history.json+trade_log.json+session_stats.json+invdiff.json'
                             '+inventory_snapshots+item_history.json+materials.json'
                             '+materials_prev.json')


def test_today_block_matches_an_independent_rewalk(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    write_all(data)
    run(mod)
    t = read_json(data / 'progress.json')['today']

    # independent re-derivation straight from the fixture: step-walk + raw event scan
    today_plat, prev = 0, None
    for p in sorted(POINTS, key=lambda x: x['ts']):
        if prev is not None and p['plat'] != prev and p['ts'] >= at(D17, 0, 0):
            today_plat += p['plat'] - prev
        prev = p['plat']
    today_trades = [e for e in EVENTS
                    if at(D17, 0, 0) <= e['ts'] < at(D17 + timedelta(days=1), 0, 0)
                    and e['kind'] in ('sale', 'purchase')]

    assert t['date'] == '2026-06-17'
    assert (t['plat_start'], t['plat_now'], t['plat_delta']) == (130, 230, today_plat)
    assert today_plat == 100
    assert t['trades']['count'] == len(today_trades) == 1
    assert t['first_ts'] == at(D17, 0, 5) and t['last_ts'] == at(D17, 19, 58)
    assert t['mr'] == 10 and t['credits_delta'] == -50


def test_plat_step_lands_on_the_day_it_shows(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    write_all(data)
    run(mod)
    days = {r['date']: r for r in read_json(data / 'progress.json')['days']}

    assert days['2026-06-17']['plat_delta'] == 100      # the 00:05 step
    assert days['2026-06-16']['plat_delta'] == 0        # 23:50 mark shows no change
    assert days['2026-06-13']['plat_delta'] == 30       # 10:00 -> 10:10 run
    assert days['2026-06-15']['plat_delta'] == 0
    assert [r['date'] for r in read_json(data / 'progress.json')['days']] == [
        '2026-06-17', '2026-06-16', '2026-06-15', '2026-06-13']   # no empty 06-14 row


def test_day_boundary_session_is_clipped_to_today(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    write_all(data)
    run(mod)
    doc = read_json(data / 'progress.json')

    crossing = doc['sessions'][1]
    assert (crossing['start_ts'], crossing['end_ts']) == (at(D16, 23, 50), at(D17, 0, 5))
    assert crossing['minutes'] == 15.0 and crossing['plat_delta'] == 100
    # today gets only the part after local midnight: 00:00-00:05 + the evening run
    assert doc['today']['sessions'] == {'count': 2, 'minutes': 13.0, 'current': True}
    assert doc['today']['first_ts'] == at(D17, 0, 5)     # not the 23:50 mark
    assert {r['date']: r['sessions'] for r in doc['days']} == {
        '2026-06-17': 2, '2026-06-16': 1, '2026-06-15': 1, '2026-06-13': 1}


def test_current_session_flag(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    write_all(data)
    run(mod)
    doc = read_json(data / 'progress.json')

    assert [s['current'] for s in doc['sessions']] == [True, False, False, False]
    assert doc['today']['sessions']['current'] is True
    assert doc['sessions'][0]['headline'].startswith('idle')
    assert doc['sessions'][1]['headline'] == '1 trade \u00b7 +100p'
    assert doc['sessions'][2]['headline'] == '1 trade \u00b7 +0p \u00b7 +1 items'
    assert doc['sessions'][3]['headline'] == '1 trade \u00b7 +30p'

    # a stale newest mark (10:00, ten hours before the pinned clock) is not current
    write_core(data, points=[dict(p) for p in POINTS
                             if p['ts'] not in (at(D17, 19, 50), at(D17, 19, 58))])
    run(mod)
    doc = read_json(data / 'progress.json')
    assert doc['today']['sessions']['current'] is False
    assert doc['sessions'][0]['current'] is False


# ------------------------------------------------------------------ missing inputs

def test_missing_trade_log_is_noted_and_zero(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    write_core(data, events=None)
    write_inventory(data)

    assert run(mod) == 0
    doc = read_json(data / 'progress.json')
    assert any('trade_log.json' in n for n in doc['notes'])
    assert doc['today']['trades'] == {'count': 0, 'sales': 0, 'purchases': 0,
                                      'plat_in': 0, 'plat_out': 0}
    assert doc['sessions'][0]['events'] == 0


def test_empty_trade_log_is_noted(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    write_core(data, events=[])
    run(mod)
    assert any('empty' in n for n in read_json(data / 'progress.json')['notes'])


def test_missing_plat_history_nulls_the_curve(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    write_core(data)
    (data / 'plat_history.json').unlink()

    assert run(mod) == 0
    doc = read_json(data / 'progress.json')
    t = doc['today']
    assert any('plat_history.json' in n for n in doc['notes'])
    assert (t['plat_start'], t['plat_now'], t['plat_delta'], t['credits_delta'],
            t['mr']) == (None, None, None, None, None)
    assert t['trades']['count'] == 1          # the trade log still counts
    assert all(r['plat_delta'] is None for r in doc['days'])
    assert doc['streaks']['plat_this_week'] is None
    assert 'plat n/a' in mod.summary_line(doc)


def test_no_readable_inputs_exits_1(tmp_path, monkeypatch, capsys):
    mod, data, static = prog(tmp_path, monkeypatch)

    assert run(mod) == 1
    assert 'no readable inputs' in capsys.readouterr().out
    assert not (data / 'progress.json').exists()
    assert not (static / 'progress.json').exists()


def test_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    mod, data, static = prog(tmp_path, monkeypatch)
    write_all(data)

    assert run(mod, '--dry-run') == 0
    out = capsys.readouterr().out
    assert 'dry-run - nothing written' in out
    assert not (data / 'progress.json').exists()
    assert not (static / 'progress.json').exists()


def test_out_flag_and_no_static_copy(tmp_path, monkeypatch):
    mod, data, static = prog(tmp_path, monkeypatch)
    write_all(data)
    target = tmp_path / 'elsewhere' / 'progress.json'

    assert run(mod, '--out', str(target), '--no-static-copy') == 0
    assert read_json(target)['schema'] == 1
    assert not (static / 'progress.json').exists()
    assert not (data / 'progress.json').exists()


# ------------------------------------------------------------------ history depth

def test_days_flag_windows_days_and_sessions(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    write_all(data)

    assert run(mod, '--days', '2') == 0
    doc = read_json(data / 'progress.json')
    assert [r['date'] for r in doc['days']] == ['2026-06-17', '2026-06-16']
    assert [s['start_ts'] for s in doc['sessions']] == [at(D17, 19, 50), at(D16, 23, 50)]

    assert run(mod, '--days', '1') == 0
    doc = read_json(data / 'progress.json')
    assert [r['date'] for r in doc['days']] == ['2026-06-17']
    assert doc['streaks']['days_active'] == 4            # streaks are all-time, not windowed

    assert run(mod) == 0                                 # default 30 keeps the 13th
    assert len(read_json(data / 'progress.json')['days']) == 4


def test_streak_maths(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    write_all(data)
    run(mod)
    streaks = read_json(data / 'progress.json')['streaks']

    week_start = BASE - timedelta(days=BASE.weekday())   # Mon 2026-06-15
    assert week_start == D15
    # this week's session overlap: Mon 09:00-09:30 (30m) + 23:50->00:05 (15m) + 19:50-19:58
    # (8m); the Saturday run is last week
    expected_hours = round((30 + 15 + 8) / 60.0, 2)
    assert streaks == {'days_active': 4, 'last_active_date': '2026-06-17',
                       'hours_this_week': expected_hours,
                       'trades_this_week': 2,        # Mon sale + today's purchase
                       'plat_this_week': 100}        # only the today step is in the week


# ------------------------------------------------------------------ the session gap

def test_gap_comes_from_session_stats_json(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    points = [{'ts': at(D17, 18, 0), 'plat': 10, 'credits': 1},
              {'ts': at(D17, 18, 20), 'plat': 11, 'credits': 1}]

    write_core(data, points=points, events=None, gap=10)   # 20 min apart, gap 10 -> two
    run(mod)
    assert len(read_json(data / 'progress.json')['sessions']) == 2

    write_core(data, points=points, events=None, gap=45)   # gap 45 -> one
    run(mod)
    assert len(read_json(data / 'progress.json')['sessions']) == 1


def test_gap_falls_back_to_45_when_session_stats_missing(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    write_core(data, events=None, gap=None,
               points=[{'ts': at(D17, 18, 0), 'plat': 10, 'credits': 1},
                       {'ts': at(D17, 18, 20), 'plat': 11, 'credits': 1}])
    run(mod)
    doc = read_json(data / 'progress.json')
    assert len(doc['sessions']) == 1                     # session_stats.py's own 45 min
    assert any('45 min' in n for n in doc['notes'])


def test_listing_events_are_not_trades(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    write_core(data, events=[{'ts': at(D17, 18, 10), 'kind': 'listing', 'slug': 'x'}],
               points=[{'ts': at(D17, 18, 0), 'plat': 10, 'credits': 1}])
    run(mod)
    doc = read_json(data / 'progress.json')
    s = doc['sessions'][0]
    assert (s['events'], s['trades'], s['sales']) == (1, 0, 0)
    assert s['headline'] == '1 event \u00b7 +0p'
    assert doc['today']['trades']['count'] == 0


# ------------------------------------------------------------------ inventory deltas

def test_invdiff_wins_when_its_reference_matches(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    inv = dict(INVDIFF, summary=dict(added=5, removed=0, changed=1))
    write_core(data)
    write_inventory(data, invdiff=inv)
    run(mod)
    t = read_json(data / 'progress.json')['today']
    assert (t['items_added'], t['items_removed']) == (5, 0)
    assert t['items_total'] == 3


def test_stale_invdiff_reference_falls_back_to_snapshots(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    inv = dict(INVDIFF, reference='data/inventory_snapshots/owned_2026-06-13.json')
    write_core(data)
    write_inventory(data, invdiff=inv)
    run(mod)
    doc = read_json(data / 'progress.json')
    t = doc['today']
    assert (t['items_added'], t['items_removed']) == (1, 1)   # the 16th -> 17th pair
    assert any('reference' in n for n in doc['notes'])


def test_items_total_without_invdiff_uses_the_newest_snapshot(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    write_core(data)
    write_inventory(data, invdiff=None)
    run(mod)
    assert read_json(data / 'progress.json')['today']['items_total'] == 3


def test_missing_inventory_inputs_are_null_and_noted(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    write_core(data)
    run(mod)
    doc = read_json(data / 'progress.json')
    assert doc['today']['items_added'] is None and doc['today']['items_removed'] is None
    assert doc['today']['items_total'] is None
    assert any('invdiff' in n for n in doc['notes'])


# ------------------------------------------------------------------ items / materials

def test_session_items_gained_counts_increases_only(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    write_all(data)
    run(mod)
    starts = {s['start_ts']: s for s in read_json(data / 'progress.json')['sessions']}

    assert starts[at(D17, 19, 50)]['items_gained'] == 1     # ferrite_mod 1 -> 3; shrinking fell
    assert starts[at(D15, 9, 0)]['items_gained'] == 1       # monday_gain 1 -> 2
    assert starts[at(D16, 23, 50)]['items_gained'] == 0

    (data / 'item_history.json').unlink()
    run(mod)
    doc = read_json(data / 'progress.json')
    assert all(s['items_gained'] is None for s in doc['sessions'])
    assert any('item_history.json' in n for n in doc['notes'])


def test_materials_delta_from_prev_sample(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    write_all(data)
    run(mod)
    t = read_json(data / 'progress.json')['today']
    assert t['materials_gained'] == [{'name': 'Ferrite', 'delta': 300}]   # the drop is ignored
    assert t['material_delta_total'] == 300
    assert any('materials_prev.json' in n for n in read_json(data / 'progress.json')['notes'])

    write_json(data / 'materials_prev.json', dict(MATERIALS_PREV, updated=NOW - 4 * 86400))
    run(mod)
    doc = read_json(data / 'progress.json')
    assert doc['today']['materials_gained'] == [] and doc['today']['material_delta_total'] == 0
    assert any('older than yesterday' in n for n in doc['notes'])

    (data / 'materials_prev.json').unlink()
    run(mod)
    doc = read_json(data / 'progress.json')
    assert doc['today']['materials_gained'] == []
    assert any('no previous materials sample' in n for n in doc['notes'])


def test_missing_materials_json_is_noted(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    write_core(data)
    run(mod)
    doc = read_json(data / 'progress.json')
    assert doc['today']['materials_gained'] == [] and doc['today']['material_delta_total'] == 0
    assert any('materials.json' in n for n in doc['notes'])


# ------------------------------------------------------------------ ISO fields

def test_iso_fields_carry_the_local_offset(tmp_path, monkeypatch):
    mod, data, _ = prog(tmp_path, monkeypatch)
    write_all(data)
    run(mod)
    doc = read_json(data / 'progress.json')
    pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$'
    assert re.match(pattern, doc['updated_iso'])
    assert re.match(pattern, doc['sessions'][0]['start_iso'])
    assert re.match(pattern, doc['sessions'][0]['end_iso'])
    assert doc['sessions'][0]['start_iso'].startswith('2026-06-17T19:50:00')
    assert doc['sessions'][0]['end_iso'].startswith('2026-06-17T19:58:00')


def test_materials_baseline_is_stamped_only_when_missing(tmp_path, monkeypatch):
    """Fresh install: the first run writes a baseline so tomorrow's delta works; an existing
    baseline is never clobbered (a stale one must keep reporting as stale)."""
    mod, data, _ = prog(tmp_path, monkeypatch)
    write_core(data)
    cur = {'updated': NOW - 60, 'materials': [{'slug': 'ferrite', 'name': 'Ferrite', 'count': 1300}]}
    write_json(data / 'materials.json', cur)
    assert not (data / 'materials_prev.json').exists()

    run(mod)
    prev = read_json(data / 'materials_prev.json')
    assert prev['materials'] == cur['materials'], 'the sample is copied verbatim'
    assert prev['stamped'] == '2026-06-17', 'stamped with the sample date'
    assert any('no previous materials sample' in n
               for n in read_json(data / 'progress.json')['notes']), 'this run still says it had none'

    before = (data / 'materials_prev.json').read_text(encoding='utf-8')
    run(mod)
    assert (data / 'materials_prev.json').read_text(encoding='utf-8') == before, 'never clobbered'
    doc = read_json(data / 'progress.json')
    assert any('materials delta vs' in n for n in doc['notes']), 'the second run compares against it'
    assert doc['today']['materials_gained'] == [], 'nothing gained between the two samples'
