"""Manifesto de integridade das respostas gravadas (sem Ollama)."""

import json
import shutil
from pathlib import Path

import pytest

from agent_ops_kit import cli
from agent_ops_kit.config import load_config
from agent_ops_kit.eval import runner
from agent_ops_kit.eval.checks import REFUSAL_PHRASE
from agent_ops_kit.eval.dataset import load_dataset

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "examples" / "rag_agent" / "agent.yaml"
CASES = load_dataset(ROOT / "evals" / "dataset.jsonl")[:6]


def _answer(case):
    if not case.answerable:
        return REFUSAL_PHRASE
    return f"{'; '.join(case.expected)}.\nFonte: {case.sources[0]}"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Cópia de prompts e dataset em tmp_path e um LLM falso (sem Ollama)."""
    shutil.copytree(ROOT / "evals" / "prompts", tmp_path / "prompts")
    dataset = tmp_path / "dataset.jsonl"
    lines = (ROOT / "evals" / "dataset.jsonl").read_text(encoding="utf-8").splitlines()[:6]
    dataset.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def llm(model, messages, tools):
        return {"message": {"role": "assistant", "content": "Resposta: x"}}

    monkeypatch.setattr(runner, "make_ollama_llm", lambda seed=42: llm)
    return tmp_path


def _argv(env, *extra, reuse):
    argv = [
        "eval", "--baseline", "v1", "--candidate", "v2",
        "--dataset", str(env / "dataset.jsonl"),
        "--prompts-dir", str(env / "prompts"),
        "--config", str(CONFIG),
        "--answers-dir", str(env / "answers"),
    ]  # fmt: skip
    return argv + (["--reuse"] if reuse else []) + list(extra)


def _record(env):
    assert cli.main(_argv(env, "--seed", "7", reuse=False)) == 0


def test_eval_grava_manifesto_com_hashes(env):
    _record(env)
    data = json.loads((env / "answers" / "manifest.json").read_text(encoding="utf-8"))
    assert set(data) == {"v1", "v2"}
    for v in ("v1", "v2"):
        e = data[v]
        assert e["prompt_sha256"] == runner.sha256_text(
            (env / "prompts" / f"{v}.md").read_text(encoding="utf-8").strip() + "\n"
        )
        assert e["dataset_sha256"] == runner.dataset_hash(env / "dataset.jsonl")
        assert e["model"] == load_config(CONFIG).model
        assert e["seed"] == 7 and e["n_cases"] == 6 and e["date"]


def test_reuse_verifica_ok(env, capsys):
    _record(env)
    capsys.readouterr()
    assert cli.main(_argv(env, reuse=True)) == 0
    assert "manifesto verificado" in capsys.readouterr().out


def test_prompt_alterado_falha(env, capsys):
    _record(env)
    capsys.readouterr()
    with open(env / "prompts" / "v2.md", "a", encoding="utf-8") as f:
        f.write("\nSeja mais breve.\n")
    assert cli.main(_argv(env, reuse=True)) == 2
    err = capsys.readouterr().err
    assert "respostas gravadas desatualizadas: regrave com aok eval" in err
    assert "o prompt v2 mudou" in err and "v1:" not in err


def test_dataset_alterado_falha(env, capsys):
    _record(env)
    capsys.readouterr()
    with open(env / "dataset.jsonl", "a", encoding="utf-8") as f:
        f.write("\n")
    assert cli.main(_argv(env, reuse=True)) == 2
    err = capsys.readouterr().err
    assert "respostas gravadas desatualizadas" in err and "o dataset mudou" in err


def test_manifesto_ausente_falha_e_no_verify_pula(env, capsys):
    _record(env)
    (env / "answers" / "manifest.json").unlink()
    capsys.readouterr()
    assert cli.main(_argv(env, reuse=True)) == 2
    assert "manifesto não encontrado" in capsys.readouterr().err
    assert cli.main(_argv(env, "--no-verify", reuse=True)) == 0
    assert "NÃO verificado" in capsys.readouterr().out


def test_no_verify_pula_divergencia(env, capsys):
    _record(env)
    with open(env / "prompts" / "v1.md", "a", encoding="utf-8") as f:
        f.write("\nmudou\n")
    capsys.readouterr()
    assert cli.main(_argv(env, reuse=True)) == 2
    assert cli.main(_argv(env, "--no-verify", reuse=True)) == 0


def test_modelo_e_numero_de_respostas_divergentes_falham(env, capsys):
    _record(env)
    path = env / "answers" / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["v1"]["model"] = "outro:1b"
    path.write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()
    assert cli.main(_argv(env, reuse=True)) == 2
    assert "o modelo mudou" in capsys.readouterr().err
    data["v1"]["model"] = load_config(CONFIG).model
    data["v1"]["n_cases"] = 99
    path.write_text(json.dumps(data), encoding="utf-8")
    assert cli.main(_argv(env, reuse=True)) == 2
    assert "o arquivo tem 6 respostas" in capsys.readouterr().err


def test_manifesto_do_repo_confere_com_os_arquivos_atuais():
    """O manifesto commitado (v1/v2) bate com prompts e dataset do repositório."""
    runner.verify_manifest(
        ROOT / "evals" / "answers",
        ["v1", "v2"],
        load_config(CONFIG),
        ROOT / "evals" / "dataset.jsonl",
        ROOT / "evals" / "prompts",
    )
