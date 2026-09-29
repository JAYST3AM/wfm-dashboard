#!/usr/bin/env python
"""design/_session/home_buyer_gate.py - does Home show a buyer the row's lane does not have?

    python design/_session/home_buyer_gate.py          # prints each check, exits 0/1

The regression it pins (2026-09-29): renderNextAction() read `sessionAskedBy(r) || who[0]`, so a top
plan row for rank 6 - a lane with no buyer - painted the rank-0 buyer for the same slug, whisper
button and all. The rule was right; the render undid it. The fix removed the fallback and the
slug-wide helper with it.

WHAT IT DOES: makes one throwaway data dir, boots the real server against it (WFM_ROOT=<repo> so the
real static/ serves the page, WFM_DATA=<throwaway> so the developer's data/ is never touched),
rewrites only trader_plan.json + run_queue.json between the two scenarios, drives the real Home page
with puppeteer-core, and reads what was painted. Nothing is clicked that writes anything.

Scenario A: top plan row rank 6; the run queue holds only a rank-0 buyer for that slug.
            Home must offer NO whisper button, name no buyer, and send the user to the buyers surface.
Scenario B: top plan row rank 0; the run queue holds that lane's buyer. Home must offer exactly one
            whisper button for the right-lane buyer - and the session panel must agree with Home.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import workflow_gate as wg          # noqa: E402  (the boot template, free_port, wait_ready, http_json)

DRIVER = os.path.join(HERE, 'home_buyer_gate.js')
SLUG = 'primed_continuity'
NAME = 'Primed Continuity'


def jwrite(path, obj):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, indent=1)


def seed(data, lane, buyer, buyer_lane):
    """One plan row in `lane`, and a run queue holding that one buyer (or none, when buyer is None)."""
    rank = None if not str(lane).startswith('rank ') else int(str(lane).split()[1])
    jwrite(os.path.join(data, 'trader_plan.json'), {
        'generated': datetime.now().astimezone().isoformat(), 'dry_run': True,
        'account': 'HomeBuyerGate',
        'plan': [{'slug': SLUG, 'name': NAME, 'per_trade': 3, 'price': 48,
                  'rank': None, 'lane': lane}]})
    jwrite(os.path.join(data, 'report.json'), {
        'totals': {'sellable': 4},
        'sell_now': [{'slug': SLUG, 'name': NAME, 'cat': 'mod', 'lane_rank': rank,
                      'lane_ask': 60, 'sellable_count': 4}]})
    queue = [] if buyer is None else [{
        'slug': SLUG, 'lane': buyer_lane, 'rank': None if not buyer_lane.startswith('rank ')
        else int(buyer_lane.split()[1]),
        'qty': 3, 'my_price': 48, 'buyer': buyer, 'buyer_status': 'ingame', 'buy_price': 48,
        'why': 'seeded by home_buyer_gate.py'}]
    jwrite(os.path.join(data, 'run_queue.json'), {'queue': queue, 'summary': {}})
    jwrite(os.path.join(data, 'trader_limits.json'),
           {'plat': 1220, 'account': 'HomeBuyerGate', 'trades_left': 6, 'trade_cap': 20, 'ts': 0})
    jwrite(os.path.join(data, 'plat_history.json'),
           [{'ts': int(time.time()) - 3600, 'plat': 1220}])


def main():
    data = tempfile.mkdtemp(prefix='home-buyer-')
    boot = os.path.join(data, '_boot.py')
    log = os.path.join(data, '_server.log')
    port = wg.free_port()
    base = 'http://127.0.0.1:%d' % port
    proc = None
    try:
        with open(boot, 'w', encoding='utf-8') as fh:
            fh.write(wg.boot_source())
        env = dict(os.environ, WFM_ROOT=wg.REPO, WFM_DATA=data, WFM_PORT=str(port),
                   WFM_HOST='127.0.0.1')
        # scenario A first: the rank-6 lane has no buyer, the rank-0 buyer exists for the same slug
        seed(data, 'rank 6', 'WrongLane', 'rank 0')
        with open(log, 'wb') as fh:
            proc = subprocess.Popen([sys.executable, boot], cwd=wg.REPO, env=env,
                                    stdout=fh, stderr=subprocess.STDOUT)
        why = wg.wait_ready(base, proc, log)
        if why:
            print('HOME BUYER GATE: FAIL - ' + why)
            return 1
        print('gate server on %s, data dir %s' % (base, data))

        # The driver runs ONE scenario per process: the launcher rewrites the fixture between them,
        # so the only thing that has to be timed is the page load (the app always reads from disk).
        results = []
        for scen, lane, buyer, buyer_lane in (('A', 'rank 6', 'WrongLane', 'rank 0'),
                                              ('B', 'rank 0', 'RightLane', 'rank 0')):
            seed(data, lane, buyer, buyer_lane)
            run = subprocess.run(['node', DRIVER, base, scen], cwd=wg.REPO, capture_output=True,
                                 text=True, timeout=300)
            lines = [l for l in (run.stdout or '').splitlines() if l.strip().startswith('{')]
            if run.returncode != 0 or not lines:
                print('HOME BUYER GATE: FAIL - driver rc=%s (scenario %s) stderr=%s'
                      % (run.returncode, scen, (run.stderr or '')[-300:]))
                print(run.stdout[-600:])
                return 1
            results.extend(json.loads(l) for l in lines)
        fatal = [r for r in results if r.get('fatal')]
        if fatal:
            print('HOME BUYER GATE: FAIL - ' + str(fatal[0]['fatal']))
            return 1
        checks = [r for r in results if not r.get('summary')]
        failed = [c for c in checks if not c['ok']]
        for c in checks:
            print('  %s %s%s' % ('ok  ' if c['ok'] else 'FAIL', c['title'],
                                 '' if c['ok'] else '  (expected %s, saw %s)'
                                 % (c['expected'], str(c['observed'])[:120])))
        print('HOME BUYER %s - %d of %d checks'
              % ('PASS' if not failed else 'FAIL', len(checks) - len(failed), len(checks)))
        return 0 if not failed else 1
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
        shutil.rmtree(data, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
