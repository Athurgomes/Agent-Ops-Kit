"""Mapa de cobertura OWASP LLM Top 10 (2025): validação do YAML e cálculo sobre números do red team."""

from pathlib import Path

import pytest
import yaml

from agent_ops_kit.report import coverage

ROOT = Path(__file__).resolve().parent.parent
MAP = ROOT / "policies" / "coverage" / "owasp_llm_2025.yaml"


def _doc():
    return yaml.safe_load(MAP.read_text(encoding="utf-8"))


def _write(tmp_path, doc):
    p = tmp_path / "map.yaml"
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return p


def _row(n, s):
    return {"n": n, "successes": s}


def test_default_map_loads_with_official_names():
    m = coverage.load_map()
    assert list(m["names"]) == list(coverage.OWASP_IDS)
    assert m["names"]["LLM01"] == "Prompt Injection" and m["names"]["LLM10"] == "Unbounded Consumption"
    assert len(m["sha256"]) == 64 and m["path_relative"].endswith("owasp_llm_2025.yaml")


def test_map_is_read_with_safe_load(tmp_path):
    p = tmp_path / "evil.yaml"
    p.write_text("id: !!python/object/apply:os.getcwd []\n", encoding="utf-8")
    with pytest.raises(coverage.CoverageError):
        coverage.load_map(p)


@pytest.mark.parametrize(
    ("edit", "msg"),
    [
        (lambda d: d["attack_categories"].update({"injecao_direta": ["LLM11"]}), "ID inválido"),
        (lambda d: d["attack_categories"].update({"injecao_direta": []}), "lista não vazia"),
        (lambda d: d["attack_categories"].update({"categoria_inventada": ["LLM01"]}), "categoria de ataque desconhecida"),
        (lambda d: d["controls"].update({"guardrail_inventado": ["LLM01"]}), "guardrail desconhecido"),
        (lambda d: d["not_covered"].update({"LLM01": "motivo"}), "também tem ataque ou controle"),
        (lambda d: d["not_covered"].pop("LLM03"), "sem ataque, controle ou 'not_covered'"),
        (lambda d: d["not_covered"].update({"LLM03": " "}), "precisa de um motivo"),
        (lambda d: d["categories"].pop("LLM09"), "exatamente LLM01..LLM10"),
    ],
)
def test_invalid_maps_are_rejected(tmp_path, edit, msg):
    doc = _doc()
    edit(doc)
    with pytest.raises(coverage.CoverageError, match=msg):
        coverage.load_map(_write(tmp_path, doc))


def test_missing_map_is_an_error(tmp_path):
    with pytest.raises(coverage.CoverageError, match="não encontrado"):
        coverage.load_map(tmp_path / "nada.yaml")


def test_compute_groups_by_llm_and_marks_not_covered():
    rt = {"asr": {
        "baseline": {"injecao_direta": _row(2, 1), "injecao_indireta": _row(1, 1), "abuso_de_tools": _row(3, 2),
                     "saida_insegura": _row(1, 0), "total": _row(7, 4)},
        "guardrails": {"injecao_direta": _row(2, 0), "injecao_indireta": _row(1, 0), "abuso_de_tools": _row(3, 1),
                       "saida_insegura": _row(1, 0), "total": _row(7, 1)},
    }}
    cov = coverage.compute(coverage.load_map(), rt)
    by = {c["id"]: c for c in cov["categories"]}
    assert [c["id"] for c in cov["categories"]] == list(coverage.OWASP_IDS)
    assert by["LLM01"]["status"] == "testado"
    assert by["LLM01"]["baseline"] == _row(3, 2) and by["LLM01"]["guardrails"] == _row(3, 0)
    assert by["LLM01"]["controls"] == ["input_filter", "untrusted_content"]
    assert by["LLM06"]["baseline"] == _row(3, 2) and by["LLM06"]["guardrails"] == _row(3, 1)
    assert by["LLM05"]["status"] == "testado" and by["LLM05"]["controls"] == []
    assert by["LLM02"]["status"] == "só controle"  # sem ataque de vazamento neste exemplo
    assert by["LLM07"]["status"] == "só controle" and by["LLM07"]["controls"] == ["output_filter"]
    assert by["LLM10"]["status"] == "não coberto"  # categoria mapeada, mas sem ataque e sem controle
    for lid in ("LLM03", "LLM04", "LLM08", "LLM09"):
        assert by[lid]["status"] == "não coberto" and by[lid]["reason"]
    assert cov["unmapped_attack_categories"] == []


def test_compute_lists_unmapped_attack_categories():
    rt = {"asr": {"baseline": {"nova": _row(1, 1), "total": _row(1, 1)}, "guardrails": {"total": _row(0, 0)}}}
    assert coverage.compute(coverage.load_map(), rt)["unmapped_attack_categories"] == ["nova"]


def test_real_results_numbers_match_asr_totals():
    """Soma por LLM = ASR total dos mesmos JSONL (os números vêm de redteam_numbers, sem duplicar)."""
    import json

    from agent_ops_kit.redteam.report import _load_attacks
    from agent_ops_kit.report import build

    d = ROOT / "redteam" / "results_owasp"
    base, guard = _load_attacks(d / "baseline.jsonl"), _load_attacks(d / "guardrails.jsonl")
    ds = [json.loads(x) for x in (d / "fp_dataset.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    bn = [json.loads(x) for x in (d / "fp_benign.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    rt = build.redteam_numbers(base, guard, ds, bn)
    cov = coverage.compute(coverage.load_map(), rt)
    for cfg in ("baseline", "guardrails"):
        assert sum(c[cfg]["n"] for c in cov["categories"]) == rt["asr"][cfg]["total"]["n"]
        assert sum(c[cfg]["successes"] for c in cov["categories"]) == rt["asr"][cfg]["total"]["successes"]
