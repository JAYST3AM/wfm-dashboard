"""The Phase 6 migration gate (6.2): same input -> same conditions -> same refusals -> same traces
-> same numbers.

Extracts the pre-migration engine (`git archive <ref>` into a scratch directory), runs the probe
there and in the working tree against the *same* database, and diffs the canonical payloads case by
case. Any difference is a migration defect: investigate it, never re-pin it.

One allowance, and it is deliberately narrow: a field a *new* Phase 6 mechanic declares appears in
`evaluation.consumed` for existing cases (the path now asks the Heat question, exactly as it started
asking the corrosive question in Phase 5). The gate drops the Phase 6 field names from `consumed`
before comparing, reports how many cases needed that, and fails on anything else - including any
other key inside `evaluation`.

    python design/_planner/phase6_migration.py                 # ref defaults to the Phase 5 tip
    python design/_planner/phase6_migration.py --ref HEAD~1
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROBE = 'design/_planner/phase6_probe.py'
PY = sys.executable
REF = 'f1f2db3'          # the Phase 5 tip: the engine this migration must not change

# The declared Phase 6 inputs: they may appear in `evaluation.consumed` (a field the path now asks
# about) and nowhere else.
PHASE6_FIELDS = ('target.heat_strip', 'target.overguard', 'target.preset')


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _engine_output(tree, db_path, out_path, probe=PROBE):
    # The probe script is Phase 6's own (it does not exist in the pre-migration archive), so it is
    # copied into whichever tree is being measured - it is tree-agnostic by construction.
    target = os.path.join(tree, probe.replace('/', os.sep))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    source = os.path.join(REPO, probe.replace('/', os.sep))
    if os.path.abspath(source) != os.path.abspath(target):
        shutil.copyfile(source, target)
    result = run([PY, target, '--db', db_path, '--out', out_path], cwd=tree)
    if result.returncode != 0:
        raise RuntimeError('probe failed in %s:\n%s\n%s' % (tree, result.stdout[-2000:],
                                                            result.stderr[-2000:]))
    with open(out_path, encoding='utf-8') as handle:
        return json.load(handle)


def _strip_allowance(payload_text):
    """Return (payload without the Phase 6 consumed fields, whether the allowance was needed)."""
    try:
        payload = json.loads(payload_text)
        # the probe stores each case as the canonical JSON *text*, so a stored value is a string
        # containing the payload and needs its second parse
        if isinstance(payload, str):
            payload = json.loads(payload)
    except (TypeError, ValueError):
        return payload_text, False
    if not isinstance(payload, dict):
        return payload_text, False
    used = [False]

    def strip(obj):
        # every 'consumed' list anywhere in the payload (the top-level evaluation and its echo
        # inside result both carry one)
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == 'consumed' and isinstance(value, list):
                    kept = [field for field in value if field not in PHASE6_FIELDS]
                    if kept != value:
                        used[0] = True
                    obj[key] = kept
                else:
                    strip(value)
        elif isinstance(obj, list):
            for item in obj:
                strip(item)

    strip(payload)
    return json.dumps(payload, sort_keys=True, separators=(',', ':')), used[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Phase 6 migration gate')
    parser.add_argument('--ref', default=REF, help='git ref of the pre-migration engine')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    db_path = os.path.join(REPO, 'data', 'build_data.json')
    if not os.path.exists(db_path):
        print('no database at %s - run: python builds/ingest.py' % db_path)
        return 2
    scratch = tempfile.mkdtemp(prefix='wfm-phase6-migration-')
    try:
        archive = os.path.join(scratch, 'engine.tar')
        extract = os.path.join(scratch, 'engine')
        os.makedirs(extract, exist_ok=True)
        with open(archive, 'wb') as handle:
            proc = subprocess.run(['git', '-C', REPO, 'archive', args.ref], stdout=handle,
                                  stderr=subprocess.PIPE)
        if proc.returncode != 0:
            print('git archive %s failed: %s' % (args.ref, proc.stderr.decode('utf-8', 'replace')))
            return 2
        run(['tar', '-xf', archive, '-C', extract], cwd=REPO)
        before = _engine_output(extract, db_path, os.path.join(scratch, 'before.json'))
        after = _engine_output(REPO, db_path, os.path.join(scratch, 'after.json'))
        diffs, allowed = [], []
        for case_id in sorted(set(before) | set(after)):
            a, b = before.get(case_id), after.get(case_id)
            if a == b:
                continue
            a2, _used_a = _strip_allowance(a)
            b2, _used_b = _strip_allowance(b)
            if a2 == b2:
                allowed.append(case_id)
                continue
            diffs.append({'case': case_id, 'before': a2, 'after': b2})
        summary = {'ref': args.ref, 'cases': len(before), 'diffs': len(diffs),
                   'diff_ids': [d['case'] for d in diffs],
                   'allowance_ids': allowed, 'ok': not diffs}
        if args.json:
            print(json.dumps(summary, indent=1))
        else:
            for diff in diffs:
                print('DIFF %s' % diff['case'])
                a, b = diff['before'] or '', diff['after'] or ''
                for i in range(0, max(len(a), len(b)), 400):
                    if a[i:i + 400] != b[i:i + 400]:
                        print('   before: %s' % a[i:i + 400])
                        print('   after : %s' % b[i:i + 400])
                        break
            print('migration gate: %d cases, %d diff(s) against %s - %s'
                  % (summary['cases'], summary['diffs'], args.ref,
                     'IDENTICAL' if summary['ok'] else 'MIGRATION CHANGED AN ANSWER'))
            if allowed:
                print('  (%d case(s) differ only by a declared Phase 6 field in '
                      'evaluation.consumed: %s)' % (len(allowed), ', '.join(allowed[:6])))
        return 0 if summary['ok'] else 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
