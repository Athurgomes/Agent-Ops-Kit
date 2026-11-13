"""Carregamento das variantes de prompt (evals/prompts/<nome>.md)."""

from pathlib import Path

DEFAULT_PROMPTS_DIR = "evals/prompts"


def load_prompt(name: str, prompts_dir: str | Path = DEFAULT_PROMPTS_DIR) -> str:
    """Devolve o texto da variante `name`. Levanta FileNotFoundError se não existir."""
    if Path(name).name != name or not name:
        raise ValueError(f"nome de variante inválido: {name!r}")
    path = Path(prompts_dir) / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"variante de prompt não encontrada: {path}")
    return path.read_text(encoding="utf-8").strip() + "\n"
