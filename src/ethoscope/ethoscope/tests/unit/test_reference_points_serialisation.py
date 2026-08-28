#!/usr/bin/env python3
"""
Unit tests for how target coordinates are written into METADATA.

``reference_points`` is the only record of where an experiment believed its
arena targets were. It is written with ``str()`` over a list of tuples, and the
values come from a float32 array, so the elements are numpy scalars.

NumPy 2.0 changed scalar repr from ``1205.1133`` to ``np.float32(1205.1133)``.
Because ``str()`` of a list calls repr on its elements, every run after that
upgrade stored a string no consumer can read back: ``json.loads`` rejects it and
``ast.literal_eval`` rejects it, and ``eval`` only works if numpy happens to be
imported under that exact name. Sampling the archive, 108 of 168 recent
experiments were affected.

These tests pin the stored form to something parseable, for any input type.
"""

import ast

import numpy as np
import pytest


def _serialise(reference_points):
    """The expression used in ControlThread._build_metadata."""
    return str([(float(p[0]), float(p[1])) for p in reference_points])


@pytest.mark.parametrize(
    "points",
    [
        np.array([(1160.6, 137.1), (1163.2, 837.9), (49.7, 851.4)], dtype=np.float32),
        np.array([(1160.6, 137.1), (1163.2, 837.9), (49.7, 851.4)], dtype=np.float64),
        [(1160.6, 137.1), (1163.2, 837.9), (49.7, 851.4)],
        [[1160.6, 137.1], [1163.2, 837.9], [49.7, 851.4]],
    ],
    ids=["float32-array", "float64-array", "list-of-tuples", "list-of-lists"],
)
def test_the_stored_string_can_be_read_back(points):
    """Regression: numpy scalar repr leaked into the database."""
    stored = _serialise(points)

    assert "np.float" not in stored, f"numpy repr leaked into METADATA: {stored}"

    parsed = ast.literal_eval(stored)
    assert len(parsed) == 3
    for got, want in zip(parsed, points, strict=True):
        assert got[0] == pytest.approx(float(want[0]), abs=1e-3)
        assert got[1] == pytest.approx(float(want[1]), abs=1e-3)


def test_the_format_matches_what_older_runs_wrote():
    """Consumers already read the pre-NumPy-2.0 form; do not change it."""
    points = np.array([(1.5, 2.5), (3.5, 4.5), (5.5, 6.5)], dtype=np.float32)

    assert _serialise(points) == "[(1.5, 2.5), (3.5, 4.5), (5.5, 6.5)]"


def test_the_old_expression_is_what_broke():
    """Document the defect, so the fix is not undone as redundant."""
    points = np.array([(1.5, 2.5), (3.5, 4.5), (5.5, 6.5)], dtype=np.float32)

    broken = str([(p[0], p[1]) for p in points])

    if "np.float" in broken:  # NumPy >= 2.0
        with pytest.raises((ValueError, SyntaxError)):
            ast.literal_eval(broken)
    else:  # NumPy 1.x wrote a parseable string, which is why this went unnoticed
        assert ast.literal_eval(broken)
