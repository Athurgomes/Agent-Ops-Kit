import json
from pathlib import Path

import pytest

from agent_ops_kit import cli
from agent_ops_kit.eval import judge as judge_mod
from agent_ops_kit.eval import runner
from agent_ops_kit.eval.checks import REFUSAL_PHRASE
from agent_ops_kit.eval.dataset import load_dataset

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "evals" / "dataset.jsonl"
CONFIG = ROOT / "examples" / "rag_agent" / "agent.yaml"
PROMPTS = ROOT / "evals" / "prompts"
CASES = load_dataset(DATASET)[:8]


def _good(case):
    if not case.answerable:
        return REFUSAL_PHRASE
    return f"{'; '.join(case.expected)}.\nFonte: {case.sources[0]}"


def _bad(case):
    return "x"


def _write(path, answer_fn, variant):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for c in CASES:
            rec = {
                "case_id": c.id,
                "variant": variant,
                "answer": answer_fn(c),
                "latency_s": 0.1,
                "input_tokens": 1,
                "output_tokens": 1,
                "error": None,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _args(tmp_path, *extra, baseline="v1", candidate="v2", reuse=True):
    argv = [
        "eval",
        "--baseline", baseline,
        "--candidate", candidate,
        "--dataset", str(DATASET),
        "--prompts-dir", str(PROMPTS),
        "--config", str(CONFIG),
        "--answers-dir", str(tmp_path / "answers"),
        "--limit", str(len(CASES)),
    ]  # fmt: skip
    if reuse:
        argv += ["--reuse", "--no-verify"]  # manifesto é testado em test_manifest.py
    return argv + list(extra)


@pytest.fixture
def no_model(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("o modelo não deveria ser chamado")

    monkeypatch.setattr(runner, "run_variant", boom)
    monkeypatch.setattr(runner, "make_ollama_llm", boom)
    monkeypatch.setattr(judge_mod, "make_ollama_judge_llm", boom)


def test_reuse_gera_relatorio_sem_chamar_o_modelo(tmp_path, no_model, capsys):
    _write(tmp_path / "answers" / "v1.jsonl", _good, "v1")
    _write(
        tmp_path / "answers" / "v2.jsonl",
        lambda c: "x" if c.id == CASES[0].id else _good(c),
        "v2",
    )
    report = tmp_path / "out" / "r.md"
    code = cli.main(_args(tmp_path, "--report", str(report)))
    out = capsys.readouterr().out
    assert code == 0
    assert report.read_text(encoding="utf-8").strip() == out.strip()
    for section in (
        "Relatório de avaliação A/B",
        "aok eval --baseline v1 --candidate v2",
        "Semente: 42",
        "Casos: 8",
        "Modelo: llama3.1:8b",
        "Métrica determinística",
        "p-valor",
        "Taxa de aprovação por checagem",
        "contains_expected",
        "## Erros",
    ):
        assert section in out
    assert "Juiz" not in out and "Gate de regressão" not in out


def test_fail_on_regression_devolve_1_em_regressao_clara(tmp_path, no_model, capsys):
    _write(tmp_path / "answers" / "v1.jsonl", _good, "v1")
    _write(tmp_path / "answers" / "v2.jsonl", _bad, "v2")
    code = cli.main(_args(tmp_path, "--fail-on-regression"))
    out = capsys.readouterr().out
    assert code == 1
    assert "Gate de regressão" in out and "regressão detectada" in out


def test_fail_on_regression_devolve_0_sem_regressao(tmp_path, no_model, capsys):
    _write(tmp_path / "answers" / "v1.jsonl", _good, "v1")
    _write(tmp_path / "answers" / "v2.jsonl", _good, "v2")
    assert cli.main(_args(tmp_path, "--fail-on-regression")) == 0
    assert "sem regressão" in capsys.readouterr().out
    # candidata melhor que a base também não falha
    _write(tmp_path / "answers" / "v1.jsonl", _bad, "v1")
    assert cli.main(_args(tmp_path, "--fail-on-regression")) == 0


def test_sem_a_flag_regressao_nao_falha(tmp_path, no_model):
    _write(tmp_path / "answers" / "v1.jsonl", _good, "v1")
    _write(tmp_path / "answers" / "v2.jsonl", _bad, "v2")
    assert cli.main(_args(tmp_path)) == 0


def test_sem_reuse_roda_variantes_e_grava_respostas(tmp_path, monkeypatch, capsys):
    def llm(model, messages, tools):
        return {"message": {"role": "assistant", "content": "Resposta: x"}}

    monkeypatch.setattr(runner, "make_ollama_llm", lambda seed=42: llm)
    assert cli.main(_args(tmp_path, reuse=False)) == 0
    for v in ("v1", "v2"):
        recs = runner.load_records(tmp_path / "answers" / f"{v}.jsonl")
        assert len(recs) == len(CASES) and recs[0]["variant"] == v
    assert "geradas nesta execução" in capsys.readouterr().out


def test_judge_entra_no_relatorio_com_aviso(tmp_path, monkeypatch, capsys):
    _write(tmp_path / "answers" / "v1.jsonl", _good, "v1")
    _write(tmp_path / "answers" / "v2.jsonl", _good, "v2")
    calls = []

    def fake_llm(messages):
        calls.append(1)
        return '{"fidelidade": 4, "relevancia": 4, "completude": 3, "justificativa": "ok"}'

    monkeypatch.setattr(judge_mod, "make_ollama_judge_llm", lambda model, seed: fake_llm)
    assert cli.main(_args(tmp_path, "--judge")) == 0
    out = capsys.readouterr().out
    assert "Juiz (LLM-as-judge)" in out and "autopreferência" in out
    assert "nota do juiz, 1 a 5" in out
    assert len(calls) == 2 * len(CASES)


def test_erro_variante_inexistente(tmp_path, capsys):
    code = cli.main(_args(tmp_path, baseline="v1", candidate="nao_existe", reuse=False))
    assert code == 2
    assert "variante de prompt não encontrada" in capsys.readouterr().err


def test_erro_respostas_gravadas_inexistentes(tmp_path, capsys):
    _write(tmp_path / "answers" / "v1.jsonl", _good, "v1")
    code = cli.main(_args(tmp_path))
    assert code == 2
    err = capsys.readouterr().err
    assert "respostas gravadas não encontradas" in err and "v2.jsonl" in err


def test_erro_dataset_inexistente(tmp_path, capsys):
    argv = _args(tmp_path) + ["--dataset", str(tmp_path / "nada.jsonl")]
    assert cli.main(argv) == 2
    assert "dataset não encontrado" in capsys.readouterr().err


def test_erro_baseline_igual_candidate(tmp_path, capsys):
    assert cli.main(_args(tmp_path, baseline="v1", candidate="v1")) == 2
    assert "diferentes" in capsys.readouterr().err


def _write_records(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _ops_records(variant, lats, tin, tout, errors=()):
    return [
        {
            "case_id": c.id,
            "variant": variant,
            "answer": _good(c),
            "latency_s": lats[i],
            "input_tokens": tin[i],
            "output_tokens": tout[i],
            "error": "boom" if i in errors else None,
        }
        for i, c in enumerate(CASES)
    ]


def _fake_ops(tmp_path):
    v1 = _ops_records("v1", [1, 2, 3, 4, 5, 6, 7, 8], [10] * 8, [2] * 8)
    v2 = _ops_records("v2", [2] * 8, list(range(8)), [5] * 8, errors=(0, 1))
    _write_records(tmp_path / "answers" / "v1.jsonl", v1)
    _write_records(tmp_path / "answers" / "v2.jsonl", v2)
    return v1, v2


def test_relatorio_tem_metricas_operacionais_que_batem(tmp_path, no_model, capsys):
    from agent_ops_kit.metrics import summarize_records

    v1, v2 = _fake_ops(tmp_path)
    assert cli.main(_args(tmp_path)) == 0
    out = capsys.readouterr().out
    assert out.index("Taxa de aprovação") < out.index("## Métricas operacionais") < out.index("## Erros")
    sec = out.split("## Métricas operacionais")[1].split("## Erros")[0]
    s1, s2 = summarize_records(v1, "llama3.1:8b"), summarize_records(v2, "llama3.1:8b")
    assert f"| {s1['llm_calls']} | {s2['llm_calls']} |" in sec
    lat = f"| Latência por caso, p50 (s) | {s1['llm_latency_p50_s']:.2f} | {s2['llm_latency_p50_s']:.2f} |"
    assert lat in sec
    assert f"| Latência por caso, p95 (s) | {s1['llm_latency_p95_s']:.2f} | " in sec
    assert f"| Tokens de entrada, média por caso | {s1['avg_input_tokens']:.2f} | {s2['avg_input_tokens']:.2f} |" in sec
    assert f"| Tokens de saída, média por caso | {s1['avg_output_tokens']:.2f} | {s2['avg_output_tokens']:.2f} |" in sec
    assert "| Taxa de erro do agente | 0.0000 | 0.2500 |" in sec
    assert "| Taxa de erro de tool | n/d (o runner não registra tools por caso) |" in sec
    assert "| Custo estimado | 0.0000 | 0.0000 |" in sec
    assert "Local = 0.0" in sec
    assert "Valores por caso (soma das chamadas de LLM do caso), não por chamada" in sec
    assert "hardware" in sec and "carga a frio" in sec and "não é medida no CI" in sec


def test_prices_yaml_define_o_custo(tmp_path, no_model, capsys):
    from agent_ops_kit.metrics import PriceTable, summarize_records

    v1, v2 = _fake_ops(tmp_path)
    prices = tmp_path / "prices.yaml"
    prices.write_text("llama3.1:8b: {input: 100000.0, output: 200000.0}\n", encoding="utf-8")
    assert cli.main(_args(tmp_path, "--prices", str(prices))) == 0
    out = capsys.readouterr().out
    table = PriceTable.from_yaml(prices)
    c1 = summarize_records(v1, "llama3.1:8b", table)["estimated_cost"]
    c2 = summarize_records(v2, "llama3.1:8b", table)["estimated_cost"]
    assert c1 > 0 and f"| Custo estimado | {c1:.4f} | {c2:.4f} |" in out
    assert "--prices" in out and "Preço da tabela informada" in out


def test_modelo_fora_da_tabela_custo_nd(tmp_path, no_model, capsys):
    _fake_ops(tmp_path)
    prices = tmp_path / "prices.yaml"
    prices.write_text("outro-modelo: {input: 1.0, output: 1.0}\n", encoding="utf-8")
    assert cli.main(_args(tmp_path, "--prices", str(prices))) == 0
    out = capsys.readouterr().out
    assert "| Custo estimado | n/d | n/d |" in out and "Modelo fora da tabela: n/d" in out


def test_erro_prices_inexistente_ou_invalido(tmp_path, capsys):
    _fake_ops(tmp_path)
    assert cli.main(_args(tmp_path, "--prices", str(tmp_path / "nada.yaml"))) == 2
    assert "tabela de preços não encontrada" in capsys.readouterr().err
    bad = tmp_path / "bad.yaml"
    bad.write_text("llama3.1:8b: {input: 1.0}\n", encoding="utf-8")
    assert cli.main(_args(tmp_path, "--prices", str(bad))) == 2
    assert "tabela de preços inválida" in capsys.readouterr().err
    broken = tmp_path / "broken.yaml"
    broken.write_text("a: [unclosed\n", encoding="utf-8")
    assert cli.main(_args(tmp_path, "--prices", str(broken))) == 2
    assert "tabela de preços inválida" in capsys.readouterr().err
