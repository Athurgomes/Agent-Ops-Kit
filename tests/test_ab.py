import math

import pytest

from agent_ops_kit.eval.ab import format_ab_markdown, paired_ab


def _scores(values):
    return {f"c{i}": v for i, v in enumerate(values)}


def test_identical_scores():
    s = _scores([0.2, 0.5, 0.9, 1.0])
    r = paired_ab(s, dict(s))
    assert r.mean_diff == 0
    assert r.p_value == 1.0
    assert r.ci_low == 0 and r.ci_high == 0


def test_consistent_improvement_large_n():
    base = _scores([0.4 + 0.01 * (i % 7) for i in range(30)])
    cand = {k: v + 0.3 for k, v in base.items()}
    r = paired_ab(base, cand)
    assert r.n == 30 and r.p_method == "monte_carlo"
    assert r.mean_diff == pytest.approx(0.3)
    assert r.p_value < 0.001
    assert r.ci_low > 0


def test_symmetric_differences_high_p():
    base = _scores([0.5] * 20)
    cand = _scores([0.5 + (0.2 if i % 2 else -0.2) for i in range(20)])
    r = paired_ab(base, cand)
    assert r.mean_diff == pytest.approx(0)
    assert r.p_value > 0.9
    assert r.ci_low < 0 < r.ci_high


def test_exact_enumeration_by_hand():
    # diffs = +1, +2, +3: 8 sinais; |soma| >= 6 só em (+++) e (---) -> p = 2/8
    base = {"a": 0.0, "b": 0.0, "c": 0.0}
    cand = {"a": 1.0, "b": 2.0, "c": 3.0}
    r = paired_ab(base, cand)
    assert r.p_method == "exact"
    assert r.p_value == pytest.approx(0.25)
    assert r.mean_diff == pytest.approx(2.0)


def test_exact_enumeration_mixed_signs_by_hand():
    # diffs = +1, +1, -1: |soma| observada = 1; somas possíveis: ±3 (2x), ±1 (6x) -> todas >= 1
    base = {"a": 0.0, "b": 0.0, "c": 1.0}
    cand = {"a": 1.0, "b": 1.0, "c": 0.0}
    assert paired_ab(base, cand).p_value == 1.0


def test_deterministic_same_seed_and_seed_matters():
    base = _scores([0.1 * (i % 10) for i in range(25)])
    cand = _scores([0.1 * ((i * 3) % 10) for i in range(25)])
    a = paired_ab(base, cand, seed=7)
    assert a == paired_ab(base, cand, seed=7)
    assert a.seed == 7 and a.n_resamples == 10_000
    assert a != paired_ab(base, cand, seed=8)


def test_dropped_ids_counted_not_zero_filled():
    base = {"a": 1.0, "b": 1.0, "c": None, "d": 1.0, "only_base": 1.0}
    cand = {"a": 2.0, "b": 2.0, "c": 5.0, "d": math.nan, "only_cand": 3.0}
    r = paired_ab(base, cand)
    assert r.n == 2
    assert r.n_dropped == 4  # c, d, only_base, only_cand
    assert r.mean_baseline == 1.0 and r.mean_candidate == 2.0


def test_too_few_pairs_raises():
    with pytest.raises(ValueError):
        paired_ab({"a": 1.0}, {"a": 2.0})
    with pytest.raises(ValueError):
        paired_ab({"a": 1.0, "b": None}, {"a": 1.0, "b": 2.0})


def test_format_markdown_fields():
    base = _scores([0.0, 0.1, 0.2, 0.1, 0.0, 0.3])
    cand = {k: v + 0.5 for k, v in base.items()}
    r = paired_ab(base, cand)
    assert r.p_value == pytest.approx(2 / 64)
    md = format_ab_markdown(r, "v1", "v2", "determinístico")
    for text in ["v1", "v2", "determinístico", "IC 95%", "p-valor", "Descartados", "42", "causalidade"]:
        assert text in md
    assert "estatisticamente distinguível" in md  # p = 2/64 < 0.05
    for bad in ["melhor", "pior"]:
        assert bad not in md


def test_format_markdown_no_significance_claim_when_p_high():
    s = _scores([0.1, 0.2, 0.3])
    md = format_ab_markdown(paired_ab(s, dict(s)), "v1", "v2", "m")
    assert "estatisticamente distinguível" not in md
