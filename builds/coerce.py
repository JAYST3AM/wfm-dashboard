#!/usr/bin/env python3
"""Numeric coercion, in its own module so that validation and capacity cannot depend on
each other.

`validation` imports `capacity`; `capacity` needed `as_int`; importing it back from
`validation` made the pair order-dependent and `import builds.validation` failed outright
whenever validation was imported first (found by the Phase 4 adversarial review).
"""
import math


def as_int(value, default=0, minimum=None, maximum=None):
    """A build field that should be an integer, coerced WITHOUT ever raising (Phase 4).

    `int(chr(97)+chr(98)+chr(99))` raises ValueError and `int(1e400)` raises OverflowError -
    both of which used to escape `compute()` and turn a malformed build into a 500. A value
    that is not a finite integer is not coerced into one here: the caller reports its own
    validation error and carries on with the default, which is what makes "malformed input
    must not crash the engine" true rather than aspirational. Booleans are refused too
    (`True` is not rank 1). Out-of-range values are clamped to the range, which is a
    documented coercion rather than a refusal.
    """
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, float):
        if not math.isfinite(value) or value != int(value):
            return default
        value = int(value)
    elif isinstance(value, int):
        pass
    elif isinstance(value, str):
        text = value.strip()
        if not text or text.lstrip(chr(43) + chr(45)).isdigit() is False:
            return default
        try:
            value = int(text)
        except ValueError:
            return default
    else:
        return default
    if minimum is not None and value < minimum:
        return minimum
    if maximum is not None and value > maximum:
        return maximum
    return value
