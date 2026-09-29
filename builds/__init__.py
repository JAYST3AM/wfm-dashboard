#!/usr/bin/env python3
"""The WFM Build Planner engine (Phase 1: math + data foundation).

A self-contained, stdlib-only calculation layer that answers "what does this build
produce?" for Warframe equipment. Nothing here touches the DOM, the market, the network
or the AlecaFrame save: inputs are plain JSON-shaped dicts (norma data + a build
configuration) and outputs are JSON-shaped dicts with a step-by-step trace.

Layout
    schema.py       canonical ids, polarities, damage types, slot kinds, stat ids
    trace.py        the explainability primitives ("why is this number this number")
    effects.py      mod stat parsing (WFCD levelStats -> per-rank effect tables)
    elements.py     elemental-combination order engine (mod placement hierarchy)
    capacity.py     mod capacity / drain engine (polarity, aura, stance, exilus, Forma)
    weapons.py      weapon stat engine (damage, elements, crit, status, multishot, ...)
    warframes.py    Warframe stat engine (health/shield/armor/energy + ability stats)
    validation.py   structured build validation (never raises on a bad build)
    unsupported.py  the explicit unsupported-mechanics registry
    data.py         loader + indexes for the ingested build database
    ingest.py       data ingestion/update path (WFCD -> data/build_data.json)
    api.py          the one entry point: compute_build(build, data) -> result
    debug.py        tiny developer surface for inspecting the engine

Ground rules (Phase 1 brief)
  * Deterministic and pure: no globals, no I/O in the math modules, no market data.
  * Never approximate silently: anything not modelled is returned as an explicit
    unsupported marker instead of a plausible-looking number.
  * Values carry provenance: every data row records the source that owns it.
  * The Python engine owns the formulas; a UI consumes its JSON later.
"""

__all__ = ['schema', 'trace', 'effects', 'elements', 'capacity', 'weapons', 'warframes',
           'validation', 'unsupported', 'data', 'api']

SCHEMA_VERSION = 1  # the shape of data/build_data.json + the build representation
