"""scripts/notify.py: config bootstrap, outbox ledger, webhook delivery, --selftest.

notify.py keeps its paths in module globals (CONFIG_PATH / OUTBOX_PATH), so the
fixture points them at tmp_path - the repo's real data/ directory is never read or
written. HTTP is exercised only against notify.Sink, a 127.0.0.1 loopback
http.server, so the suite never touches the network.
"""
import os

import pytest

from conftest import load_script, read_json, write_json

DEFAULT_HOOK = {'name': 'my-channel', 'url': '', 'kind': 'discord'}


@pytest.fixture
def notify(tmp_path, monkeypatch):
    mod = load_script('notify', monkeypatch=monkeypatch)
    data = tmp_path / 'data'
    data.mkdir()
    monkeypatch.setattr(mod, 'ROOT', str(tmp_path))
    monkeypatch.setattr(mod, 'DATA', str(data))
    monkeypatch.setattr(mod, 'CONFIG_PATH', str(data / 'notify_config.json'))
    monkeypatch.setattr(mod, 'OUTBOX_PATH', str(data / 'notify_outbox.json'))
    monkeypatch.setattr(mod, 'RETRY_WAIT', 0.0)          # no sleeping in tests
    return mod


@pytest.fixture
def sink(notify):
    """Loopback sink answering 204 (Discord's success code)."""
    with notify.Sink() as s:
        yield s


def live_cfg(notify, hooks, dry_run=False, rules=None):
    doc = {'dry_run': dry_run, 'webhooks': hooks}
    if rules is not None:
        doc['rules'] = rules
    return notify.normalize(doc)


# ----------------------------------------------------------------- config bootstrap

def test_config_is_created_with_the_documented_shape(notify, capsys):
    cfg = notify.load_config()

    assert cfg['dry_run'] is True
    assert cfg['webhooks'] == [DEFAULT_HOOK]
    assert cfg['rules'] == {'sales': True, 'alerts': True, 'digest': False}
    assert 'created' in capsys.readouterr().out
    raw = read_json(notify.CONFIG_PATH)                   # the file on disk matches
    assert set(raw) == {'_comment', 'dry_run', 'webhooks', 'rules'}
    assert raw['_comment'] and raw['webhooks'] == [DEFAULT_HOOK]


def test_existing_config_is_never_overwritten(notify):
    mine = {'_comment': 'mine', 'dry_run': False, 'rules': {'digest': True},
            'webhooks': [{'name': 'keep', 'url': 'http://127.0.0.1:9/hook', 'kind': 'generic'}]}
    write_json(notify.CONFIG_PATH, mine)
    before = open(notify.CONFIG_PATH, encoding='utf-8').read()

    cfg = notify.load_config()

    assert cfg['dry_run'] is False and cfg['rules']['digest'] is True
    assert cfg['webhooks'] == [{'name': 'keep', 'url': 'http://127.0.0.1:9/hook',
                               'kind': 'generic'}]
    assert open(notify.CONFIG_PATH, encoding='utf-8').read() == before


def test_unreadable_config_falls_back_to_safe_defaults(notify, capsys):
    with open(notify.CONFIG_PATH, 'w', encoding='utf-8') as fh:
        fh.write('{not json')

    cfg = notify.load_config()

    assert cfg['dry_run'] is True and cfg['webhooks'] == [DEFAULT_HOOK]
    assert 'WARN' in capsys.readouterr().out
    assert open(notify.CONFIG_PATH, encoding='utf-8').read() == '{not json'   # kept as-is


def test_normalize_fills_defaults_and_ignores_unnamed_webhooks(notify, capsys):
    cfg = notify.normalize({'webhooks': [{'url': 'http://127.0.0.1:9/x'}, 'junk',
                                         {'name': 'ok'}],
                            'rules': {'digest': True, 'custom': False, 'junk': 'nope'}})

    assert cfg['webhooks'] == [{'name': 'ok', 'url': '', 'kind': 'discord'}]
    assert cfg['rules'] == {'sales': True, 'alerts': True, 'digest': True, 'custom': False}
    assert 'no name' in capsys.readouterr().out


# --------------------------------------------------------------------- dry run path

def test_dry_run_appends_a_row_and_posts_nothing(notify, sink):
    cfg = live_cfg(notify, [{'name': 'sink', 'url': sink.url, 'kind': 'discord'}], dry_run=True)

    rows = notify.deliver(cfg, 'Sale ping', '3x Primed Continuity at 42p')

    assert sink.records == []                             # dry run never posts
    assert len(rows) == 1 and set(rows[0]) == {'ts', 'to', 'title', 'body', 'status'}
    assert rows[0]['status'] == 'dry_run' and rows[0]['to'] == 'sink'
    assert rows[0]['title'] == 'Sale ping' and rows[0]['body'] == '3x Primed Continuity at 42p'
    assert rows[0]['ts'].endswith('Z') and 'T' in rows[0]['ts']
    assert read_json(notify.OUTBOX_PATH) == rows          # ledger holds the same row


def test_dry_run_is_the_default_when_the_config_has_no_dry_run_key(notify):
    cfg = notify.normalize({})
    assert cfg['dry_run'] is True
    rows = notify.deliver(cfg, 'T', 'B')
    assert rows[0]['status'] == 'dry_run'


def test_main_send_to_a_named_dry_target(notify, capsys):
    write_json(notify.CONFIG_PATH, {
        'dry_run': True, 'rules': {},
        'webhooks': [{'name': 'alpha', 'url': '', 'kind': 'discord'},
                     {'name': 'beta', 'url': '', 'kind': 'discord'}]})

    assert notify.main(['--send', 'Hi there', '--body', 'Body text', '--to', 'beta']) == 0
    out = capsys.readouterr().out
    assert 'dry_run' in out and 'Hi there' in out and 'Body text' in out
    assert '"dry_run": false' in out
    rows = read_json(notify.OUTBOX_PATH)
    assert [r['to'] for r in rows] == ['beta'] and rows[0]['status'] == 'dry_run'


def test_default_target_is_the_first_configured_webhook(notify, sink):
    cfg = live_cfg(notify, [{'name': 'first', 'url': sink.url, 'kind': 'discord'},
                            {'name': 'second', 'url': sink.url, 'kind': 'discord'}])
    rows = notify.deliver(cfg, 'T', 'B')
    assert [r['to'] for r in rows] == ['first'] and len(sink.records) == 1


# -------------------------------------------------------------------- live delivery

def test_live_discord_posts_content_and_records_sent(notify, sink):
    cfg = live_cfg(notify, [{'name': 'sink', 'url': sink.url, 'kind': 'discord'}])

    rows = notify.deliver(cfg, 'Live title', 'Live body')

    assert rows[0]['status'] == 'sent' and 'HTTP 204' in rows[0]['detail']
    assert len(sink.records) == 1
    assert sink.json() == {'content': 'Live title\n\nLive body'}
    assert sink.records[0]['headers']['content-type'] == 'application/json'
    assert read_json(notify.OUTBOX_PATH)[-1]['status'] == 'sent'


def test_discord_content_is_truncated_to_2000_chars(notify, sink):
    cfg = live_cfg(notify, [{'name': 'sink', 'url': sink.url, 'kind': 'discord'}])

    notify.deliver(cfg, 'Long', 'x' * 2500)

    content = sink.json()['content']
    assert len(content) == notify.DISCORD_LIMIT and content.endswith('...')


def test_generic_kind_posts_title_and_body(notify, sink):
    cfg = live_cfg(notify, [{'name': 'sink', 'url': sink.url, 'kind': 'generic'}])

    rows = notify.deliver(cfg, 'Gen title', 'Gen body')

    assert sink.json() == {'title': 'Gen title', 'body': 'Gen body'}
    assert rows[0]['status'] == 'sent'


def test_all_sends_to_every_webhook(notify):
    with notify.Sink() as a, notify.Sink() as b:
        cfg = live_cfg(notify, [{'name': 'a', 'url': a.url, 'kind': 'discord'},
                                {'name': 'b', 'url': b.url, 'kind': 'discord'}])
        rows = notify.deliver(cfg, 'T', 'B', every=True)

        assert [r['to'] for r in rows] == ['a', 'b']
        assert [r['status'] for r in rows] == ['sent', 'sent']
        assert a.json() == b.json() == {'content': 'T\n\nB'}


def test_empty_url_is_skipped_with_a_clear_message(notify, sink):
    cfg = live_cfg(notify, [{'name': 'my-channel', 'url': '', 'kind': 'discord'}])

    rows = notify.deliver(cfg, 'Nope', 'Nope')

    assert rows[0]['status'] == 'skipped' and 'no url' in rows[0]['detail']
    assert 'my-channel' in rows[0]['detail'] and sink.records == []


def test_main_reports_skipped_url_and_exits_1(notify, capsys):
    write_json(notify.CONFIG_PATH, {'dry_run': False, 'rules': {},
                                    'webhooks': [DEFAULT_HOOK]})

    assert notify.main(['--send', 'Nope', '--body', 'Nope']) == 1
    out = capsys.readouterr().out
    assert 'skipped' in out and 'no url' in out
    assert read_json(notify.OUTBOX_PATH)[0]['status'] == 'skipped'


def test_failed_attempt_is_retried_once_then_succeeds(notify):
    with notify.Sink(fail_first=True) as flaky:
        cfg = live_cfg(notify, [{'name': 'flaky', 'url': flaky.url, 'kind': 'discord'}])
        rows = notify.deliver(cfg, 'Retry me', 'body')

        assert rows[0]['status'] == 'sent'
        assert len(flaky.records) == 2                    # first attempt + exactly one retry


def test_permanently_failing_webhook_records_failed(notify):
    with notify.Sink(status=500) as broken:
        cfg = live_cfg(notify, [{'name': 'broken', 'url': broken.url, 'kind': 'discord'}])
        rows = notify.deliver(cfg, 'Never lands', 'body')

        assert rows[0]['status'] == 'failed' and 'HTTP 500' in rows[0]['detail']
        assert len(broken.records) == 2


def test_post_rejects_a_url_that_is_not_http(notify, sink):
    ok, detail = notify.post('my-channel', {'content': 'x'})
    assert ok is False and 'http' in detail and sink.records == []


def test_unknown_to_name_lists_known_webhooks(notify, capsys):
    write_json(notify.CONFIG_PATH, {'dry_run': True, 'rules': {},
                                    'webhooks': [{'name': 'alpha', 'url': '', 'kind': 'discord'}]})

    assert notify.main(['--send', 'T', '--to', 'nope']) == 1
    out = capsys.readouterr().out
    assert 'no webhook named' in out and 'alpha' in out
    assert not os.path.exists(notify.OUTBOX_PATH)


def test_no_webhooks_configured_is_a_clear_error(notify, capsys):
    write_json(notify.CONFIG_PATH, {'dry_run': True, 'rules': {}, 'webhooks': []})

    assert notify.main(['--send', 'T']) == 1
    assert 'no webhooks' in capsys.readouterr().out


# ------------------------------------------------------------------------ rules

def test_rule_gate_blocks_disabled_rules(notify, sink, capsys):
    write_json(notify.CONFIG_PATH, {
        'dry_run': False, 'rules': {'sales': True, 'alerts': True, 'digest': False},
        'webhooks': [{'name': 'sink', 'url': sink.url, 'kind': 'discord'}]})

    assert notify.main(['--send', 'Digest', '--body', 'b', '--rule', 'digest']) == 0
    assert 'nothing sent' in capsys.readouterr().out
    assert sink.records == []

    assert notify.main(['--send', 'Sale', '--body', 'b', '--rule', 'sales']) == 0
    assert sink.json() == {'content': 'Sale\n\nb'}


def test_unknown_rules_stay_enabled(notify):
    cfg = notify.normalize({'rules': {'digest': False}})
    assert notify.rule_enabled(cfg, 'sales') is True
    assert notify.rule_enabled(cfg, 'watchlist') is True       # new callers not blocked
    assert notify.rule_enabled(cfg, 'digest') is False


# ------------------------------------------------------------------------ outbox

def test_outbox_listing_is_newest_first_and_honours_limit(notify, capsys):
    notify.append_outbox([{'ts': '2026-01-01T00:00:0%dZ' % i, 'to': 'c', 'title': 't%d' % i,
                           'body': 'b%d' % i, 'status': 'dry_run'} for i in range(3)])

    assert notify.main(['--outbox', '--limit', '2']) == 0
    out = capsys.readouterr().out
    assert 't2' in out and 't1' in out and 't0' not in out
    assert out.index('t2') < out.index('t1')              # newest first
    assert '3' in out                                     # total row count


def test_empty_outbox_says_so(notify, capsys):
    assert notify.main(['--outbox']) == 0
    assert 'outbox is empty' in capsys.readouterr().out


def test_outbox_keeps_the_newest_rows_only(notify, monkeypatch):
    monkeypatch.setattr(notify, 'OUTBOX_KEEP', 3)
    notify.append_outbox([{'ts': 'T%d' % i, 'status': 'dry_run'} for i in range(5)])

    rows = read_json(notify.OUTBOX_PATH)
    assert [r['ts'] for r in rows] == ['T2', 'T3', 'T4']


def test_corrupt_outbox_is_moved_aside_not_dropped(notify, capsys):
    with open(notify.OUTBOX_PATH, 'w', encoding='utf-8') as fh:
        fh.write('{{broken')

    assert notify.load_outbox() == []
    assert 'moved aside' in capsys.readouterr().out
    spare = [p for p in os.listdir(notify.DATA) if 'corrupt' in p]
    assert spare and open(os.path.join(notify.DATA, spare[0]),
                          encoding='utf-8').read() == '{{broken'

    rows = notify.append_outbox([{'ts': 'T', 'status': 'dry_run'}])
    assert [r['ts'] for r in rows] == ['T']


def test_send_via_the_programmatic_api(notify, sink, capsys):
    write_json(notify.CONFIG_PATH, {
        'dry_run': False, 'rules': {}, 'webhooks': [{'name': 'sink', 'url': sink.url,
                                                     'kind': 'discord'}]})

    rows = notify.send('Watchlist hit', 'Primed Continuity under 40p', rule='alerts')

    assert rows[0]['status'] == 'sent' and sink.json()['content'].startswith('Watchlist hit')
    assert 'sent' in capsys.readouterr().out
    assert read_json(notify.OUTBOX_PATH)[0]['to'] == 'sink'


# ---------------------------------------------------------------------- selftest

def test_selftest_passes_offline_and_leaves_the_real_ledger_alone(notify, capsys):
    write_json(notify.CONFIG_PATH, {'dry_run': True, 'rules': {}, 'webhooks': [DEFAULT_HOOK]})
    notify.append_outbox([{'ts': 'T', 'to': 'c', 'title': 'x', 'body': '', 'status': 'dry_run'}])
    before = (open(notify.CONFIG_PATH, encoding='utf-8').read(),
              open(notify.OUTBOX_PATH, encoding='utf-8').read())

    assert notify.main(['--selftest']) == 0

    out = capsys.readouterr().out
    assert 'selftest OK' in out and 'FAIL' not in out and 'PASS' in out
    assert (open(notify.CONFIG_PATH, encoding='utf-8').read(),
            open(notify.OUTBOX_PATH, encoding='utf-8').read()) == before


def test_cli_guards(notify, capsys):
    assert notify.main([]) == 2                                        # nothing to do
    assert notify.main(['--send', 'T', '--outbox']) == 2               # one mode only
    assert notify.main(['--selftest', '--send', 'T']) == 2
    assert notify.main(['--to', 'x']) == 2                             # --to needs --send
    assert notify.main(['--send', 'T', '--to', 'x', '--all']) == 2
    assert 'need --send' in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:                             # argparse-level
        notify.main(['--outbox', '--limit', '0'])
    assert exc.value.code == 2
