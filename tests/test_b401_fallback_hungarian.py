"""B401: Der scipy-freie Fallback muss korrekt UND polynomiell sein."""
import random
import time

import pytest

from tracking.association import _fallback_linear_sum_assignment

scipy_lsa = pytest.importorskip("scipy.optimize").linear_sum_assignment


def _cost_of(matrix, rows, cols):
    return sum(matrix[i][j] for i, j in zip(rows, cols))


def test_matches_scipy_on_square_matrix():
    m = [[4.0, 1.0, 3.0], [2.0, 0.0, 5.0], [3.0, 2.0, 2.0]]
    r_f, c_f = _fallback_linear_sum_assignment(m)
    r_s, c_s = scipy_lsa(m)
    assert _cost_of(m, r_f, c_f) == pytest.approx(_cost_of(m, list(r_s), list(c_s)))


def test_matches_scipy_on_rectangular_matrix():
    """Nach B400 ist die Matrix n_det x (n_trk + n_det) — immer rechteckig."""
    m = [[0.10, 0.95, 0.80, 1e6], [0.20, 0.99, 1e6, 0.80]]
    r_f, c_f = _fallback_linear_sum_assignment(m)
    r_s, c_s = scipy_lsa(m)
    assert _cost_of(m, r_f, c_f) == pytest.approx(_cost_of(m, list(r_s), list(c_s)))


def test_b400_dummy_case_picks_good_pair():
    """Der konkrete B400-Fall: gutes Paar + bewusste Nicht-Zuordnung."""
    m = [[0.10, 0.95, 0.80, 1e6], [0.20, 0.99, 1e6, 0.80]]
    rows, cols = _fallback_linear_sum_assignment(m)
    assignment = dict(zip(rows, cols))
    assert assignment[0] == 0, "D1 muss T1 (0.10) bekommen"
    assert assignment[1] == 3, "D2 muss die Dummy-Spalte (0.80) waehlen"


@pytest.mark.parametrize("seed", range(20))
def test_matches_scipy_on_random_matrices(seed):
    rng = random.Random(seed)
    n = rng.randint(1, 5)
    m_cols = n + rng.randint(0, 4)
    m = [[rng.uniform(0, 1) for _ in range(m_cols)] for _ in range(n)]
    r_f, c_f = _fallback_linear_sum_assignment(m)
    r_s, c_s = scipy_lsa(m)
    assert _cost_of(m, r_f, c_f) == pytest.approx(_cost_of(m, list(r_s), list(c_s)), abs=1e-9)


def test_handles_more_rows_than_cols():
    """n > m: der Algorithmus transponiert."""
    m = [[1.0, 2.0], [3.0, 0.5], [0.2, 4.0]]
    r_f, c_f = _fallback_linear_sum_assignment(m)
    r_s, c_s = scipy_lsa(m)
    assert _cost_of(m, r_f, c_f) == pytest.approx(_cost_of(m, list(r_s), list(c_s)))


def test_each_column_used_once():
    m = [[0.1, 0.9, 0.5, 0.5], [0.2, 0.8, 0.5, 0.5], [0.3, 0.7, 0.5, 0.5]]
    rows, cols = _fallback_linear_sum_assignment(m)
    assert len(set(cols)) == len(cols)
    assert len(set(rows)) == len(rows)


def test_realistic_size_is_fast():
    """KERNREGRESSION: 8 Zellen -> 8x16 Matrix. Brute Force braeuchte ~17 min."""
    n = 8
    m = [[float((i * 7 + j * 3) % 11) / 10.0 for j in range(2 * n)] for i in range(n)]
    start = time.time()
    rows, cols = _fallback_linear_sum_assignment(m)
    elapsed = time.time() - start
    assert elapsed < 1.0, f"Fallback brauchte {elapsed:.1f}s fuer 8x16 — faktorielle Laufzeit?"
    assert len(rows) == n


def test_larger_size_still_terminates():
    """12 Zellen: Brute Force waere 24!/12! ~ 1.3e15 Iterationen."""
    n = 12
    m = [[float((i * 13 + j * 5) % 17) / 10.0 for j in range(2 * n)] for i in range(n)]
    start = time.time()
    rows, _ = _fallback_linear_sum_assignment(m)
    assert time.time() - start < 2.0
    assert len(rows) == n


def test_empty_matrix_is_safe():
    assert _fallback_linear_sum_assignment([]) == ([], [])
    assert _fallback_linear_sum_assignment([[]]) == ([], [])


def test_no_bruteforce_left():
    import inspect
    import tracking.association as A
    src = inspect.getsource(A._fallback_linear_sum_assignment)
    assert "itertools.permutations" not in src, "Brute-Force-Aufzaehlung noch vorhanden"


def test_rows_are_sorted():
    """scipy liefert row_ind aufsteigend — der Fallback muss das auch."""
    m = [[0.5, 0.1, 0.9], [0.2, 0.8, 0.3]]
    rows, _ = _fallback_linear_sum_assignment(m)
    assert rows == sorted(rows)
