"""Append an event to the dashboard's trade log (data/trade_log.json).

Usage: python log_trade.py <kind> <name> <qty> <plat> [total] [note...]
kinds: sale | purchase | listing | unlist | reprice | note
"""
import json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
KINDS = ('sale', 'purchase', 'listing', 'unlist', 'reprice', 'note')


def main(argv):
    if len(argv) < 5:
        print(__doc__)
        return 2
    kind, name = argv[1], argv[2]
    if kind not in KINDS:
        print('bad kind, use one of', KINDS)
        return 2
    qty, plat = int(argv[3]), float(argv[4])
    args = argv[5:]
    total = qty * plat
    if args and args[0].replace('.', '', 1).isdigit():
        total = float(args[0])
        args = args[1:]
    note = ' '.join(args)
    ev = dict(ts=int(time.time()), kind=kind, name=name, qty=qty, plat=plat,
              total=round(total, 2), note=note)
    path = os.path.join(DATA, 'trade_log.json')
    hist = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else []
    hist.append(ev)
    json.dump(hist, open(path, 'w', encoding='utf-8'), indent=1)
    print(json.dumps(ev))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
