"""The conditional-effect corpus census (Phase 5): what the corpus carries, what now applies,
what still refuses and why. Read-only; the numbers this prints belong in the phase report."""
import collections
import sys
sys.path.insert(0, r'F:/VSC Projects/wfm-dashboard')
from builds import buffs, data

DB = data.load(r'F:/VSC Projects/wfm-dashboard/data/build_data.json')

lines = []
for row in DB['mods'].values():
    for text in (row.get('effects') or {}).get('conditional') or []:
        lines.append((row, text))

TRIGGER_WORDS = (
    ('on kill', 'on kill'), ('weak point', 'weak point / headshot'),
    ('headshot', 'weak point / headshot'), ('on hit', 'on hit'), ('on reload', 'on reload'),
    ('when aiming', 'aiming'), ('for every', 'per-stack ("for every")'),
    ('stacks with', 'stacks with'), ('on status', 'on status'),
    ('per status', 'per status type'), ('on crit', 'on crit'), ('holster', 'holster/reload'),
    ('on damage', 'on taking damage'), ('on dodge', 'on dodge'), ('on ability', 'on ability'),
    ('on cast', 'on cast'),
)
kinds = collections.Counter()
rider_states = collections.Counter()
refusals = collections.Counter()
enabled = []
for mod, text in lines:
    rider = buffs.parse_rider(text)
    is_rider_shape = bool(rider) and rider.get('trigger') == 'on_kill'
    if not is_rider_shape:
        low = text.lower()
        label = 'no recognised trigger word'
        for word, name in TRIGGER_WORDS:
            if word in low:
                label = name
                break
        kinds['not an on-kill rider: ' + label] += 1
        continue
    kinds['on-kill rider shape'] += 1
    if rider.get('enabled'):
        enabled.append((mod.get('name'), rider['stat'], rider['max_stacks']))
        rider_states['applies from a stated state'] += 1
    elif rider.get('applicable'):
        rider_states['refused: stat not applied conditionally'] += 1
        refusals['stat not applied conditionally: ' + str(rider.get('stat'))] += 1
    else:
        rider_states['refused: not applicable'] += 1
        refusals[str(rider.get('reason'))[:78]] += 1

print('conditional lines in the corpus:', len(lines))
print('mods carrying them:', len({m['id'] for m, _ in lines}))
print()
print('shape:')
for k, v in kinds.most_common():
    print('  %-64s %d' % (k, v))
print()
print('on-kill rider outcome:')
for k, v in rider_states.most_common():
    print('  %-64s %d' % (k, v))
print()
print('enabled riders (apply from a stated state):', len(enabled))
print('  stats they move:', dict(collections.Counter(s for _, s, _ in enabled)))
print('  mods:', ', '.join(sorted({n for n, _, _ in enabled})))
print()
print('refusal reasons among rider-shaped lines:')
for k, v in refusals.most_common(10):
    print('  %-64s %d' % (k, v))
