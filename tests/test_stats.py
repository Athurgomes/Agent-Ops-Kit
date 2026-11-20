import copy
import json
from pathlib import Path

import pytest

from agent_ops_kit.redteam.harness import AttackRecord
from agent_ops_kit.report import build, render
from agent_ops_kit.report import stats as st

ROOT = Path(__file__).resolve().parent.parent


def _r(cid, success=False, error=None, blind=False):
    return AttackRecord(case_id=cid, category="injecao_direta", success=success, error=error, is_blind=blind)


# ---- McNemar exato (valores calculados à mão: 2 * P(X <= min(b, c)), X ~ Bin(b + c, 0,5)) ----

@pytest.mark.parametrize(
    ("b", "c", "p"),
    [
        (0, 0, 1.0),
        (1, 0, 1.0),  # 2 * 1/2
        (2, 0, 0.5),  # 2 * 1/4
        (5, 0, 0.0625),  # 2 * 1/32
        (8, 2, 0.109375),  # 2 * (1 + 10 + 45)/1024
        (3, 3, 1.0),  # 2 * 42/64 > 1, limitado a 1
        (2, 8, 0.109375),  # simétrico
        (10, 0, 2 / 1024),
    ],
)
def test_mcnemar_exact_p_by_hand(b, c, p):
    assert st.mcnemar_exact_p(b, c) == pytest.approx(p, abs=1e-15)


def test_mcnemar_exact_p_huge_counts_do_not_overflow():
    assert st.mcnemar_exact_p(5000, 5000) == 1.0
    assert 0 <= st.mcnemar_exact_p(4000, 6000) < 1e-30


def test_mcnemar_block_counts_and_exclusions():
    base = [_r("a", True), _r("b", True), _r("c"), _r("d", True), _r("e", True), _r("only_base")]
    guard = [
        _r("a"), _r("b", True), _r("c", True), _r("d", True, error="boom"), _r("e", True),
        _r("only_guard"),
    ]
    mc = st.mcnemar_block(base, guard)
    # a: só baseline (b); b: ambos; c: só guardrails (c); d: erro (excluído); e: ambos
    assert (mc["b"], mc["c"], mc["both"], mc["neither"], mc["n_paired"]) == (1, 1, 2, 0, 4)
    assert mc["excluded"] == {"errors": 1, "unpaired": 2, "total": 3}
    assert mc["p_value"] == 1.0 and mc["applicable"] is True and mc["reason"] is None


def test_mcnemar_error_on_baseline_side_also_excluded():
    mc = st.mcnemar_block([_r("a", True, error="x"), _r("b", True)], [_r("a"), _r("b")])
    assert (mc["n_paired"], mc["b"], mc["excluded"]["errors"]) == (1, 1, 1)


def test_mcnemar_repeated_runs_pair_by_occurrence():
    base = [_r("a", True), _r("a", True)]
    guard = [_r("a"), _r("a", True)]
    mc = st.mcnemar_block(base, guard)
    assert (mc["n_paired"], mc["b"], mc["c"], mc["both"]) == (2, 1, 0, 1)


def test_mcnemar_all_excluded_is_not_applicable():
    mc = st.mcnemar_block([_r("a", error="x")], [_r("a")])
    assert mc["applicable"] is False and mc["p_value"] is None
    assert mc["excluded"]["errors"] == 1 and "nenhum par" in mc["reason"]


def test_mcnemar_single_configuration_not_applicable():
    mc = st.mcnemar_block([_r("a")], None)
    assert mc["applicable"] is False and "só uma configuração" in mc["reason"]
    assert mc["p_value"] is None and mc["b"] is None


# ---- MDE ----

def test_mde_formulas():
    # (1,959964 + 0,841621) * sqrt(0,5 / 100)
    assert st.mde_proportion(100) == pytest.approx(2.801585 * 0.0707106781, rel=1e-6)
    assert st.mde_proportion(0) is None
    # meia-largura 0,1 -> 0,1 * 2,801585 / 1,959964
    assert st.mde_from_ci(0.0, 0.2) == pytest.approx(0.1 * 2.801585 / 1.959964, rel=1e-6)


# ---- ressalvas ----

def _prov(**runs):
    return {"git_commit": None, "git_dirty": None, "executions": runs}


def _row(n, k):
    return {"n": n, "successes": k, "asr": k / n, "ci95_low": 0.0, "ci95_high": 0.05, "errors": 0}


@pytest.fixture
def data():
    fp = {"n": 100, "blocked": 0, "rate": 0.0, "ci95_low": 0.0, "ci95_high": 0.04, "errors": 0}
    return {
        "eval": {
            "baseline": "v1", "candidate": "v2", "n_pairs": 50, "ci95_low": -0.01, "ci95_high": 0.03,
            "p_value": 0.01,
        },
        "redteam": {
            "n_attacks": 100, "n_blind_attacks": 0,
            "asr": {"baseline": {"total": _row(100, 20)}, "guardrails": {"total": _row(100, 5)}},
            "false_positives": {"dataset": fp, "benign": dict(fp)},
            "mcnemar": st.mcnemar_block(
                [_r(f"a{i}", i < 20) for i in range(100)], [_r(f"a{i}", i < 5) for i in range(100)]
            ),
        },
        "provenance": {
            "git_commit": "c" * 40, "git_dirty": False,
            "executions": {
                "eval": {"v1": {"git_commit": "a" * 40, "git_dirty": False},
                         "v2": {"git_commit": "a" * 40, "git_dirty": False}},
                "redteam": {"baseline": {"git_commit": "a" * 40, "git_dirty": False},
                            "guardrails": {"git_commit": "a" * 40, "git_dirty": False},
                            "false_positives": {"git_commit": "a" * 40, "git_dirty": False}},
            },
        },
    }


def test_caveats_deterministic_and_have_one_line_per_measurement(data):
    a = st.statistical_caveats(data)
    assert a == st.statistical_caveats(copy.deepcopy(data))
    lines = [x for x in a if "efeito mínimo detectável" in x]
    assert len(lines) == 5
    assert lines[1].startswith("ASR sem guardrails: n = 100, IC 95% [0.0%; 5.0%]")
    # 2,801585 * sqrt(0,005) = 0,19810 -> 19,9 pontos percentuais (arredondado para cima)
    assert "19.9 pontos percentuais" in lines[1]
    assert not any("n pequeno" in x for x in a)
    assert not any("commits diferentes" in x or "árvore" in x for x in a)
    assert any("McNemar" not in x and "pública" in x for x in a)


def test_caveat_mcnemar_p_value_from_data(data):
    # b = 15, c = 0 -> p = 2 / 2**15, significativo: sem aviso de não significativo
    assert data["redteam"]["mcnemar"]["b"] == 15
    assert not any("McNemar: p" in x for x in st.statistical_caveats(data))


def test_caveats_small_n_wide_ci_and_nonsignificant(data):
    data["eval"].update(n_pairs=10, ci95_low=-0.2, ci95_high=0.3, p_value=0.4)
    data["redteam"]["mcnemar"] = st.mcnemar_block([_r("a", True), _r("b")], [_r("a"), _r("b", True)])
    out = st.statistical_caveats(data)
    assert any(x.startswith("n pequeno") and "n = 10" in x for x in out)
    assert any(x.startswith("IC largo") and "Eval" in x for x in out)
    assert any(x.startswith("Eval: p = 0.4000, não significativo") for x in out)
    assert any(x.startswith("McNemar: p = 1.0000, não significativo") for x in out)


def test_caveat_commits_differ_and_dirty(data):
    ex = data["provenance"]["executions"]
    ex["redteam"]["guardrails"] = {"git_commit": "b" * 40, "git_dirty": True}
    data["provenance"]["git_dirty"] = True
    out = st.statistical_caveats(data)
    diff = next(x for x in out if x.startswith("Execuções em commits diferentes"))
    assert "red team guardrails em " + "b" * 12 in diff and "eval v1 em " + "a" * 12 in diff
    assert any(x.startswith("Execuções com árvore git") and "red team guardrails" in x for x in out)
    assert any(x.startswith("O relatório foi gerado com a árvore git") for x in out)
    # ordem fixa: commits antes de árvore suja
    assert out.index(diff) < next(i for i, x in enumerate(out) if x.startswith("Execuções com árvore"))


def test_caveat_commit_not_recorded(data):
    data["provenance"]["executions"]["eval"]["v1"] = {"git_commit": None, "git_dirty": None}
    out = st.statistical_caveats(data)
    assert any(x.startswith("Commit não registrado") and "eval v1" in x for x in out)
    assert not any("commits diferentes" in x for x in out)


def test_caveat_suite_blind_variants(data):
    data["redteam"]["n_blind_attacks"] = 10
    assert any(x.startswith("Só 10 de 100 ataques vêm de suíte cega") for x in st.statistical_caveats(data))
    del data["redteam"]["n_blind_attacks"]
    assert any("não há registro de suíte cega" in x.lower() for x in st.statistical_caveats(data))


def test_caveat_no_second_configuration(data):
    data["redteam"]["mcnemar"] = st.mcnemar_block([_r("a")], None)
    out = st.statistical_caveats(data)
    assert any(x.startswith("McNemar não aplicável: há só uma configuração") for x in out)


# ---- integração: build, JSON e render ----

def _write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _rec(cid, success=False, error=None):
    return {"case_id": cid, "category": "injecao_direta", "success": success, "error": error}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp("mc")
    _write(d / "b.jsonl", [_rec("a1", True), _rec("a2", True), _rec("a3"), _rec("a4", True)])
    _write(d / "g.jsonl", [_rec("a1"), _rec("a2", True), _rec("a3", True), _rec("a4", error="x")])
    ben = {"case_id": "q1", "blocked": False, "blocked_by": [], "reasons": [], "error": None}
    _write(d / "fp_dataset.jsonl", [ben])
    _write(d / "fp_benign.jsonl", [{**ben, "case_id": "b1"}])
    return build.build_data(
        config=str(ROOT / "examples/rag_agent/agent.yaml"),
        dataset=str(ROOT / "evals/dataset.jsonl"),
        prompts_dir=str(ROOT / "evals/prompts"),
        answers_dir=str(ROOT / "evals/answers"),
        baseline="v1", candidate="v2", seed=42,
        redteam_baseline=str(d / "b.jsonl"), redteam_guardrails=str(d / "g.jsonl"), fp_dir=str(d),
    )


def test_build_json_has_mcnemar_and_generated_caveats(built):
    mc = built["redteam"]["mcnemar"]
    assert (mc["n_paired"], mc["b"], mc["c"], mc["p_value"]) == (3, 1, 1, 1.0)
    assert mc["excluded"] == {"errors": 1, "unpaired": 0, "total": 1}
    assert any(x.startswith("n pequeno") for x in built["limitations"])
    assert not any("os intervalos de confiança são largos" in x for x in built["limitations"])
    assert json.loads(json.dumps(built)) == built


def test_render_shows_mcnemar_table_and_not_applicable(built):
    md = render.to_markdown(render.build_blocks(built))
    assert "Teste de McNemar exato" in md and "1.0000" in md and "1 (1 / 0)" in md
    alt = copy.deepcopy(built)
    alt["redteam"]["mcnemar"] = st.mcnemar_block([_r("a")], None)
    md2 = render.to_markdown(render.build_blocks(alt))
    assert "não aplicável" in md2 and "só uma configuração" in md2
    old = copy.deepcopy(built)
    del old["redteam"]["mcnemar"]
    assert "McNemar" in render.to_markdown(render.build_blocks(old))

