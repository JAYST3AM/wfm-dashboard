"""Backup + export for the WFM dashboard (roadmap #42).

- zip: every data/*.json (and data/research/) into data/backups/wfm-backup-YYYYmmdd-HHMMSS.zip
  Logs, exports and the backups folder itself are excluded. Newest 12 zips are kept.
- --picks-csv: also exports today's sell picks (report.sell_now) to data/exports/picks-YYYYmmdd.csv

Restore: stop the server, unzip the backup over the data/ folder.
Usage:  python scripts/backup.py [--picks-csv]
"""
import csv, glob, json, os, sys, time, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
BACKUPS = os.path.join(DATA, 'backups')
EXPORTS = os.path.join(DATA, 'exports')
KEEP = 12
SKIP_DIRS = {'backups', 'exports'}
SKIP_EXT = {'.log', '.zip'}


def make_zip():
    os.makedirs(BACKUPS, exist_ok=True)
    out = os.path.join(BACKUPS, time.strftime('wfm-backup-%Y%m%d-%H%M%S.zip'))
    n = 0
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for base, dirs, files in os.walk(DATA):
            rel = os.path.relpath(base, DATA)
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                if os.path.splitext(f)[1].lower() in SKIP_EXT:
                    continue
                arc = f if rel == '.' else os.path.join(rel, f)
                z.write(os.path.join(base, f), arc)
                n += 1
    zips = sorted(glob.glob(os.path.join(BACKUPS, 'wfm-backup-*.zip')))
    for old in zips[:-KEEP]:
        os.remove(old)
    return out, n, min(len(zips), KEEP)


def picks_csv():
    os.makedirs(EXPORTS, exist_ok=True)
    rep = json.load(open(os.path.join(DATA, 'report.json'), encoding='utf-8'))
    out = os.path.join(EXPORTS, time.strftime('picks-%Y%m%d.csv'))
    cols = ['slug', 'name', 'cat', 'count', 'wts', 'wtb', 'med', 'vol48', 'value', 'spread', 'sellable_count']
    rows = [r for r in (rep.get('sell_now') or []) if not r.get('in_use_only')]
    with open(out, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['rank'] + cols)
        for i, r in enumerate(rows, 1):
            w.writerow([i] + [r.get(c) for c in cols])
    return out, len(rows)


def main():
    z, n, kept = make_zip()
    print(f'backup: {z}  ({n} files, {kept} zips kept)')
    if '--picks-csv' in sys.argv:
        p, rows = picks_csv()
        print(f'picks csv: {p}  ({rows} rows)')
    print('restore: stop the server, unzip the backup over the data/ folder')


if __name__ == '__main__':
    main()
