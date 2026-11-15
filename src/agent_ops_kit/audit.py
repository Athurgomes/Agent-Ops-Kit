"""Log de auditoria append-only com hash encadeado (somente biblioteca padrão).

Esquema (uma linha JSON por evento, UTF-8, terminada em "\\n"):

    {"seq": 0, "ts": "2026-01-01T12:00:00.000000+00:00", "event": "question",
     "data": {...}, "prev_hash": "<64 hex>", "hash": "<64 hex>"}

- ``seq``: 0, 1, 2, ... sem lacunas.
- ``ts``: ISO-8601 em UTC.
- ``event``: tipo livre ("question", "tool_call", "guardrail", "answer", ...).
- ``data``: dict serializável em JSON.
- ``prev_hash``: ``hash`` da linha anterior; na 1ª linha é a gênese ``"0" * 64``.
- ``hash``: sha256 (hex) da serialização canônica de ``seq, ts, event, data,
  prev_hash`` (tudo menos ``hash``), com
  ``json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)``
  codificada em UTF-8.

O que a verificação detecta: edição do conteúdo de uma linha, remoção ou troca
de ordem de linhas no MEIO da cadeia, inserção de linha forjada (o hash
recalculado só da linha inserida não fecha a cadeia seguinte) e linha
truncada/inválida. Aponta a PRIMEIRA linha com problema.

LIMITAÇÕES (ver ADR-004 em docs/decisoes.md). Este log NÃO é imutável:
- não detecta truncamento do FIM do arquivo (apagar as últimas linhas deixa uma
  cadeia válida mais curta);
- não detecta a reescrita completa da cadeia por quem tem acesso de escrita ao
  arquivo e recalcula todos os hashes.
Mitigação parcial e opcional para o truncamento: ``anchor(path)`` devolve o
último hash para o operador guardar FORA do arquivo (ex.: no CI ou num commit),
e ``verify(path, expected_last_hash=..., expected_n=...)`` confere essa âncora.

Escrita: thread-safe dentro de um processo (lock); não há coordenação entre
processos escrevendo no mesmo arquivo. O relatório reflete apenas o que a
aplicação registrou no log; o módulo não coleta nem filtra dados por conta própria.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64
_FIELDS = ("seq", "ts", "event", "data", "prev_hash", "hash")
_HASHED_FIELDS = ("seq", "ts", "event", "data", "prev_hash")


class AuditChainError(RuntimeError):
    """A cadeia do log está quebrada; não é seguro continuar."""


@dataclass
class VerifyResult:
    ok: bool
    n_lines: int
    first_bad_line: int | None = None  # 1-based
    reason: str | None = None
    last_hash: str | None = None  # hash da última linha (gênese se vazio)


def canonical(obj: dict[str, Any]) -> str:
    """Serialização canônica usada no cálculo do hash."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(entry: dict[str, Any]) -> str:
    """sha256 hex de seq/ts/event/data/prev_hash da entrada (ignora `hash`)."""
    body = {k: entry[k] for k in _HASHED_FIELDS}
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def _check_entry(obj: Any) -> str | None:
    """Devolve o motivo se a estrutura da linha for inválida."""
    if not isinstance(obj, dict):
        return "linha não é JSON válido"
    for k in _FIELDS:
        if k not in obj:
            return "campo ausente"
    if set(obj) - set(_FIELDS):
        return "campo inesperado"
    if (
        isinstance(obj["seq"], bool)
        or not isinstance(obj["seq"], int)
        or not isinstance(obj["ts"], str)
        or not isinstance(obj["event"], str)
        or not isinstance(obj["data"], dict)
        or not isinstance(obj["prev_hash"], str)
        or not isinstance(obj["hash"], str)
    ):
        return "campo ausente ou inválido (tipo incorreto)"
    return None


def _read_lines(path: Path) -> list[Any]:
    """Lê o arquivo; cada item é o objeto JSON da linha ou None se inválida."""
    if not path.is_file():
        raise FileNotFoundError(f"arquivo de auditoria não encontrado: {path}")
    out = path.read_bytes().split(b"\n")
    if out and out[-1] == b"":  # terminador final do arquivo
        out.pop()
    parsed: list[Any] = []
    for raw in out:
        try:
            parsed.append(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, ValueError, RecursionError):
            parsed.append(None)
    return parsed


def verify(
    path: str | Path,
    expected_last_hash: str | None = None,
    expected_n: int | None = None,
) -> VerifyResult:
    """Recalcula a cadeia do início e aponta a primeira linha adulterada.

    Arquivo vazio é íntegro (0 linhas); arquivo inexistente levanta
    FileNotFoundError. ``expected_last_hash`` e ``expected_n`` (opcionais)
    conferem a âncora guardada fora do arquivo e detectam truncamento do fim.
    """
    lines = _read_lines(Path(path))
    prev = GENESIS_HASH
    for i, obj in enumerate(lines):
        n = i + 1

        def bad(reason: str, n: int = n) -> VerifyResult:
            return VerifyResult(False, len(lines), n, reason)

        if obj is None:
            return bad("linha não é JSON válido")
        problem = _check_entry(obj)
        if problem:
            return bad(problem)
        if obj["seq"] != i:
            return bad("seq fora de ordem")
        if obj["prev_hash"] != prev:
            return bad("prev_hash não confere com a linha anterior")
        if compute_hash(obj) != obj["hash"]:
            return bad("hash não confere")
        prev = obj["hash"]

    n_lines = len(lines)
    if expected_n is not None and n_lines != expected_n:
        return VerifyResult(
            False,
            n_lines,
            None,
            f"número de eventos ({n_lines}) difere do esperado ({expected_n}): "
            "possível truncamento ou acréscimo após a âncora",
            prev,
        )
    if expected_last_hash is not None and prev != expected_last_hash:
        return VerifyResult(
            False,
            n_lines,
            None,
            "último hash não confere com a âncora informada",
            prev,
        )
    return VerifyResult(True, n_lines, None, None, prev)


def anchor(path: str | Path) -> str:
    """Último hash da cadeia (gênese se vazio), para guardar fora do arquivo."""
    res = verify(path)
    if not res.ok:
        raise AuditChainError(
            f"cadeia quebrada na linha {res.first_bad_line}: {res.reason}"
        )
    return res.last_hash or GENESIS_HASH


class AuditLog:
    """Log append-only. Ao abrir arquivo existente, valida e continua a cadeia."""

    def __init__(self, path: str | Path, fsync: bool = False) -> None:
        self.path = Path(path)
        self.fsync = fsync
        self._lock = threading.Lock()
        self._seq = 0
        self._last_hash = GENESIS_HASH
        self._needs_newline = False
        if self.path.exists() and self.path.stat().st_size > 0:
            res = verify(self.path)
            if not res.ok:
                raise AuditChainError(
                    f"cadeia de auditoria quebrada na linha {res.first_bad_line} "
                    f"({res.reason}); recusando continuar {self.path}"
                )
            self._seq = res.n_lines
            self._last_hash = res.last_hash or GENESIS_HASH
            with self.path.open("rb") as f:
                f.seek(-1, os.SEEK_END)
                self._needs_newline = f.read(1) != b"\n"
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Acrescenta um evento e devolve a entrada escrita."""
        with self._lock:
            entry: dict[str, Any] = {
                "seq": self._seq,
                "ts": datetime.now(UTC).isoformat(timespec="microseconds"),
                "event": event,
                "data": data if data is not None else {},
                "prev_hash": self._last_hash,
            }
            entry["hash"] = compute_hash(entry)
            payload = (canonical(entry) + "\n").encode("utf-8")  # erro antes de escrever
            if self._needs_newline:
                payload = b"\n" + payload
            with self.path.open("ab") as f:
                f.write(payload)
                f.flush()
                if self.fsync:
                    os.fsync(f.fileno())
            self._needs_newline = False
            self._seq += 1
            self._last_hash = entry["hash"]
            return entry


def _short(value: Any, limit: int = 60) -> str:
    text = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), default=str
    )
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit] + f"… (+{len(text) - limit} caracteres)"
    return text


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _summarize(data: Any, limit: int = 160) -> str:
    if not isinstance(data, dict) or not data:
        return ""
    text = ", ".join(f"{k}={_short(v)}" for k, v in data.items())
    return text if len(text) <= limit else text[:limit] + "…"


def report(
    path: str | Path,
    title: str = "Relatório de auditoria",
    max_rows: int = 500,
) -> str:
    """Relatório em markdown (pt-BR): resumo, verificação da cadeia e linha do tempo.

    Valores longos são truncados na linha do tempo. O conteúdo reflete o que a
    aplicação registrou no log.
    """
    path = Path(path)
    res = verify(path)
    lines = _read_lines(path)
    valid = [o for o in lines if o is not None and _check_entry(o) is None]

    counts: dict[str, int] = {}
    for o in valid:
        counts[o["event"]] = counts.get(o["event"], 0) + 1

    out = [f"# {title}", "", "## Resumo", ""]
    out.append(f"- Arquivo: `{path.name}`")
    out.append(f"- Eventos (linhas): {len(lines)}")
    if valid:
        out.append(
            f"- Intervalo: {_short(valid[0]['ts'], 40)} a {_short(valid[-1]['ts'], 40)}"
        )
    else:
        out.append("- Intervalo: sem eventos")
    if res.ok:
        out.append("- Cadeia de hashes: **íntegra**")
    else:
        out.append(
            f"- Cadeia de hashes: **QUEBRADA** na linha {res.first_bad_line}: {res.reason}"
        )
    if counts:
        out += ["", "### Eventos por tipo", "", "| Evento | Quantidade |", "|---|---|"]
        for name, c in sorted(counts.items()):
            out.append(f"| {_cell(_short(name, 40))} | {c} |")

    out += ["", "## Linha do tempo", ""]
    if not lines:
        out.append("Nenhum evento registrado.")
    else:
        out += ["| seq | Hora | Evento | Dados |", "|---|---|---|---|"]
        for n, o in enumerate(lines[:max_rows], start=1):
            if o is None or _check_entry(o) is not None:
                out.append(f"| (linha {n}) | - | inválida | - |")
                continue
            out.append(
                f"| {_cell(_short(o['seq'], 40))} | {_cell(_short(o['ts'], 40))} | {_cell(_short(o['event'], 40))} "
                f"| {_cell(_summarize(o['data']))} |"
            )
        if len(lines) > max_rows:
            out += ["", f"_Mostrando os primeiros {max_rows} de {len(lines)} eventos._"]

    out += [
        "",
        "## Observações",
        "",
        "- O relatório reflete o que a aplicação registrou no log; valores longos são truncados.",
        (
            "- O hash encadeado detecta alteração e remoção no meio da cadeia, mas não "
            "truncamento do fim nem reescrita completa por quem tem acesso de escrita "
            "(use a âncora, `anchor`, guardada fora do arquivo). Ver ADR-004."
        ),
        "",
    ]
    return "\n".join(out)
