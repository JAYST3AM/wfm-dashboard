"""scripts/sell_timing.py: hour/weekday bucketing, the SELL_NOW/HOLD rules, and the
data/sell_timing.json contract.

The script takes --root DIR and --now, so every CLI test runs inside tmp_path against a
synthetic trade_log.json - no repo data/ (CI checks out a clean tree) and no network.
Expected clock values are built with the script's own local_tz(), so they hold whether the
machine resolves Australia/Melbourne through zoneinfo or falls back to a fixed UTC+10.
"""
import time
from datetime import datetime, timedelta, timezone

import pytest

from conftest import load_script, read_json, write_json


@pytest.fixture
def stt(monkeypatch):
    return load_script('sell_timing', monkeypatch=monkeypatch)


def at(mod, y, mo, d, h, mi=0, tz=None):
    """Epoch seconds for a local wall time in the script's own timezone."""
    return int(datetime(y, mo, d, h, mi, tzinfo=tz or mod.local_tz()).timestamp())


def sale(ts, name='Wukong Prime Systems Blueprint', total=10):
    return {'ts': ts, 'kind': 'sale', 'name': name, 'qty': 1, 'plat': total, 'total': total}


def write_log(root, events):
    return write_json(root / 'data' / 'trade_log.json', events)


def run(stt, root, *extra):
    return stt.main(['sell_timing.py', '--root', str(root), *extra])


# ------------------------------------------------------------------ pure logic

@pytest.mark.parametrize('tags,want', [
    (['relic', 'axi'], 'relic'),
    (['mod', 'rare'], 'mod'),
    (['arcane_enhancement', 'legendary'], 'arcane'),
    (['component', 'weapon', 'prime'], 'prime_part'),
    (['blueprint', 'warframe', 'prime'], 'prime_bp'),
    (['prime', 'set'], 'prime_set'),
    (['component', 'weapon'], 'other'),
    (['relic', 'mod'], 'relic'),                 # first match wins, exactly like server.py
    ([], 'other'),
    (None, 'other'),
])
def test_cat_of_matches_the_dashboard_tag_chain(stt, tags, want):
    assert stt.cat_of(tags) == want


@pytest.mark.parametrize('name,want', [
    ('Axi A1 Relic', 'relic'),
    ('Meso N15', 'relic'),
    ('Requiem Relic', 'relic'),
    ('Arcane Energize', 'arcane'),
    ('Octavia Prime Chassis Blueprint', 'prime_part'),
    ('Scourge Prime Barrel', 'prime_part'),
    ('Wukong Prime Blueprint', 'prime_bp'),
    ('Octavia Prime Set', 'prime_set'),
    ('Pathocyst Blade', 'other'),
    ('Galvanized Chamber', 'other'),             # name rules alone cannot know it is a mod
    ('', 'other'),
])
def test_name_kind_fallback_rules(stt, name, want):
    assert stt.name_kind(name) == want


def test_kind_of_prefers_local_tags_then_falls_back(stt):
    idx = {'Galvanized Chamber': {'mod'}, 'Axi A1 Relic': {'relic', 'axi'}}
    assert stt.kind_of('Galvanized Chamber', idx) == 'mod'
    assert stt.kind_of('Octavia Prime Chassis Blueprint', idx) == 'prime_part'
    assert stt.kind_of('Axi A1', {}) == 'relic' and stt.kind_of('Axi A1', None) == 'relic'


def test_bucket_tallies_hours_weekdays_cells_and_kinds(stt):
    tz = timezone(timedelta(hours=10))

    def ts(h, mi=0):                             # 2026-09-21 is a Monday
        return int(datetime(2026, 9, 21, h, mi, tzinfo=tz).timestamp())

    events = [sale(ts(2)), sale(ts(2, 30), 'Arcane Energize', 100), sale(ts(3, 10), 'Axi A1 Relic', 8),
              {'ts': ts(4), 'kind': 'purchase', 'name': 'X', 'total': 99},      # not a sale
              {'ts': ts(5), 'kind': 'sale', 'name': 'Y'}]                       # no total/plat

    b = stt.bucket(stt.trade_events(events), tz)

    assert b['hours'][2] == [2, 110] and b['hours'][3] == [1, 8]
    assert b['hours'][4] == [0, 0] and b['hours'][5] == [1, 0]     # plat falls back to 0
    assert b['weekdays'][0] == [4, 118] and b['weekdays'][1] == [0, 0]
    assert b['cells'][(0, 2)] == [2, 110] and b['cells'][(0, 5)] == [1, 0]
    assert sorted(b['kind_hours']) == ['arcane', 'other', 'prime_part', 'relic']
    assert b['kind_hours']['arcane'][2] == [1, 100]
    assert b['kind_hours']['prime_part'][2] == [1, 10]
    assert stt.trade_events([{'ts': 1, 'kind': 'note', 'name': 'Z'}]) == []


def test_rank_hours_and_best_windows_tie_breaks(stt):
    hours = stt.hour_rows([[0, 0] for _ in range(24)])
    hours[1] = {'hour': 1, 'sales': 2, 'plat': 30}
    hours[5] = {'hour': 5, 'sales': 2, 'plat': 10}
    hours[9] = {'hour': 9, 'sales': 2, 'plat': 30}          # ties hour 1 on sales+plat: lower hour wins

    assert [h['hour'] for h in stt.rank_hours(hours)[:3]] == [1, 9, 5]

    cells = {(1, 2): [2, 9], (2, 9): [2, 9], (3, 4): [2, 5], (0, 0): [1, 99], (6, 6): [1, 99]}
    win = stt.best_windows(cells, limit=3)
    assert [(w['dow'], w['hour']) for w in win] == [(1, 2), (2, 9), (3, 4)]
    assert win[0]['plat'] == 9
    assert stt.best_windows(cells, limit=99) == stt.best_windows(cells, limit=len(cells))
    assert stt.best_windows({}) == []


def test_next_slot_is_strictly_future(stt):
    tz = timezone(timedelta(hours=10))
    one = [{'dow': 0, 'hour': 2, 'sales': 5, 'plat': 50}]

    assert stt.next_slot(one, datetime(2026, 9, 21, 1, 0, tzinfo=tz))['label'] == 'Mon 02:00 (in 1h)'
    assert stt.next_slot(one, datetime(2026, 9, 21, 1, 1, tzinfo=tz))['label'] == 'Mon 02:00 (in 59m)'
    # the slot is exactly now -> next week's, not "in 0s"
    assert stt.next_slot(one, datetime(2026, 9, 21, 2, 0, tzinfo=tz))['label'] == 'Mon 02:00 (in 7.0d)'
    assert stt.next_slot([], datetime(2026, 9, 21, 1, 0, tzinfo=tz)) is None

    multi = one + [{'dow': 1, 'hour': 20, 'sales': 3, 'plat': 30}]
    slot = stt.next_slot(multi, datetime(2026, 9, 21, 2, 30, tzinfo=tz))
    assert (slot['dow'], slot['hour']) == (1, 20)                 # Tue 20:00 beats next Monday
    assert slot['label'].startswith('Tue 20:00 (in ')


def test_decide_requires_a_top_hour_and_real_sample(stt):
    tz = timezone(timedelta(hours=10))
    hours = stt.hour_rows([[0, 0] for _ in range(24)])
    hours[2] = {'hour': 2, 'sales': 6, 'plat': 60}
    hours[9] = {'hour': 9, 'sales': 4, 'plat': 400}
    windows = [{'dow': 0, 'hour': 2, 'sales': 6, 'plat': 60}]

    verdict, reason, slot = stt.decide(datetime(2026, 9, 21, 2, 30, tzinfo=tz), hours, windows)
    assert verdict == 'SELL_NOW' and 'top-3 sale hour (6 sales, 60p in sample)' in reason
    assert (slot['dow'], slot['hour']) == (0, 2)                  # next week's slot
    assert set(slot) == {'dow', 'hour', 'label'}

    verdict, reason, _ = stt.decide(datetime(2026, 9, 21, 9, 30, tzinfo=tz), hours, windows)
    assert verdict == 'HOLD' and 'has 4 sales in sample' in reason    # top hour, but thin
    assert stt.decide(datetime(2026, 9, 21, 9, 30, tzinfo=tz), hours, windows, min_sales=4)[0] == 'SELL_NOW'

    verdict, reason, slot = stt.decide(datetime(2026, 9, 21, 15, 0, tzinfo=tz), hours, windows)
    assert verdict == 'HOLD' and 'has 0 sales in sample' in reason
    assert 'top hours 02:00, 09:00' in reason                     # zero-sample hours never pad the list
    assert slot['label'].startswith('Mon 02:00')
    assert stt.decide(datetime(2026, 9, 21, 9, 30, tzinfo=tz), hours, windows, top_n=1)[0] == 'HOLD'
    assert stt.decide(datetime(2026, 9, 21, 2, 30, tzinfo=tz), hours, windows, top_n=1)[0] == 'SELL_NOW'


def test_parse_now_accepts_epoch_iso_and_none(stt):
    tz = stt.local_tz()
    assert stt.parse_now('1700000000', tz) == 1700000000
    assert stt.parse_now('1700000000.0', tz) == 1700000000
    assert stt.parse_now('2026-09-21T02:00', tz) == at(stt, 2026, 9, 21, 2, 0)
    assert stt.parse_now('2026-09-21T00:00:00Z', tz) == int(
        datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc).timestamp())
    assert abs(stt.parse_now(None, tz) - time.time()) < 5


def test_local_tz_falls_back_when_zoneinfo_is_missing(stt, monkeypatch):
    monkeypatch.setattr(stt, 'ZoneInfo', None)
    assert stt.local_tz().utcoffset(datetime(2026, 9, 21)) == timedelta(hours=10)


def test_local_tz_falls_back_on_an_empty_tz_database(stt, monkeypatch):
    monkeypatch.setattr(stt, 'TZ_NAME', 'Nowhere/Nothing')
    assert stt.local_tz().utcoffset(datetime(2026, 9, 21)) == timedelta(hours=10)


# ------------------------------------------------------------------ tag index

def test_tags_index_owned_first_and_catalog_fills(stt, tmp_path, data_dir):
    write_json(data_dir / 'owned.json', [{'name': 'A', 'tags': ['mod']}, {'name': 'B'}, 'junk'])
    write_json(data_dir / 'wfm_items_v2.json',
               {'data': [{'i18n': {'en': {'name': 'A'}}, 'tags': ['relic']},
                         {'i18n': {'en': {'name': 'B'}}, 'tags': ['relic', 'axi']},
                         {'name': 'C', 'tags': ['prime', 'set']}, 'junk']})

    idx = stt.tags_index(str(data_dir))

    assert idx == {'A': {'mod'}, 'B': {'relic', 'axi'}, 'C': {'prime', 'set'}}
    assert stt.tags_index(str(tmp_path / 'no-such-dir')) == {}


# ------------------------------------------------------------------ sell_timing.json contract

def test_main_writes_the_contract(stt, tmp_path):
    mon2 = at(stt, 2026, 9, 21, 2, 0)
    write_log(tmp_path,
              [sale(mon2 + 60 * i) for i in range(5)]
              + [sale(mon2 + 1800, 'Galvanized Chamber', 40)]
              + [sale(at(stt, 2026, 9, 22, 9, 0), 'Wukong Prime Blueprint', 120)])
    now = mon2 + 15 * 60

    assert run(stt, tmp_path, '--now', str(now)) == 0

    out = tmp_path / 'data' / 'sell_timing.json'
    assert out.exists() and not (tmp_path / 'data' / (out.name + '.tmp')).exists()
    doc = read_json(out)
    assert set(doc) == {'generated', 'generated_local', 'tz', 'hours', 'weekdays', 'best_windows',
                        'verdict', 'verdict_reason', 'next_window', 'by_kind', 'sample'}
    assert doc['generated'] == now and doc['tz'] == 'Australia/Melbourne'
    assert doc['generated_local'] == datetime.fromtimestamp(now, stt.local_tz()).strftime(
        '%Y-%m-%d %H:%M')

    hours = doc['hours']
    assert [h['hour'] for h in hours] == list(range(24))
    assert all(set(h) == {'hour', 'sales', 'plat'} for h in hours)
    assert hours[2] == {'hour': 2, 'sales': 6, 'plat': 90}
    assert hours[9] == {'hour': 9, 'sales': 1, 'plat': 120}
    assert sum(h['sales'] for h in hours) == 7 and sum(h['plat'] for h in hours) == 210

    weekdays = doc['weekdays']
    assert [w['dow'] for w in weekdays] == list(range(7))
    assert all(set(w) == {'dow', 'sales', 'plat'} for w in weekdays)
    assert weekdays[0] == {'dow': 0, 'sales': 6, 'plat': 90}
    assert weekdays[1] == {'dow': 1, 'sales': 1, 'plat': 120}
    assert sum(w['sales'] for w in weekdays) == 7

    assert all(set(w) == {'dow', 'hour', 'sales', 'plat'} for w in doc['best_windows'])
    assert [(w['dow'], w['hour']) for w in doc['best_windows']] == [(0, 2), (1, 9)]
    assert doc['verdict'] == 'SELL_NOW'
    assert 'top-3 sale hour (6 sales, 90p in sample)' in doc['verdict_reason']
    assert set(doc['next_window']) == {'dow', 'hour', 'label'}
    assert (doc['next_window']['dow'], doc['next_window']['hour']) == (1, 9)   # Tue 09:00
    assert doc['next_window']['label'].startswith('Tue 09:00 (in ')

    kinds = doc['by_kind']
    assert list(kinds) == ['prime_part', 'other', 'prime_bp']      # by sales, then name
    assert set(kinds['prime_part']) == {'sales', 'plat', 'best_hours'}
    assert kinds['prime_part'] == {'sales': 5, 'plat': 50,
                                   'best_hours': [{'hour': 2, 'sales': 5, 'plat': 50}]}
    assert kinds['prime_bp']['best_hours'] == [{'hour': 9, 'sales': 1, 'plat': 120}]
    assert kinds['prime_bp']['note'] == 'thin sample (1 sale) - hours are a hint only'
    assert kinds['other']['sales'] == 1                            # Galvanized Chamber, no tags
    assert 'note' not in kinds['prime_part']

    sample = doc['sample']
    assert (sample['sales_total'], sample['active_days'], sample['span_days']) == (7, 2, 1.3)
    assert (sample['first_sale'], sample['last_sale']) == ('2026-09-21', '2026-09-22')
    assert '7 sales over 2 active day(s) in a 1.3d window' in sample['note']
    assert 'thin sample - treat windows as hints, not rules' in sample['note']
    assert 'no sample for relic/arcane/prime_set' in sample['note']


def test_main_kind_split_prefers_local_tags_over_name_rules(stt, tmp_path):
    ts = at(stt, 2026, 9, 21, 2, 0)
    write_log(tmp_path, [sale(ts + 60 * i, 'Galvanized Chamber', 8) for i in range(5)])
    write_json(tmp_path / 'data' / 'owned.json',
               [{'slug': 'galvanized_chamber', 'name': 'Galvanized Chamber', 'count': 3,
                 'tags': ['mod', 'rare']}])
    write_json(tmp_path / 'data' / 'wfm_items_v2.json',
               {'data': [{'i18n': {'en': {'name': 'Arcane Energize'}},
                          'tags': ['arcane_enhancement']}]})

    assert run(stt, tmp_path, '--now', str(ts)) == 0

    doc = read_json(tmp_path / 'data' / 'sell_timing.json')
    assert list(doc['by_kind']) == ['mod']        # name rules alone would report 'other'
    assert doc['by_kind']['mod'] == {'sales': 5, 'plat': 40,
                                     'best_hours': [{'hour': 2, 'sales': 5, 'plat': 40}]}
    assert doc['verdict'] == 'SELL_NOW'
    assert doc['sample']['sales_total'] == 5


def test_thin_sample_is_labelled_not_dressed_up(stt, tmp_path):
    ts = at(stt, 2026, 9, 21, 2, 0)
    write_log(tmp_path, [sale(ts, 'Axi A1 Relic', 5), sale(ts + 60, 'Arcane Energize', 30)])

    assert run(stt, tmp_path, '--now', str(ts)) == 0

    doc = read_json(tmp_path / 'data' / 'sell_timing.json')
    sample = doc['sample']
    assert (sample['sales_total'], sample['active_days'], sample['span_days']) == (2, 1, 0.0)
    assert 'thin sample - treat windows as hints, not rules' in sample['note']
    assert '1/24 hours and 1/7 weekdays have sample' in sample['note']
    assert list(doc['by_kind']) == ['arcane', 'relic']
    for kind in ('arcane', 'relic'):
        assert doc['by_kind'][kind]['note'] == 'thin sample (1 sale) - hours are a hint only'
    assert doc['verdict'] == 'HOLD'               # 2 sales is nowhere near the 5-sale bar
    assert 'has 2 sales in sample' in doc['verdict_reason']


def test_cli_top_and_min_sales_flags_and_iso_now(stt, tmp_path):
    mon = at(stt, 2026, 9, 21, 0, 0)
    write_log(tmp_path, [sale(mon + 2 * 3600 + 60 * i) for i in range(5)]        # Mon 02:00 x5
              + [sale(mon + 9 * 3600 + 60 * i, 'Adaptation', 20) for i in range(5)])   # Mon 09:00 x5

    assert run(stt, tmp_path, '--now', '2026-09-21T09:30') == 0
    assert read_json(tmp_path / 'data' / 'sell_timing.json')['verdict'] == 'SELL_NOW'

    assert run(stt, tmp_path, '--now', '2026-09-21T02:30') == 0
    assert read_json(tmp_path / 'data' / 'sell_timing.json')['verdict'] == 'SELL_NOW'

    assert run(stt, tmp_path, '--now', '2026-09-21T09:30', '--min-sales', '6') == 0
    assert read_json(tmp_path / 'data' / 'sell_timing.json')['verdict'] == 'HOLD'

    assert run(stt, tmp_path, '--now', '2026-09-21T02:30', '--top', '1') == 0
    doc = read_json(tmp_path / 'data' / 'sell_timing.json')
    assert doc['verdict'] == 'HOLD' and 'top hours 09:00;' in doc['verdict_reason']


def test_trade_log_dict_wrapper_is_tolerated(stt, tmp_path):
    ts = at(stt, 2026, 9, 21, 2, 0)
    write_json(tmp_path / 'data' / 'trade_log.json', {'events': [sale(ts, 'Axi A1 Relic', 5)]})

    assert run(stt, tmp_path, '--now', str(ts)) == 0

    assert read_json(tmp_path / 'data' / 'sell_timing.json')['sample']['sales_total'] == 1


def test_no_sales_returns_1_and_writes_nothing(stt, tmp_path):
    write_log(tmp_path, [{'ts': at(stt, 2026, 9, 21, 2, 0), 'kind': 'purchase', 'name': 'X',
                          'total': 5}])
    assert run(stt, tmp_path) == 1
    assert not (tmp_path / 'data' / 'sell_timing.json').exists()

    (tmp_path / 'empty' / 'data').mkdir(parents=True)             # no trade_log.json at all
    assert stt.main(['sell_timing.py', '--root', str(tmp_path / 'empty')]) == 1


def test_bad_flag_exits_2(stt, tmp_path):
    with pytest.raises(SystemExit) as exc:
        run(stt, tmp_path, '--nope')
    assert exc.value.code == 2


def test_selftest_is_offline_and_leaves_no_files(stt, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(stt, 'ROOT', str(tmp_path / 'ghost'))     # proves it needs no data/

    assert stt.main(['sell_timing.py', '--selftest']) == 0

    assert 'selftest OK' in capsys.readouterr().out
    assert not (tmp_path / 'ghost').exists() and not (tmp_path / 'data').exists()
