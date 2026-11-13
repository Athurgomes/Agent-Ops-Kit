from pathlib import Path

from agent_ops_kit.config import load_config
from agent_ops_kit.eval.dataset import load_dataset
from agent_ops_kit.eval.runner import final_answer, load_records, run_variant, score_records
from examples.rag_agent.agent import CONFIG_PATH

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "evals" / "prompts"
CASES = load_dataset(ROOT / "evals" / "dataset.jsonl")
CONFIG = load_config(CONFIG_PATH)
REFUSAL = "Não encontrei essa informação nos documentos."


def _reply(text):
    return {
        "message": {"role": "assistant", "content": text},
        "prompt_eval_count": 11,
        "eval_count": 4,
    }


def _good_llm(model, messages, tools):
    return _reply("Resposta qualquer.")


def test_roda_3_casos_grava_e_relê_jsonl(tmp_path):
    out = tmp_path / "sub" / "v1.jsonl"
    recs = run_variant(
        "v1", CASES, CONFIG, llm=_good_llm, out_path=out, limit=3, prompts_dir=PROMPTS
    )
    assert [r["case_id"] for r in recs] == [c.id for c in CASES[:3]]
    assert set(recs[0]) == {
        "case_id",
        "variant",
        "answer",
        "latency_s",
        "input_tokens",
        "output_tokens",
        "error",
    }
    assert recs[0]["variant"] == "v1" and recs[0]["error"] is None
    assert recs[0]["input_tokens"] == 11 and recs[0]["output_tokens"] == 4
    assert recs[0]["latency_s"] >= 0
    assert load_records(out) == recs


def test_usa_o_prompt_da_variante():
    seen = []

    def llm(model, messages, tools):
        seen.append(messages[0]["content"])
        return _reply("ok")

    run_variant("v2", CASES, CONFIG, llm=llm, limit=1, prompts_dir=PROMPTS)
    assert "Exemplo 1" in seen[0]
    run_variant("v1", CASES, CONFIG, llm=llm, limit=1, prompts_dir=PROMPTS)
    assert "Exemplo 1" not in seen[1]
    assert "Exemplo 1" not in CONFIG.system_prompt  # config original intacta


def test_erro_em_um_caso_nao_derruba_a_execucao(tmp_path):
    calls = []

    def llm(model, messages, tools):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("ollama fora do ar")
        return _reply("ok")

    out = tmp_path / "r.jsonl"
    recs = run_variant("v1", CASES, CONFIG, llm=llm, out_path=out, limit=3, prompts_dir=PROMPTS)
    assert [r["error"] is None for r in recs] == [True, False, True]
    assert "RuntimeError" in recs[1]["error"] and recs[1]["answer"] == ""
    assert len(load_records(out)) == 3


def test_score_records():
    by_id = {c.id: c for c in CASES}
    ans, una = by_id["q004"], by_id["q041"]
    recs = [
        {
            "case_id": ans.id,
            "answer": "Bebidas alcoólicas e multas de trânsito não são "
            "reembolsáveis.\nFonte: 02_reembolso_de_despesas.md",
        },
        {"case_id": una.id, "answer": REFUSAL},
        {"case_id": CASES[0].id, "answer": "", "error": "x"},
    ]
    scores = score_records(CASES, recs)
    assert scores[ans.id] == 1.0
    assert scores[una.id] == 1.0
    assert scores[CASES[0].id] < 1.0


def test_final_answer():
    assert final_answer("Raciocínio: x\nResposta: 25 dias.\nFonte: x.md") == "25 dias.\nFonte: x.md"
    assert final_answer("sem marcador, 30 dias") == "sem marcador, 30 dias"
    assert final_answer("Resposta: a\nresposta: b") == "b"
    assert final_answer("**Resposta:** ok") == "ok"
    assert final_answer("RESPOSTA : ok") == "ok"
    assert final_answer("Correspondência: ok") == "Correspondência: ok"


def test_score_usa_so_a_resposta_final():
    case = next(c for c in CASES if c.id == "q027")  # expected: "30 dias"
    src = case.sources[0]
    cot = f"Raciocínio: o trecho diz 30 dias.\nResposta: 25 dias.\nFonte: {src}"
    ok = f"Raciocínio: x.\nResposta: 30 dias.\nFonte: {src}"
    plain = f"30 dias.\nFonte: {src}"  # v1, sem marcador
    recs = [{"case_id": case.id, "answer": a} for a in (cot, ok, plain)]
    scores = [score_records(CASES, [r])[case.id] for r in recs]
    assert scores[0] < 1.0
    assert scores[1] == 1.0
    assert scores[2] == 1.0
    assert recs[0]["answer"] == cot  # resposta bruta intacta
