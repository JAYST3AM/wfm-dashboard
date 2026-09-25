"""Snapshot platinum (and credits) into data/plat_history.json.

Append rule: value changed -> append; unchanged -> heartbeat append at most every 30 min.
Ran by: Task Scheduler every 15 min (optional), and after every dashboard 'Refresh'.
"""
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
AF = os.path.expandvars(r'%LOCALAPPDATA%\AlecaFrame')
HEARTBEAT = 1800  # seconds


def main():
    from refresh import decrypt
    pt = decrypt(os.path.join(AF, 'lastData.dat'))
    save = json.loads(pt.decode('utf-8'))
    plat = save.get('PremiumCredits')
    credits = save.get('RegularCredits')
    if plat is None:
        print('no PremiumCredits in save; skipped')
        return
    hist_p = os.path.join(DATA, 'plat_history.json')
    hist = json.load(open(hist_p, encoding='utf-8')) if os.path.exists(hist_p) else []
    now = int(time.time())
    if hist:
        last = hist[-1]
        if last.get('plat') == plat and (now - last['ts']) < HEARTBEAT:
            print(f'unchanged ({plat}p); skipped (last point {now - last["ts"]}s ago)')
            return
    hist.append(dict(ts=now, plat=plat, credits=credits))
    json.dump(hist, open(hist_p, 'w', encoding='utf-8'))
    print(f'appended {plat}p (points: {len(hist)})')


if __name__ == '__main__':
    main()
