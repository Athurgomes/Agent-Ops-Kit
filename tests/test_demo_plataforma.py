"""Testes do script scripts/demo_plataforma.py (funções puras; não sobe uvicorn)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "demo_plataforma.py"


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location("demo_plataforma", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pid_morto() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _lock(pasta: Path, pid: int, porta: int = 8123) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "demo.lock").write_text(json.dumps({"pid": pid, "porta": porta}), encoding="utf-8")


def _pasta_demo(base: Path, nome: str = "dados") -> Path:
    pasta = base / nome
    (pasta / "aok_data").mkdir(parents=True)
    (pasta / "demo.db").write_text("x", encoding="utf-8")
    (pasta / "pacote").mkdir()
    (pasta / "pacote" / "relatorio.json").write_text("{}", encoding="utf-8")
    return pasta


def test_pid_vivo(demo):
    assert demo.pid_vivo(os.getpid())
    assert not demo.pid_vivo(_pid_morto())
    assert not demo.pid_vivo(0)


def test_trava_viva_recusa(demo, tmp_path, capsys):
    _lock(tmp_path, os.getpid(), 8123)
    with pytest.raises(SystemExit) as exc:
        demo.checar_instancia(tmp_path)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert f"pid {os.getpid()}" in err and "porta 8123" in err and "--dados" in err
    assert (tmp_path / "demo.lock").exists()


def test_trava_com_pid_morto_e_removida(demo, tmp_path):
    _lock(tmp_path, _pid_morto())
    demo.checar_instancia(tmp_path)
    assert not (tmp_path / "demo.lock").exists()


def test_trava_corrompida_e_tratada_como_velha(demo, tmp_path):
    (tmp_path / "demo.lock").write_text("nao e json", encoding="utf-8")
    demo.checar_instancia(tmp_path)
    assert not (tmp_path / "demo.lock").exists()


def test_trava_sem_segredo_e_exclusiva(demo, tmp_path):
    demo.gravar_trava(tmp_path, 8123)
    corpo = json.loads((tmp_path / "demo.lock").read_text(encoding="utf-8"))
    assert set(corpo) == {"pid", "porta", "inicio"}
    assert corpo["pid"] == os.getpid() and corpo["porta"] == 8123
    with pytest.raises(SystemExit):
        demo.gravar_trava(tmp_path, 8124)
    demo.remover_trava(tmp_path)
    assert not (tmp_path / "demo.lock").exists()


def test_remover_trava_nao_apaga_a_de_outro_pid(demo, tmp_path):
    _lock(tmp_path, _pid_morto())
    demo.remover_trava(tmp_path)
    assert (tmp_path / "demo.lock").exists()


def test_reset_renomeia_e_apaga_sem_tocar_o_resto(demo, tmp_path):
    pasta = _pasta_demo(tmp_path)
    vizinha = _pasta_demo(tmp_path, "outra")
    demo.resetar(pasta)
    assert not pasta.exists()
    assert not list(tmp_path.glob("*.apagando-*"))
    assert (vizinha / "demo.db").is_file() and (vizinha / "pacote" / "relatorio.json").is_file()


def test_reset_aborta_sem_apagar_quando_pasta_em_uso(demo, tmp_path, monkeypatch, capsys):
    pasta = _pasta_demo(tmp_path)

    def falha(*_a, **_k):
        raise PermissionError("arquivo aberto")

    monkeypatch.setattr(demo.os, "replace", falha)
    with pytest.raises(SystemExit) as exc:
        demo.resetar(pasta)
    assert exc.value.code == 1
    assert "pasta em uso" in capsys.readouterr().err
    assert (pasta / "demo.db").is_file() and (pasta / "aok_data").is_dir()
    assert (pasta / "pacote" / "relatorio.json").is_file()
    assert not list(tmp_path.glob("*.apagando-*"))


def test_reset_recusa_pasta_alheia_com_aok_data_e_codigo(demo, tmp_path, capsys):
    pasta = tmp_path / "meu_projeto"
    (pasta / "aok_data").mkdir(parents=True)
    (pasta / "src").mkdir()
    (pasta / "src" / "codigo.py").write_text("x = 1", encoding="utf-8")
    (pasta / "notas.txt").write_text("nao apague", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        demo.resetar(pasta)
    assert exc.value.code == 1
    assert "'notas.txt'" in capsys.readouterr().err
    assert (pasta / "notas.txt").is_file() and (pasta / "src" / "codigo.py").is_file()
    assert (pasta / "aok_data").is_dir()


@pytest.mark.parametrize("nome", ["aok_data", "pacote"])
def test_reset_recusa_pasta_so_com_aok_data_ou_pacote(demo, tmp_path, nome):
    pasta = tmp_path / "dados"
    (pasta / nome).mkdir(parents=True)
    with pytest.raises(SystemExit) as exc:
        demo.resetar(pasta)
    assert exc.value.code == 1
    assert (pasta / nome).is_dir()


def test_reset_recusa_item_estranho_mesmo_com_marcador(demo, tmp_path):
    pasta = tmp_path / "dados"
    pasta.mkdir()
    (pasta / ".aok-demo").write_text("x", encoding="utf-8")
    (pasta / "outro.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit):
        demo.resetar(pasta)
    assert (pasta / "outro.txt").is_file() and (pasta / ".aok-demo").is_file()


def test_reset_aceita_pasta_legitima_com_trava_morta(demo, tmp_path):
    pasta = _pasta_demo(tmp_path)
    (pasta / "demo.db-wal").write_text("x", encoding="utf-8")
    _lock(pasta, _pid_morto())
    demo.resetar(pasta)
    assert not pasta.exists() and not list(tmp_path.glob("*.apagando-*"))


def test_reset_aceita_pasta_que_so_tem_o_marcador(demo, tmp_path):
    pasta = tmp_path / "dados"
    pasta.mkdir()
    (pasta / ".aok-demo").write_text("x", encoding="utf-8")
    demo.resetar(pasta)
    assert not pasta.exists()


def test_dados_apontando_para_arquivo_da_mensagem_clara(demo, tmp_path, capsys):
    arquivo = tmp_path / "arquivo.txt"
    arquivo.write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        demo.main(["--dados", str(arquivo), "--porta", "65000"])
    assert exc.value.code == 1
    assert "é um arquivo" in capsys.readouterr().err
    assert arquivo.read_text(encoding="utf-8") == "x"


def test_reset_recusa_link_simbolico(demo, tmp_path):
    real = _pasta_demo(tmp_path, "real")
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("não foi possível criar link simbólico sem privilégio neste sistema")
    with pytest.raises(SystemExit) as exc:
        demo.resetar(link)
    assert exc.value.code == 1
    assert (real / "demo.db").is_file()


def test_reset_recusa_a_raiz_do_repositorio(demo):
    with pytest.raises(SystemExit):
        demo.resetar(demo.ROOT)
    assert (demo.ROOT / "pyproject.toml").is_file()


def test_dados_isola_banco_e_travas(demo, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    env_a, env_b = demo.base_env(a), demo.base_env(b)
    assert env_a["AOK_DATABASE_URL"] != env_b["AOK_DATABASE_URL"]
    assert env_a["AOK_DATABASE_URL"].startswith("sqlite:///") and "/a/demo.db" in env_a["AOK_DATABASE_URL"]
    assert Path(env_a["AOK_DATA_DIR"]) == (a / "aok_data").resolve()
    assert env_a["AOK_COOKIE_SECURE"] == "false" and "AOK_ADMIN_BOOTSTRAP_KEY" not in env_a
    _lock(a, os.getpid())
    demo.checar_instancia(b)  # outra pasta não é afetada pela trava de a


def test_main_com_instancia_viva_recusa_e_nao_toca_na_pasta(demo, tmp_path):
    pasta = _pasta_demo(tmp_path)
    _lock(pasta, os.getpid())
    for extra in ([], ["--reset"]):
        with pytest.raises(SystemExit) as exc:
            demo.main([*extra, "--dados", str(pasta), "--porta", "65000"])
        assert exc.value.code == 1
    assert (pasta / "demo.db").is_file() and (pasta / "aok_data").is_dir()
    assert (pasta / "pacote" / "relatorio.json").is_file() and (pasta / "demo.lock").is_file()


def test_aviso_gitignore_so_para_pasta_no_repo_fora_do_padrao(demo, tmp_path, capsys):
    demo.aviso_gitignore(tmp_path / "fora")
    demo.aviso_gitignore(demo.ROOT / ".demo")
    demo.aviso_gitignore(demo.ROOT / ".demo-tela")
    assert capsys.readouterr().out == ""
    demo.aviso_gitignore(demo.ROOT / "minha-demo")
    assert ".gitignore" in capsys.readouterr().out
