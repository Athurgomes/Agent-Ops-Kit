"""Testes para medição de variância multi-execução (`aok eval --runs N`)."""

from __future__ import annotations

import json
import math
import re
import shutil
import statistics
from pathlib import Path

import pytest

from agent_ops_kit import cli
from agent_ops_kit.config import load_config
from agent_ops_kit.eval import runner
from agent_ops_kit.eval.checks import REFUSAL_PHRASE
from agent_ops_kit.eval.dataset import load_dataset
from agent_ops_kit.report import build, render

ROOT = Path(__file__).resolve().parent.parent
DATASET_PATH = ROOT / "evals" / "dataset.jsonl"
PROMPTS_DIR = ROOT / "evals" / "prompts"
CONFIG_PATH = ROOT / "examples" / "rag_agent" / "agent.yaml"
CASES = load_dataset(DATASET_PATH)[:4]
CONFIG = load_config(CONFIG_PATH)

BANNED = re.compile(r"\b(seguro|segura|robust[oa]s?|eficaz(es)?)\b", re.IGNORECASE)


def _good_answer(case) -> str:
    if not case.answerable:
        return REFUSAL_PHRASE
    return f"{'; '.join(case.expected)}.\nFonte: {case.sources[0]}"


def _reply(text: str) -> dict:
    return {
        "message": {"role": "assistant", "content": text},
        "prompt_eval_count": 10,
        "eval_count": 5,
    }


def _attack_rec(cid: str, cat: str, success: bool = False) -> dict:
    return {
        "case_id": cid,
        "category": cat,
        "success": success,
        "blocked_by": [],
        "final_answer": "ok",
        "raw_answer": "ok",
    }


def _fp_rec(cid: str) -> dict:
    return {
        "case_id": cid,
        "blocked": False,
        "blocked_by": [],
        "reasons": [],
        "answer": "ok",
        "raw_answer": "ok",
        "score": 1.0,
        "error": None,
    }


# ---- runner: run_variant, score_records, score_runs, summarize_runs ----


def test_run_variant_rejeita_runs_nao_positivo():
    with pytest.raises(ValueError, match="runs deve ser >= 1"):
        runner.run_variant(
            "v1", CASES, CONFIG, llm=lambda m, msg, t: _reply("ok"), limit=1, runs=0
        )
    with pytest.raises(ValueError, match="runs deve ser >= 1"):
        runner.run_variant(
            "v1", CASES, CONFIG, llm=lambda m, msg, t: _reply("ok"), limit=1, runs=-2
        )


def test_run_variant_runs_1_preserva_formato_sem_run_index(tmp_path):
    out = tmp_path / "v1.jsonl"
    recs = runner.run_variant(
        "v1",
        CASES,
        CONFIG,
        llm=lambda m, msg, t: _reply("ok"),
        out_path=out,
        limit=2,
        prompts_dir=PROMPTS_DIR,
        runs=1,
    )
    assert len(recs) == 2
    assert "run_index" not in recs[0]
    assert set(recs[0]) == {
        "case_id",
        "variant",
        "answer",
        "latency_s",
        "input_tokens",
        "output_tokens",
        "error",
    }
    assert runner.load_records(out) == recs


def test_run_variant_multirun_grava_run_index_e_usa_sementes_incrementais(tmp_path, monkeypatch):
    seen_seeds: list[int] = []

    def fake_make_llm(seed: int = 42):
        seen_seeds.append(seed)

        def llm(model, messages, tools):
            return _reply(f"Resposta: semente {seed}")

        return llm

    monkeypatch.setattr(runner, "make_ollama_llm", fake_make_llm)
    out = tmp_path / "v1.jsonl"
    recs = runner.run_variant(
        "v1",
        CASES,
        CONFIG,
        out_path=out,
        limit=2,
        seed=100,
        prompts_dir=PROMPTS_DIR,
        runs=3,
    )
    assert seen_seeds == [100, 101, 102]
    assert len(recs) == 6
    assert [r["run_index"] for r in recs] == [0, 0, 1, 1, 2, 2]
    assert [r["case_id"] for r in recs] == [CASES[0].id, CASES[1].id] * 3
    assert [r["answer"] for r in recs] == [
        "Resposta: semente 100",
        "Resposta: semente 100",
        "Resposta: semente 101",
        "Resposta: semente 101",
        "Resposta: semente 102",
        "Resposta: semente 102",
    ]
    assert runner.load_records(out) == recs


def test_run_variant_multirun_com_llm_injetado_variando_por_chamada():
    calls = {"n": 0}

    def llm(model, messages, tools):
        calls["n"] += 1
        return _reply(f"Resposta: chamada {calls['n']}")

    recs = runner.run_variant(
        "v1", CASES, CONFIG, llm=llm, limit=2, prompts_dir=PROMPTS_DIR, runs=3
    )
    assert len(recs) == 6
    assert [r["run_index"] for r in recs] == [0, 0, 1, 1, 2, 2]
    assert [r["answer"] for r in recs] == [f"Resposta: chamada {i}" for i in range(1, 7)]


def test_score_records_faz_media_por_case_id_em_multirun():
    c0, c1 = CASES[0], CASES[1]
    good0 = _good_answer(c0)
    good1 = _good_answer(c1)
    bad = "sem resposta util"
    records = [
        {"case_id": c0.id, "answer": good0, "run_index": 0},
        {"case_id": c1.id, "answer": good1, "run_index": 0},
        {"case_id": c0.id, "answer": bad, "run_index": 1},
        {"case_id": c1.id, "answer": good1, "run_index": 1},
    ]
    s0_good = runner.score_records(CASES, [{"case_id": c0.id, "answer": good0}])[c0.id]
    s0_bad = runner.score_records(CASES, [{"case_id": c0.id, "answer": bad}])[c0.id]
    s1_good = runner.score_records(CASES, [{"case_id": c1.id, "answer": good1}])[c1.id]

    avg_scores = runner.score_records(CASES, records)
    assert avg_scores[c0.id] == pytest.approx((s0_good + s0_bad) / 2)
    assert avg_scores[c1.id] == pytest.approx(s1_good)


def test_summarize_runs_caso_constante_e_caso_variante():
    c0, c1 = CASES[0], CASES[1]
    good0, good1 = _good_answer(c0), _good_answer(c1)

    # 1) Tudo constante em 3 execuções -> stdev 0.0, consistência 1.0
    const_recs = [
        {"case_id": c0.id, "answer": good0, "run_index": r} for r in range(3)
    ] + [
        {"case_id": c1.id, "answer": good1, "run_index": r} for r in range(3)
    ]
    const_summary = runner.summarize_runs(CASES, const_recs)
    assert const_summary["n_runs"] == 3
    assert const_summary["per_run_means"] == [1.0, 1.0, 1.0]
    assert const_summary["mean"] == 1.0
    assert const_summary["run_stdev"] == 0.0
    assert const_summary["mean_case_stdev"] == 0.0
    assert const_summary["exact_score_consistency_rate"] == 1.0
    assert const_summary["exact_answer_consistency_rate"] == 1.0

    # 2) c0 varia resposta mas mantém score; c1 varia resposta e score
    bad1 = "resposta errada"
    alt0 = f"{good0} (detalhe extra)"
    s0 = runner.score_records(CASES, [{"case_id": c0.id, "answer": good0}])[c0.id]
    s0_alt = runner.score_records(CASES, [{"case_id": c0.id, "answer": alt0}])[c0.id]
    assert s0 == 1.0 and s0_alt == 1.0
    s1_ok = 1.0
    s1_bad = runner.score_records(CASES, [{"case_id": c1.id, "answer": bad1}])[c1.id]
    assert s1_bad < 1.0

    var_recs = [
        {"case_id": c0.id, "answer": good0, "run_index": 0},
        {"case_id": c1.id, "answer": good1, "run_index": 0},
        {"case_id": c0.id, "answer": f"Raciocínio: x\nResposta: {alt0}", "run_index": 1},
        {"case_id": c1.id, "answer": bad1, "run_index": 1},
        {"case_id": c0.id, "answer": good0, "run_index": 2},
        {"case_id": c1.id, "answer": good1, "run_index": 2},
    ]
    run_scores = runner.score_runs(CASES, var_recs)
    assert len(run_scores) == 3
    assert run_scores[0] == {c0.id: 1.0, c1.id: s1_ok}
    assert run_scores[1] == {c0.id: 1.0, c1.id: s1_bad}
    assert run_scores[2] == {c0.id: 1.0, c1.id: s1_ok}

    expected_run_means = [
        (1.0 + s1_ok) / 2,
        (1.0 + s1_bad) / 2,
        (1.0 + s1_ok) / 2,
    ]
    expected_run_stdev = statistics.stdev(expected_run_means)
    c1_stdev = statistics.stdev([s1_ok, s1_bad, s1_ok])
    expected_mean_case_stdev = (0.0 + c1_stdev) / 2

    summary = runner.summarize_runs(CASES, var_recs)
    assert summary["n_runs"] == 3
    assert summary["per_run_means"] == pytest.approx(expected_run_means)
    assert summary["mean"] == pytest.approx(statistics.fmean(expected_run_means))
    assert summary["run_stdev"] == pytest.approx(expected_run_stdev)
    assert summary["mean_case_stdev"] == pytest.approx(expected_mean_case_stdev)
    # c0 teve mesmo score nas 3 execuções; c1 mudou -> 1/2 = 0.5
    assert summary["exact_score_consistency_rate"] == pytest.approx(0.5)
    # c0 mudou a final_answer na run 1; c1 mudou na run 1 -> 0/2 = 0.0
    assert summary["exact_answer_consistency_rate"] == pytest.approx(0.0)


def test_score_runs_e_summarize_runs_fallback_sem_run_index_e_vazio():
    c0 = CASES[0]
    good0 = _good_answer(c0)
    # Sem run_index, 1 execução -> n_runs=1, consistência 1.0
    single = [{"case_id": c0.id, "answer": good0}]
    s_single = runner.summarize_runs(CASES, single)
    assert s_single == {
        "n_runs": 1,
        "per_run_means": [1.0],
        "mean": 1.0,
        "run_stdev": 0.0,
        "mean_case_stdev": 0.0,
        "exact_score_consistency_rate": 1.0,
        "exact_answer_consistency_rate": 1.0,
    }

    # Sem run_index, 2 ocorrências sequenciais do mesmo caso
    seq_recs = [
        {"case_id": c0.id, "answer": good0},
        {"case_id": c0.id, "answer": "errado"},
    ]
    runs = runner.score_runs(CASES, seq_recs)
    assert len(runs) == 2
    assert runs[0][c0.id] == 1.0 and runs[1][c0.id] < 1.0

    # Lista vazia
    assert runner.score_runs(CASES, []) == []
    assert runner.summarize_runs(CASES, []) == {
        "n_runs": 0,
        "per_run_means": [],
        "mean": 0.0,
        "run_stdev": 0.0,
        "mean_case_stdev": 0.0,
        "exact_score_consistency_rate": 0.0,
        "exact_answer_consistency_rate": 0.0,
    }


def test_score_runs_caso_desconhecido_levanta_key_error():
    with pytest.raises(KeyError):
        runner.score_runs(CASES, [{"case_id": "inexistente", "answer": "x", "run_index": 0}])


# ---- CLI aok eval --runs N ----


def test_cli_eval_runs_3_gera_secao_variancia_e_rejeita_invalido(tmp_path, monkeypatch, capsys):
    shutil.copytree(PROMPTS_DIR, tmp_path / "prompts")
    ds_lines = DATASET_PATH.read_text(encoding="utf-8").splitlines()[:4]
    ds_path = tmp_path / "dataset.jsonl"
    ds_path.write_text("\n".join(ds_lines) + "\n", encoding="utf-8")
    sub_cases = load_dataset(ds_path)
    by_question = {c.question: c for c in sub_cases}

    def fake_make_llm(seed: int = 42):
        def llm(model, messages, tools):
            user_text = messages[-1]["content"]
            matched = next((c for q, c in by_question.items() if q in user_text), sub_cases[0])
            # v2 (com Exemplo 1 no system) erra só na seed 11 para gerar variância mensurável
            is_v2 = "Exemplo 1" in messages[0]["content"]
            if is_v2 and seed == 11 and matched.id == sub_cases[0].id:
                return _reply("Resposta: resposta incompleta")
            return _reply(f"Resposta: {_good_answer(matched)}")

        return llm

    monkeypatch.setattr(runner, "make_ollama_llm", fake_make_llm)

    base_argv = [
        "eval",
        "--baseline",
        "v1",
        "--candidate",
        "v2",
        "--dataset",
        str(ds_path),
        "--prompts-dir",
        str(tmp_path / "prompts"),
        "--config",
        str(CONFIG_PATH),
        "--answers-dir",
        str(tmp_path / "answers"),
        "--seed",
        "10",
    ]

    # Rejeita --runs 0
    assert cli.main(base_argv + ["--runs", "0"]) == 2
    assert "--runs deve ser >= 1" in capsys.readouterr().err

    # Executa com --runs 3
    report = tmp_path / "relatorio.md"
    assert cli.main(base_argv + ["--runs", "3", "--report", str(report)]) == 0
    out = capsys.readouterr().out
    assert "- Execuções por configuração: 3" in out
    assert "## Variância entre execuções" in out
    assert "Desvio-padrão (execuções)" in out
    assert "Desvio médio por caso" in out
    assert "Consistência exata (score / resposta)" in out
    assert "- Médias por execução (v1):" in out
    assert "- Médias por execução (v2):" in out
    assert report.read_text(encoding="utf-8").strip() == out.strip()

    # Verifica JSONL e manifesto gravados
    v1_recs = runner.load_records(tmp_path / "answers" / "v1.jsonl")
    v2_recs = runner.load_records(tmp_path / "answers" / "v2.jsonl")
    assert len(v1_recs) == 12 and len(v2_recs) == 12
    assert [r["run_index"] for r in v2_recs] == [0] * 4 + [1] * 4 + [2] * 4
    manifest = json.loads((tmp_path / "answers" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["v1"]["n_cases"] == 12 and manifest["v2"]["n_cases"] == 12

    # --reuse --runs 3 é rejeitado com código 2 e mensagem clara
    assert cli.main(base_argv + ["--reuse", "--runs", "3"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("erro:") and "--runs não pode ser usado com --reuse" in err
    assert "Traceback" not in err

    # --reuse --summary com os arquivos multi-run gerados também funciona e verifica o manifesto
    assert cli.main(base_argv + ["--reuse", "--summary", "--report", str(report)]) == 0
    summary_out = capsys.readouterr().out
    assert "3 execuções" in summary_out


def test_cli_eval_reuse_summary_repositorio_passa_intacto(capsys):
    manifest_before = (ROOT / "evals" / "answers" / "manifest.json").read_text(encoding="utf-8")
    code = cli.main(["eval", "--baseline", "v1", "--candidate", "v2", "--reuse", "--summary"])
    out = capsys.read_text() if hasattr(capsys, "read_text") else capsys.readouterr().out
    assert code == 0
    assert "Avaliação A/B: v1 (baseline) vs v2 (candidate)" in out
    assert "execuções" not in out  # 1 execução mantém placar enxuto
    assert (ROOT / "evals" / "answers" / "manifest.json").read_text(encoding="utf-8") == manifest_before


# ---- report/build.py + report/render.py ----


def test_report_multirun_exibe_variancia_em_secao_3_e_apendice_a1(tmp_path):
    shutil.copytree(PROMPTS_DIR, tmp_path / "prompts")
    ds_lines = DATASET_PATH.read_text(encoding="utf-8").splitlines()[:4]
    ds_path = tmp_path / "dataset.jsonl"
    ds_path.write_text("\n".join(ds_lines) + "\n", encoding="utf-8")
    sub_cases = load_dataset(ds_path)

    ans_dir = tmp_path / "answers"
    ans_dir.mkdir()
    for variant in ("v1", "v2"):
        recs = []
        for run_idx in range(3):
            for i, c in enumerate(sub_cases):
                ans = _good_answer(c)
                if variant == "v2" and run_idx == 1 and i == 0:
                    ans = "incompleta"
                recs.append(
                    {
                        "case_id": c.id,
                        "variant": variant,
                        "answer": ans,
                        "latency_s": 0.1,
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "error": None,
                        "run_index": run_idx,
                    }
                )
        (ans_dir / f"{variant}.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n", encoding="utf-8"
        )
        entry = runner.manifest_entry(variant, CONFIG, ds_path, len(recs), 42, tmp_path / "prompts")
        runner.write_manifest_entry(ans_dir, variant, entry)

    rt_dir = tmp_path / "rt"
    rt_dir.mkdir()
    for name, rows in (
        ("baseline.jsonl", [_attack_rec("a1", "injecao_direta", True)]),
        ("guardrails.jsonl", [_attack_rec("a1", "injecao_direta", False)]),
        ("fp_dataset.jsonl", [_fp_rec("q1")]),
        ("fp_benign.jsonl", [_fp_rec("b1")]),
    ):
        (rt_dir / name).write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
        )

    data = build.build_data(
        config=str(CONFIG_PATH),
        dataset=str(ds_path),
        prompts_dir=str(tmp_path / "prompts"),
        answers_dir=str(ans_dir),
        baseline="v1",
        candidate="v2",
        seed=42,
        redteam_baseline=str(rt_dir / "baseline.jsonl"),
        redteam_guardrails=str(rt_dir / "guardrails.jsonl"),
        fp_dir=str(rt_dir),
    )
    ev = data["eval"]
    assert ev["runs_per_config"] == 3
    assert set(ev["variance"]) == {"v1", "v2"}
    assert ev["variance"]["v1"]["run_stdev"] == 0.0
    assert ev["variance"]["v2"]["run_stdev"] > 0.0
    assert not math.isnan(ev["variance"]["v2"]["mean_case_stdev"])

    blocks = render.build_blocks(data)
    md = render.to_markdown(blocks)
    html = render.to_html(blocks, "Relatório multi-run")

    assert "Variância entre execuções:" in md
    assert "A.1.1 Variância entre execuções por variante" in md
    assert "Desvio-padrão (execuções)" in md
    assert "Consistência exata (score)" in md
    assert "variância medida entre execuções" in md

    assert "Variância entre execuções:" in html
    assert "A.1.1 Variância entre execuções por variante" in html
    assert "<script" not in html
    assert not BANNED.search(md)
    assert not BANNED.search(html)


def test_report_single_run_mantem_nota_uma_execucao_por_configuracao(tmp_path):
    rt_dir = tmp_path / "rt"
    rt_dir.mkdir()
    for name, rows in (
        ("baseline.jsonl", [_attack_rec("a1", "injecao_direta", True)]),
        ("guardrails.jsonl", [_attack_rec("a1", "injecao_direta", False)]),
        ("fp_dataset.jsonl", [_fp_rec("q1")]),
        ("fp_benign.jsonl", [_fp_rec("b1")]),
    ):
        (rt_dir / name).write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
        )

    data = build.build_data(
        config=str(CONFIG_PATH),
        dataset=str(DATASET_PATH),
        prompts_dir=str(PROMPTS_DIR),
        answers_dir=str(ROOT / "evals" / "answers"),
        baseline="v1",
        candidate="v2",
        seed=42,
        redteam_baseline=str(rt_dir / "baseline.jsonl"),
        redteam_guardrails=str(rt_dir / "guardrails.jsonl"),
        fp_dir=str(rt_dir),
    )
    assert data["eval"]["runs_per_config"] == 1
    assert data["eval"]["variance"]["v1"]["n_runs"] == 1
    md = render.to_markdown(render.build_blocks(data))
    assert "uma execução por configuração" in md
    assert "Não há medida da variação entre execuções." in md
    assert "A.1.1 Variância entre execuções" not in md
