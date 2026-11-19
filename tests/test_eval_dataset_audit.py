"""Testes para o dataset expandido de auditoria (200 casos) e suporte completo via --dataset."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

from agent_ops_kit import cli
from agent_ops_kit.config import load_config
from agent_ops_kit.eval import runner
from agent_ops_kit.eval.checks import REFUSAL_PHRASE, _has_token, _norm, run_checks
from agent_ops_kit.eval.dataset import load_dataset

ROOT = Path(__file__).resolve().parent.parent
AUDIT_DATASET = ROOT / "evals" / "dataset_audit_200.jsonl"
BASE_DATASET = ROOT / "evals" / "dataset.jsonl"
CORPUS_DIR = ROOT / "examples" / "rag_agent" / "corpus"
PROMPTS_DIR = ROOT / "evals" / "prompts"
CONFIG_PATH = ROOT / "examples" / "rag_agent" / "agent.yaml"
ANSWERS_MANIFEST = ROOT / "evals" / "answers" / "manifest.json"


def _mock_reply(text: str) -> dict:
    return {
        "message": {"role": "assistant", "content": text},
        "prompt_eval_count": 12,
        "eval_count": 6,
    }


def _good_answer(case) -> str:
    if not case.answerable:
        return REFUSAL_PHRASE
    return f"{'; '.join(case.expected)}.\nFonte: {case.sources[0]}"


def _write_minimal_redteam(rt_dir: Path) -> None:
    rt_dir.mkdir(parents=True, exist_ok=True)
    attack_base = {
        "case_id": "a1",
        "category": "injecao_direta",
        "success": True,
        "blocked_by": [],
        "final_answer": "ok",
        "raw_answer": "ok",
    }
    attack_guard = {**attack_base, "success": False}
    fp_ok = {
        "case_id": "q1",
        "blocked": False,
        "blocked_by": [],
        "reasons": [],
        "answer": "ok",
        "raw_answer": "ok",
        "score": 1.0,
        "error": None,
    }
    for name, rows in (
        ("baseline.jsonl", [attack_base]),
        ("guardrails.jsonl", [attack_guard]),
        ("fp_dataset.jsonl", [fp_ok]),
        ("fp_benign.jsonl", [fp_ok]),
    ):
        (rt_dir / name).write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n",
            encoding="utf-8",
        )


def test_audit_dataset_estrutura_cobertura_e_fidelidade_ao_corpus():
    cases = load_dataset(AUDIT_DATASET)
    assert len(cases) == 200
    assert len(cases) >= 200

    ids = [c.id for c in cases]
    assert len(set(ids)) == 200

    norm_questions = [_norm(c.question) for c in cases]
    assert len(set(norm_questions)) == 200

    base_cases = load_dataset(BASE_DATASET)
    base_ids = {c.id for c in base_cases}
    base_questions = {_norm(c.question) for c in base_cases}
    assert set(ids).isdisjoint(base_ids)
    assert set(norm_questions).isdisjoint(base_questions)

    answerable = [c for c in cases if c.answerable]
    unanswerable = [c for c in cases if not c.answerable]
    assert len(answerable) >= 150
    assert len(unanswerable) >= 25

    corpus_files = {p.name: _norm(p.read_text(encoding="utf-8")) for p in CORPUS_DIR.glob("*.md")}
    assert len(corpus_files) == 15

    source_counts: Counter[str] = Counter()
    for c in answerable:
        for src in c.sources:
            assert src in corpus_files, f"{c.id}: fonte inexistente {src}"
            source_counts[src] += 1
        for exp in c.expected:
            needle = _norm(exp)
            assert any(_has_token(corpus_files[s], needle) for s in c.sources), (
                f"{c.id}: esperado {exp!r} ausente nas fontes {c.sources}"
            )
        if len(c.sources) > 1:
            for src in c.sources:
                assert any(_has_token(corpus_files[src], _norm(e)) for e in c.expected), (
                    f"{c.id}: fonte {src} sem item correspondente em expected"
                )
        assert run_checks(c, _good_answer(c)).score == 1.0, c.id

    for c in unanswerable:
        assert c.expected == []
        assert c.sources == []
        assert run_checks(c, _good_answer(c)).score == 1.0, c.id

    assert set(source_counts) == set(corpus_files)
    assert all(count >= 10 for count in source_counts.values())


def test_audit_dataset_execucao_runner_1_e_2_execucoes_deterministica(tmp_path):
    cases = load_dataset(AUDIT_DATASET)
    config = load_config(CONFIG_PATH)
    by_question = {c.question: c for c in cases}

    def make_deterministic_llm():
        def llm(model, messages, tools):
            user_text = messages[-1]["content"]
            case = by_question[user_text]
            is_v2 = "Exemplo 1" in messages[0]["content"]
            if is_v2 and case.id == "aud-001":
                return _mock_reply("Resposta: incompleta")
            return _mock_reply(f"Resposta: {_good_answer(case)}")

        return llm

    # 1 execução
    out_1 = tmp_path / "run1" / "v1.jsonl"
    recs_1 = runner.run_variant(
        "v1",
        cases,
        config,
        llm=make_deterministic_llm(),
        out_path=out_1,
        prompts_dir=PROMPTS_DIR,
        runs=1,
    )
    assert len(recs_1) == 200
    scores_1 = runner.score_records(cases, recs_1)
    assert len(scores_1) == 200
    assert all(v == 1.0 for v in scores_1.values())
    summary_1 = runner.summarize_runs(cases, recs_1)
    assert summary_1["n_runs"] == 1
    assert summary_1["mean"] == 1.0
    assert summary_1["exact_answer_consistency_rate"] == 1.0

    # 2 execuções (determinístico e estável)
    out_2a = tmp_path / "run2a" / "v2.jsonl"
    out_2b = tmp_path / "run2b" / "v2.jsonl"
    recs_2a = runner.run_variant(
        "v2",
        cases,
        config,
        llm=make_deterministic_llm(),
        out_path=out_2a,
        prompts_dir=PROMPTS_DIR,
        runs=2,
    )
    recs_2b = runner.run_variant(
        "v2",
        cases,
        config,
        llm=make_deterministic_llm(),
        out_path=out_2b,
        prompts_dir=PROMPTS_DIR,
        runs=2,
    )
    assert len(recs_2a) == 400
    assert [r["run_index"] for r in recs_2a] == [0] * 200 + [1] * 200
    assert [(r["case_id"], r["answer"], r["run_index"]) for r in recs_2a] == [
        (r["case_id"], r["answer"], r["run_index"]) for r in recs_2b
    ]
    scores_2 = runner.score_records(cases, recs_2a)
    assert len(scores_2) == 200
    assert scores_2["aud-001"] < 1.0
    summary_2 = runner.summarize_runs(cases, recs_2a)
    assert summary_2["n_runs"] == 2
    assert summary_2["exact_score_consistency_rate"] == 1.0
    assert summary_2["exact_answer_consistency_rate"] == 1.0


def test_cli_eval_report_e_check_com_dataset_audit_200(tmp_path, monkeypatch, capsys):
    manifest_before = ANSWERS_MANIFEST.read_text(encoding="utf-8")
    cases = load_dataset(AUDIT_DATASET)
    by_question = {c.question: c for c in cases}

    shutil.copytree(PROMPTS_DIR, tmp_path / "prompts")
    answers_dir = tmp_path / "answers"

    def fake_make_llm(seed: int = 42):
        def llm(model, messages, tools):
            case = by_question[messages[-1]["content"]]
            is_v2 = "Exemplo 1" in messages[0]["content"]
            if is_v2 and case.id in {"aud-001", "aud-002", "aud-003"}:
                return _mock_reply("Resposta: sem dados suficientes")
            return _mock_reply(f"Resposta: {_good_answer(case)}")

        return llm

    monkeypatch.setattr(runner, "make_ollama_llm", fake_make_llm)

    eval_report = tmp_path / "eval_report.md"
    code = cli.main(
        [
            "eval",
            "--baseline",
            "v1",
            "--candidate",
            "v2",
            "--dataset",
            str(AUDIT_DATASET),
            "--prompts-dir",
            str(tmp_path / "prompts"),
            "--config",
            str(CONFIG_PATH),
            "--answers-dir",
            str(answers_dir),
            "--seed",
            "42",
            "--summary",
            "--report",
            str(eval_report),
        ]
    )
    assert code == 0
    eval_out = capsys.readouterr().out
    assert "200 casos (200 pareados)" in eval_out
    assert "média v1: 1.0000" in eval_out
    assert eval_report.is_file()

    # Reutilização via --reuse validando o manifesto gerado para os 200 casos
    assert (
        cli.main(
            [
                "eval",
                "--baseline",
                "v1",
                "--candidate",
                "v2",
                "--dataset",
                str(AUDIT_DATASET),
                "--prompts-dir",
                str(tmp_path / "prompts"),
                "--config",
                str(CONFIG_PATH),
                "--answers-dir",
                str(answers_dir),
                "--reuse",
                "--summary",
                "--report",
                str(eval_report),
            ]
        )
        == 0
    )
    capsys.readouterr()

    # Suporte ponta a ponta em `aok report build --dataset` e `aok check --dataset`
    rt_dir = tmp_path / "rt"
    _write_minimal_redteam(rt_dir)
    pkg_dir = tmp_path / "pacote"
    assert (
        cli.main(
            [
                "report",
                "build",
                "--dataset",
                str(AUDIT_DATASET),
                "--prompts-dir",
                str(tmp_path / "prompts"),
                "--config",
                str(CONFIG_PATH),
                "--answers-dir",
                str(answers_dir),
                "--redteam-baseline",
                str(rt_dir / "baseline.jsonl"),
                "--redteam-guardrails",
                str(rt_dir / "guardrails.jsonl"),
                "--fp-dir",
                str(rt_dir),
                "--out",
                str(pkg_dir),
            ]
        )
        == 0
    )
    capsys.readouterr()
    data = json.loads((pkg_dir / "relatorio.json").read_text(encoding="utf-8"))
    assert data["eval"]["n_cases"] == 200
    assert data["eval"]["n_pairs"] == 200
    assert data["eval"]["manifest"]["v1"]["n_cases"] == 200
    assert data["eval"]["manifest"]["v2"]["n_cases"] == 200

    pub_dir = tmp_path / "publicados"
    chk_dir = tmp_path / "pacote_check"
    assert (
        cli.main(
            [
                "check",
                "--dataset",
                str(AUDIT_DATASET),
                "--prompts-dir",
                str(tmp_path / "prompts"),
                "--config",
                str(CONFIG_PATH),
                "--answers-dir",
                str(answers_dir),
                "--redteam-baseline",
                str(rt_dir / "baseline.jsonl"),
                "--redteam-guardrails",
                str(rt_dir / "guardrails.jsonl"),
                "--fp-dir",
                str(rt_dir),
                "--out",
                str(chk_dir),
                "--publish",
                str(pub_dir),
                "--agent-id",
                "rag-audit",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (pub_dir / "rag-audit" / "index.json").is_file()
    assert ANSWERS_MANIFEST.read_text(encoding="utf-8") == manifest_before
