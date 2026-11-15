import pytest
from pydantic import ValidationError

from agent_ops_kit.config import load_config

VALID = """\
name: rag-agent
model: llama3.1:8b
prompt_version: v1
system_prompt: Responda com base nos documentos.
tools: [search, calculator]
guardrails: [input_filter]
retrieval:
  top_k: 4
"""


def write(tmp_path, text):
    p = tmp_path / "agent.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_valid_yaml_loads(tmp_path):
    cfg = load_config(write(tmp_path, VALID))
    assert cfg.name == "rag-agent"
    assert cfg.tools == ["search", "calculator"]
    assert cfg.retrieval["top_k"] == 4


def test_defaults_for_optional_fields(tmp_path):
    text = "name: a\nmodel: m\nprompt_version: v1\nsystem_prompt: s\n"
    cfg = load_config(write(tmp_path, text))
    assert cfg.tools == [] and cfg.guardrails == [] and cfg.retrieval == {}


def test_missing_required_field_fails(tmp_path):
    text = VALID.replace("model: llama3.1:8b\n", "")
    with pytest.raises(ValidationError):
        load_config(write(tmp_path, text))


BASE = "name: a\nmodel: m\nprompt_version: v1\nsystem_prompt: s\n"


def test_audit_field_optional(tmp_path):
    assert load_config(write(tmp_path, BASE)).audit is None
    cfg = load_config(write(tmp_path, BASE + "audit: logs/audit.jsonl\n"))
    assert cfg.audit == "logs/audit.jsonl"


def test_extra_field_still_forbidden(tmp_path):
    with pytest.raises(ValidationError):
        load_config(write(tmp_path, BASE + "audit: x.jsonl\nauditoria: y\n"))


def test_wrong_type_fails(tmp_path):
    text = VALID.replace("tools: [search, calculator]", "tools: not-a-list")
    with pytest.raises(ValidationError):
        load_config(write(tmp_path, text))
