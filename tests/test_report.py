import copy
import json
import re
from pathlib import Path

import pytest

from agent_ops_kit import cli
from agent_ops_kit.audit import AuditLog
from agent_ops_kit.report import build, render

ROOT = Path(__file__).resolve().parent.parent
ATTACK_SECRET = "TEXTO-DE-ATAQUE-SECRETO"
AUDIT_SECRET = "PERGUNTA-SECRETA-DA-AUDITORIA"
REQUIRED_LIMITATIONS = (
    (
        "As notas do juiz (modelo) não entram neste pacote; só as checagens determinísticas. "
        "Consulte docs/resultados.md."
    ),
    (
        "Quando o ASR em abuso de ferramentas é zero, isso decorre em grande parte da allowlist de "
        "ferramentas do agente e não indica robustez geral; a queda do ASR sem guardrails para "
        "com guardrails não pode ser atribuída apenas aos guardrails."
    ),
)
BANNED = re.compile(r"\b(seguro|segura|robust[oa]s?|eficaz(es)?)\b", re.IGNORECASE)


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _attack(cid, cat, success=False, blocked=()):
    return {
        "case_id": cid, "category": cat, "success": success, "blocked_by": list(blocked),
        "final_answer": ATTACK_SECRET, "raw_answer": ATTACK_SECRET,
    }


def _fp(cid, blocked=False):
    return {
        "case_id": cid, "blocked": blocked, "blocked_by": ["output"] if blocked else [],
        "reasons": ["canary_leak"] if blocked else [], "answer": ATTACK_SECRET,
        "raw_answer": ATTACK_SECRET, "score": 1.0, "error": None,
    }


@pytest.fixture
def rt_dir(tmp_path):
    d = tmp_path / "rt"
    d.mkdir()
    _write(d / "baseline.jsonl", [
        _attack("a1", "injecao_direta", True), _attack("a2", "injecao_direta"),
        _attack("x1", "exfiltracao", True),
    ])
    _write(d / "guardrails.jsonl", [
        _attack("a1", "injecao_direta", False, ["input"]), _attack("a2", "injecao_direta"),
        _attack("x1", "exfiltracao", False, ["output"]),
    ])
    _write(d / "fp_dataset.jsonl", [_fp("q1"), _fp("q2")])
    _write(d / "fp_benign.jsonl", [_fp("b1"), _fp("b2")])
    return d


def _argv(out, rt, *extra):
    return [
        "report", "build", "--out", str(out),
        "--dataset", str(ROOT / "evals/dataset.jsonl"),
        "--prompts-dir", str(ROOT / "evals/prompts"),
        "--config", str(ROOT / "examples/rag_agent/agent.yaml"),
        "--answers-dir", str(ROOT / "evals/answers"),
        "--redteam-baseline", str(rt / "baseline.jsonl"),
        "--redteam-guardrails", str(rt / "guardrails.jsonl"),
        "--fp-dir", str(rt), *extra,
    ]


@pytest.fixture(scope="module")
def real_data(tmp_path_factory):
    """Dados do eval real do repositório (sem modelo) + red team sintético."""
    d = tmp_path_factory.mktemp("real")
    _write(d / "b.jsonl", [_attack("a1", "injecao_direta", True)])
    _write(d / "g.jsonl", [_attack("a1", "injecao_direta")])
    _write(d / "fp_dataset.jsonl", [_fp("q1")])
    _write(d / "fp_benign.jsonl", [_fp("b1")])
    return build.build_data(
        config=str(ROOT / "examples/rag_agent/agent.yaml"),
        dataset=str(ROOT / "evals/dataset.jsonl"),
        prompts_dir=str(ROOT / "evals/prompts"),
        answers_dir=str(ROOT / "evals/answers"),
        baseline="v1", candidate="v2", seed=42,
        redteam_baseline=str(d / "b.jsonl"), redteam_guardrails=str(d / "g.jsonl"),
        fp_dir=str(d),
    )


# ---- semáforo ----

def _ev(**kw):
    return {"regression": False, "mean_diff": 0.0, **kw}


def _rt(successes=0, fp_blocked=0):
    return {
        "asr": {"guardrails": {"total": {"successes": successes}}},
        "false_positives": {"dataset": {"blocked": fp_blocked}, "benign": {"blocked": 0}},
    }


AUDIT_OK = {"ok": True}
AUDIT_BAD = {"ok": False}


def test_semaphore_green():
    s = build.semaphore(_ev(mean_diff=0.05), _rt(), AUDIT_OK)
    assert s["color"] == "green" and s["triggered"] == []


@pytest.mark.parametrize(
    ("ev", "rt", "au", "rule"),
    [
        (_ev(), _rt(successes=1), AUDIT_OK, "attack_success_with_guardrails"),
        (_ev(), _rt(fp_blocked=1), AUDIT_OK, "false_positive"),
        (_ev(mean_diff=-0.1), _rt(), AUDIT_OK, "eval_nonsignificant_drop"),
        (_ev(), _rt(), None, "no_audit"),
    ],
)
def test_semaphore_yellow(ev, rt, au, rule):
    s = build.semaphore(ev, rt, au)
    assert s["color"] == "yellow" and s["triggered"] == [rule]


def test_semaphore_red():
    s = build.semaphore(_ev(mean_diff=-0.2, regression=True), _rt(), AUDIT_OK)
    assert s["color"] == "red" and s["triggered"] == ["eval_regression"]
    s = build.semaphore(_ev(), _rt(successes=2), AUDIT_BAD)
    assert s["color"] == "red" and s["triggered"][0] == "audit_invalid"


@pytest.mark.parametrize("color", ["green", "yellow", "red"])
def test_green_text_only_when_green_and_banned_words(real_data, color):
    d = copy.deepcopy(real_data)
    if color == "green":
        d["semaphore"] = {"color": "green", "triggered": [], "rules_version": "provisoria-1"}
        d["audit"] = {"ok": True, "n_events": 3, "anchor": "a" * 64, "first_bad_line": None, "reason": None}
    elif color == "yellow":
        d["semaphore"] = {
            "color": "yellow",
            "triggered": ["no_audit", "false_positive", "attack_success_with_guardrails"],
            "rules_version": "provisoria-1",
        }
        d["eval"]["mean_diff"] = -0.02
        d["redteam"]["asr"]["guardrails"]["total"]["successes"] = 1
        d["redteam"]["false_positives"]["dataset"]["blocked"] = 1
    else:
        d["semaphore"] = {
            "color": "red",
            "triggered": ["eval_regression", "audit_invalid"],
            "rules_version": "provisoria-1",
        }
        d["eval"]["regression"] = True
        d["eval"]["mean_diff"] = -0.2
        d["audit"] = {
            "ok": False, "n_events": 2, "anchor": "b" * 64,
            "first_bad_line": 1, "reason": "hash mismatch",
        }

    blocks = render.build_blocks(d)
    md = render.to_markdown(blocks)
    html = render.to_html(blocks, "t")
    if color == "green":
        assert build.GREEN_TEXT in md and build.GREEN_TEXT in html
        md_clean = md.replace(build.GREEN_TEXT, "")
        html_clean = html.replace(build.GREEN_TEXT, "")
    else:
        assert build.GREEN_TEXT not in md and build.GREEN_TEXT not in html
        md_clean, html_clean = md, html
    assert not BANNED.search(md_clean), f"Palavra banida no MD ({color}): {BANNED.search(md_clean)}"
    assert not BANNED.search(html_clean), f"Palavra banida no HTML ({color}): {BANNED.search(html_clean)}"
    assert "PROVISÓRIA" in md and "PROVISÓRIA" in html


def test_abnt_structure_and_print_css(real_data):
    blocks = render.build_blocks(real_data)
    md = render.to_markdown(blocks)
    html = render.to_html(blocks, "Relatório")
    assert md == render.to_markdown(render.build_blocks(real_data))
    assert html == render.to_html(render.build_blocks(real_data), "Relatório")

    for marker in (
        "ABNT NBR 10719:2015",
        "REL-AOK-",
        "1 INTRODUÇÃO",
        "2 PARECER EXECUTIVO",
        "3 ANÁLISE DE QUALIDADE",
        "4 ANÁLISE DE EXPOSIÇÃO",
        "5 RASTREABILIDADE",
        "6 CONCLUSÃO",
        "APÊNDICE A",
        "Quadro de Ciência e Aprovação",
        "Auditoria Interna",
        "Dimensão",
        "Indicador medido",
        "Leitura para o negócio",
    ):
        assert marker in md, f"Ausente no MD: {marker}"
        assert marker in html, f"Ausente no HTML: {marker}"

    assert "@page" in html
    assert re.search(r"size:\s*A4", html)
    assert re.search(r"margin:\s*3cm 2cm 2cm 3cm", html)
    assert re.search(r"page-break-before:\s*always", html)
    assert re.search(r"page-break-inside:\s*avoid", html)
    assert "12pt" in html and "10pt" in html
    assert "overflow-wrap:anywhere" in html or "overflow-wrap: anywhere" in html


def test_html_has_viewport_page_number_and_print_colors(real_data):
    html = render.to_html(render.build_blocks(real_data), "Relatório")
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in html
    assert "@top-right{content:counter(page)" in html
    assert "print-color-adjust:exact" in html


# ---- escape de HTML ----

def test_html_escapes_data(real_data):
    evil = copy.deepcopy(real_data)
    evil["agent"]["name"] = "<script>alert(1)</script>"
    evil["agent"]["model"] = '"><img src=x onerror=alert(1)>'
    blocks = render.build_blocks(evil)
    html = render.to_html(blocks, "t <b>")
    assert "<script" not in html and "<img" not in html and "<b>" not in html
    assert "&lt;script&gt;" in html
    md = render.to_markdown(blocks)
    assert "<script" not in md and "<img" not in md


def test_html_is_static(real_data):
    html = render.to_html(render.build_blocks(real_data), "t")
    assert "<script" not in html and "<link" not in html and "http://" not in html and "https://" not in html
    assert "<style>" in html


# ---- CLI ----

def test_cli_writes_package_without_leaks(tmp_path, rt_dir, capsys):
    log = tmp_path / "audit.jsonl"
    al = AuditLog(log)
    al.append("question", {"text": AUDIT_SECRET})
    last = al.append("answer", {"text": AUDIT_SECRET})
    out = tmp_path / "pk"
    assert cli.main(_argv(out, rt_dir, "--audit", str(log))) == 0
    files = {p.name for p in out.iterdir()}
    assert files == {"relatorio.md", "relatorio.html", "relatorio.json"}
    data = json.loads((out / "relatorio.json").read_text(encoding="utf-8"))
    assert data["audit"] == {
        "ok": True, "n_events": 2, "anchor": last["hash"], "first_bad_line": None, "reason": None,
    }
    assert set(data) == {
        "schema_version", "generated_at", "agent", "profile", "semaphore", "policy", "indicators",
        "eval", "redteam", "audit", "hashes", "findings", "coverage", "provenance", "previous",
        "limitations",
    }
    for name in files:
        text = (out / name).read_text(encoding="utf-8")
        assert AUDIT_SECRET not in text and ATTACK_SECRET not in text
    assert last["hash"] in (out / "relatorio.md").read_text(encoding="utf-8")
    assert last["hash"] in (out / "relatorio.html").read_text(encoding="utf-8")
    assert sum((out / name).stat().st_size for name in files) < 1024 * 1024
    assert "Semáforo" in capsys.readouterr().out
    for phrase in REQUIRED_LIMITATIONS:
        assert phrase in data["limitations"]
        assert phrase in (out / "relatorio.md").read_text(encoding="utf-8")
        assert phrase in (out / "relatorio.html").read_text(encoding="utf-8")


def test_required_limitations_in_function(real_data):
    for phrase in REQUIRED_LIMITATIONS:
        assert phrase in build.limitations(real_data)


def test_cli_broken_audit_chain_is_red(tmp_path, rt_dir):
    log = tmp_path / "audit.jsonl"
    al = AuditLog(log)
    al.append("e", {"x": 1})
    al.append("e", {"x": 2})
    log.write_text(log.read_text(encoding="utf-8").replace('"x":1', '"x":9'), encoding="utf-8")
    out = tmp_path / "pk"
    assert cli.main(_argv(out, rt_dir, "--audit", str(log))) == 0
    data = json.loads((out / "relatorio.json").read_text(encoding="utf-8"))
    assert data["audit"]["ok"] is False and data["audit"]["first_bad_line"] == 1
    assert data["semaphore"]["color"] == "red"


def test_cli_same_input_same_content(tmp_path, rt_dir):
    for n in ("a", "b"):
        assert cli.main(_argv(tmp_path / n, rt_dir)) == 0
    a = json.loads((tmp_path / "a/relatorio.json").read_text(encoding="utf-8"))
    b = json.loads((tmp_path / "b/relatorio.json").read_text(encoding="utf-8"))
    a.pop("generated_at"), b.pop("generated_at")
    a["provenance"].pop("command"), b["provenance"].pop("command")  # traz o --out de cada execução
    assert a == b


def test_cli_previous(tmp_path, rt_dir, capsys):
    first = tmp_path / "p1"
    assert cli.main(_argv(first, rt_dir)) == 0
    # segunda versão: guardrails passam a falhar em um ataque
    _write(rt_dir / "guardrails.jsonl", [
        _attack("a1", "injecao_direta", True), _attack("a2", "injecao_direta"),
        _attack("x1", "exfiltracao", False, ["output"]),
    ])
    second = tmp_path / "p2"
    assert cli.main(_argv(second, rt_dir, "--previous", str(first / "relatorio.json"))) == 0
    data = json.loads((second / "relatorio.json").read_text(encoding="utf-8"))
    rows = {r["metric"]: r for r in data["previous"]["rows"]}
    key = "Red team: ataques com sucesso com guardrails"
    assert rows[key]["before"].startswith("0/3") and rows[key]["after"].startswith("1/3")
    md = (second / "relatorio.md").read_text(encoding="utf-8")
    assert "| Antes | Agora |" in md and key in md
    assert "Relatório anterior não informado" in (first / "relatorio.md").read_text(encoding="utf-8")


def test_cli_previous_invalid(tmp_path, rt_dir, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema_version": 1}', encoding="utf-8")
    assert cli.main(_argv(tmp_path / "o", rt_dir, "--previous", str(bad))) == 2
    err = capsys.readouterr().err
    assert err.startswith("erro:") and "Traceback" not in err


@pytest.mark.parametrize(
    ("flag", "label"),
    [
        ("--redteam-baseline", "red team"),
        ("--redteam-guardrails", "red team"),
        ("--answers-dir", "manifesto"),
        ("--dataset", "dataset"),
        ("--config", "config"),
        ("--fp-dir", "falsos positivos"),
        ("--audit", "auditoria"),
        ("--previous", "anterior"),
    ],
)
def test_cli_missing_file_exit_2(tmp_path, rt_dir, capsys, flag, label):
    argv = _argv(tmp_path / "o", rt_dir, "--audit", str(tmp_path / "x.jsonl"))
    if flag in argv[: len(argv) - 2]:
        argv[argv.index(flag) + 1] = str(tmp_path / "nao_existe")
    else:
        argv += [flag, str(tmp_path / "nao_existe")]
    if flag == "--audit":
        argv = _argv(tmp_path / "o", rt_dir, "--audit", str(tmp_path / "nao_existe"))
    assert cli.main(argv) == 2
    captured = capsys.readouterr()
    assert captured.err.startswith("erro:") and label in captured.err
    assert "Traceback" not in captured.err
    assert not (tmp_path / "o").exists()


def test_cli_invalid_jsonl_exit_2(tmp_path, rt_dir, capsys):
    (rt_dir / "baseline.jsonl").write_text("{não é json\n", encoding="utf-8")
    assert cli.main(_argv(tmp_path / "o", rt_dir)) == 2
    assert "Traceback" not in capsys.readouterr().err
