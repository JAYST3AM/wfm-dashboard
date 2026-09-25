"""scripts/trader/detector.py v1: 3-signal sale confirmation, weak-candidate rejection,
self-order exclusion and the single-run pidlock (stale-lock recovery).

scripts/trader/ is private (gitignored - absent from a public checkout), so the whole module
skips when the engine is not on disk. Every test runs inside tmp_path: DATA / HERE / AF are
redirected there and the settings CLI is stubbed, so the repo's real data/ directory and Jay's
real AlecaFrame save are never read or written, and no session is ever created.
"""
import hashlib
import importlib.util
import itertools
import json
import os
import re
import subprocess
import sys
import time

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADER = os.path.join(REPO, 'scripts', 'trader')
SRC = os.path.join(TRADER, 'detector.py')

pytestmark = pytest.mark.skipif(
    not os.path.exists(SRC),
    reason='scripts/trader is private (gitignored) - not present in this checkout')

SETTINGS = {'dry_run': True, 'max_new_listings_per_day': 15, 'max_active_listings': 40,
            'undercut_platinum': 1, 'min_price_pct_of_median': 55, 'min_price_platinum': 3,
            'buy_budget_cap_platinum': 0, 'poll_seconds': 15}
NOW = 1790550000
ITEM_MOD = {'id': 'i-galv', 'slug': 'galvanized_chamber', 'tags': ['mod'],
            'i18n': {'en': {'name': 'Galvanized Chamber'}}}
ITEM_PART = {'id': 'i-burston', 'slug': 'burston_prime_stock', 'tags': ['component', 'prime'],
             'i18n': {'en': {'name': 'Burston Prime Stock'}}}
PREV_ORDER = {'slug': 'galvanized_chamber', 'name': 'Galvanized Chamber', 'type': 'sell',
              'qty': 1, 'plat': 40, 'visible': True, 'lane': 'rank 6'}

_seq = itertools.count()


def write_json(p, obj):
    p = str(p)
    os.makedirs(os.path.dirname(p) or '.', exist_ok=True)
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, indent=1)
    return p


def read_json(p):
    with open(str(p), encoding='utf-8') as fh:
        return json.load(fh)


def read_text(p):
    with open(str(p), encoding='utf-8') as fh:
        return fh.read()


def sha(p):
    try:
        return hashlib.sha256(open(str(p), 'rb').read()).hexdigest()
    except OSError:
        return None


class FakeSession:
    """A stand-in for wfm_session.Session - cycle() only uses .user and .my_orders()."""

    def __init__(self, orders, name='TESTER'):
        self.user = {'ingameName': name}
        self._orders = list(orders)

    def my_orders(self):
        return list(self._orders)


def order(oid, item_id=ITEM_MOD['id'], typ='sell', qty=1, plat=40, **extra):
    o = {'id': oid, 'itemId': item_id, 'type': typ, 'quantity': qty, 'platinum': plat,
         'visible': True, 'rank': 6}
    o.update(extra)
    return o


def save_doc(plat=1300, trades=12, ranked=(6, 6, 6)):
    """A decrypted-save stand-in: premium credits, trades left, one mod's ranked copies."""
    return {'PremiumCredits': plat, 'TradesRemaining': trades, 'PlayerLevel': 30,
            'Upgrades': [{'ItemType': '/Lotus/Upgrades/Galv',
                          'UpgradeFingerprint': '{"lvl": %d}' % lvl, 'ItemId': {'$oid': 'x%d' % i}}
                         for i, lvl in enumerate(ranked)]}


def owned_doc(copies=3):
    """owned.json rows matching save_doc()'s ranked copies of galvanized_chamber."""
    return [{'slug': 'galvanized_chamber', 'name': 'Galvanized Chamber', 'count': 1,
             'tags': ['mod'], 'section': 'Upgrades', 'path': '/Lotus/Upgrades/Galv',
             'refinement': None} for _ in range(copies)]


@pytest.fixture
def det(tmp_path, monkeypatch):
    """detector.py as a fresh module with DATA / HERE / AF / the settings CLI redirected."""
    name = 'wfm_detector_%d' % next(_seq)
    spec = importlib.util.spec_from_file_location(name, SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    data = tmp_path / 'data'
    scripts = tmp_path / 'scripts' / 'trader'
    aleca = tmp_path / 'aleca-frame'                    # never Jay's real %LOCALAPPDATA%\AlecaFrame
    data.mkdir()
    scripts.mkdir(parents=True)
    aleca.mkdir()
    write_json(scripts / 'settings.json', SETTINGS)
    stub = tmp_path / 'stub_settings_cli.py'            # stands in for settings.py --show
    stub.write_text('import json\nprint(json.dumps(%r))\n' % (SETTINGS,), encoding='utf-8')
    monkeypatch.setattr(mod, 'DATA', str(data))
    monkeypatch.setattr(mod, 'HERE', str(scripts))
    monkeypatch.setattr(mod, 'AF', str(aleca))
    monkeypatch.setattr(mod, 'SETTINGS_PY', str(stub))
    return mod


def stage(det, tmp_path, *, prev_orders=None, prev_plat=1300, prev_copies=3, save_plat=1300,
          ranked=(6, 6, 6), orders=(), self_orders=None, snapshot=True):
    """Write everything one cycle reads: the save, owned.json, catalog, state, baseline.

    The save is a plaintext JSON file where the live AlecaFrame save would be (refresh.decrypt
    passes plaintext through), so read_save()/read_save_full() are exercised for real.
    """
    data = tmp_path / 'data'
    write_json(tmp_path / 'aleca-frame' / 'lastData.dat', save_doc(plat=save_plat, ranked=ranked))
    write_json(data / 'lastData.dec.json', save_doc(plat=save_plat, ranked=ranked))
    write_json(data / 'owned.json', owned_doc(len(ranked)))
    write_json(data / 'wfm_items_v2.json', {'data': [ITEM_MOD, ITEM_PART]})
    write_json(data / 'trader_state.json',
               {'ts': NOW - 120, 'account': 'TESTER', 'plat': prev_plat, 'trades_left': 12, 'mr': 30,
                'orders': prev_orders or {}, 'last_cycle_events': 0})
    if snapshot:
        prev_save = save_doc(plat=prev_plat, ranked=(6,) * prev_copies)
        write_json(data / 'detector_inventory.json',
                   det.inventory_snapshot(prev_save, owned_doc(prev_copies), ts=NOW - 120,
                                          source='live'))
    if self_orders is not None:
        write_json(data / 'self_orders.json', self_orders)
    return data


def run_cycle(det, orders=(), now=NOW):
    return det.cycle(session=FakeSession(orders), now=now)


# ------------------------------------------------------------ third signal
def test_three_signals_confirm_the_sale_into_the_trade_log(det, tmp_path):
    """order gone + plat up + one owned copy gone = confirmed sale (3/3)."""
    data = stage(det, tmp_path, prev_orders={'o1': dict(PREV_ORDER)}, save_plat=1340,
                 ranked=(6, 6), orders=[])

    summary = run_cycle(det)

    assert (summary['confirmed'], summary['weak'], summary['self_skipped']) == (1, 0, 0)
    assert summary['status'] == 'ok'
    log = read_json(data / 'trade_log.json')
    assert len(log) == 1
    row = log[0]
    assert row['kind'] == 'sale' and row['slug'] == 'galvanized_chamber' and row['qty'] == 1
    assert row['total'] == 40 and row['ts'] == NOW
    assert row['signals'] == {'orders_ok': True, 'plat_ok': True, 'inventory_ok': True}
    assert 'rank 6' in row['evidence']['inventory']

    queue = read_json(data / 'trader_relist_queue.json')
    assert queue[-1]['sold'] == 1 and queue[-1]['status'] == 'pending'
    state = read_json(data / 'trader_state.json')
    assert state['weak_candidates'] == [] and state['orders'] == {} and state['ts'] == NOW
    assert state['last_cycle'] == {'events': 1, 'confirmed': 1, 'weak': 0, 'self_skipped': 0}
    snap = read_json(data / 'detector_inventory.json')
    assert snap['counts']['galvanized_chamber|rank 6'] == 2
    assert snap['slugs']['galvanized_chamber'] == 2 and snap['ts'] == NOW


def test_a_two_signal_sale_is_a_weak_candidate_and_never_reaches_the_trade_log(det, tmp_path):
    """order gone + plat up, but the owned count did not drop - 2/3, so candidate (weak) only."""
    data = stage(det, tmp_path, prev_orders={'o1': dict(PREV_ORDER)}, save_plat=1340,
                 ranked=(6, 6, 6), orders=[])

    summary = run_cycle(det)

    assert (summary['confirmed'], summary['weak']) == (0, 1)
    assert not (data / 'trade_log.json').exists()
    assert not (data / 'trader_relist_queue.json').exists()
    state = read_json(data / 'trader_state.json')
    assert state['last_cycle_events'] == 0
    weak = state['weak_candidates']
    assert len(weak) == 1
    assert weak[0]['note'] == 'candidate (weak)' and weak[0]['status'] == 'candidate (weak)'
    assert weak[0]['signals'] == {'orders_ok': True, 'plat_ok': True, 'inventory_ok': False}
    assert weak[0]['plat'] == 40 and weak[0]['lane'] == 'rank 6'
    assert 'owned count dropped 0' in weak[0]['evidence']['inventory']
    assert 'candidate (weak)' in read_text(data / 'trader_state.json')


def test_without_a_baseline_the_sale_stays_a_weak_candidate(det, tmp_path):
    """First ever cycle: no inventory baseline - honest 2/3, never a confirmed sale."""
    data = stage(det, tmp_path, prev_orders={'o1': dict(PREV_ORDER)}, save_plat=1340,
                 ranked=(6, 6), orders=[], snapshot=False)

    summary = run_cycle(det)

    assert (summary['confirmed'], summary['weak']) == (0, 1)
    assert not (data / 'trade_log.json').exists()
    weak = read_json(data / 'trader_state.json')['weak_candidates']
    assert 'no inventory baseline' in weak[0]['evidence']['inventory']


def test_a_lane_less_v0_baseline_still_confirms_via_the_slug_total(det, tmp_path):
    """A state/baseline written by v0 (no lane keys) must not lose a real sale."""
    data = stage(det, tmp_path, prev_orders={'o1': dict(PREV_ORDER, lane='')}, save_plat=1340,
                 ranked=(6, 6))
    write_json(data / 'detector_inventory.json',
               {'ts': NOW - 120, 'source': 'live', 'rows': 3, 'copies': 3,
                'counts': {'galvanized_chamber': 3}, 'slugs': {'galvanized_chamber': 3}})

    summary = run_cycle(det)

    assert summary['confirmed'] == 1
    row = read_json(data / 'trade_log.json')[0]
    assert row['signals']['inventory_ok'] is True and 'slug total' in row['evidence']['inventory']


def test_inventory_counts_lanes_and_the_slug_total(det):
    """The baseline itself: rank lanes, relic refinements, plain slugs, no double counting."""
    owned = [{'slug': 'ghost', 'count': 69, 'tags': ['mod'], 'section': 'RawUpgrades',
              'path': '/p/Ghost'}]
    owned += owned_doc(2)                                     # 2 Upgrades rows, same path
    owned += [{'slug': 'lith_f1_relic', 'count': 3, 'tags': ['relic'], 'section': 'MiscItems',
               'refinement': 'Radiant', 'path': '/p/Relic'},
              {'slug': 'burston_prime_stock', 'count': 2, 'tags': ['component', 'prime'],
               'section': 'MiscItems', 'path': '/p/Stock'}]
    save = save_doc(ranked=(6, 6))                            # two rank-6 fingerprints

    counts = det.inventory_counts(save, owned)

    assert counts[('ghost', 'rank 0')] == 69
    assert counts[('galvanized_chamber', 'rank 6')] == 2       # not 4 (rows must not inflate it)
    assert counts[('lith_f1_relic', 'radiant')] == 3
    assert counts[('burston_prime_stock', '')] == 2
    assert sum(counts.values()) == sum((o.get('count') or 1) for o in owned)   # no copy is lost
    veiled = [{'slug': 'melee_riven_mod_(veiled)', 'count': 1, 'tags': ['mod'], 'section': 'Upgrades',
               'path': '/p/Riven'} for _ in range(4)]
    riven = det.inventory_counts(
        {'Upgrades': [{'ItemType': '/p/Riven', 'UpgradeFingerprint': '{"lvl":8}'}]}, veiled)
    assert riven == {('melee_riven_mod_(veiled)', 'rank 8'): 1,
                     ('melee_riven_mod_(veiled)', ''): 3}       # no-lvl fingerprints keep the count
    snap = det.inventory_snapshot(save, owned, ts=NOW, source='cached (5m old)')
    assert snap['slugs']['galvanized_chamber'] == 2 and snap['copies'] == 69 + 2 + 3 + 2
    assert snap['source'] == 'cached (5m old)' and snap['counts']['lith_f1_relic|radiant'] == 3


def test_inventory_drop_prefers_the_lane_then_the_slug_total(det):
    prev = {'counts': {'galvanized_chamber|rank 6': 3}, 'slugs': {'galvanized_chamber': 3}}
    cur = {'counts': {'galvanized_chamber|rank 6': 2}, 'slugs': {'galvanized_chamber': 2}}

    assert det.inventory_drop(prev, cur, 'galvanized_chamber', 'rank 6', 1) == (
        True, 'lane rank 6 3->2 (-1)')
    assert det.inventory_drop(prev, cur, 'galvanized_chamber', 'rank 4', 1)[0] is True
    assert det.inventory_drop(cur, cur, 'galvanized_chamber', 'rank 6', 1)[0] is False
    assert det.inventory_drop(prev, cur, 'galvanized_chamber', 'rank 6', 2)[0] is False
    assert det.inventory_drop(None, cur, 'galvanized_chamber', 'rank 6', 1)[1] == 'no inventory baseline yet'


def test_inventory_is_read_from_the_same_save_path_as_platinum(det, tmp_path):
    """Live save first (as read_save does), then the cached decrypt when the live one is gone."""
    stage(det, tmp_path)

    save, source, err = det.read_save_full()
    assert err is None and source == 'live' and save['PremiumCredits'] == 1300
    assert det.read_save()['plat'] == 1300                   # v0 reader agrees with the v1 one

    os.remove(str(tmp_path / 'aleca-frame' / 'lastData.dat'))
    save, source, err = det.read_save_full()
    assert err is None and save['PremiumCredits'] == 1300
    assert source.startswith('cached (') and source.endswith('m old)')


# ------------------------------------------------------------ v0 behaviour
def test_v0_churn_kinds_still_land_in_the_trade_log(det, tmp_path):
    """A reprice is not a sale - it still reaches the trade log exactly like v0, no candidates."""
    data = stage(det, tmp_path, prev_orders={'o1': dict(PREV_ORDER, plat=40)}, save_plat=1300)

    summary = run_cycle(det, [order('o1', plat=41)])

    assert summary['confirmed'] == 0 and summary['weak'] == 0
    log = read_json(data / 'trade_log.json')
    assert [r['kind'] for r in log] == ['reprice'] and log[0]['plat'] == 41
    assert read_json(data / 'trader_state.json')['weak_candidates'] == []


def test_order_gone_with_flat_plat_is_an_unlist_not_a_candidate(det, tmp_path):
    data = stage(det, tmp_path, prev_orders={'o1': dict(PREV_ORDER)}, save_plat=1300, ranked=(6, 6, 6))

    summary = run_cycle(det, [])

    assert (summary['confirmed'], summary['weak']) == (0, 0)
    assert [r['kind'] for r in read_json(data / 'trade_log.json')] == ['unlist']
    assert read_json(data / 'trader_state.json')['weak_candidates'] == []


# ------------------------------------------------------------ self orders
def test_self_created_orders_are_excluded_from_sale_inference(det, tmp_path):
    """A marked order that vanished (relist churn) must not become a sale or a candidate."""
    data = stage(det, tmp_path, prev_orders={'o1': dict(PREV_ORDER)}, save_plat=1340, ranked=(6, 6),
                 self_orders=['o1'])

    summary = run_cycle(det, [])

    assert (summary['confirmed'], summary['weak'], summary['self_skipped']) == (0, 0, 1)
    assert not (data / 'trade_log.json').exists()               # nothing else to log either
    state = read_json(data / 'trader_state.json')
    assert state['weak_candidates'] == []
    skip = state['self_skipped'][-1]
    assert skip['order_id'] == 'o1' and 'sale inference skipped' in skip['note']
    assert skip['slug'] == 'galvanized_chamber' and skip['qty'] == 1


def test_classify_skips_self_ids_and_still_infers_real_sales(det):
    prev = {'o1': dict(PREV_ORDER), 'o2': dict(PREV_ORDER, slug='galvanized_chamber')}

    events = det.classify(prev, {}, 40, {'o1'})

    assert [e['kind'] for e in events] == ['self', 'sale']
    assert events[0]['note'] == 'lister-managed order - sale inference skipped'
    assert [e['kind'] for e in det.classify(prev, {}, 40)] == ['sale', 'sale']
    # a partial fill on a self order is churn too (the lister shrank its own stack)
    assert [e['kind'] for e in det.classify({'o1': {'slug': 'x', 'type': 'sell', 'qty': 5, 'plat': 10}},
                                            {'o1': {'slug': 'x', 'type': 'sell', 'qty': 4, 'plat': 10}},
                                            30, ['o1'])] == ['self']
    # a relist (new id) is not news either
    assert det.classify({}, {'o1': {'slug': 'x', 'type': 'sell', 'qty': 1, 'plat': 10}}, 0, ['o1']) == []


def test_self_order_cli_marks_lists_and_unmarks(det, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(det, '_killswitch_blocked', lambda: False)
    f = tmp_path / 'data' / 'self_orders.json'

    assert det.main(['--mark-self', '12345']) == 0
    assert read_json(f) == ['12345']                            # a plain list of ids
    assert det.main(['--mark-self', '12345']) == 0              # idempotent
    assert 'already marked' in capsys.readouterr().out
    assert det.main(['--mark-self', '999']) == 0
    assert det.main(['--unmark-self', '12345']) == 0
    assert read_json(f) == ['999']
    assert det.main(['--unmark-self', 'nope']) == 0
    assert 'not marked' in capsys.readouterr().out
    assert det.main(['--list-self']) == 0
    listed = capsys.readouterr().out
    assert '999' in listed and '1 order id(s)' in listed
    # a list file that never came from the CLI (hand-edited / dict shape) is tolerated
    write_json(f, {'ids': ['7']})
    assert det.main(['--list-self']) == 0 and '7' in capsys.readouterr().out


# ------------------------------------------------------------ pidlock
def test_stale_lock_recovery_and_the_single_run_rule(det, tmp_path):
    lock = str(tmp_path / 'data' / det.LOCK_NAME)

    ok, info = det.acquire_lock(lock, now=1000)
    assert (ok, info['reason']) == (True, 'acquired')
    assert read_json(lock)['pid'] == os.getpid()

    # a live holder (injected liveness keeps this deterministic) is never taken over
    ok, info = det.acquire_lock(lock, now=1001, alive=lambda pid: True)
    assert not ok and info['reason'] == 'another detector run is active'
    assert info['pid'] == os.getpid() and info['age'] == 1

    # dead pid -> stale -> recovered
    write_json(lock, {'pid': 999999, 'ts': 1000})
    ok, info = det.acquire_lock(lock, now=1002, alive=lambda pid: pid != 999999)
    assert ok and info['stale_pid'] == 999999 and 'dead pid' in info['reason']
    assert read_json(lock)['pid'] == os.getpid() and read_json(lock)['ts'] == 1002

    # a live pid that has not heartbeat-ed past the window -> also stale
    write_json(lock, {'pid': 4242, 'ts': 1000})
    ok, info = det.acquire_lock(lock, now=1000 + det.LOCK_STALE_SECONDS + 1, alive=lambda pid: True)
    assert ok and 'older' in info['reason'] and info['stale_age'] == det.LOCK_STALE_SECONDS + 1

    # fresh live holder -> refused (no takeover, file untouched)
    write_json(lock, {'pid': 4242, 'ts': 1001})
    before = sha(lock)
    ok, info = det.acquire_lock(lock, now=1002, alive=lambda pid: True)
    assert not ok and sha(lock) == before
    assert det.release_lock(lock) is False                      # never steals another run's lock

    assert det.touch_lock(lock) is False                        # ... and never heartbeats it either
    write_json(lock, {'pid': os.getpid(), 'ts': 1000})
    assert det.touch_lock(lock, now=2000) is True
    assert read_json(lock)['ts'] == 2000
    assert det.release_lock(lock) is True and not os.path.exists(lock)
    assert det.release_lock(lock) is False                      # release without a lock is a no-op


def test_a_second_run_is_refused_with_exit_3(det, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(det, '_killswitch_blocked', lambda: False)
    write_json(tmp_path / 'data' / det.LOCK_NAME, {'pid': os.getpid(), 'ts': int(time.time())})

    assert det.main(['--cycle']) == 3
    assert 'another detector run is active' in capsys.readouterr().out


def test_pid_alive_never_signals_the_target(det):
    assert det.pid_alive(os.getpid()) is True
    for bad in (0, -1, None, 'x', ''):
        assert det.pid_alive(bad) is False


def test_loop_exits_cleanly_on_ctrl_c_and_releases_the_lock(det, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(det, '_killswitch_blocked', lambda: False)
    calls = []

    def one_cycle(*a, **k):
        calls.append(1)
        raise KeyboardInterrupt

    monkeypatch.setattr(det, 'cycle', one_cycle)

    assert det.loop() == 0

    assert calls == [1]
    assert 'ctrl-c' in capsys.readouterr().out
    assert not (tmp_path / 'data' / det.LOCK_NAME).exists()     # lock released on the way out


def test_loop_refuses_every_cycle_while_the_kill_switch_is_armed(det, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(det, '_killswitch_blocked', lambda: True)
    monkeypatch.setattr(det, 'cycle', lambda *a, **k: pytest.fail('cycle must not run when armed'))

    assert det.loop() == 2

    assert 'kill switch engaged' in capsys.readouterr().out
    assert not (tmp_path / 'data' / det.LOCK_NAME).exists()
    assert 'kill-switch' in read_text(tmp_path / 'data' / det.LOG_NAME)


def test_loop_polls_at_the_settings_poll_seconds(det, tmp_path, monkeypatch):
    monkeypatch.setattr(det, '_killswitch_blocked', lambda: False)
    seen = {}
    ticks = []

    def fake_cycle(*a, **k):
        ticks.append(1)
        if len(ticks) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(det, 'cycle', fake_cycle)
    monkeypatch.setattr(det, 'read_settings',
                        lambda script=None: ({'dry_run': True, 'poll_seconds': 42}, 'stub'))
    monkeypatch.setattr(det.time, 'sleep', lambda s: seen.setdefault('sleep', s))

    assert det.loop() == 0

    assert seen['sleep'] == 42 and len(ticks) == 2


# ------------------------------------------------------------ settings + log
def test_read_settings_prefers_the_settings_cli(det, tmp_path, monkeypatch):
    stub = tmp_path / 'stub_settings.py'
    stub.write_text('import json\nprint("noise before the json")\n'
                    'print(json.dumps({"dry_run": True, "poll_seconds": 7}))\n', encoding='utf-8')
    monkeypatch.setattr(det, 'SETTINGS_PY', str(stub))

    doc, source = det.read_settings()

    assert doc == {'dry_run': True, 'poll_seconds': 7} and source == 'settings.py --show'


def test_read_settings_falls_back_to_the_local_file(det, tmp_path, monkeypatch):
    bad = tmp_path / 'broken_settings.py'
    bad.write_text('import sys\nsys.exit(1)\n', encoding='utf-8')
    monkeypatch.setattr(det, 'SETTINGS_PY', str(bad))

    doc, source = det.read_settings()

    assert doc == SETTINGS and source == 'settings.json'        # HERE/settings.json fixture


def test_every_cycle_appends_exactly_one_log_line(det, tmp_path):
    data = stage(det, tmp_path, prev_orders={'o1': dict(PREV_ORDER)}, save_plat=1340, ranked=(6, 6))

    run_cycle(det)
    run_cycle(det, now=NOW + 120)

    lines = read_text(data / det.LOG_NAME).strip().split('\n')
    assert len(lines) == 2
    assert 'confirmed 1' in lines[0] and 'weak 0' in lines[0] and 'status ok' in lines[0]
    assert 'confirmed 0' in lines[1] and 'events 0' in lines[1]


# ------------------------------------------------------------ selftest
def test_selftest_covers_the_v0_cases_and_more_offline(det, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(det, '_killswitch_blocked', lambda: True)

    assert det.main(['--selftest']) == 0

    out = capsys.readouterr().out
    m = re.search(r'selftest: all (\d+)/(\d+) checks passed', out)
    assert m and m.group(1) == m.group(2) and int(m.group(2)) >= 9     # v0's 9 grew, all pass
    assert os.listdir(str(tmp_path / 'data')) == []                    # nothing written


def test_armed_kill_switch_refuses_every_mode_with_exit_2(det, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(det, '_killswitch_blocked', lambda: True)

    for argv in (['--cycle'], ['--once'], ['--loop'], ['--mark-self', 'x'], ['--unmark-self', 'x'],
                 ['--list-self']):
        assert det.main(argv) == 2, argv
        assert 'kill switch engaged' in capsys.readouterr().out

    assert det.main(['--selftest']) == 0               # the offline checks are always allowed
    assert 'checks passed' in capsys.readouterr().out
    assert os.listdir(str(tmp_path / 'data')) == []    # nothing was written by any refused mode


def test_selftest_cli_passes_offline():
    r = subprocess.run([sys.executable, SRC, '--selftest'], capture_output=True, text=True,
                       cwd=REPO, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'selftest: all' in r.stdout and 'checks passed' in r.stdout
