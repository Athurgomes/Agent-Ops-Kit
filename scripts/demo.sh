#!/usr/bin/env bash
# Demo do agent-ops-kit (roteiro da gravação), reproduzível e rápido.
#
# ATENÇÃO: este demo NÃO chama o modelo. Ele usa RESPOSTAS GRAVADAS
# (evals/answers/ e redteam/results/, geradas com semente fixa 42); os números que
# aparecem na tela vêm dessas execuções gravadas, não de uma execução ao vivo.
# O log de auditoria da cena 4 é fictício e usa relógio fixo, então a saída é
# sempre a mesma.
#
# Uso (na raiz do repositório ou fora dela):
#   bash scripts/demo.sh            roda tudo sem pausas
#   DEMO_PAUSE=1 bash scripts/demo.sh   pausa (Enter) entre as cenas
#   bash scripts/demo.sh --help     mostra esta ajuda
#
# Requisitos: Python 3.11+ com o pacote instalado (pip install -e .). Usa `aok` se
# estiver no PATH; senão, `python -m agent_ops_kit.cli`. Define PYTHON para escolher
# o interpretador. Tudo o que é gerado fica em reports/demo/ (ignorado pelo git).
set -euo pipefail

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

cd "$(dirname "$0")/.."
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8

PY="${PYTHON:-python}"
command -v "$PY" >/dev/null 2>&1 || PY=python3
if command -v aok >/dev/null 2>&1; then
  AOK=(aok)
else
  AOK=("$PY" -m agent_ops_kit.cli)
fi

WORK="reports/demo"
rm -rf "$WORK"
mkdir -p "$WORK"

scene() {
  echo
  echo "=== $1 ==="
  if [ "${DEMO_PAUSE:-0}" = "1" ]; then
    read -r -p "(Enter para continuar) " _ || true
  fi
}

echo "Demo do agent-ops-kit: usa respostas gravadas (não chama o modelo)."

scene "1/5 Incluir o agente: aok new meu-agente"
"${AOK[@]}" new meu-agente --dir "$WORK/agentes"

scene "2/5 Testar a qualidade: aok eval --baseline v1 --candidate v2"
"${AOK[@]}" eval --baseline v1 --candidate v2 --reuse --summary --report "$WORK/eval.md"

scene "3/5 Testar a segurança: aok redteam report"
"${AOK[@]}" redteam report \
  --baseline redteam/results/baseline.jsonl \
  --guardrails redteam/results/guardrails.jsonl \
  --fp-dir redteam/results --summary --output "$WORK/redteam.md"

scene "4/5 Relatório de auditoria e prova de integridade"
echo "Os eventos deste log são FICTÍCIOS: gerados para a demonstração, com relógio fixo."
"$PY" - "$WORK/auditoria.jsonl" <<'PY'
import datetime as dt
import sys

from agent_ops_kit import audit


class Clock(dt.datetime):  # relógio fixo: hashes e horas iguais em toda execução
    t = dt.datetime(2026, 1, 15, 9, 0, 0, tzinfo=dt.UTC)

    @classmethod
    def now(cls, tz=None):
        cls.t += dt.timedelta(seconds=7)
        return cls.t


audit.datetime = Clock
log = audit.AuditLog(sys.argv[1])
log.append("session_start", {"agent": "meu-agente"})
log.append("question", {"text": "Quantos dias de férias a Aurora Papéis concede?"})
log.append("guardrail", {"stage": "input", "reasons": []})
log.append("tool_call", {"name": "search_docs", "arguments": {"query": "férias"}, "status": "ok"})
log.append("answer", {"text": "30 dias corridos por ano.", "blocked_by": None})
log.append("session_end", {"status": "ok"})
PY
"${AOK[@]}" audit report "$WORK/auditoria.jsonl" --title "Relatório de auditoria (demo)"
echo
"${AOK[@]}" audit verify "$WORK/auditoria.jsonl"

scene "5/5 Adulterar uma linha de uma cópia e verificar de novo"
"$PY" - "$WORK/auditoria.jsonl" "$WORK/auditoria_adulterada.jsonl" <<'PY'
import sys

src, dst = sys.argv[1:3]
lines = open(src, encoding="utf-8").read().splitlines()
assert "30 dias" in lines[4]
lines[4] = lines[4].replace("30 dias", "45 dias")  # linha 5: a resposta
open(dst, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
print("Cópia adulterada: a resposta da linha 5 foi trocada de '30 dias' para '45 dias'.")
PY
"${AOK[@]}" audit verify "$WORK/auditoria_adulterada.jsonl" || echo "(código de saída: $?)"

echo
echo "Fim do demo. Relatórios completos em $WORK/ (ignorado pelo git)."
