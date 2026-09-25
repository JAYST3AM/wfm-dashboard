"""First-run setup: connect everything in order and build the dashboard's data.

Steps:
  1. Check AlecaFrame is installed and has synced an inventory
  2. Read + decrypt the inventory (scripts/refresh.py)
  3. Fetch live prices for your items (scripts/fetch_prices.py, resumable)
  4. Fetch 48h sale statistics (scripts/fetch_stats.py, resumable)
  5. Build the report (scripts/report.py) + seed the platinum history

Safe to re-run: every step is resumable and skips what's already done.
"""
import os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, 'scripts')
AF = os.path.expandvars(r'%LOCALAPPDATA%\AlecaFrame')


def run(name, *args):
    print(f'\n=== {name} ===', flush=True)
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, name), *args], cwd=ROOT)
    if r.returncode != 0:
        print(f'\n{name} failed (exit {r.returncode}). Fix the error above and re-run: python scripts/setup.py')
        sys.exit(r.returncode)


def main():
    print('WFM Trader — first-run setup')
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

    run('refresh.py')        # read inventory -> data/owned.json
    run('fetch_prices.py')   # live prices   -> data/prices.json
    run('fetch_stats.py')    # 48h stats     -> data/stats.json
    run('report.py')         # sell/buy plan -> data/report.json
    run('sell_advisor.py', '--write')  # per-item advice -> data/sell_advisor.json
    run('snapshot_plat.py')  # seed plat history

    print('\nAll done.')
    print('Start the dashboard:  python server.py   (or start.bat)')
    print('Then open:            http://127.0.0.1:8787')


if __name__ == '__main__':
    main()
