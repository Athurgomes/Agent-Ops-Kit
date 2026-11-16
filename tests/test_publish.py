import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_ops_kit import cli
from agent_ops_kit.audit import AuditLog
from agent_ops_kit.report import publish

ROOT = Path(__file__).resolve().parent.parent
AUDIT_SECRET = "PERGUNTA-SECRETA-DA-AUDITORIA"
CONFIG = ROOT / "examples/rag_agent/agent.yaml"


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _attack(cid, cat, success=False):
    return {"case_id": cid, "category": cat, "success": success, "blocked_by": [],
            "final_answer": "x", "raw_answer": "x"}


def _fp(cid):
    return {"case_id": cid, "blocked": False, "blocked_by": [], "reasons": [], "answer": "x",
            "raw_answer": "x", "score": 1.0, "error": None}


@pytest.fixture
def rt_dir(tmp_path):
    d = tmp_path / "rt"
    d.mkdir()
    _write(d / "baseline.jsonl", [_attack("a1", "injecao_direta", True), _attack("a2", "exfiltracao")])
    _write(d / "guardrails.jsonl", [_attack("a1", "injecao_direta"), _attack("a2", "exfiltracao")])
    _write(d / "fp_dataset.jsonl", [_fp("q1"), _fp("q2")])
    _write(d / "fp_benign.jsonl", [_fp("b1"), _fp("b2")])
    return d


def _argv(tmp_path, rt, *extra, config=True):
    argv = [
        "check", "--out", str(tmp_path / "pk"),
        "--dataset", str(ROOT / "evals/dataset.jsonl"),
        "--prompts-dir", str(ROOT / "evals/prompts"),
        "--answers-dir", str(ROOT / "evals/answers"),
        "--redteam-baseline", str(rt / "baseline.jsonl"),
        "--redteam-guardrails", str(rt / "guardrails.jsonl"),
        "--fp-dir", str(rt), *extra,
    ]
    if config:
        argv += ["--config", str(CONFIG)]
    return argv


def _clock(monkeypatch, *stamps):
    it = iter(stamps)
    monkeypatch.setattr(publish, "_utcnow", lambda: next(it))


def _t(second):
    return datetime(2026, 1, 2, 3, 4, second, tzinfo=UTC)


def test_check_without_publish_only_builds_package(tmp_path, rt_dir, capsys):
    assert cli.main(_argv(tmp_path, rt_dir)) == 0
    assert {p.name for p in (tmp_path / "pk").iterdir()} == {
        "relatorio.md", "relatorio.html", "relatorio.json",
    }
    assert "Semáforo" in capsys.readouterr().out


def test_two_versions_index_most_recent_first(tmp_path, rt_dir, monkeypatch, capsys):
    pub = tmp_path / "pub"
    _clock(monkeypatch, _t(1), _t(2))
    argv = _argv(tmp_path, rt_dir, "--publish", str(pub), "--agent-id", "meu-agente")
    assert cli.main(argv) == 0
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "20260102T030402Z" in out and "Publicado em" in out
    index = json.loads((pub / "meu-agente" / "index.json").read_text(encoding="utf-8"))
    assert [v["timestamp"] for v in index["versions"]] == ["20260102T030402Z", "20260102T030401Z"]
    sha = hashlib.sha256((tmp_path / "pk" / "relatorio.json").read_bytes()).hexdigest()
    assert index["versions"][0]["report_sha256"] == sha
    assert index["versions"][0]["semaphore"] in {"green", "yellow", "red"}
    assert not list((pub / "meu-agente").glob("*.tmp"))


def test_timestamp_collision_never_overwrites(tmp_path, rt_dir, monkeypatch, capsys):
    pub = tmp_path / "pub"
    _clock(monkeypatch, _t(1), _t(1))
    argv = _argv(tmp_path, rt_dir, "--publish", str(pub), "--agent-id", "a1")
    assert cli.main(argv) == 0
    folder = pub / "a1" / "20260102T030401Z"
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    index_before = (pub / "a1" / "index.json").read_bytes()
    assert cli.main(argv) == 2
    assert "imutável" in capsys.readouterr().err
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
    assert (pub / "a1" / "index.json").read_bytes() == index_before


@pytest.mark.parametrize("bad", ["../x", "", "Maiusculas", "a/b", "a\\b", "a_b", "x" * 65])
def test_invalid_agent_id_exit_2(tmp_path, rt_dir, bad):
    pub = tmp_path / "pub"
    assert cli.main(_argv(tmp_path, rt_dir, "--publish", str(pub), "--agent-id", bad)) == 2
    assert not pub.exists()


def test_publish_without_agent_id_nor_config_exit_2(tmp_path, rt_dir, capsys):
    pub = tmp_path / "pub"
    assert cli.main(_argv(tmp_path, rt_dir, "--publish", str(pub), config=False)) == 2
    assert "--agent-id" in capsys.readouterr().err
    assert not pub.exists()


def test_agent_id_defaults_to_config_name(tmp_path, rt_dir):
    pub = tmp_path / "pub"
    assert cli.main(_argv(tmp_path, rt_dir, "--publish", str(pub))) == 0
    assert (pub / "rag-agent" / "index.json").is_file()


def test_pacote_json_matches_file_hashes_and_has_no_audit(tmp_path, rt_dir, monkeypatch):
    log = tmp_path / "audit.jsonl"
    al = AuditLog(log)
    al.append("question", {"text": AUDIT_SECRET})
    al.append("answer", {"text": AUDIT_SECRET})
    pub = tmp_path / "pub"
    _clock(monkeypatch, _t(5))
    argv = _argv(tmp_path, rt_dir, "--audit", str(log), "--publish", str(pub), "--agent-id", "ag")
    assert cli.main(argv) == 0
    folder = pub / "ag" / "20260102T030405Z"
    meta = json.loads((folder / "pacote.json").read_text(encoding="utf-8"))
    assert meta["agent_id"] == "ag" and meta["timestamp"] == "20260102T030405Z"
    assert set(meta["sha256"]) == {"relatorio.md", "relatorio.html", "relatorio.json"}
    for name, digest in meta["sha256"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
    assert {p.name for p in folder.iterdir()} == {*meta["sha256"], "pacote.json"}
    for p in (pub / "ag").rglob("*"):
        if p.is_file():
            assert AUDIT_SECRET not in p.read_text(encoding="utf-8")
    assert json.loads((folder / "relatorio.json").read_text(encoding="utf-8"))["audit"]["ok"]


def test_corrupt_index_exit_2(tmp_path, rt_dir):
    pub = tmp_path / "pub"
    (pub / "ag").mkdir(parents=True)
    (pub / "ag" / "index.json").write_text("{nao é json", encoding="utf-8")
    assert cli.main(_argv(tmp_path, rt_dir, "--publish", str(pub), "--agent-id", "ag")) == 2
