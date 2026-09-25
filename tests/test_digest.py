"""scripts/digest.py: the daily digest composer - section contract, staleness wording and the
Discord blob budget.

Every test builds its own fixtures under tmp_path and points the composer at them with
--root / build(root), so the repo's real data/ is never read and never written, nothing here
reaches the network, and scripts/trader/* (private, gitignored) is never imported - the one
place a trader module could be touched, test_notify_*, plants its own stub under tmp_path.

The composer only ever composes: these tests therefore assert what it reads (source ages from
each file's mtime), what it says when a file is missing/stale ('no data (data/x 3.0d old)') and
that the Discord markdown never exceeds the hard limit.
"""
import json
import os
import subprocess
import sys
import time

import pytest

from conftest import SCRIPTS, load_script, read_json, write_json

DIGEST_PATH = os.path.join(SCRIPTS, 'digest.py')
NOW = 1790344512          # frozen clock for every check (the fixtures use relative epochs)

LIMITS = {
    'account': 'SampleTennoIX', 'mr': 22, 'trade_cap': 22, 'trades_used': 3, 'trades_left': 19,
    'plat': 1247, 'reset_epoch': NOW + 39476, 'reset_melbourne': '2026-09-26T10:00:00+10:00',
}
PLAT_HISTORY = [{'ts': NOW - 90000, 'plat': 6190, 'credits': 3766131},
                {'ts': NOW - 60, 'plat': 1022, 'credits': 4005108}]
KILL_OFF = {'active': False, 'note': '', 'ts': NOW - 300}
KILL_ON = {'active': True, 'note': 'wallet reset', 'ts': NOW - 300}
SESSIONS = {'generated': '2026-09-25 22:37', 'gap_min': 45, 'sessions': [
    {'date': '2026-09-25', 'end_at': '2026-09-25 22:18', 'kind': 'idle', 'sales': 0, 'net': 0,
     'dur_min': 96.5}]}
FLIP_DIGEST = {
    'generated': NOW - 3600, 'counts': {'fresh': 309, 'stale_excluded': 80},
    # deliberately NOT ordered by margin: the composer must keep this order, not re-rank
    'digest': [
        {'slug': 'low_margin', 'name': 'Low Margin Mod', 'kind': 'undercut', 'buy_at': 175,
         'sell_at': 299, 'profit': 124, 'margin_pct': 70.9, 'sales_day': 52.5, 'queue_ahead': 2},
        {'slug': 'high_margin', 'name': 'High Margin Mod', 'kind': 'spread', 'buy_at': 69,
         'sell_at': 300, 'profit': 231, 'margin_pct': 334.8, 'sales_day': 128.0, 'queue_ahead': 19},
        {'slug': 'third_mod', 'name': 'Third Mod', 'kind': 'spread', 'buy_at': 5, 'sell_at': 20,
         'profit': 15, 'margin_pct': 300.0, 'sales_day': 4.0, 'queue_ahead': 0},
    ],
    'flips': [{'slug': 'high_margin', 'name': 'High Margin Mod', 'profit': 231, 'margin_pct': 334.8,
               'sales_day': 128.0}],
}
TRENDS = {'generated': NOW - 600, 'top_spikes': [
              {'slug': 's1', 'name': 'Spike One', 'vol48': 60, 'ratio': 5.39, 'price_trend_pct': -40.0},
              {'slug': 's2', 'name': 'Spike Two', 'vol48': 109, 'ratio': 2.04, 'price_trend_pct': 20.0},
              {'slug': 's3', 'name': 'Spike Three', 'vol48': 3, 'ratio': 2.0, 'price_trend_pct': None}],
          'top_fades': [
              {'slug': 'f1', 'name': 'Fade One', 'vol48': 0, 'ratio': 0.3, 'price_trend_pct': None},
              {'slug': 'f2', 'name': 'Fade Two', 'vol48': 30, 'ratio': 0.62, 'price_trend_pct': 66.5},
              {'slug': 'f3', 'name': 'Fade Three', 'vol48': 5, 'ratio': 0.4, 'price_trend_pct': 1.0}]}
META_WATCH = {'generated': NOW - 120, 'spike': [
                  {'slug': 'm1', 'name': 'Meta Spike', 'vol48_per_day': 30.0, 'ratio': 5.39,
                   'price_trend_pct': -40.0, 'post_patch': True}],
              'sink': [{'slug': 'm2', 'name': 'Meta Sink', 'vol48_per_day': 60.5, 'ratio': 0.38,
                        'price_trend_pct': 28.6, 'post_patch': True}]}
BARO = {'generated': NOW - 600,
        'trader': {'character': "Baro Ki'Teer", 'active': False, 'location': 'Kronia Relay (Saturn)',
                   'starts_in': '7d 0h 8m',
                   'status_text': "NOT active -- next visit Fri 2026-10-02 13:00 UTC (in 7d 0h 8m)"},
        'player': {'ducats': 6250, 'credits': 3893672},
        'summary': {'burnable_parts': 29, 'ducats_from_burnable_parts': 2360},
        'wishlist_buys': [], 'rows': []}
NUDGES = {'generated': NOW - 600, 'counts': {'ready': 5, 'one_away': 9, 'two_away': 24, 'conflicts': 1},
          'ready': [{'slug': 'hydroid_prime_set', 'name': 'Hydroid Prime Set', 'category': 'READY',
                     'action': 'assemble + sell, 1 trade', 'set_value': 73.0, 'urgency': 73.0},
                    {'slug': 'inaros_prime_set', 'name': 'Inaros Prime Set', 'category': 'READY',
                     'action': 'assemble + sell, 1 trade', 'set_value': 61.0, 'urgency': 61.0}],
          'one_away': [{'slug': 'larkspur_prime_set', 'name': 'Larkspur Prime Set',
                        'category': 'ONE_AWAY', 'missing_name': 'Larkspur Prime Stock',
                        'cost_est': 6.7, 'set_value': 62.7, 'urgency': 33.6}]}
WISHLIST = {'generated': NOW - 600,
            'summary': {'buy_now_count': 6, 'budget_needed': 94, 'budget_available': 1247,
                        'budget_leftover': 1153, 'trades_needed': 6, 'status': 'OK'},
            'suggested': [
                {'slug': 'bronco_prime_barrel', 'name': 'Bronco Prime Barrel', 'status': 'BUY_NOW',
                 'max_price': 7, 'floor': 2, 'ratio': 3.5, 'set_action': 'COMPLETE_MAYBE'},
                {'slug': 'revenant_prime_blueprint', 'name': 'Revenant Prime Blueprint',
                 'status': 'BUY_NOW', 'max_price': 34, 'floor': 20, 'ratio': 1.7,
                 'set_action': 'COMPLETE'},
                {'slug': 'wait_row', 'name': 'Wait Row', 'status': 'WAIT', 'max_price': 9,
                 'floor': 1}]}
TRADER_PLAN = {'generated': NOW - 600, 'dry_run': True, 'live_orders': 0,
               'summary': {'orders': 19, 'copies': 130,
                           'by_section': {'mod': {'orders': 8, 'copies': 36},
                                          'relic': {'orders': 6, 'copies': 71}}},
               'plan': [{'slug': 'primed_continuity', 'name': 'Primed Continuity', 'qty': 3,
                         'est_total': 141}],
               'held_list': [['Esher Devar', 'below min price (1p < 3p)']]}
SELL_TIMING = {'generated': NOW - 300, 'verdict': 'HOLD',
               'verdict_reason': '23:00 AEST has 5 sales in sample; next window Mon 02:00 (in 2.1d)',
               'next_window': {'dow': 0, 'hour': 2, 'label': 'Mon 02:00 (in 2.1d)'},
               'sample': {'sales_total': 122, 'active_days': 17, 'span_days': 455.7}}

FIXTURES = {
    'trader_limits.json': LIMITS, 'plat_history.json': PLAT_HISTORY, 'kill_switch.json': KILL_OFF,
    'session_stats.json': SESSIONS, 'flip_digest.json': FLIP_DIGEST, 'trends.json': TRENDS,
    'meta_watch.json': META_WATCH, 'baro.json': BARO, 'nudges.json': NUDGES,
    'wishlist.json': WISHLIST, 'trader_plan.json': TRADER_PLAN, 'sell_timing.json': SELL_TIMING,
}
SOURCE_NAMES = [name for name, _ in FIXTURES.items()]


def seed(root, age_min=0.5, **overrides):
    """Write the full fixture set into <root>/data; an override value of None deletes the file.

    mtimes are pinned relative to the frozen clock (NOW), so every age the composer reports is
    exact on any machine - the tests never depend on the wall clock.
    """
    data = os.path.join(str(root), 'data')
    os.makedirs(data, exist_ok=True)
    for name, obj in dict(FIXTURES, **overrides).items():
        path = os.path.join(data, name)
        if obj is None:
            if os.path.exists(path):
                os.remove(path)
            continue
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(obj, fh, indent=1)
        stamp = NOW - age_min * 60.0
        os.utime(path, (stamp, stamp))
    return str(root)


@pytest.fixture
def dg(monkeypatch):
    return load_script('digest', monkeypatch=monkeypatch)


@pytest.fixture
def root(tmp_path):
    return seed(tmp_path)


def by_id(doc):
    return {sec['id']: sec for sec in doc['sections']}


# ------------------------------------------------------------------------ section contract

def test_sections_contract_and_order(dg, root):
    doc = dg.build(root, NOW)
    assert [s['id'] for s in doc['sections']] == [
        'account', 'flips', 'demand', 'baro', 'nudges', 'wishlist', 'plan', 'timing', 'data']
    for sec in doc['sections']:
        assert set(sec) == {'id', 'title', 'lines'}
        assert isinstance(sec['title'], str) and sec['title']
        assert 1 <= len(sec['lines']) <= 5
        assert all(isinstance(line, str) and line.strip() for line in sec['lines'])
    for key in ('generated', 'sections', 'discord_markdown', 'source_ages'):
        assert key in doc
    assert doc['generated'] == NOW
    assert doc['markdown_chars'] == len(doc['discord_markdown'])


def test_flips_keep_the_digest_ranking_and_show_margin_and_liquidity(dg, root):
    doc = dg.build(root, NOW)
    lines = by_id(doc)['flips']['lines']
    # the file lists low_margin first on purpose: no re-ranking is allowed here
    assert lines[0].startswith('1. Low Margin Mod [undercut]')
    assert lines[1].startswith('2. High Margin Mod')
    assert lines[2].startswith('3. Third Mod')
    assert '+124p (+70.9%)' in lines[0] and '52.5/day' in lines[0] and 'queue 2' in lines[0]
    assert lines[3] == '309 fresh, 80 stale hidden'
    assert 'Low Margin Mod' in doc['discord_markdown']


def test_account_line_trades_and_kill_switch(dg, root):
    doc = dg.build(root, NOW)
    lines = by_id(doc)['account']['lines']
    assert lines[0] == 'SampleTennoIX | MR 22 | 1,247p (trader_limits)'
    assert lines[1].startswith('trades 3/22 used - 19 left | reset 2026-09-26 10:00 (in ')
    assert lines[2] == 'kill switch: off'
    assert lines[3] == 'last session 2026-09-25 22:18 - idle, 0 sales, net 0p (96.5m)'

    armed = seed(root, **{'kill_switch.json': KILL_ON})
    assert by_id(dg.build(armed, NOW))['account']['lines'][2] == 'kill switch: ARMED - wallet reset'


def test_trades_used_is_derived_when_absent(dg, root):
    partial = dict(LIMITS)
    partial.pop('trades_used')
    by_hand = seed(root, **{'trader_limits.json': partial})
    lines = by_id(dg.build(by_hand, NOW))['account']['lines']
    assert lines[1].startswith('trades 3/22 used - 19 left')


def test_plat_falls_back_to_the_plat_history_last_point(dg, root):
    seed(root, **{'trader_limits.json': dict(LIMITS, plat=None)})
    head = by_id(dg.build(root, NOW))['account']['lines'][0]
    assert '1,022p (plat_history' in head and 'trader_limits' not in head


def test_plat_is_unknown_when_both_sources_lack_it(dg, root):
    seed(root, **{'trader_limits.json': dict(LIMITS, plat=None), 'plat_history.json': []})
    head = by_id(dg.build(root, NOW))['account']['lines'][0]
    assert head.endswith('| plat unknown')


def test_demand_uses_trends_then_meta_watch(dg, root):
    lines = by_id(dg.build(root, NOW))['demand']['lines']
    assert len(lines) == 4
    assert lines[0].startswith('SPIKE Spike One - 5.39x/30d, 30/day, price -40.0% [trends]')
    assert lines[2].startswith('FADE Fade One - 0.30x/30d, 0/day, price n/a [trends]')

    without_trends = seed(root, **{'trends.json': None})
    fallback = by_id(dg.build(without_trends, NOW))['demand']['lines']
    assert fallback[0].startswith('SPIKE Meta Spike - 5.39x/30d, 30/day, price -40.0%, post-patch [meta]')
    assert fallback[1].startswith('FADE Meta Sink')


def test_baro_countdown_and_money(dg, root):
    lines = by_id(dg.build(root, NOW))['baro']['lines']
    assert lines[0] == ("Baro Ki'Teer: next visit Fri 2026-10-02 13:00 UTC (in 7d 0h 8m)")
    assert lines[1] == 'ducats 6,250 (+2,360 from 29 burnable parts) | credits 3,893,672'
    assert lines[2].startswith('stock: no rows')


def test_baro_active_visit_reads_as_a_closing_countdown(dg, root):
    active = {'trader': {'character': "Baro Ki'Teer", 'active': True, 'location': 'Larunda Relay',
                         'closes_in': '21h 14m'}, 'player': {}, 'summary': {}, 'rows': [{'name': 'X'}]}
    seed(root, **{'baro.json': active})
    lines = by_id(dg.build(root, NOW))['baro']['lines']
    assert lines[0] == "Baro Ki'Teer: ACTIVE at Larunda Relay - closes in 21h 14m"
    assert 'stock: no rows' not in ' '.join(lines)


def test_nudges_are_ordered_by_urgency_and_spell_the_missing_part(dg, root):
    lines = by_id(dg.build(root, NOW))['nudges']['lines']
    assert lines[0] == '[READY] Hydroid Prime Set - assemble + sell, 1 trade, 73p'
    assert lines[1] == '[READY] Inaros Prime Set - assemble + sell, 1 trade, 61p'
    assert lines[2] == '[ONE_AWAY] Larkspur Prime Set - buy Larkspur Prime Stock (~6.7p) -> set sale 62.7p'
    assert lines[3] == 'sets: 5 ready, 9 one-away, 24 two-away (1 conflict(s) flagged)'


def test_wishlist_budget_headroom_and_buy_now_rows(dg, root):
    lines = by_id(dg.build(root, NOW))['wishlist']['lines']
    assert lines[0] == 'BUY_NOW 6 - 94p of 1,247p (headroom 1,153p, 6 trades)'
    assert lines[1] == 'Bronco Prime Barrel 7p (floor 2, ratio 3.5, COMPLETE_MAYBE)'
    assert lines[2].startswith('Revenant Prime Blueprint 34p')
    assert 'Wait Row' not in ' '.join(lines)          # WAIT rows never make the digest


def test_wishlist_flags_a_degraded_budget(dg, root):
    degraded = dict(WISHLIST, summary=dict(WISHLIST['summary'], status='DEGRADED',
                                           budget_source='trader_state'))
    seed(root, **{'wishlist.json': degraded})
    lines = by_id(dg.build(root, NOW))['wishlist']['lines']
    assert lines[-1].startswith('budget flagged DEGRADED (source trader_state)')


def test_plan_summary_and_timing_verdict(dg, root):
    doc = dg.build(root, NOW)
    plan = by_id(doc)['plan']['lines']
    assert plan[0] == '19 orders / 130 copies - est 141p (dry_run true, live orders 0)'
    assert plan[1] == 'sections: mod 8/36, relic 6/71'
    assert plan[2].startswith('1 rows held back - e.g. Esher Devar')

    timing = by_id(doc)['timing']['lines']
    assert timing[0].startswith('HOLD - 23:00 AEST has 5 sales in sample')
    assert timing[1] == 'next window Mon 02:00 (in 2.1d) | sample 122 sales over 17 active days'


# ------------------------------------------------------------------- missing / stale / empty

def test_missing_files_read_as_no_data_without_guessing(dg, tmp_path):
    root = seed(tmp_path, **{'flip_digest.json': None, 'trends.json': None,
                             'meta_watch.json': None, 'baro.json': None, 'nudges.json': None,
                             'wishlist.json': None, 'trader_plan.json': None,
                             'sell_timing.json': None, 'trader_limits.json': None,
                             'kill_switch.json': None, 'session_stats.json': None})
    doc = dg.build(root, NOW)
    secs = by_id(doc)
    assert secs['flips']['lines'] == ['no data (data/flip_digest.json missing)']
    assert secs['demand']['lines'] == ['no data (data/trends.json missing; data/meta_watch.json missing)']
    assert secs['baro']['lines'] == ['no data (data/baro.json missing)']
    assert secs['nudges']['lines'] == ['no data (data/nudges.json missing)']
    assert secs['wishlist']['lines'] == ['no data (data/wishlist.json missing)']
    assert secs['plan']['lines'] == ['no data (data/trader_plan.json missing)']
    assert secs['timing']['lines'] == ['no data (data/sell_timing.json missing)']
    assert secs['account']['lines'][1] == 'no data (data/trader_limits.json missing)'
    assert secs['account']['lines'][2] == 'kill switch: no data (data/kill_switch.json missing)'
    assert secs['account']['lines'][0] == 'unknown account | 1,022p (plat_history just now)'
    assert doc['source_ages']['flip_digest.json'] is None
    assert doc['source_ages']['plat_history.json'] is not None   # the one file left on disk
    assert len(doc['missing']) == len(SOURCE_NAMES) - 1
    assert doc['markdown_chars'] <= dg.DISCORD_LIMIT


def test_stale_file_reads_as_no_data_with_its_age(dg, root):
    old = seed(root, **{'trends.json': TRENDS, 'meta_watch.json': META_WATCH})
    for name in ('trends.json', 'meta_watch.json'):
        path = os.path.join(old, 'data', name)
        stamp = NOW - 3 * 24 * 3600
        os.utime(path, (stamp, stamp))
    doc = dg.build(old, NOW)
    assert by_id(doc)['demand']['lines'] == [
        'no data (data/trends.json 3.0d old; data/meta_watch.json 3.0d old)']
    assert doc['stale'] == ['trends.json', 'meta_watch.json']
    assert any('stale source file(s)' in note for note in doc['notes'])


def test_a_stale_primary_source_falls_back_before_saying_no_data(dg, root):
    path = os.path.join(root, 'data', 'trends.json')
    stamp = NOW - 3 * 24 * 3600
    os.utime(path, (stamp, stamp))
    lines = by_id(dg.build(root, NOW))['demand']['lines']
    assert lines[0].startswith('SPIKE Meta Spike')       # meta_watch is fresh, so it is used
    assert 'no data' not in ' '.join(lines)


def test_unreadable_file_says_unreadable(dg, root):
    with open(os.path.join(root, 'data', 'nudges.json'), 'w', encoding='utf-8') as fh:
        fh.write('{not json')
    line = by_id(dg.build(root, NOW))['nudges']['lines'][0]
    assert line.startswith('no data (data/nudges.json unreadable')


def test_empty_documents_still_compose(dg, tmp_path):
    root = tmp_path
    for name in SOURCE_NAMES:
        write_json(os.path.join(str(root), 'data', name), {})
    doc = dg.build(str(root), NOW)
    secs = by_id(doc)
    assert len(doc['sections']) == 9
    assert secs['flips']['lines'][0].startswith('no ranked flips')
    assert secs['nudges']['lines'][0].startswith('no READY or ONE_AWAY')
    assert secs['plan']['lines'][0].startswith('0 orders / ? copies')
    assert secs['timing']['lines'][0].startswith('no verdict')
    assert doc['markdown_chars'] <= dg.DISCORD_LIMIT


def test_missing_data_dir_is_not_fatal(dg, tmp_path):
    doc = dg.build(str(tmp_path / 'nothing_here'), NOW)
    assert len(doc['sections']) == 9
    assert all(age is None for age in doc['source_ages'].values())
    assert doc['generated'] == NOW


# ------------------------------------------------------------------------- source ages / blob

def test_source_ages_are_minutes_since_each_mtime(dg, root):
    doc = dg.build(root, NOW)
    assert sorted(doc['source_ages']) == sorted(SOURCE_NAMES)
    aged = seed(root, **{'trends.json': TRENDS})
    stamp = NOW - 130 * 60
    os.utime(os.path.join(aged, 'data', 'trends.json'), (stamp, stamp))
    doc = dg.build(aged, NOW)
    assert doc['source_ages']['trends.json'] == 130.0
    assert 'trends 2.2h ago' in by_id(doc)['data']['lines'][0]
    assert by_id(doc)['data']['lines'][0].startswith('generated ')


def test_markdown_budget_truncates_gracefully(dg, tmp_path):
    long_name = 'Wishlist Row With An Absurdly Long Name' + ' x' * 60
    verbose = dict(FIXTURES)
    verbose['wishlist.json'] = {
        'summary': WISHLIST['summary'],
        'suggested': [dict(WISHLIST['suggested'][0], name=long_name),
                      dict(WISHLIST['suggested'][1], name=long_name + ' two'),
                      dict(WISHLIST['suggested'][2])]}
    verbose['flip_digest.json'] = {
        'counts': FLIP_DIGEST['counts'],
        'digest': [dict(row, name=row['name'] + ' ' + 'y' * 80) for row in FLIP_DIGEST['digest']]}
    seed(tmp_path, **verbose)
    doc = dg.build(str(tmp_path), NOW)

    assert doc['truncated'] is True
    assert doc['markdown_chars'] <= dg.DISCORD_LIMIT
    assert len(doc['discord_markdown']) <= dg.DISCORD_LIMIT
    for sec in doc['sections']:
        assert ('**%s**' % sec['title']) in doc['discord_markdown']     # no section vanishes
    assert any('... (+' in line for line in doc['discord_markdown'].splitlines())
    assert 'truncated to fit' in by_id(doc)['data']['lines'][0]
    assert len(doc['discord_markdown_full']) >= len(doc['discord_markdown'])
    assert doc['clipped_sections']


def test_lean_digest_is_not_truncated(dg, tmp_path):
    lean = dict(FIXTURES)
    lean['flip_digest.json'] = {'counts': {'fresh': 4}, 'digest': FLIP_DIGEST['digest'][:1]}
    lean['trends.json'] = {'top_spikes': TRENDS['top_spikes'][:1], 'top_fades': TRENDS['top_fades'][:1]}
    lean['nudges.json'] = {'counts': {'ready': 1}, 'ready': NUDGES['ready'][:1]}
    lean['wishlist.json'] = {'summary': WISHLIST['summary'], 'suggested': WISHLIST['suggested'][:1]}
    seed(tmp_path, **lean)
    doc = dg.build(str(tmp_path), NOW)
    assert doc['truncated'] is False
    assert doc['markdown_chars'] <= dg.DISCORD_LIMIT
    assert doc['discord_markdown'] == doc['discord_markdown_full']


def test_hard_clip_backstop_never_leaves_a_dangling_bold(dg):
    text = '\n'.join('**Fresh flips**\n' + 'x' * 200 for _ in range(12))
    clipped = dg.hard_clip(text, 200)
    assert len(clipped) <= 200
    assert clipped.endswith('...')
    assert clipped.count('**') % 2 == 0


# ------------------------------------------------------------------------------ cli surface

def test_print_emits_markdown_only_on_stdout(dg, root, capsys):
    rc = dg.main(['digest.py', '--root', root, '--print', '--no-save', '--now', str(NOW)])
    out, err = capsys.readouterr()
    assert rc == 0
    doc = dg.build(root, NOW)
    assert out == doc['discord_markdown'] + '\n'
    assert '[digest]' in err.splitlines()[0]           # status goes to stderr, not the blob
    assert not os.path.exists(os.path.join(root, 'data', 'daily_digest.json'))


def test_saves_the_json_by_default_and_no_save_writes_nothing(dg, root, capsys):
    rc = dg.main(['digest.py', '--root', root, '--now', str(NOW)])
    capsys.readouterr()
    out_path = os.path.join(root, 'data', 'daily_digest.json')
    assert rc == 0 and os.path.exists(out_path)
    saved = read_json(out_path)
    assert saved['generated'] == NOW
    assert saved['markdown_chars'] == len(saved['discord_markdown'])
    assert sorted(saved['source_ages']) == sorted(SOURCE_NAMES)
    assert [s['id'] for s in saved['sections']][0] == 'account'
    assert not os.path.exists(out_path + '.tmp')

    os.remove(out_path)
    assert dg.main(['digest.py', '--root', root, '--no-save']) == 0
    assert not os.path.exists(out_path)


def test_now_flag_accepts_epoch_and_iso(dg):
    assert dg.parse_now(str(NOW)) == NOW
    stamp = dg.parse_now('2026-09-25T10:00:00')
    assert dg.iso(stamp).endswith('Z') and str(stamp).startswith('1790')
    with pytest.raises(SystemExit):
        dg.parse_now('not-a-time')


def test_notify_is_skipped_when_the_bridge_is_absent(dg, root, capsys):
    rc = dg.main(['digest.py', '--root', root, '--notify', '--no-save'])
    out = capsys.readouterr()
    assert rc == 0
    assert 'skipped' in out.out
    assert not os.path.exists(os.path.join(root, 'scripts', 'trader', 'notify_rules.py'))


def test_notify_hands_the_blob_to_the_bridge_when_present(dg, root, capsys):
    trader_dir = os.path.join(root, 'scripts', 'trader')
    os.makedirs(trader_dir, exist_ok=True)
    stub = os.path.join(trader_dir, 'notify_rules.py')
    sent = os.path.join(trader_dir, 'sent.json')
    with open(stub, 'w', encoding='utf-8') as fh:
        fh.write('import json, os\n\n\ndef emit(kind, body):\n'
                 '    with open(os.path.join(os.path.dirname(__file__), "sent.json"), "w") as out:\n'
                 '        json.dump({"kind": kind, "chars": len(body), "body": body}, out)\n'
                 '    return len(body)\n')
    assert dg.main(['digest.py', '--root', root, '--notify', '--no-save', '--now', str(NOW)]) == 0
    capsys.readouterr()
    written = read_json(sent)
    assert written['kind'] == 'daily_digest'
    assert written['body'] == dg.build(root, NOW)['discord_markdown']
    assert written['chars'] <= dg.DISCORD_LIMIT

    # a keyword-only signature must still be accepted (the sibling bridge is not written yet)
    with open(stub, 'w', encoding='utf-8') as fh:
        fh.write('import json, os\n\n\ndef emit(kind, *, body):\n'
                 '    with open(os.path.join(os.path.dirname(__file__), "sent.json"), "w") as out:\n'
                 '        json.dump({"kind": kind, "chars": len(body)}, out)\n')
    assert dg.notify_emit(root, dg.build(root, NOW)) == 'sent'
    assert read_json(sent)['kind'] == 'daily_digest'


def test_notify_failure_is_reported_not_raised(dg, root, capsys):
    trader_dir = os.path.join(root, 'scripts', 'trader')
    os.makedirs(trader_dir, exist_ok=True)
    with open(os.path.join(trader_dir, 'notify_rules.py'), 'w', encoding='utf-8') as fh:
        fh.write('def emit(*a, **k):\n    raise RuntimeError("bridge exploded")\n')
    assert dg.notify_emit(root, dg.build(root, NOW)) == 'error'
    assert 'bridge exploded' in capsys.readouterr().out


def test_does_not_read_the_repo_data_directory(dg, tmp_path, monkeypatch):
    """build()/main() must only open files under the given root (repo data/ is off limits)."""
    opened = []
    real_open = open

    def spy(path, *args, **kwargs):
        opened.append(str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr('builtins.open', spy)
    root = seed(tmp_path)
    dg.build(root, NOW)
    repo_data = os.path.join(os.path.dirname(SCRIPTS), 'data')
    assert opened and all(not os.path.abspath(p).startswith(repo_data + os.sep) for p in opened)


# ---------------------------------------------------------------------------------- selftest

def test_selftest_passes_offline(dg, capsys):
    assert dg.selftest() == 0
    out = capsys.readouterr().out
    assert 'selftest OK' in out
    assert 'checks' in out


def test_selftest_subprocess_writes_nothing_into_the_cwd(tmp_path):
    """--selftest must stay offline and touch nothing outside its own tmp dir."""
    proc = subprocess.run([sys.executable, DIGEST_PATH, '--selftest'], cwd=str(tmp_path),
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert 'selftest OK' in proc.stdout
    assert os.listdir(str(tmp_path)) == []
    assert not os.path.exists(os.path.join(str(tmp_path), 'data'))
