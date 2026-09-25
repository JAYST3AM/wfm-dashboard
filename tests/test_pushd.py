"""scripts/pushd.py: trigger markers, digest composition and the state-file contract.

pushd is the cron-side push daemon: it polls the dashboard's data files, composes ONE
digest for whatever is new since the last run and hands it to scripts/notify.py.

Nothing here reaches the network or the repo's real data/: every test redirects
PUSHD_DATA_DIR/PUSHD_STATE_PATH into tmp_path and patches notify.send with a recorder, so
the only thing under test is the marker logic. --selftest is also run in a subprocess to
prove it stays offline and writes nothing into the cwd.
"""
import json
import os
import subprocess
import sys

import pytest

from conftest import SCRIPTS, load_script, read_json, write_json

PUSHD_PATH = os.path.join(SCRIPTS, 'pushd.py')

SALE = {'ts': 1000, 'kind': 'sale', 'name': 'Primed Continuity', 'qty': 1, 'plat': 42,
        'total': 42, 'note': 'with BuyerOne'}
BUY = {'ts': 1001, 'kind': 'purchase', 'name': 'Neo D3 Relic', 'qty': 6, 'plat': 7,
       'total': 42, 'note': 'with SellerOne'}
ALERT = {'level': 'buy', 'slug': 'primed_target_cracker', 'name': 'Primed Target Cracker',
         'floor': 35, 'target': 60, 'distance_p': 25, 'vol48': 129,
         'message': 'BUY Primed Target Cracker: floor 35p <= max_buy 60p'}
LIMITS_OK = {'trades_left': 22, 'trade_cap': 22, 'reset_epoch': 5000,
             'reset_melbourne': '2026-09-26T10:00:00+10:00'}
KILL_OFF = {'active': False, 'note': '', 'ts': 900}
BARO_CLOSED = {'trader': {'active': False, 'character': "Baro Ki'Teer"}}


@pytest.fixture
def data(monkeypatch, tmp_path):
    """Throwaway data/ dir; pushd's env hooks point at it for the whole test."""
    d = tmp_path / 'data'
    d.mkdir()
    monkeypatch.setenv('PUSHD_DATA_DIR', str(d))
    monkeypatch.setenv('PUSHD_STATE_PATH', str(d / 'pushd_state.json'))
    return d


@pytest.fixture
def pushd(monkeypatch, data):
    return load_script('pushd', monkeypatch=monkeypatch)


class Recorder(list):
    """Captured notify.send calls: a list of {title, body, kwargs} dicts.

    Set .reply to steer what the fake sender returns ([] = rule-blocked, a 'failed' row =
    a broken webhook) and .error to make it raise notify.NotifyError. Nothing here can
    reach the real sender, and no test ever un-patches it mid-test.
    """

    reply = None
    error = None

    def __call__(self, title, body='', **kwargs):
        self.append({'title': title, 'body': body, 'kwargs': kwargs})
        if self.error is not None:
            raise self.error
        if self.reply is not None:
            return self.reply
        return [{'ts': 'recorder', 'to': 'recorder', 'title': title, 'body': body,
                 'status': 'dry_run'}]


@pytest.fixture
def sent(monkeypatch, pushd):
    """notify.send replaced by a recorder for the whole test (monkeypatch restores it)."""
    rec = Recorder()
    monkeypatch.setattr(pushd.notify, 'send', rec)
    return rec


def write_inputs(data, events=None, alerts=None, limits=None, kill=None, baro=None):
    write_json(data / 'trade_log.json', [SALE, BUY] if events is None else events)
    write_json(data / 'watchlist.json', {'alerts': [ALERT] if alerts is None else alerts})
    write_json(data / 'trader_limits.json', LIMITS_OK if limits is None else limits)
    write_json(data / 'kill_switch.json', KILL_OFF if kill is None else kill)
    write_json(data / 'baro.json', BARO_CLOSED if baro is None else baro)
    return data


def paths_of(pushd):
    return pushd.resolve_paths()


def data_files(data):
    return sorted(os.listdir(str(data)))


# ------------------------------------------------------------------ offline selftest

def test_selftest_runs_offline_and_passes(tmp_path):
    proc = subprocess.run([sys.executable, PUSHD_PATH, '--selftest'],
                          capture_output=True, text=True, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.rstrip().endswith('selftest OK (tmp fixtures only, notify.send '
                                         'patched to a recorder, no network)')
    assert 'FAIL' not in proc.stdout
    assert not (tmp_path / 'data').exists()          # selftest writes nothing into the cwd


def test_env_hooks_redirect_every_path(pushd, data):
    paths = paths_of(pushd)
    assert paths['state'] == str(data / 'pushd_state.json')
    for name in pushd.INPUTS:
        assert paths[name[:-5]] == str(data / name)
    assert paths['data'] == str(data)


def test_reads_only_and_writes_only_the_state_file(pushd, data, sent, monkeypatch):
    write_inputs(data)
    replaced = []
    real_replace = pushd.os.replace

    def spy(src, dst):
        replaced.append((os.path.basename(src), os.path.basename(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(pushd.os, 'replace', spy)
    assert pushd.run(paths_of(pushd), now=2000) == 0
    pushd.run(paths_of(pushd), now=2001)
    assert data_files(data) == ['baro.json', 'kill_switch.json', 'pushd_state.json',
                                'trade_log.json', 'trader_limits.json', 'watchlist.json']
    assert replaced == [('pushd_state.json.tmp', 'pushd_state.json')] * 2   # atomic writes only


# ------------------------------------------------------------------------ first run

def test_first_run_baselines_and_writes_the_documented_state(pushd, data, sent):
    write_inputs(data)
    assert pushd.run(paths_of(pushd), now=2000) == 0
    assert sent == []                                # pre-existing events are never spammed
    st = read_json(data / 'pushd_state.json')
    assert sorted(st) == ['baro', 'digests_sent', 'kill_switch', 'last_digest_utc',
                          'last_run_utc', 'limits', 'trade_log', 'version', 'watch_alerts']
    assert st['version'] == 1 and st['digests_sent'] == 0 and st['last_digest_utc'] is None
    assert st['last_run_utc'].endswith('Z')
    assert st['trade_log']['last_ts'] == 1001 and len(st['trade_log']['sigs']) == 2
    assert st['watch_alerts']['seen'] == ['buy|primed_target_cracker|35']
    assert st['limits'] == {'last_window': None}
    assert st['kill_switch'] == {'last_active': False} and st['baro'] == {'last_active': False}
    assert pushd.run(paths_of(pushd), now=2001) == 0 and sent == []


def test_new_sale_fires_once_and_never_again(pushd, data, sent):
    write_inputs(data)
    pushd.run(paths_of(pushd), now=2000)
    fresh = dict(SALE, ts=1500, name='Wukong Prime Systems Blueprint', plat=14, total=14,
                 note='with BuyerTwo')
    write_inputs(data, events=[SALE, BUY, fresh])
    assert pushd.run(paths_of(pushd), now=2001) == 0
    assert len(sent) == 1 and sent[0]['title'] == 'WFM Trader digest'
    assert sent[0]['body'] == '[sale] Wukong Prime Systems Blueprint x1 @ 14p - with BuyerTwo'
    assert sent[0]['kwargs'] == {'rule': 'digest'}   # dry_run is left to notify's own config
    pushd.run(paths_of(pushd), now=2002)
    assert len(sent) == 1
    write_inputs(data, events=[SALE, BUY, fresh, fresh])       # duplicate row
    pushd.run(paths_of(pushd), now=2003)
    assert len(sent) == 1


def test_boundary_second_is_caught_by_signature(pushd, data, sent):
    write_inputs(data)
    pushd.run(paths_of(pushd), now=2000)
    same_second = {'ts': 1001, 'kind': 'sale', 'name': 'Boundary Sale', 'qty': 1, 'plat': 5,
                   'total': 5, 'note': ''}               # same ts as the marker, new items
    write_inputs(data, events=[SALE, BUY, same_second])
    pushd.run(paths_of(pushd), now=2001)
    assert len(sent) == 1 and sent[0]['body'] == '[sale] Boundary Sale x1 @ 5p'
    pushd.run(paths_of(pushd), now=2002)
    assert len(sent) == 1


def test_backfilled_history_is_recorded_but_never_alerted(pushd, data, sent):
    write_inputs(data)
    pushd.run(paths_of(pushd), now=2000)
    old = {'ts': 900, 'kind': 'sale', 'name': 'Backfilled Sale', 'qty': 1, 'plat': 5,
           'total': 5, 'note': 'imported (AlecaFrame)'}
    write_inputs(data, events=[SALE, BUY, old])
    pushd.run(paths_of(pushd), now=2001)
    assert sent == []
    assert any('Backfilled Sale' in sig for sig in read_json(data / 'pushd_state.json')
               ['trade_log']['sigs'])                # recorded, just not messaged


def test_non_alert_kinds_are_recorded_without_a_line(pushd, data, sent):
    write_inputs(data)
    pushd.run(paths_of(pushd), now=2000)
    write_inputs(data, events=[SALE, BUY,
                               {'ts': 1500, 'kind': 'reprice', 'name': 'Primed Continuity',
                                'qty': 1, 'plat': 40, 'total': 40, 'note': 'price 42p -> 40p'}])
    pushd.run(paths_of(pushd), now=2001)
    assert sent == []


def test_purchase_uses_its_own_prefix_and_shows_the_total(pushd, data, sent):
    write_inputs(data)
    pushd.run(paths_of(pushd), now=2000)
    write_inputs(data, events=[SALE, BUY,
                               {'ts': 1500, 'kind': 'purchase', 'name': 'Neo D3 Relic',
                                'qty': 6, 'plat': 7, 'total': 42, 'note': 'with SellerTwo'}])
    pushd.run(paths_of(pushd), now=2001)
    assert sent and sent[0]['body'] == \
        '[buy] Neo D3 Relic x6 @ 7p each (42p total) - with SellerTwo'


def test_signature_list_is_capped(pushd, data, sent, monkeypatch):
    monkeypatch.setattr(pushd, 'SIG_KEEP', 3)
    write_inputs(data, events=[dict(SALE, ts=1000 + i, name='Item %d' % i) for i in range(6)])
    pushd.run(paths_of(pushd), now=2000)
    st = read_json(data / 'pushd_state.json')
    assert len(st['trade_log']['sigs']) == 3 and st['trade_log']['last_ts'] == 1005


# ------------------------------------------------------------------------- watchlist

def test_watch_alerts_dedupe_on_level_slug_floor(pushd, data, sent):
    write_inputs(data)
    pushd.run(paths_of(pushd), now=2000)
    sell = dict(ALERT, level='sell', slug='galvanized_hell', name='Galvanized Hell', floor=8,
                message='SELL Galvanized Hell: floor 8p >= min_sell 6p')
    write_inputs(data, alerts=[ALERT, sell])
    pushd.run(paths_of(pushd), now=2001)
    assert len(sent) == 1 and sent[0]['body'] == \
        '[watch] SELL Galvanized Hell: floor 8p >= min_sell 6p'
    pushd.run(paths_of(pushd), now=2002)
    assert len(sent) == 1                                # same key, no repeat
    write_inputs(data, alerts=[ALERT, sell, dict(ALERT, floor=99)])
    pushd.run(paths_of(pushd), now=2003)
    assert len(sent) == 2                                # same level+slug, new floor -> new key
    write_inputs(data, alerts=[])                        # alerts leaving the file changes nothing
    pushd.run(paths_of(pushd), now=2004)
    assert len(sent) == 2


# --------------------------------------------------------------------- limits / safety

def test_limits_fire_once_per_reset_window(pushd, data, sent):
    write_inputs(data)
    pushd.run(paths_of(pushd), now=2000)
    write_inputs(data, limits=dict(LIMITS_OK, trades_left=0))
    pushd.run(paths_of(pushd), now=2001)
    assert len(sent) == 1 and sent[0]['body'] == \
        '[limits] trades exhausted - 0/22 left, resets 2026-09-26T10:00:00+10:00'
    pushd.run(paths_of(pushd), now=2002)
    assert len(sent) == 1                                # same window, quiet
    write_inputs(data, limits=dict(LIMITS_OK, trades_left=0, reset_epoch=6000,
                                   reset_melbourne='2026-09-27T10:00:00+10:00'))
    pushd.run(paths_of(pushd), now=2003)
    assert len(sent) == 2                                # new reset window fires again
    write_inputs(data, limits=dict(LIMITS_OK, trades_left=22, reset_epoch=6000))
    pushd.run(paths_of(pushd), now=2004)
    assert len(sent) == 2                                # trades back: nothing to say


def test_kill_switch_transitions_and_fail_closed(pushd, data, sent):
    write_inputs(data)
    pushd.run(paths_of(pushd), now=2000)
    write_inputs(data, kill={'active': True, 'note': 'manual', 'ts': 1000})
    pushd.run(paths_of(pushd), now=2001)
    assert len(sent) == 1 and sent[0]['body'] == '[safety] kill switch ARMED - manual'
    pushd.run(paths_of(pushd), now=2002)
    assert len(sent) == 1                                # armed is a state, not a repeat
    write_inputs(data, kill={'active': False, 'note': '', 'ts': 1001})
    pushd.run(paths_of(pushd), now=2003)
    assert len(sent) == 1                                # disarm is silent
    (data / 'kill_switch.json').write_text('{not json', encoding='utf-8')
    pushd.run(paths_of(pushd), now=2004)
    assert len(sent) == 2 and sent[1]['body'] == \
        '[safety] kill switch ARMED - unreadable - fail-closed'
    pushd.run(paths_of(pushd), now=2005)
    assert len(sent) == 2                                # reported once, not every run
    write_inputs(data, kill={'active': False, 'note': '', 'ts': 1002})
    pushd.run(paths_of(pushd), now=2006)
    write_inputs(data, kill={'active': True, 'note': 'again', 'ts': 1003})
    pushd.run(paths_of(pushd), now=2007)
    assert len(sent) == 3 and sent[2]['body'].endswith('- again')


def test_baro_window_transition_fires_once(pushd, data, sent):
    write_inputs(data)
    pushd.run(paths_of(pushd), now=2000)
    open_baro = {'trader': {'active': True, 'character': "Baro Ki'Teer",
                            'location': 'Kronia Relay (Saturn)',
                            'expiry_text': 'Sun 2026-10-04 13:00 UTC'}}
    write_inputs(data, baro=open_baro)
    pushd.run(paths_of(pushd), now=2001)
    assert len(sent) == 1 and sent[0]['body'] == \
        "[baro] Baro Ki'Teer window open - Kronia Relay (Saturn), closes Sun 2026-10-04 13:00 UTC"
    pushd.run(paths_of(pushd), now=2002)
    assert len(sent) == 1


# -------------------------------------------------------------------- digest grouping

def test_digest_groups_every_due_trigger_into_one_ordered_send(pushd, data, sent):
    write_inputs(data)
    pushd.run(paths_of(pushd), now=2000)
    write_inputs(data)
    pushd.run(paths_of(pushd), now=2001)                 # steady state
    write_inputs(data,
                 events=[SALE, BUY, {'ts': 3000, 'kind': 'sale', 'name': 'Trinity Prime '
                                     'Systems Blueprint', 'qty': 3, 'plat': 9, 'total': 27,
                                     'note': 'with BuyerThree'}],
                 alerts=[ALERT, dict(ALERT, slug='arcane_energize', level='sell', floor=150,
                                     name='Arcane Energize',
                                     message='SELL Arcane Energize: floor 150p >= min_sell 140p')],
                 limits=dict(LIMITS_OK, trades_left=0),
                 kill={'active': True, 'note': 'grouped'},
                 baro={'trader': {'active': True, 'character': "Baro Ki'Teer",
                                  'location': 'Kronia Relay (Saturn)',
                                  'expiry_text': 'Sun 2026-10-04 13:00 UTC'}})
    assert pushd.run(paths_of(pushd), now=2002) == 0
    assert len(sent) == 1                                # five triggers, ONE digest
    body = sent[0]['body'].split('\n')
    assert [line.split(' ', 1)[0] for line in body] == \
        ['[safety]', '[baro]', '[limits]', '[sale]', '[watch]']
    assert body[3] == '[sale] Trinity Prime Systems Blueprint x3 @ 9p each (27p total) ' \
                      '- with BuyerThree'
    assert body[4] == '[watch] SELL Arcane Energize: floor 150p >= min_sell 140p'
    assert read_json(data / 'pushd_state.json')['digests_sent'] == 1
    pushd.run(paths_of(pushd), now=2003)
    assert len(sent) == 1


def test_digest_body_is_capped(pushd, data, sent, monkeypatch):
    monkeypatch.setattr(pushd, 'MAX_LINES', 2)
    write_inputs(data)
    pushd.run(paths_of(pushd), now=2000)
    write_inputs(data, events=[SALE, BUY] + [dict(SALE, ts=2000 + i, name='Item %d' % i)
                                             for i in range(4)])
    pushd.run(paths_of(pushd), now=2001)
    body = sent[0]['body'].split('\n')
    assert len(body) == 3 and body[2] == '(+2 more this run)'
    assert pushd.compose(['x' * 3000])[1].endswith('...')


# ------------------------------------------------------------------- state handling

def test_print_composes_without_sending_or_writing_state(pushd, data, sent):
    write_inputs(data)
    pushd.run(paths_of(pushd), now=2000)
    write_inputs(data, events=[SALE, BUY, dict(SALE, ts=4000, name='Preview Sale', plat=3,
                                               total=3, note='')])
    before = (data / 'pushd_state.json').read_bytes()
    assert pushd.run(paths_of(pushd), print_only=True, now=2001) == 0
    assert sent == [] and (data / 'pushd_state.json').read_bytes() == before
    assert pushd.run(paths_of(pushd), now=2002) == 0     # still pending, then delivered
    assert len(sent) == 1 and sent[0]['body'] == '[sale] Preview Sale x1 @ 3p'


def test_unreadable_state_starts_a_fresh_baseline(pushd, data, sent):
    write_inputs(data)
    pushd.run(paths_of(pushd), now=2000)
    (data / 'pushd_state.json').write_text('{broken', encoding='utf-8')
    assert pushd.run(paths_of(pushd), now=2001) == 0
    st = read_json(data / 'pushd_state.json')
    assert sorted(st) == ['baro', 'digests_sent', 'kill_switch', 'last_digest_utc',
                          'last_run_utc', 'limits', 'trade_log', 'version', 'watch_alerts']
    assert sent == []                                    # the history is not replayed
    write_json(data / 'pushd_state.json', ['not', 'an', 'object'])
    assert pushd.run(paths_of(pushd), now=2002) == 0 and sent == []


def test_missing_input_files_are_survived(pushd, data, sent):
    assert pushd.run(paths_of(pushd), now=2000) == 0     # empty data dir: nothing to read
    assert sent == [] and read_json(data / 'pushd_state.json')['digests_sent'] == 0
    write_json(data / 'trade_log.json', {})              # wrong shape entirely
    assert pushd.run(paths_of(pushd), now=2001) == 0 and sent == []


# --------------------------------------------------------------------- delivery paths

def test_rule_blocked_digest_keeps_the_lines_pending(pushd, data, sent):
    write_inputs(data)
    pushd.run(paths_of(pushd), now=2000)
    write_inputs(data, events=[SALE, BUY, dict(SALE, ts=5000, name='Pending Sale')])
    sent.reply = []                                      # rules.digest = false in notify
    assert pushd.run(paths_of(pushd), now=2001) == 0
    assert len(sent) == 1                                # it did try; notify said no
    assert read_json(data / 'pushd_state.json')['trade_log']['last_ts'] == 1001
    sent.reply = None                                    # rule re-enabled, rules only
    assert pushd.run(paths_of(pushd), now=2002) == 0
    assert len(sent) == 2 and '[sale] Pending Sale' in sent[1]['body']
    assert read_json(data / 'pushd_state.json')['trade_log']['last_ts'] == 5000


def test_failed_delivery_returns_1_and_keeps_the_lines_pending(pushd, data, sent):
    write_inputs(data)
    pushd.run(paths_of(pushd), now=2000)
    write_inputs(data, events=[SALE, BUY, dict(SALE, ts=6000, name='Retry Me')])
    sent.reply = [{'status': 'failed', 'to': 'hook'}]
    assert pushd.run(paths_of(pushd), now=2001) == 1
    assert read_json(data / 'pushd_state.json')['trade_log']['last_ts'] == 1001
    assert read_json(data / 'pushd_state.json')['digests_sent'] == 0
    sent.reply = [{'status': 'sent', 'to': 'hook'}]      # webhook back up
    assert pushd.run(paths_of(pushd), now=2002) == 0
    st = read_json(data / 'pushd_state.json')
    assert st['trade_log']['last_ts'] == 6000 and st['digests_sent'] == 1 \
        and st['last_digest_utc'].endswith('Z')
    assert sent[-1]['body'] == '[sale] Retry Me x1 @ 42p - with BuyerOne'


def test_notify_config_problem_is_reported(pushd, data, sent):
    write_inputs(data)
    pushd.run(paths_of(pushd), now=2000)
    write_inputs(data, events=[SALE, BUY, dict(SALE, ts=7000, name='Blocked Sale')])
    sent.error = pushd.notify.NotifyError('no webhooks in data/notify_config.json')
    assert pushd.run(paths_of(pushd), now=2001) == 1
    assert read_json(data / 'pushd_state.json')['trade_log']['last_ts'] == 1001
    sent.error = None
    assert pushd.run(paths_of(pushd), now=2002) == 0     # nothing was lost on the error


# ------------------------------------------------------------------------------- main

def test_main_default_cycle_and_print_flag(pushd, data, sent):
    write_inputs(data)
    assert pushd.main(['pushd.py']) == 0
    assert (data / 'pushd_state.json').exists()
    write_inputs(data, events=[SALE, BUY, dict(SALE, ts=8000, name='CLI Sale')])
    assert pushd.main(['pushd.py', '--once', '--print']) == 0
    assert sent == [] and read_json(data / 'pushd_state.json')['trade_log']['last_ts'] == 1001
    assert pushd.main(['pushd.py', '--once']) == 0
    assert len(sent) == 1 and sent[0]['body'] == '[sale] CLI Sale x1 @ 42p - with BuyerOne'
