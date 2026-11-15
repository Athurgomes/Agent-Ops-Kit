import json

import pytest

from agent_ops_kit import cli
from agent_ops_kit.redteam.report import ReportError, build_report


def _rec(cid, cat, success=False, blocked=()):
    return {"case_id": cid, "category": cat, "success": success, "blocked_by": list(blocked)}


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def files(tmp_path):
    base = _write(tmp_path / "base.jsonl", [
        _rec("a1", "injecao_direta", True),
        _rec("a2", "injecao_direta"),
        _rec("t1", "abuso_de_tools", True),
        _rec("t2", "abuso_de_tools", True),
        _rec("x1", "exfiltracao", True),
    ])
    guard = _write(tmp_path / "guard.jsonl", [
        _rec("a1", "injecao_direta", False, ["input"]),
        _rec("a2", "injecao_direta"),
        _rec("t1", "abuso_de_tools", False, ["tool"]),
        _rec("t2", "abuso_de_tools"),
        _rec("x1", "exfiltracao", False, ["output"]),
    ])
    return base, guard


def test_asr_table_and_attribution(files):
    out = build_report(*files)
    assert "| total | sem guardrails | 5 | 4 | 80.0 |" in out
    assert "| total | com guardrails | 5 | 0 | 0.0 |" in out
    assert "| injecao_direta | 2 | 1 | 0 | 0 | 1 |" in out
    assert "| abuso_de_tools | 2 | 0 | 1 | 0 | 1 |" in out
    assert "| total | 5 | 1 | 1 | 1 | 2 |" in out
    assert "- a1 (injecao_direta): bloqueado no estágio input" in out
    assert "- t2 (abuso_de_tools): falhou na execução com guardrails SEM bloqueio" in out
    assert "2 dos 5 ataques não foram bloqueados" in out
    assert "Falsos positivos" not in out.split("Limitações")[0]


def test_fp_section_lists_blocked(files, tmp_path):
    fp = tmp_path / "fp"
    fp.mkdir()
    ok = {"blocked": False, "blocked_by": [], "reasons": [], "score": 1.0, "error": None}
    bad = {"blocked": True, "blocked_by": ["output"], "reasons": ["canary_leak"],
           "score": 0.0, "error": None}
    _write(fp / "fp_dataset.jsonl", [{"case_id": "q1", **ok}, {"case_id": "q2", **ok}])
    _write(fp / "fp_benign.jsonl", [{"case_id": "b1", **ok}, {"case_id": "b2", **bad}])
    out = build_report(*files, fp_dir=fp, dataset=tmp_path / "x", v1_answers=tmp_path / "y")
    assert "| Benignas novas (2) | 2 | 1 | 50.0 |" in out
    assert "Benignas novas (2) / b2: estágio(s) output; motivos: canary_leak" in out
    assert "0/2 no dataset e 1/2 nas benignas" in out
    assert "A/B de utilidade indisponível" in out


def test_missing_file_clear_error(files, tmp_path, capsys):
    with pytest.raises(ReportError, match="arquivo não encontrado"):
        build_report(files[0], tmp_path / "nao_existe.jsonl")
    rc = cli.main(["redteam", "report", "--baseline", str(files[0]),
                   "--guardrails", str(tmp_path / "nao_existe.jsonl")])
    assert rc == 2
    assert "arquivo não encontrado" in capsys.readouterr().err


def test_cli_report_writes_output(files, tmp_path, capsys):
    out = tmp_path / "sub" / "r.md"
    rc = cli.main(["redteam", "report", "--baseline", str(files[0]),
                   "--guardrails", str(files[1]), "--output", str(out)])
    assert rc == 0
    assert "Atribuição por estágio" in out.read_text(encoding="utf-8")


def test_run_limit_zero_does_not_overwrite_baseline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "redteam" / "results").mkdir(parents=True)
    baseline = tmp_path / "redteam" / "results" / "baseline.jsonl"
    baseline.write_text("intacto\n", encoding="utf-8")
    out = tmp_path / "g.jsonl"
    rc = cli.main(["redteam", "run", "--guardrails", "all", "--out", str(out), "--limit", "0"])
    assert rc == 0
    assert out.read_text(encoding="utf-8") == ""
    assert baseline.read_text(encoding="utf-8") == "intacto\n"


def test_run_guardrails_requires_out():
    with pytest.raises(SystemExit):
        cli.main(["redteam", "run", "--guardrails", "all", "--limit", "0"])



def test_summary_compacto_e_arquivo_completo(files, tmp_path, capsys):
    fp = tmp_path / "fp"
    fp.mkdir()
    ok = {"blocked": False, "blocked_by": [], "reasons": [], "score": 1.0, "error": None}
    bad = {**ok, "blocked": True, "blocked_by": ["output"], "reasons": ["canary_leak"]}
    _write(fp / "fp_dataset.jsonl", [{"case_id": "q1", **ok}])
    _write(fp / "fp_benign.jsonl", [{"case_id": "b1", **ok}, {"case_id": "b2", **bad}])
    out_md = tmp_path / "r" / "full.md"
    rc = cli.main(["redteam", "report", "--baseline", str(files[0]), "--guardrails",
                   str(files[1]), "--fp-dir", str(fp), "--dataset", str(tmp_path / "x"),
                   "--v1-answers", str(tmp_path / "y"), "--summary", "--output", str(out_md)])
    out = capsys.readouterr().out
    assert rc == 0
    assert len(out.strip().splitlines()) <= 12
    assert "injecao_direta" in out and "1/2 (50,0%)" in out and "0/2 (0,0%)" in out
    assert "total" in out and "4/5 (80,0%)" in out
    assert "Falsos positivos: 0/1 no dataset de avaliação, 1/2 nas benignas novas" in out
    assert str(out_md) in out
    assert "Limitações e leitura honesta" not in out and "canary_leak" not in out
    assert "Limitações e leitura honesta" in out_md.read_text(encoding="utf-8")


def test_summary_sem_output_usa_caminho_padrao(files, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["redteam", "report", "--baseline", str(files[0]),
                     "--guardrails", str(files[1]), "--summary"]) == 0
    out = capsys.readouterr().out
    assert "reports/redteam_report.md" in out and "Falsos positivos" not in out
    assert (tmp_path / "reports" / "redteam_report.md").is_file()
