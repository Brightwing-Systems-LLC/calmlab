from __future__ import annotations

import random

from calmlab import stats


def test_ranks_share_ties():
    assert stats.ranks([10, 20, 20, 5]) == [2, 3.5, 3.5, 1]


def test_spearman_reads_order_not_size():
    assert stats.spearman([1, 2, 3, 4], [1, 10, 100, 1000]) == 1
    assert stats.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1
    assert stats.spearman([1, 2, 3, 4], [3, 3, 3, 3]) is None


def test_a_perfect_link_is_significant_and_noise_is_not():
    rho, p = stats.spearman_test(list(range(10)), list(range(10)))
    assert rho == 1 and p < 0.001
    rng = random.Random(3)
    noise = [rng.random() for _ in range(30)]
    rho, p = stats.spearman_test(list(range(30)), noise)
    assert p > 0.05


def test_the_same_data_gives_the_same_p_value():
    xs, ys = [1, 4, 2, 8, 5, 7, 3], [2, 3, 1, 5, 4, 5, 2]
    assert stats.spearman_test(xs, ys) == stats.spearman_test(xs, ys)


def test_benjamini_hochberg():
    # Five tests at 5%: thresholds are 0.01, 0.02, 0.03, 0.04, 0.05 by rank.
    assert stats.significant([0.001, 0.015, 0.04, 0.2, 0.9]) == [True, True, False, False, False]
    # The largest rank that passes carries every smaller p-value with it.
    assert stats.significant([0.012, 0.011, 0.03, 0.04, 0.9]) == [True, True, True, True, False]
    assert stats.significant([0.04]) == [True]
    assert stats.significant([0.2, 0.3]) == [False, False]
