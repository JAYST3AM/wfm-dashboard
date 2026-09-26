"""First-run setup: connect everything in order and build the dashboard's data.

Stage 1 - core (required):
  1. Check AlecaFrame is installed and has synced an inventory
  2. Read + decrypt the inventory (scripts/refresh.py) - also downloads the WFM
     item catalogue to data/wfm_items_v2.json on the first run
  3. Fetch live prices for your items (scripts/fetch_prices.py, resumable)
  4. Fetch 48h sale statistics (scripts/fetch_stats.py, resumable)
  5. Rank lanes: per-rank order book for owned mods (scripts/fetch_lanes.py, resumable)
  6. Build the report + the smart sell advisor, seed the platinum history

Stage 2 - page data (optional, skippable):
  Collection log, mod cards and the market tools that every dashboard page reads.
  A step that fails here does not stop setup - it is listed at the end with the
  exact command to run by hand.

Safe to re-run: every step is resumable and skips what it already built.
Ctrl+C is safe too: re-run and setup continues where it stopped.
"""
import os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, 'scripts')
AF = os.path.expandvars(r'%LOCALAPPDATA%\AlecaFrame')

CORE_STEPS = [
    ('refresh.py',),                    # inventory -> owned.json (+ item catalogue)
    ('fetch_prices.py',),               # live prices  -> prices.json
    ('fetch_stats.py',),                # 48h stats    -> stats.json
    ('fetch_lanes.py',),                # rank lanes   -> price_lanes.json
    ('report.py',),                     # sell/buy plan -> report.json
    ('sell_advisor.py', '--write'),     # per-item advice -> sell_advisor.json
    ('snapshot_plat.py',),              # seed the platinum history
]

PAGE_STEPS = [
    ('collection_log.py',),             # Collection page (WFCD catalogue, one-time fetch)
    ('mod_cards.py',),                  # Cards page (WFCD mod catalogue, one-time fetch)
    ('invdiff.py',),                    # Inventory changes
    ('price_history.py',),              # price snapshots -> Movers
    ('item_history.py',),               # intraday per-item points -> sparklines / price page
    ('sets.py',),                       # set completion
    ('ducats.py',),                     # sell vs burn
    ('relic_ev.py',),                   # open vs sell relics
    ('craft.py',),                      # build vs buy
    ('nudges.py',),                     # almost-complete sets
    ('wishlist.py',),                   # budget planner
    ('trends.py',),                     # demand trends
    ('baro.py',),                       # Baro Ki'Teer planner
    ('rivens.py',),                     # riven price bands
    ('meta_watcher.py', '--fetch'),     # post-patch demand spikes
    ('deal_scanner.py',),               # whole-market deals (rotating, resumable)
    ('sell_timing.py',),                # best time to sell (needs trade history)
    ('session_stats.py',),              # session analytics (needs trade history)
]


def run(name, *args):
    print(f'\n=== {name} ===', flush=True)
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, name), *args], cwd=ROOT)
    if r.returncode != 0:
        print(f'\n{name} failed (exit {r.returncode}). Fix the error above and re-run: python scripts/setup.py')
        sys.exit(r.returncode)


def run_soft(name, *args):
    """Optional step: a failure is remembered, never fatal."""
    print(f'\n=== {name} (optional) ===', flush=True)
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, name), *args], cwd=ROOT)
    return r.returncode == 0


def main():
    print('WFM Trader - first-run setup')
    print(f'Looking for AlecaFrame at: {AF}')
    dat = os.path.join(AF, 'lastData.dat')
    if not os.path.exists(dat):
        print('\nAlecaFrame cache not found.')
        print('  1. Install AlecaFrame: https://alecaframe.com')
        print('  2. Open Warframe once so AlecaFrame syncs your inventory')
        print('  3. Run this again: python scripts/setup.py')
        sys.exit(1)
    print(f'Found: lastData.dat ({os.path.getsize(dat):,} bytes)')

    try:
        import cryptography  # noqa: F401
    except ImportError:
        print('\nMissing dependency: cryptography')
        print('Install it with: pip install cryptography')
        sys.exit(1)

    print('\n--- core data (the long part: prices + stats + rank lanes, resumable) ---')
    for step in CORE_STEPS:
        run(*step)

    print('\n--- page data (optional - each step skips automatically when up to date) ---')
    skipped = []
    for step in PAGE_STEPS:
        if not run_soft(*step):
            skipped.append(step[0])

    print('\nAll done.' if not skipped
          else f'\nCore data is ready; {len(skipped)} optional step(s) were skipped.')
    if skipped:
        print('Everything still works - re-run any of these later (they resume):')
        for name in skipped:
            print(f'  python scripts/{name}')
    print('\nStart the dashboard:  start.bat   (or: python server.py)')
    print('Then open:            http://127.0.0.1:8787')
    print('Refresh any time:     refresh.bat')


if __name__ == '__main__':
    main()
