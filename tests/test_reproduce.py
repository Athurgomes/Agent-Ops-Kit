"""`aok reproduce` (A9): reexecuta um pacote e compara com o declarado. Sem Ollama real: o agente
é o fixture (target python) e o LLM é falso; o pacote de partida é gerado pelo próprio kit."""

import hashlib
import json
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agent_ops_kit import audit, cli, ollama_chat, provenance, reproduce
from agent_ops_kit.config import load_config
from agent_ops_kit.eval import runner
from agent_ops_kit.eval.dataset import load_dataset
from agent_ops_kit.redteam import false_positives as fp
from agent_ops_kit.redteam import harness
from agent_ops_kit.redteam.attacks import load_attacks
from agent_ops_kit.report import verify
from examples.rag_agent.agent import CONFIG_PATH

SRC = Path(__file__).resolve().parent.parent
MODEL = load_config(CONFIG_PATH).model


@contextmanager
def _cd(path):
    old = os.getcwd()
    os.chdir(path)
    sys.path.insert(0, str(path))
    try:
        yield
    finally:
        sys.path.remove(str(path))
        sys.modules.pop("fxagent", None)
        os.chdir(old)


def fetch_for(version="0.9.9", digest="abc123"):
    def fetch(path):
        if path == "/api/version":
            return {"version": version}
        return {"models": [{"name": MODEL, "digest": digest}]}
    return fetch


def make_llm(mode):
    """LLM falso: `oracle` responde o esperado do dataset (ou "ok"); `blank` responde sempre igual."""
    by_q = {c.question: c for c in load_dataset(SRC / "evals" / "dataset.jsonl")}

    def llm(model, messages, tools=None):
        q = messages[-1]["content"]
        if mode == "blank":
            text = "não sei"
        else:
            case = by_q.get(q)
            text = case.expected[0] if case and case.expected else "ok"
        return {"message": {"content": text}, "prompt_eval_count": 1, "eval_count": 1}
    return llm


def _write_agent_yaml(root):
    data = json.loads(load_config(CONFIG_PATH).model_dump_json())
    data["target"] = {"type": "python", "ref": "fxagent:agent_llm"}
    (root / "agent.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _build_package(root):
    """Eval (6 casos), red team (30 ataques), falsos positivos (4+4) e `report build` em `root`."""
    llm, fetch = make_llm("oracle"), fetch_for()
    cfg = load_config("agent.yaml")
    dataset = load_dataset("evals/dataset.jsonl")
    info = {**provenance.execution_info(cfg.model, "aok eval", fetch=fetch), **provenance.target_info(cfg)}
    for v in ("v1", "v2"):
        recs = runner.run_variant(v, dataset, cfg, llm=llm, out_path=f"evals/answers/{v}.jsonl",
                                  limit=6, seed=42, prompts_dir="evals/prompts")
        entry = runner.manifest_entry(v, cfg, "evals/dataset.jsonl", len(recs), 42, "evals/prompts",
                                      answers_path=f"evals/answers/{v}.jsonl", extra=info)
        runner.write_manifest_entry("evals/answers", v, entry)
    adir, pdir = Path("redteam/attacks"), Path("redteam/poisoned_corpus")
    meta = {
        **provenance.execution_info(cfg.model, "python -m agent_ops_kit.redteam.harness", fetch=fetch),
        "attacks_dir": provenance.rel_path(adir), "attacks_sha256": provenance.sha256_dir(adir),
        "poisoned_dir": provenance.rel_path(pdir), "poisoned_sha256": provenance.sha256_dir(pdir, "*.md"),
    }
    cases = load_attacks(adir, pdir)
    for name in ("baseline", "guardrails"):
        harness.run_suite(cases, cfg, llm=llm, out_path=f"rt/{name}.jsonl", limit=30, seed=42,
                          poisoned_dir=pdir, meta=dict(meta))
    benign = fp.load_benign("redteam/benign/benign.jsonl")
    fp.run_benign(dataset[:4], cfg, [], llm=llm, out_path="rt/fp_dataset.jsonl", seed=42)
    fp.run_benign(benign[:4], cfg, [], llm=llm, out_path="rt/fp_benign.jsonl", seed=42)
    fp.write_fp_meta("rt", cfg.model, 42, [], "evals/dataset.jsonl", "redteam/benign/benign.jsonl", "fp",
                     extra={**info})
    # pacote "antigo": mesmos resultados, sem sidecars do red team
    shutil.copytree("rt", "rt_legacy", ignore=shutil.ignore_patterns("*.meta.json"))
    common = ["--config", "agent.yaml", "--policy", "policies/default.yaml",
              "--coverage-map", "policies/coverage/owasp_llm_2025.yaml"]
    for out, rt in (("pk", "rt"), ("pk_legacy", "rt_legacy")):
        assert cli.main([
            "report", "build", "--out", out, "--redteam-baseline", f"{rt}/baseline.jsonl",
            "--redteam-guardrails", f"{rt}/guardrails.jsonl", "--fp-dir", rt, *common,
        ]) == 0


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    root = tmp_path_factory.mktemp("repo")
    shutil.copy(SRC / "tests" / "fixture_agent.py", root / "fxagent.py")
    shutil.copytree(SRC / "evals" / "prompts", root / "evals" / "prompts")
    shutil.copy(SRC / "evals" / "dataset.jsonl", root / "evals" / "dataset.jsonl")
    shutil.copytree(SRC / "policies", root / "policies")
    shutil.copytree(SRC / "redteam" / "attacks", root / "redteam" / "attacks")
    shutil.copytree(SRC / "redteam" / "poisoned_corpus", root / "redteam" / "poisoned_corpus")
    (root / "redteam" / "benign").mkdir()
    shutil.copy(SRC / "redteam" / "benign" / "benign.jsonl", root / "redteam" / "benign" / "benign.jsonl")
    _write_agent_yaml(root)
    with _cd(root):
        _build_package(root)
    return root


@pytest.fixture
def repo(sandbox, tmp_path, monkeypatch):
    dst = tmp_path / "repo"
    shutil.copytree(sandbox, dst)
    monkeypatch.chdir(dst)
    monkeypatch.syspath_prepend(str(dst))
    sys.modules.pop("fxagent", None)
    yield dst
    sys.modules.pop("fxagent", None)


def run(pkg="pk", mode="oracle", fetch=None, **kw):
    return reproduce.reproduce(pkg, llm=make_llm(mode), fetch=fetch or fetch_for(), **kw)


def verdicts(res):
    return {i["id"]: i["verdict"] for i in res["data"]["items"]}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tree_hash(root):
    return {p.relative_to(root).as_posix(): _sha(p) for p in sorted(Path(root).rglob("*")) if p.is_file()}


# --- reproduz igual ---------------------------------------------------------------------------


def test_intact_package_is_reproduced_equal(repo):
    before = _tree_hash(repo / "pk")
    res = run()
    d = res["data"]
    assert set(verdicts(res).values()) == {"reproduzido"}, d["differences"]
    assert d["environment"]["status"] == "igual" and d["parameters"]["partial"] is False
    assert [p["status"] for p in d["parts"]] == ["reexecutado"] * 3
    assert {"eval.mean.v1", "eval.mean_diff", "redteam.baseline.asr", "redteam.guardrails.answers",
            "false_positives.benign.rate"} <= set(verdicts(res))
    assert all(g["identical_rate"] == 1.0 for p in d["parts"] for g in p["groups"])
    assert _tree_hash(repo / "pk") == before  # o pacote original não é tocado
    assert res["out"].name == "pk_reproducao" and (res["out"] / "eval" / "answers" / "v1.jsonl").is_file()
    assert (res["out"] / "redteam" / "guardrails.jsonl").is_file()
    reproduce.validate(json.loads(res["json"].read_text(encoding="utf-8")))
    md = res["md"].read_text(encoding="utf-8")
    assert md == reproduce.render_markdown(d) and "não aprova nem reprova" in md
    assert "Ollama pode não ser determinístico" in md and "## Regras de veredito" in md


def test_event_is_chained_and_audit_verify_ok(repo, capsys):
    res = run()
    log = res["audit_log"]
    assert log == res["out"] / "audit" / "reproducao.jsonl"
    assert cli.main(["audit", "verify", str(log)]) == 0
    assert "Cadeia íntegra (1 eventos)" in capsys.readouterr().out
    ev = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert ev["event"] == "reproduction" and ev["seq"] == 0
    assert ev["data"]["original_report_sha256"] == _sha(repo / "pk" / "relatorio.json")
    assert ev["data"]["reproducao_json_sha256"] == _sha(res["json"])
    assert set(ev["data"]["verdicts"].values()) == {"reproduzido"}
    assert ev["data"]["verdict_counts"]["reproduzido"] == len(ev["data"]["verdicts"])


def test_existing_log_is_appended_and_anchor_signed(repo, capsys):
    (repo / "audit").mkdir()
    log = audit.AuditLog(repo / "audit" / "a.jsonl")
    log.append("question", {"text": "x"})
    log.append("answer", {"text": "y"})
    assert cli.main(["audit", "keygen", "--private-out", "k.pem", "--public-out", "k.pub"]) == 0
    res = run(audit_log="audit/a.jsonl", signing_key="k.pem")
    assert res["audit_seq"] == 2 and res["signature"] == Path("audit/a.sig.json")
    capsys.readouterr()
    assert cli.main(["audit", "verify", "audit/a.jsonl", "--signature", "audit/a.sig.json",
                     "--public-key", "k.pub"]) == 0
    assert "Assinatura válida" in capsys.readouterr().out
    events = [json.loads(x)["event"] for x in (repo / "audit" / "a.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events == ["question", "answer", "reproduction"]


def test_broken_log_is_refused_without_writing(repo):
    (repo / "audit").mkdir()
    audit.AuditLog(repo / "audit" / "a.jsonl").append("question", {})
    (repo / "audit" / "a.jsonl").write_text("lixo\n", encoding="utf-8")
    with pytest.raises(reproduce.ReproduceError, match="log de auditoria recusado"):
        run(audit_log="audit/a.jsonl")


# --- divergência e ambiente -------------------------------------------------------------------


def test_divergence_is_detected_and_never_called_variance(repo):
    res = run(mode="blank")
    v, d = verdicts(res), res["data"]
    assert v["eval.mean.v1"] == "divergente" and v["eval.answers.v1"] == "divergente"
    assert v["redteam.baseline.answers"] == "divergente"
    assert "dentro da variância" not in v.values() and d["verdict_counts"]["divergente"] >= 3
    item = next(i for i in d["items"] if i["id"] == "eval.mean.v1")
    assert item["difference"] < 0 and "não declara variância" in item["reason"]
    assert any("eval.mean.v1" in x for x in d["differences"])
    g = next(g for p in d["parts"] for g in p["groups"] if g["name"] == "eval:v1")
    assert g["identical_rate"] < 1.0 and g["n_identical"] < g["n_cases"]


def test_environment_difference_is_recorded_before_running(repo):
    lines = []
    res = run(fetch=fetch_for(digest="outro", version="1.0.0"), log=lines.append)
    env = res["data"]["environment"]
    assert env["status"] == "diferente"
    assert {d["field"] for d in env["differences"]} == {"model_digest", "ollama_version"}
    assert lines[0] == "ambiente: diferente" and any("model_digest" in x for x in lines[:4])
    assert "ambiente diferente" in res["md"].read_text(encoding="utf-8")
    assert any(x.startswith("ambiente: model_digest") for x in res["data"]["differences"])


def test_unrecorded_environment_is_not_confirmed():
    original = {k: None for k in ("kit_version", "model", "model_digest", "ollama_version", "generation_limits")}
    original.update(kit_version="0.1.0", model="m")
    env = reproduce.compare_environment(original, {**original, "model_digest": "x"})
    assert env.status == "não confirmado" and "model_digest" in env.not_recorded
    assert reproduce.compare_environment({**original, "model_digest": "y"}, {**original, "model_digest": "x"}
                                         ).status == "diferente"


# --- recusas ----------------------------------------------------------------------------------


def test_tampered_package_is_refused(repo):
    p = repo / "pk" / "relatorio.json"
    raw = p.read_bytes()
    assert b'"n_cases": 6' in raw
    p.write_bytes(raw.replace(b'"n_cases": 6', b'"n_cases": 7', 1))  # um byte
    with pytest.raises(reproduce.ReproduceError, match="verificação offline"):
        run()
    assert not (repo / "pk_reproducao").exists()


def test_dataset_with_other_hash_is_refused(repo, monkeypatch):
    ds = repo / "evals" / "dataset.jsonl"
    ds.write_text(ds.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(reproduce.ReproduceError, match="verificação offline"):  # o report verify já pega
        run()
    ok = {"ok": True, "summary": {"ok": 1, "falha": 0, "nao_verificavel": 0}, "checks": []}
    monkeypatch.setattr(verify, "verify_package", lambda *_a, **_k: ok)
    ds.write_text(ds.read_text(encoding="utf-8").replace("Pessoas+", "Pessoas-"), encoding="utf-8")
    with pytest.raises(reproduce.ReproduceError, match="sha256 diferente"):  # e a checagem própria também
        run()


def test_attack_suite_with_other_hash_is_refused(repo, monkeypatch):
    ok = {"ok": True, "summary": {"ok": 1, "falha": 0, "nao_verificavel": 0}, "checks": []}
    monkeypatch.setattr(verify, "verify_package", lambda *_a, **_k: ok)
    f = next((repo / "redteam" / "attacks").glob("*.jsonl"))
    f.write_text(f.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    (repo / "redteam" / "attacks" / "extra.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(reproduce.ReproduceError, match="suíte de ataques"):
        run(only="redteam")


def test_missing_dataset_is_refused(repo, monkeypatch):
    ok = {"ok": True, "summary": {"ok": 1, "falha": 0, "nao_verificavel": 0}, "checks": []}
    monkeypatch.setattr(verify, "verify_package", lambda *_a, **_k: ok)
    (repo / "evals" / "dataset.jsonl").unlink()
    with pytest.raises(reproduce.ReproduceError, match="não encontrado"):
        run(only="eval")


def test_external_agent_not_resolvable_is_refused(repo):
    (repo / "fxagent.py").unlink()
    with pytest.raises(reproduce.ReproduceError, match="não é reprodutível por este ambiente"):
        run()


def test_must_run_from_repo_root(repo, tmp_path):
    with pytest.raises(reproduce.ReproduceError, match="raiz do repositório"):
        run(repo_root=tmp_path)


def test_never_overwrites(repo):
    first = run()
    second = run()
    assert first["out"].name == "pk_reproducao" and second["out"].name == "pk_reproducao_2"
    before = _tree_hash(first["out"])
    with pytest.raises(reproduce.ReproduceError, match="não está vazia"):
        run(out=first["out"])
    with pytest.raises(reproduce.ReproduceError, match="dentro dele"):
        run(out=repo / "pk" / "novo")
    assert _tree_hash(first["out"]) == before


def test_audit_log_inside_original_package_is_refused(repo):
    before = _tree_hash(repo / "pk")
    with pytest.raises(reproduce.ReproduceError, match="dentro do pacote original"):
        run(audit_log="pk/audit.jsonl")
    assert _tree_hash(repo / "pk") == before


def test_symlink_pointing_outside_root_is_refused(repo, tmp_path, monkeypatch):
    ok = {"ok": True, "summary": {"ok": 1, "falha": 0, "nao_verificavel": 0}, "checks": []}
    monkeypatch.setattr(verify, "verify_package", lambda *_a, **_k: ok)
    outside = tmp_path / "fora.jsonl"
    outside.write_bytes((repo / "evals" / "dataset.jsonl").read_bytes())
    (repo / "evals" / "dataset.jsonl").unlink()
    try:
        (repo / "evals" / "dataset.jsonl").symlink_to(outside)
    except OSError:
        pytest.skip("sem permissão para criar link simbólico")
    with pytest.raises(reproduce.ReproduceError, match="fora da raiz"):
        run(only="eval")


def test_old_package_without_sidecars_reproduces_only_eval(repo):
    res = run("pk_legacy")
    parts = {p["id"]: p for p in res["data"]["parts"]}
    assert parts["eval"]["status"] == "reexecutado"
    assert parts["redteam"]["status"] == parts["false_positives"]["status"] == "não reproduzível"
    assert "ADR-022" in parts["redteam"]["reason"] and "fp.meta" in parts["false_positives"]["reason"]
    v = verdicts(res)
    assert v["redteam"] == v["false_positives"] == "não reproduzível" and v["eval.mean.v1"] == "reproduzido"
    assert not (res["out"] / "redteam").exists()


def test_only_and_limit_make_a_partial_rerun(repo):
    res = run(only="eval", limit=2, mode="blank")
    d = res["data"]
    assert d["parameters"]["partial"] is True and d["parameters"]["limit_requested"] == 2
    assert {p["id"]: p["status"] for p in d["parts"]} == {
        "eval": "reexecutado", "redteam": "não solicitado", "false_positives": "não solicitado"}
    assert next(p for p in d["parts"] if p["id"] == "eval")["limit"] == 2
    assert not (res["out"] / "redteam").exists()
    assert "Reexecução parcial" in res["md"].read_text(encoding="utf-8")
    assert "dentro da variância" not in verdicts(res).values()
    res2 = run(only="redteam", limit=500)  # limite maior que o original: não é parcial
    assert res2["data"]["parameters"]["partial"] is False
    assert {p["id"]: p["status"] for p in res2["data"]["parts"]}["eval"] == "não solicitado"


# --- regras de veredito -----------------------------------------------------------------------


def test_verdict_rules():
    mk = reproduce.make_item
    assert mk("x", "d", 0.5, 0.5, tolerance=0.1).verdict == "reproduzido"
    assert mk("x", "d", 0.5, 0.52, tolerance=0.05).verdict == "dentro da variância"
    assert mk("x", "d", 0.5, 0.55, tolerance=0.05).verdict == "divergente"  # igual ao desvio: não é menor
    assert mk("x", "d", 0.5, 0.51).verdict == "divergente"  # sem variância declarada
    assert mk("x", "d", 0.5, 0.51, tolerance=0.0).verdict == "divergente"
    partial = mk("x", "d", 0.5, 0.51, tolerance=0.05, partial=True)
    assert partial.verdict == "divergente" and "parcial" in partial.reason
    nr = mk("x", "d", None, 0.5, reason="sem dado")
    assert nr.verdict == "não reproduzível" and nr.reason == "sem dado"
    ci = mk("x", "d", 0.5, 0.6, ci=((0.4, 0.6), (0.55, 0.7)))
    assert ci.verdict == "divergente" and ci.ci_overlap is True  # IC não muda o veredito
    assert mk("x", "d", 0.5, 0.9, ci=((0.4, 0.6), (0.8, 0.95))).ci_overlap is False


def test_declared_variance_allows_within_verdict_in_a_real_rerun(repo):
    """Pacote com 2 execuções por variante (variância declarada) reexecutado com resposta diferente."""
    cfg = load_config("agent.yaml")
    dataset = load_dataset("evals/dataset.jsonl")
    manifest_path = repo / "evals" / "answers2"
    info = {**provenance.execution_info(cfg.model, "aok eval", fetch=fetch_for()), **provenance.target_info(cfg)}
    # execução 0 igual ao oráculo; execução 1 com um caso errado: variância entre execuções > 0
    llms = [make_llm("oracle"), make_llm("blank")]
    for v in ("v1", "v2"):
        recs = []
        for i, llm in enumerate(llms):
            part = runner.run_variant(v, dataset, cfg, llm=llm, limit=6, seed=42 + i, prompts_dir="evals/prompts")
            for r in part:
                r["run_index"] = i
            recs += part
        manifest_path.mkdir(exist_ok=True)
        with open(manifest_path / f"{v}.jsonl", "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in recs)
        runner.write_manifest_entry(manifest_path, v, runner.manifest_entry(
            v, cfg, "evals/dataset.jsonl", len(recs), 42, "evals/prompts",
            answers_path=manifest_path / f"{v}.jsonl", extra=info))
    assert cli.main([
        "report", "build", "--out", "pk_runs", "--config", "agent.yaml", "--answers-dir", "evals/answers2",
        "--redteam-baseline", "rt/baseline.jsonl", "--redteam-guardrails", "rt/guardrails.jsonl",
        "--fp-dir", "rt", "--policy", "policies/default.yaml",
        "--coverage-map", "policies/coverage/owasp_llm_2025.yaml"]) == 0
    declared = json.loads((repo / "pk_runs" / "relatorio.json").read_text(encoding="utf-8"))["eval"]["variance"]
    assert declared["v1"]["n_runs"] == 2 and declared["v1"]["run_stdev"] > 0
    res = run("pk_runs", only="eval", mode="oracle")  # o rerun de cada execução é o oráculo
    d = res["data"]
    assert next(p for p in d["parts"] if p["id"] == "eval")["runs"] == 2
    item = next(i for i in d["items"] if i["id"] == "eval.mean.v1")
    assert item["tolerance"] == pytest.approx(declared["v1"]["run_stdev"])
    assert item["verdict"] in ("dentro da variância", "divergente")
    assert (item["verdict"] == "dentro da variância") == (abs(item["difference"]) < item["tolerance"])
    assert item["verdict"] != "reproduzido" and item["tolerance_source"]


# --- saída: esquema fechado e saneamento ------------------------------------------------------


def test_schema_is_closed(repo):
    d = run()["data"]
    assert set(d) == {
        "schema_version", "kind", "generated_at", "original", "parameters", "verification", "environment",
        "parts", "items", "verdict_counts", "differences", "artifacts", "rules", "notes",
    }
    assert d["schema_version"] == 1 and d["kind"] == "reproducao"
    reproduce.validate(d)
    def with_extra(pick):
        bad = json.loads(json.dumps(d))
        pick(bad)["extra"] = 1
        with pytest.raises(ValidationError):
            reproduce.validate(bad)

    with_extra(lambda b: b)
    with_extra(lambda b: b["original"])
    with_extra(lambda b: b["items"][0])
    with_extra(lambda b: b["parts"][0]["groups"][0])
    with_extra(lambda b: b["parts"][0]["groups"][0]["cases"][0])
    with_extra(lambda b: b["environment"])
    with_extra(lambda b: b["parameters"])
    missing = json.loads(json.dumps(d))
    del missing["items"][0]["verdict"]
    with pytest.raises(ValidationError):
        reproduce.validate(missing)


def test_no_personal_paths_attack_or_answer_text_in_outputs(repo, tmp_path):
    res = run()
    text = res["json"].read_text(encoding="utf-8") + res["md"].read_text(encoding="utf-8")
    for p in (tmp_path, repo):
        assert str(p) not in text and p.as_posix() not in text and str(p).replace("\\", "\\\\") not in text
    first = json.loads(next((repo / "redteam" / "attacks").glob("*.jsonl")).read_text(
        encoding="utf-8").splitlines()[0])
    assert first["user_input"][:30] not in text
    assert "Pessoas+" not in text  # nenhuma resposta do eval em texto, só sha256


def test_scrub_handles_windows_paths_on_any_os(tmp_path):
    assert reproduce.scrub(r"falha em C:\Users\Fulano de Tal\proj\dataset.jsonl.") == "falha em <externo>/dataset.jsonl."
    assert reproduce.scrub("erro /home/fulano/proj/x.py linha") == "erro <externo>/x.py linha"
    assert reproduce.scrub(r"\\servidor\pasta\arq.txt") == "<externo>/arq.txt"
    got = reproduce.scrub(f"em {tmp_path / 'a b' / 'c.txt'}", {"raiz": tmp_path})
    assert got.replace("\\", "/") == "em <raiz>/a b/c.txt"
    assert reproduce.scrub("e/ou n/d 1/2 http://127.0.0.1:11434") == "e/ou n/d 1/2 http://127.0.0.1:11434"


# --- CLI --------------------------------------------------------------------------------------


def test_cli_reproduce_end_to_end(repo, monkeypatch, capsys):
    llm = make_llm("oracle")
    monkeypatch.setattr(ollama_chat, "chat", lambda model, messages, tools=None, options=None, **kw: llm(model, messages, tools))
    monkeypatch.setattr(provenance, "_ollama_get", fetch_for())
    assert cli.main(["reproduce", "pk", "--out", "saida"]) == 0
    out = capsys.readouterr().out
    assert "Reexecução gravada em saida/" in out and "Ambiente: igual" in out
    assert "Descrição, não aprovação" in out and "reproduzido" in out
    assert cli.main(["audit", "verify", "saida/audit/reproducao.jsonl"]) == 0
    capsys.readouterr()
    assert cli.main(["reproduce", "pk", "--out", "saida"]) == 2  # não sobrescreve
    assert "não está vazia" in capsys.readouterr().err
    assert cli.main(["reproduce", "naoexiste"]) == 2
    assert "recusado" in capsys.readouterr().err
    assert cli.main(["reproduce", "pk", "--only", "eval", "--limit", "0", "--out", "o2"]) == 2
