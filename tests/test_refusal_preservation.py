"""The refusal-preservation gate, wired into the suite (Phase 4, milestone 4.6).

The gate itself lives in design/_planner/conditions_gate.py and runs against the real ingested
database. This file makes it a test too: against the repo's real database when one has been
ingested, and against the fixture database otherwise, so CI (which has no data/) still runs every
check - and every falsification.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from builds import ingest  # noqa: E402
from test_builds_engine import FIXTURE_EQUIPMENT, FIXTURE_MODS, _mod_row  # noqa: E402
from test_condition_states import PHASE4_MODS  # noqa: E402

GATE_PATH = REPO / 'design' / '_planner' / 'conditions_gate.py'


def _load_gate():
    spec = importlib.util.spec_from_file_location('conditions_gate', str(GATE_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.REPORT = Path(os.environ.get('TMPDIR', str(REPO))) / 'conditions-gate-report.md'
    return mod


@pytest.fixture(scope='session')
def gate():
    return _load_gate()


@pytest.fixture(scope='session')
def real_db():
    """The ingested database, when the machine has one (the gate's real target)."""
    path = os.environ.get('WFM_BUILD_DB') or str(REPO / 'data' / 'build_data.json')
    return path if Path(path).exists() else None


@pytest.fixture(scope='session')
def fixture_db():
    slugs = {'/Fixture/BratonPrime': 'braton_prime', '/Fixture/Excalibur': 'excalibur'}
    src = {'file': 'refusal-preservation-test'}
    mods = [ingest.normalise_mod(_mod_row(*row), slugs, src)
            for row in list(FIXTURE_MODS) + PHASE4_MODS]
    equipment = [ingest.normalise_equipment(dict(raw, uniqueName=unique, name=name),
                                            kind, slugs, {}, src)
                 for unique, name, kind, raw in FIXTURE_EQUIPMENT]
    return ingest.build_database(mods, equipment,
                                 {'generated_iso': 'refusal-preservation-test',
                                  'game_version': 'refusal-preservation-test'})


@pytest.fixture(scope='session')
def audit_db(gate, real_db, fixture_db):
    """The database the gate runs against, plus the corpus size it should expect."""
    if real_db:
        from builds import data
        return data.load(real_db), 100
    return fixture_db, 1


def test_the_gate_passes_on_this_engine(gate, audit_db):
    db, min_corpus = audit_db
    res = gate.run_checks(db, min_corpus=min_corpus)
    assert res.ok, 'the refusal-preservation gate failed: %s' % json.dumps(
        [{'id': r['id'], 'detail': r['detail']} for r in res.failures], indent=1)


def test_the_gate_catches_every_deliberate_break(gate, audit_db):
    """Failure is only meaningful if the checks bite. Each break must be caught."""
    db, min_corpus = audit_db
    out = gate.falsify(db, min_corpus=min_corpus)
    missed = [row['break'] for row in out if not row['caught']]
    assert not missed, 'the gate did not notice: %s' % missed
    assert len(out) >= 6, 'every break is recorded, with the checks it failed'


def test_the_gate_report_is_written_and_reads_as_evidence(gate, audit_db, tmp_path):
    db, min_corpus = audit_db
    res = gate.run_checks(db, min_corpus=min_corpus)
    out = gate.falsify(db, min_corpus=min_corpus)
    report = gate.write_report(res, out, 'test database')
    text = Path(report).read_text(encoding='utf-8')
    assert 'Refusal-preservation gate' in text
    assert '| check | result |' in text
    assert 'Falsification' in text
    assert 'breaks caught' in text


def test_the_page_purity_check_catches_a_formula_on_the_page(gate, audit_db):
    """The one break that is about the UI rather than the engine."""
    db, min_corpus = audit_db
    poisoned = {name: 'var x = 4.25;' for name in gate.PAGE_FILES}
    res = gate.run_checks(db, page_text=poisoned, min_corpus=min_corpus)
    assert [r for r in res.failures if r['id'] == 'page/no-maths']


def test_the_real_page_passes_the_purity_check(gate, audit_db):
    db, min_corpus = audit_db
    res = gate.run_checks(db, min_corpus=min_corpus)
    assert [r for r in res.rows if r['id'] == 'page/no-maths'][0]['ok']
