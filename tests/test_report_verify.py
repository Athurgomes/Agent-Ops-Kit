"""`aok report verify`: confere offline o pacote do `report build` (sem rede, sem modelo)."""

import json
import os
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest

from agent_ops_kit import cli
from agent_ops_kit.audit import AuditLog
from agent_ops_kit.report import verify

SRC = Path(__file__).resolve().parent.parent


@contextmanager
def _cd(path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _attack(cid, cat, success=False, blocked=()):
    return {"case_id": cid, "category": cat, "success": success, "blocked_by": list(blocked)}


def _fp(cid, blocked=False):
    return {
        "case_id": cid, "blocked": blocked, "blocked_by": ["output"] if blocked else [],
        "reasons": ["canary_leak"] if blocked else [], "score": 1.0, "error": None,
    }


def _build(root, name, *extra):
    with _cd(root):
        rc = cli.main([
            "report", "build", "--out", name,
            "--redteam-baseline", "rt/baseline.jsonl", "--redteam-guardrails", "rt/guardrails.jsonl",
            "--fp-dir", "rt", "--policy", "policies/default.yaml",
            "--coverage-map", "policies/coverage/owasp_llm_2025.yaml", *extra,
        ])
    assert rc == 0


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    """Mini-repositório (evidências reais do eval + red team sintético) com dois pacotes."""
    root = tmp_path_factory.mktemp("repo")
    shutil.copytree(SRC / "evals", root / "evals")
    shutil.copytree(
        SRC / "examples" / "rag_agent", root / "examples" / "rag_agent",
        ignore=shutil.ignore_patterns("__pycache__", "chroma*"),
    )
    shutil.copytree(SRC / "policies", root / "policies")
    rt = root / "rt"
    rt.mkdir()
    _write(rt / "baseline.jsonl", [
        _attack("a1", "injecao_direta", True), _attack("a2", "injecao_direta"),
        _attack("x1", "exfiltracao", True),
    ])
    _write(rt / "guardrails.jsonl", [
        _attack("a1", "injecao_direta", False, ["input"]), _attack("a2", "injecao_direta", True),
        _attack("x1", "exfiltracao", False, ["output"]),
    ])
    _write(rt / "fp_dataset.jsonl", [_fp("q1"), _fp("q2", True)])
    _write(rt / "fp_benign.jsonl", [_fp("b1"), _fp("b2")])
    (root / "audit").mkdir()
    log = AuditLog(root / "audit" / "a.jsonl")
    log.append("question", {"text": "x"})
    log.append("answer", {"text": "y"})
    with _cd(root):
        assert cli.main(["audit", "keygen", "--private-out", "audit/k.pem", "--public-out", "audit/k.pub"]) == 0
        assert cli.main([
            "audit", "sign", "audit/a.jsonl", "--out", "audit/a.sig.json", "--private-key", "audit/k.pem",
        ]) == 0
    _build(root, "pk_audit", "--audit", "audit/a.jsonl", "--audit-signature", "audit/a.sig.json",
           "--audit-public-key", "audit/k.pub")
    _build(root, "pk_plain")
    return root


@pytest.fixture
def repo(sandbox, tmp_path):
    """Cópia descartável do mini-repositório: cada teste adultera a sua."""
    dst = tmp_path / "repo"
    shutil.copytree(sandbox, dst)
    return dst


def _run(repo, pkg="pk_audit", *extra):
    return cli.main(["report", "verify", str(repo / pkg), "--repo-root", str(repo), *extra])


def _edit_json(repo, pkg, fn):
    path = repo / pkg / "relatorio.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _statuses(repo, pkg="pk_audit"):
    res = verify.verify_package(repo / pkg, repo)
    return {c["id"]: c["status"] for c in res["checks"]}


@pytest.mark.parametrize("pkg", ["pk_audit", "pk_plain"])
def test_intact_package_exit_0(repo, pkg, capsys):
    assert _run(repo, pkg) == 0
    out = capsys.readouterr().out
    assert "ÍNTEGRO" in out and "FALHA" not in out and "NÃO VERIFICÁVEL" not in out
    st = _statuses(repo, pkg)
    assert set(st.values()) == {"ok"} and {"eval", "mcnemar", "policy_sha", "findings", "audit"} <= set(st)


def test_audit_signature_is_reverified(repo):
    detail = {c["id"]: c["detail"] for c in verify.verify_package(repo / "pk_audit", repo)["checks"]}
    assert "ed25519" in detail["audit"] and "íntegra" in detail["audit"]


def _set(path, value):
    def fn(d):
        cur = d
        *head, last = path.split(".")
        for p in head:
            cur = cur[p]
        cur[last] = value
    return fn


@pytest.mark.parametrize(
    ("path", "value", "check"),
    [
        ("eval.mean_diff", 0.5, "eval"),
        ("eval.p_value", 0.001, "eval"),
        ("redteam.asr.guardrails.total.successes", 0, "asr"),
        ("redteam.asr.baseline.total.ci95_high", 0.1, "asr"),
        ("redteam.mcnemar.p_value", 0.5, "mcnemar"),
        ("redteam.false_positives.dataset.blocked", 0, "false_positives"),
        ("semaphore.color", "green", "semaphore"),
        ("hashes.redteam_baseline", "0" * 64, "hashes"),
        ("agent.model", "outro-modelo", "agent"),
    ],
)
def test_tampered_number_exit_1(repo, path, value, check, capsys):
    _edit_json(repo, "pk_audit", _set(path, value))
    assert _run(repo) == 1
    assert _statuses(repo)[check] == "falha"
    assert "FALHA" in capsys.readouterr().out


def test_tampered_findings_exit_1(repo):
    _edit_json(repo, "pk_audit", lambda d: d["findings"].pop(0))
    assert _run(repo) == 1
    assert _statuses(repo)["findings"] == "falha"


def test_tampered_markdown_exit_1(repo):
    md = repo / "pk_audit" / "relatorio.md"
    md.write_text(md.read_text(encoding="utf-8") + "\nTudo verde.\n", encoding="utf-8")
    assert _run(repo) == 1
    assert _statuses(repo)["render"] == "falha"


@pytest.mark.parametrize(
    ("rel", "old", "new"),
    [
        ("rt/guardrails.jsonl", '"success": true', '"success": false'),
        ("rt/fp_dataset.jsonl", '"blocked": true', '"blocked": false'),
        ("evals/answers/v2.jsonl", None, None),  # remove a última resposta gravada
    ],
)
def test_tampered_evidence_exit_1(repo, rel, old, new):
    path = repo / rel
    text = path.read_text(encoding="utf-8")
    if old is None:
        text = "\n".join(text.splitlines()[:-1]) + "\n"
    else:
        assert old in text
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    assert _run(repo) == 1
    assert "falha" in set(_statuses(repo).values())


def test_swapped_policy_exit_1(repo):
    pol = repo / "policies" / "default.yaml"
    pol.write_text(pol.read_text(encoding="utf-8") + "\n# afrouxada\n", encoding="utf-8")
    assert _run(repo) == 1
    st = _statuses(repo)
    assert st["policy_sha"] == "falha" and st["inputs"] == "falha"


def test_policy_threshold_changed_and_json_forged_exit_1(repo):
    """Autor troca o limiar E reescreve o hash e a cor no json: a política em disco não bate."""
    import hashlib

    pol = repo / "policies" / "default.yaml"
    raw = pol.read_bytes().replace(b"threshold: 0", b"threshold: 99", 1)
    assert raw != pol.read_bytes()
    pol.write_bytes(raw)

    def forge(d):
        d["policy"]["sha256"] = hashlib.sha256(raw).hexdigest()
        d["provenance"]["inputs"]["policies/default.yaml"] = hashlib.sha256(raw).hexdigest()
        d["semaphore"]["color"] = "green"

    _edit_json(repo, "pk_audit", forge)
    assert _run(repo) == 1
    assert _statuses(repo)["semaphore"] == "falha"


def test_tampered_audit_log_exit_1(repo):
    log = repo / "audit" / "a.jsonl"
    log.write_text(log.read_text(encoding="utf-8").replace('"x"', '"z"'), encoding="utf-8")
    assert _run(repo) == 1
    assert _statuses(repo)["audit"] == "falha"


def test_missing_evidence_is_not_verifiable_exit_1(repo, capsys):
    (repo / "rt" / "fp_benign.jsonl").unlink()
    assert _run(repo) == 1
    st = _statuses(repo)
    assert st["false_positives"] == "nao_verificavel" and "falha" not in st.values()
    assert "NÃO VERIFICÁVEL" in capsys.readouterr().out


def test_package_without_file_map_is_not_verifiable(repo):
    _edit_json(repo, "pk_plain", lambda d: d["provenance"].pop("files"))
    assert _run(repo, "pk_plain") == 1
    assert _statuses(repo, "pk_plain")["eval"] == "nao_verificavel"


def test_path_traversal_in_package_is_rejected(repo):
    _edit_json(repo, "pk_plain", lambda d: d["provenance"]["inputs"].update({"../fora.txt": "0" * 64}))
    assert _run(repo, "pk_plain") == 1
    assert _statuses(repo, "pk_plain")["inputs"] == "falha"


def test_unreadable_package_exit_2(repo, tmp_path, capsys):
    assert cli.main(["report", "verify", str(tmp_path / "nao_existe")]) == 2
    (repo / "pk_plain" / "relatorio.json").write_text("{nao e json", encoding="utf-8")
    assert _run(repo, "pk_plain") == 2
    (repo / "pk_plain" / "relatorio.json").write_text("[1, 2]", encoding="utf-8")
    assert _run(repo, "pk_plain") == 2
    assert cli.main(["report", "verify", str(repo / "pk_audit"), "--repo-root", str(tmp_path / "x")]) == 2
    assert "erro:" in capsys.readouterr().err


def test_invalid_structure_exit_1(repo):
    _edit_json(repo, "pk_plain", lambda d: d.pop("eval"))
    assert _run(repo, "pk_plain") == 1
    assert _statuses(repo, "pk_plain") == {"structure": "falha"}


def test_json_output_and_determinism(repo, capsys):
    assert _run(repo, "pk_audit", "--json") == 0
    first = capsys.readouterr().out
    assert _run(repo, "pk_audit", "--json") == 0
    second = capsys.readouterr().out
    assert first == second
    res = json.loads(first)
    assert res["ok"] is True and res["summary"]["falha"] == 0 and res["not_covered"]
    assert all(c["status"] == "ok" for c in res["checks"])
    assert _run(repo, "pk_audit") == 0
    text1 = capsys.readouterr().out
    assert _run(repo, "pk_audit") == 0
    assert text1 == capsys.readouterr().out


def test_build_and_verify_share_calculation(repo):
    """O build usa as mesmas funções de cálculo do verify (sem duplicar lógica)."""
    from agent_ops_kit.report import build

    assert verify.build.eval_numbers is build.eval_numbers
    assert verify.build.redteam_numbers is build.redteam_numbers


def test_coverage_checked_and_tampered_map_exit_1(repo):
    assert _statuses(repo)["coverage"] == "ok"
    mp = repo / "policies" / "coverage" / "owasp_llm_2025.yaml"
    mp.write_text(mp.read_text(encoding="utf-8").replace("  injecao_direta: [LLM01]", "  injecao_direta: [LLM02]"), encoding="utf-8")
    assert _run(repo) == 1
    st = _statuses(repo)
    assert st["coverage"] == "falha" and st["inputs"] == "falha"


def test_forged_coverage_block_exit_1(repo):
    def forge(d):
        d["coverage"]["categories"][2]["status"] = "testado"  # LLM03 nunca foi testado

    _edit_json(repo, "pk_audit", forge)
    assert _statuses(repo)["coverage"] == "falha"


def test_missing_evidence_message_suggests_flag(repo):
    from agent_ops_kit.report import verify as v

    ver = v._Verifier.__new__(v._Verifier)
    ver.root, ver.evidence_root = repo, None
    with pytest.raises(v._NotVerifiable, match="--evidence-root"):
        ver.path("@evidence/a/b.jsonl", "x")
    ver.evidence_root = repo
    with pytest.raises(v._NotVerifiable, match=r"procurado em --evidence-root, como a/b.jsonl"):
        ver.path("@evidence/a/b.jsonl", "x")
    ver.evidence_root = None
    with pytest.raises(v._NotVerifiable, match="procurado em pasta do pacote, como a/c.jsonl"):
        ver.path("a/c.jsonl", "x")


def test_eval_n_cases_is_executed_not_dataset():
    from agent_ops_kit.eval.dataset import load_dataset
    from agent_ops_kit.report import build as b

    ds = load_dataset(SRC / "evals" / "dataset.jsonl")
    sub = ds[:10]
    recs = {v: [{"case_id": c.id, "answer": "x", "run_index": 0} for c in sub] for v in ("v1", "v2")}
    ev, _ = b.eval_numbers(ds, recs, "v1", "v2", 42)
    assert (ev["n_cases"], ev["n_dataset"]) == (10, len(ds))
    assert b.cases_label(ev) == f"10 de {len(ds)} casos do conjunto"
