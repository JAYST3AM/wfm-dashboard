"""scripts/trader/notify_rules.py: the trader rules gate + dry-run lock in front of notify.py.

scripts/trader/ is private (gitignored - absent from a public checkout), so this module
skips when the engine is not on disk. notify_rules delegates every delivery to
scripts/notify.py, and notify.py keeps its paths in module globals - so the fixtures
redirect BOTH modules' paths into tmp_path and inject the redirected sender core into
notify_rules; the repo's real data/ files are never read or written. HTTP is exercised
only against notify.Sink, a 127.0.0.1 loopback http.server, so the suite never touches
the network.
"""
import importlib.util
import itertools
import json
import os
import sys

import pytest

from conftest import load_script, read_json, write_json

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_PY = os.path.join(REPO, 'scripts', 'trader', 'notify_rules.py')

pytestmark = pytest.mark.skipif(
    not os.path.exists(RULES_PY),
    reason='scripts/trader is private (gitignored) - not present in this checkout')

_seq = itertools.count()

DEFAULT_RULES = {'sale': True, 'undercut': True, 'watchlist_hit': True,
                 'trade_run': False, 'daily_digest': False}
HOOK = {'name': 'my-channel', 'url': '', 'kind': 'discord'}

SALE_EVENT = {'kind': 'sale', 'slug': 'primed_continuity', 'name': 'Primed Continuity',
              'qty': 1, 'plat': 42, 'total': 42, 'note': 'with BuyerOne'}
UNDERCUT_ROW = {'order_id': 'ord-1', 'slug': 'primed_continuity', 'name': 'Primed Continuity',
                'lane': 'rank 0', 'my_price': 45, 'floor': 44, 'proposed': 43,
                'action': 'reprice', 'reason': 'floor 44p'}
WATCH_ENTRY = {'slug': 'primed_target_cracker', 'name': 'Primed Target Cracker', 'floor': 35,
               'median': 62.6, 'vol48': 129, 'max_buy': 60, 'min_sell': 120,
               'status': 'HIT_BUY', 'distance_p': 25,
               'alerts': ['BUY Primed Target Cracker: floor 35p <= max_buy 60p']}
RUN_ROW = {'slug': 'meso_i1_relic', 'name': 'Meso I1 Relic', 'qty': 6, 'my_price': 7,
           'buyer': 'exo-danking', 'buyer_status': 'ingame', 'buy_price': 32,
           'why': 'ingame - pays 32p vs your 7p'}


def load_rules():
    """Fresh module object for scripts/trader/notify_rules.py."""
    name = 'wfm_notify_rules_%d' % next(_seq)
    spec = importlib.util.spec_from_file_location(name, RULES_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def core(tmp_path, monkeypatch):
    """scripts/notify.py with every path in tmp_path (test_notify's fixture shape)."""
    mod = load_script('notify', monkeypatch=monkeypatch)
    data = tmp_path / 'data'
    data.mkdir(exist_ok=True)
    monkeypatch.setattr(mod, 'ROOT', str(tmp_path))
    monkeypatch.setattr(mod, 'DATA', str(data))
    monkeypatch.setattr(mod, 'CONFIG_PATH', str(data / 'notify_config.json'))
    monkeypatch.setattr(mod, 'OUTBOX_PATH', str(data / 'notify_outbox.json'))
    monkeypatch.setattr(mod, 'RETRY_WAIT', 0.0)          # no sleeping in tests
    return mod


@pytest.fixture
def nr(core, tmp_path, monkeypatch):
    """notify_rules with its own paths AND its sender core redirected into tmp_path."""
    mod = load_rules()
    data = str(tmp_path / 'data')
    monkeypatch.setattr(mod, 'ROOT', str(tmp_path))
    monkeypatch.setattr(mod, 'DATA', data)
    monkeypatch.setattr(mod, 'CONFIG_PATH', os.path.join(data, 'notify_config.json'))
    monkeypatch.setattr(mod, 'OUTBOX_PATH', os.path.join(data, 'notify_outbox.json'))
    monkeypatch.setattr(mod, 'notify', core)             # never import the real sender here
    return mod


def write_cfg(nr, hooks=(HOOK,), dry_run=True, rules=None, allow_webhooks=None):
    """A notify_config.json in tmp_path; allow_webhooks=None leaves the key out."""
    doc = {'dry_run': dry_run, 'webhooks': list(hooks)}
    if rules is not None:
        doc['rules'] = dict(rules)
    if allow_webhooks is not None:
        doc['allow_webhooks'] = allow_webhooks
    write_json(nr.CONFIG_PATH, doc)
    return doc


def live_hook(sink):
    return {'name': 'sink', 'url': sink.url, 'kind': 'discord'}


# ------------------------------------------------------------------ config + defaults

def test_missing_config_is_created_with_our_keys(nr, capsys):
    cfg = nr.load_config()

    raw = read_json(nr.CONFIG_PATH)
    assert raw['allow_webhooks'] is False
    assert set(raw['rules']) == {'sales', 'alerts', 'digest'} | set(DEFAULT_RULES)
    assert all(raw['rules'][k] == v for k, v in DEFAULT_RULES.items())
    assert raw['dry_run'] is True and raw['webhooks'] == [HOOK]
    assert cfg['allow_webhooks'] is False and cfg['dry_run'] is True
    assert 'created' in capsys.readouterr().out


def test_existing_config_is_extended_additively_and_only_once(nr):
    write_json(nr.CONFIG_PATH, {'_comment': 'mine', 'dry_run': False, 'future_knob': 7,
                                'webhooks': [HOOK], 'rules': {'alerts': False, 'mine': True}})

    nr.load_config()

    raw = read_json(nr.CONFIG_PATH)
    assert raw['dry_run'] is False and raw['future_knob'] == 7      # values untouched
    assert raw['rules']['mine'] is True and raw['rules']['alerts'] is False
    assert raw['allow_webhooks'] is False
    assert list(raw) == ['_comment', 'dry_run', 'future_knob', 'webhooks', 'rules',
                         'allow_webhooks']                          # order kept, new key last
    assert list(raw['rules'])[:2] == ['alerts', 'mine']
    assert list(raw['rules'])[2:] == list(DEFAULT_RULES)

    before = open(nr.CONFIG_PATH, encoding='utf-8').read()
    nr.load_config()
    assert open(nr.CONFIG_PATH, encoding='utf-8').read() == before  # idempotent


def test_allow_webhooks_true_is_never_overwritten(nr):
    write_cfg(nr, hooks=[], rules={}, allow_webhooks=True)

    assert nr.load_config()['allow_webhooks'] is True
    assert read_json(nr.CONFIG_PATH)['allow_webhooks'] is True


def test_unreadable_config_falls_back_to_defaults_and_is_left_alone(nr, capsys):
    with open(nr.CONFIG_PATH, 'w', encoding='utf-8') as fh:
        fh.write('{not json')

    cfg = nr.load_config()

    assert all(cfg['rules'][k] == v for k, v in DEFAULT_RULES.items())
    assert cfg['allow_webhooks'] is False and cfg['dry_run'] is True
    assert 'WARN' in capsys.readouterr().out
    assert open(nr.CONFIG_PATH, encoding='utf-8').read() == '{not json'


# ------------------------------------------------------------------------ rules logic

def test_should_send_defaults_and_toggles(nr):
    write_cfg(nr, rules={})

    assert {r: nr.should_send(r) for r in DEFAULT_RULES} == DEFAULT_RULES
    write_cfg(nr, rules={'sale': False, 'trade_run': True, 'custom': False})
    assert nr.should_send('sale') is False
    assert nr.should_send('trade_run') is True
    assert nr.should_send('undercut') is True            # missing -> default
    assert nr.should_send('custom') is False             # any rule name works
    assert nr.should_send('never_heard_of_it') is True   # unknown stays enabled
    assert nr.should_send('') is False


def test_should_send_never_creates_the_config_file(nr):
    assert nr.should_send('sale') is True                # defaults apply
    assert nr.should_send('trade_run') is False
    assert not os.path.exists(nr.CONFIG_PATH)


def test_dry_run_for_combines_both_switches(nr):
    mk = lambda dry, allow: {'dry_run': dry, 'allow_webhooks': allow}
    assert nr.dry_run_for(mk(False, True)) is False      # the only real-POST combination
    assert nr.dry_run_for(mk(False, False)) is True
    assert nr.dry_run_for(mk(True, True)) is True
    assert nr.dry_run_for({}) is True


# ------------------------------------------------------------------------- dry-run lock

def test_allow_webhooks_false_keeps_rows_dry_run(nr, core):
    with core.Sink() as sink:
        write_cfg(nr, hooks=[live_hook(sink)], dry_run=False, rules={}, allow_webhooks=False)

        row = nr.emit('sale', 'Sale: X', '1x X @ 42p')

        assert sink.records == []                        # a configured url, still no POST
        assert row['status'] == 'dry_run' and row['to'] == 'sink' and row['rule'] == 'sale'
        assert read_json(nr.OUTBOX_PATH)[-1]['status'] == 'dry_run'


def test_absent_allow_webhooks_is_the_same_hard_default(nr, core):
    with core.Sink() as sink:
        write_cfg(nr, hooks=[live_hook(sink)], dry_run=False, rules={})   # key not written

        assert nr.allow_webhooks(nr.load_config()) is False
        row = nr.emit('sale', 'Sale: X', 'body')

        assert sink.records == [] and row['status'] == 'dry_run'


def test_allow_webhooks_true_posts_for_real(nr, core):
    with core.Sink() as sink:
        write_cfg(nr, hooks=[live_hook(sink)], dry_run=False, rules={}, allow_webhooks=True)

        row = nr.emit('sale', 'Sale: X', '1x X @ 42p')

        assert sink.json() == {'content': 'Sale: X\n\n1x X @ 42p'}
        assert row['status'] == 'sent' and 'HTTP 204' in row.get('detail', '')
        assert read_json(nr.OUTBOX_PATH)[-1]['status'] == 'sent'


def test_allow_webhooks_true_still_honours_notify_dry_run(nr, core):
    with core.Sink() as sink:
        write_cfg(nr, hooks=[live_hook(sink)], dry_run=True, rules={}, allow_webhooks=True)

        row = nr.emit('sale', 'Sale: X', 'body')

        assert sink.records == [] and row['status'] == 'dry_run'


# -------------------------------------------------------------------------- emit contract

def test_emit_returns_the_ledger_row_with_rule_and_meta(nr):
    write_cfg(nr, rules={})

    row = nr.emit('sale', 'T', 'B', meta={'slug': 'primed_continuity', 'status': 'nope',
                                          'ts': 'nope', 'nested': {'x': 1}})

    assert read_json(nr.OUTBOX_PATH) == [row]            # returned row == the ledger row
    assert row['title'] == 'T' and row['body'] == 'B' and row['to'] == 'my-channel'
    assert row['status'] == 'dry_run'                    # meta cannot clobber core keys
    assert row['ts'].endswith('Z') and row['rule'] == 'sale'
    assert row['slug'] == 'primed_continuity'
    assert 'ts' in row and row['ts'] != 'nope'
    assert 'nested' not in row                           # only scalar meta is kept


def test_emit_appends_exactly_one_row_per_delivery(nr):
    write_cfg(nr, rules={})

    nr.emit('sale', 'a', 'b')
    nr.emit('undercut', 'c', 'd')

    ledger = read_json(nr.OUTBOX_PATH)
    assert [r['title'] for r in ledger] == ['a', 'c']
    assert [r['rule'] for r in ledger] == ['sale', 'undercut']


def test_emit_accepts_a_title_only_message(nr):
    write_cfg(nr, rules={'daily_digest': True})          # the digest rule ships off

    row = nr.emit('daily_digest', 'WFM daily digest blob')   # digest.py's call shape

    assert row['status'] == 'dry_run' and row['rule'] == 'daily_digest'
    assert row['title'] == 'WFM daily digest blob' and row['body'] == ''


def test_daily_digest_is_off_by_default(nr):
    write_cfg(nr, rules={})

    row = nr.emit('daily_digest', 'blob')

    assert row['status'] == 'blocked' and not os.path.exists(nr.OUTBOX_PATH)


def test_omitting_the_body_entirely_is_the_same_title_only_shape(nr, capsys):
    write_cfg(nr, rules={'daily_digest': True})

    assert nr.main(['--emit', 'daily_digest', '--title', 'blob only']) == 0

    assert read_json(nr.OUTBOX_PATH)[-1]['body'] == ''
    assert 'blob only' in capsys.readouterr().out


def test_emit_to_every_webhook_annotates_every_row(nr):
    write_cfg(nr, hooks=[{'name': 'a', 'url': '', 'kind': 'discord'},
                         {'name': 'b', 'url': '', 'kind': 'discord'}], rules={})

    row = nr.emit('sale', 'T', 'B', every=True)

    ledger = read_json(nr.OUTBOX_PATH)
    assert [r['to'] for r in ledger] == ['a', 'b'] and len(ledger) == 2
    assert all(r['rule'] == 'sale' for r in ledger)
    assert row == ledger[0]                              # the first row is returned


def test_off_rule_blocks_emit_and_appends_nothing(nr, core, capsys):
    with core.Sink() as sink:
        write_cfg(nr, hooks=[live_hook(sink)], dry_run=False, rules={'sale': False},
                  allow_webhooks=True)

        row = nr.emit('sale', 'Blocked', 'b')

        assert row['status'] == 'blocked' and row['to'] is None and row['rule'] == 'sale'
        assert sink.records == [] and not os.path.exists(nr.OUTBOX_PATH)
        assert 'nothing sent' in capsys.readouterr().out


def test_emit_without_a_rule_name_is_a_caller_error(nr):
    with pytest.raises(ValueError):
        nr.emit('', 'T', 'B')


def test_emit_with_no_webhooks_configured_raises_notify_error(nr, core):
    write_cfg(nr, hooks=[], rules={})

    with pytest.raises(core.NotifyError):
        nr.emit('sale', 'T', 'B')


# ------------------------------------------------------------------------------ adapters

def test_emit_sale_formats_a_one_liner(nr):
    write_cfg(nr, rules={})

    row = nr.emit_sale(SALE_EVENT)

    assert row['rule'] == 'sale' and row['status'] == 'dry_run'
    assert row['title'] == 'Sale: Primed Continuity x1 @ 42p'
    assert row['body'] == '42p total | with BuyerOne'
    assert row['slug'] == 'primed_continuity' and row['qty'] == 1 and row['plat'] == 42


def test_emit_undercut_formats_a_one_liner(nr):
    write_cfg(nr, rules={})

    row = nr.emit_undercut(UNDERCUT_ROW)

    assert row['title'] == 'Undercut: Primed Continuity (rank 0)'
    assert row['body'] == 'you 45p vs floor 44p -> reprice to 43p'
    assert row['rule'] == 'undercut' and row['order_id'] == 'ord-1'


def test_emit_watchlist_hit_uses_the_entry_alert_line(nr):
    write_cfg(nr, rules={})

    row = nr.emit_watchlist_hit(WATCH_ENTRY)

    assert row['title'] == 'Watchlist hit: Primed Target Cracker (HIT_BUY)'
    assert row['body'] == WATCH_ENTRY['alerts'][0]
    assert row['rule'] == 'watchlist_hit' and row['floor'] == 35


def test_emit_watchlist_hit_builds_a_body_when_there_is_no_alert_line(nr):
    write_cfg(nr, rules={})

    row = nr.emit_watchlist_hit({'slug': 'x', 'floor': 35, 'max_buy': 60, 'status': 'HIT_BUY'})

    assert row['title'] == 'Watchlist hit: x (HIT_BUY)'
    assert 'floor 35' in row['body'] and 'max_buy 60' in row['body']


def test_emit_trade_run_formats_a_one_liner(nr):
    write_cfg(nr, rules={'trade_run': True})             # the rule ships off

    row = nr.emit_trade_run(RUN_ROW)

    assert row['title'] == 'Trade run: Meso I1 Relic x6 @ 7p'
    assert 'exo-danking (ingame)' in row['body'] and 'pays 32p' in row['body']
    assert row['rule'] == 'trade_run' and row['buyer'] == 'exo-danking'


def test_adapters_are_gated_by_their_own_rule(nr):
    write_cfg(nr, rules={})                              # trade_run default: off

    assert nr.emit_trade_run(RUN_ROW)['status'] == 'blocked'
    assert nr.emit_sale(SALE_EVENT)['status'] == 'dry_run'
    write_cfg(nr, rules={'undercut': False, 'watchlist_hit': False})
    assert nr.emit_undercut(UNDERCUT_ROW)['status'] == 'blocked'
    assert nr.emit_watchlist_hit(WATCH_ENTRY)['status'] == 'blocked'


def test_adapters_survive_missing_fields(nr):
    write_cfg(nr, rules={'trade_run': True})             # the rule ships off; turn it on

    for row in (nr.emit_sale({}), nr.emit_undercut(None), nr.emit_watchlist_hit({}),
                nr.emit_trade_run({})):
        assert row['status'] == 'dry_run'
        assert row['title'] and '\n' not in row['title'] and '\n' not in row['body']


# ----------------------------------------------------------------------------------- CLI

def test_cli_rules_prints_the_effective_switchboard(nr, capsys):
    write_cfg(nr, rules={'sale': False, 'custom': False}, allow_webhooks=True)
    nr.load_config()                                     # absorb the one-time extension print
    capsys.readouterr()

    assert nr.main(['--rules']) == 0

    doc = json.loads(capsys.readouterr().out)
    assert doc['rules']['sale'] is False and doc['rules']['undercut'] is True
    assert doc['rules']['trade_run'] is False and doc['rules']['custom'] is False
    assert doc['allow_webhooks'] is True and doc['dry_run'] is True
    assert doc['webhooks'] == ['my-channel']             # names only, never a url


def test_cli_emit_manual_message(nr, capsys):
    write_cfg(nr, rules={})

    assert nr.main(['--emit', 'sale', '--title', 'Test sale', '--body', 'Test 1x @ 10p']) == 0

    out = capsys.readouterr().out
    assert 'dry_run' in out and 'Test sale' in out and 'allow_webhooks is false' in out
    rows = read_json(nr.OUTBOX_PATH)
    assert rows[-1]['title'] == 'Test sale' and rows[-1]['body'] == 'Test 1x @ 10p'
    assert rows[-1]['rule'] == 'sale' and rows[-1]['status'] == 'dry_run'


def test_cli_emit_blocked_rule_exits_0_and_says_so(nr, capsys):
    write_cfg(nr, rules={'sale': False})

    assert nr.main(['--emit', 'sale', '--title', 'T']) == 0

    assert 'nothing sent' in capsys.readouterr().out
    assert not os.path.exists(nr.OUTBOX_PATH)


def test_cli_emit_reports_a_delivery_problem_as_exit_1(nr, capsys):
    write_cfg(nr, hooks=[], rules={})

    assert nr.main(['--emit', 'sale', '--title', 'T']) == 1
    assert 'no webhooks' in capsys.readouterr().out


def test_cli_guards(nr, capsys):
    assert nr.main([]) == 2                                   # nothing to do
    assert nr.main(['--rules', '--selftest']) == 2            # one mode only
    assert nr.main(['--emit', 'sale']) == 2                   # --emit needs --title
    assert nr.main(['--title', 'x']) == 2                     # --title needs --emit
    assert 'need' in capsys.readouterr().out


# ------------------------------------------------------------------------------ selftest

def test_selftest_passes_offline_and_leaves_the_files_alone(nr, capsys):
    write_cfg(nr, rules={})
    nr.emit('sale', 'keep me', 'b')
    before = (open(nr.CONFIG_PATH, encoding='utf-8').read(),
              open(nr.OUTBOX_PATH, encoding='utf-8').read())

    assert nr.main(['--selftest']) == 0

    out = capsys.readouterr().out
    assert 'selftest OK' in out and 'FAIL' not in out and 'PASS' in out
    assert (open(nr.CONFIG_PATH, encoding='utf-8').read(),
            open(nr.OUTBOX_PATH, encoding='utf-8').read()) == before
