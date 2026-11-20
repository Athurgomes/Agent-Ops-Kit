"""`report verify`: confere offline um pacote gerado por `report build` (ADR-026).

Só lê o relatorio.json e os arquivos de evidência que ele referencia (sob --repo-root). Não usa
rede nem modelo e não confia no autor: os números são recalculados pelas MESMAS funções do build
(`build.eval_numbers`, `build.redteam_numbers`, `policy.evaluate`, `findings.verify`,
`audit.verify`) e comparados com o que está gravado.

Status por checagem: ok, falha (divergência) e nao_verificavel (falta evidência). Só "ok" em todas
as checagens dá exit 0.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from agent_ops_kit import audit_sign, provenance
from agent_ops_kit.config import load_config
from agent_ops_kit.eval import runner
from agent_ops_kit.eval.dataset import load_dataset
from agent_ops_kit.redteam.report import ReportError, _load_attacks, _load_jsonl
from agent_ops_kit.report import build
from agent_ops_kit.report import coverage as coverage_mod
from agent_ops_kit.report import findings as findings_mod
from agent_ops_kit.report import policy as policy_mod

OK, FAIL, NOT_VERIFIABLE = "ok", "falha", "nao_verificavel"
PACKAGE_FILE = "relatorio.json"
SIG_FILE = "relatorio.json.sig"
# Declarações sobre o ambiente do build: não há arquivo que as comprove, então ficam fora do escopo.
NOT_COVERED = (
    (
        "generated_at e o ambiente do build (kit_version, git_commit, git_dirty, python, platform, "
        "command): declarações do autor, sem arquivo que as comprove"
    ),
)
_REQUIRED = ("semaphore", "policy", "indicators", "eval", "redteam", "hashes", "findings", "provenance")
_ERRORS = (
    ReportError, ValueError, KeyError, TypeError, AttributeError, OSError, yaml.YAMLError,
    RecursionError,
)
_MISSING = object()


class PackageError(Exception):
    """Pacote ausente ou ilegível (exit 2)."""


class _Fail(Exception):
    pass


class _NotVerifiable(Exception):
    pass


def _canon(x: object) -> str:
    return json.dumps(x, sort_keys=True, ensure_ascii=False) if x is not _MISSING else "<ausente>"


def _diff(stored: object, fresh: object, path: str = "") -> list[str]:
    """Caminhos pontilhados em que os dois valores divergem (comparação estrita, `0` != `false`)."""
    if isinstance(stored, dict) and isinstance(fresh, dict):
        out: list[str] = []
        for k in sorted(set(stored) | set(fresh)):
            out += _diff(stored.get(k, _MISSING), fresh.get(k, _MISSING), f"{path}.{k}" if path else k)
        return out
    return [] if _canon(stored) == _canon(fresh) else [path or "(raiz)"]


def _compare(label: str, stored: object, fresh: object) -> None:
    diffs = _diff(stored, fresh)
    if not diffs:
        return
    shown = []
    for d in diffs[:3]:
        s = stored if d == "(raiz)" else policy_mod.lookup({"v": stored}, f"v.{d}")
        f = fresh if d == "(raiz)" else policy_mod.lookup({"v": fresh}, f"v.{d}")
        shown.append(f"{d} (gravado {_short(s)}, recalculado {_short(f)})")
    more = f" e mais {len(diffs) - 3}" if len(diffs) > 3 else ""
    raise _Fail(f"{label} diverge: " + "; ".join(shown) + more)


def _short(v: object) -> str:
    text = _canon(v) if v is not None else "null"
    return text if len(text) <= 40 else text[:37] + "..."


def _norm(x: object) -> object:
    return json.loads(json.dumps(x, ensure_ascii=False))


def _aggregate(fails: list[str], unverifiable: list[str], ok_detail: str) -> str:
    """Falha vence; depois não verificável; senão devolve o detalhe do ok."""
    if fails:
        raise _Fail("; ".join(fails))
    if unverifiable:
        raise _NotVerifiable("; ".join(unverifiable))
    return ok_detail


def _run_step(cid: str, label: str, fn) -> dict:
    try:
        status, detail = OK, fn()
    except _Fail as exc:
        status, detail = FAIL, str(exc)
    except _NotVerifiable as exc:
        status, detail = NOT_VERIFIABLE, str(exc)
    except _ERRORS as exc:
        status, detail = FAIL, f"erro ao recalcular: {type(exc).__name__}: {exc}"
    return {"id": cid, "label": label, "status": status, "detail": detail or ""}


class _Verifier:
    def __init__(self, data: dict, package: Path, root: Path, hmac_key: str | None) -> None:
        self.data, self.package, self.root, self.hmac_key = data, package, root, hmac_key
        prov = data["provenance"]
        self.files = prov.get("files") if isinstance(prov.get("files"), dict) else {}
        self.checks: list[dict] = []
        self._cache: dict[str, object] = {}

    # -- infraestrutura --

    def step(self, cid: str, label: str, fn) -> None:
        self.checks.append(_run_step(cid, label, fn))

    def path(self, key: object, what: str) -> Path:
        if not isinstance(key, str) or not key:
            raise _Fail(f"caminho inválido em {what}")
        p = Path(key)
        if p.anchor or ".." in p.parts:
            raise _Fail(f"caminho fora da raiz em {what}: {key}")
        full = self.root / p
        if not full.is_file():
            raise _NotVerifiable(f"arquivo de evidência ausente: {key}")
        return full

    def file(self, role: str) -> Path:
        key = self.files.get(role)
        if key is None:
            raise _NotVerifiable(f"o pacote não referencia o arquivo '{role}' (provenance.files)")
        return self.path(key, role)

    def cached(self, name: str, fn):
        if name not in self._cache:
            try:
                self._cache[name] = fn()
            except (_Fail, _NotVerifiable, *_ERRORS) as exc:
                self._cache[name] = exc
        value = self._cache[name]
        if isinstance(value, BaseException):
            raise value
        return value

    def or_stored(self, name: str, fn, stored):
        """Valor recalculado; se não deu, o gravado (a checagem própria já registra o problema)."""
        try:
            return self.cached(name, fn)
        except (_Fail, _NotVerifiable, *_ERRORS):
            return stored

    # -- recálculo (mesmas funções do build) --

    def eval_state(self) -> dict:
        def run():
            ev = self.data["eval"]
            b, c, seed = ev["baseline"], ev["candidate"], ev["seed"]
            if isinstance(seed, bool) or not isinstance(seed, int):
                raise _Fail("eval.seed não é inteiro")
            dataset = load_dataset(self.file("eval_dataset"))
            records = {v: runner.load_records(self.file(f"eval_answers_{v}")) for v in (b, c)}
            section, scores = build.eval_numbers(dataset, records, b, c, seed)
            raw = json.loads(self.file("eval_manifest").read_text(encoding="utf-8"))
            return {
                "section": section, "scores": scores, "dataset": dataset,
                "manifest": build.manifest_view(raw, [b, c]), "manifest_raw": raw,
            }
        return self.cached("eval", run)

    def redteam_state(self) -> dict:
        def run():
            base = _load_attacks(self.file("redteam_baseline"))
            guard = _load_attacks(self.file("redteam_guardrails"))
            ds = _load_jsonl(self.file("fp_dataset"))
            bn = _load_jsonl(self.file("fp_benign"))
            return {"numbers": build.redteam_numbers(base, guard, ds, bn)}
        return self.cached("redteam", run)

    def audit_state(self) -> dict | None:
        def run():
            au = self.data.get("audit")
            if au is None:
                return None
            log = self.file("audit_log")
            sig = au.get("signature") if isinstance(au, dict) else None
            sig_path = pub = hmac = None
            if isinstance(sig, dict) and sig.get("checked"):
                sig_path = self.file("audit_signature")
                if self.files.get("audit_public_key"):
                    pub = self.file("audit_public_key")
                elif sig.get("algorithm") == "hmac-sha256":
                    if not self.hmac_key:
                        raise _NotVerifiable(
                            "assinatura HMAC: informe a chave em --audit-hmac-key-env"
                        )
                    hmac = self.hmac_key
            return build._audit_section(
                str(log), str(sig_path) if sig_path else None, str(pub) if pub else None, hmac
            )
        return self.cached("audit", run)

    # -- checagens --

    def check_hashes(self) -> str:
        fails, unver = [], []
        hashes = self.data["hashes"]
        ev = self.data["eval"]
        expected = {
            "config", "eval_dataset", "eval_manifest", "redteam_baseline", "redteam_guardrails",
            "fp_dataset", "fp_benign", f"eval_answers_{ev['baseline']}", f"eval_answers_{ev['candidate']}",
        }
        for name in sorted(expected - set(hashes)):
            fails.append(f"hash '{name}' ausente do pacote")
        for name, sha in sorted(hashes.items()):
            try:
                if provenance.sha256_file(self.file(name)) != sha:
                    fails.append(f"{name}: sha256 do arquivo diverge do gravado")
            except _NotVerifiable as exc:
                unver.append(f"{name}: {exc}")
        return _aggregate(fails, unver, f"{len(hashes)} hashes conferem com os arquivos")

    def check_inputs(self) -> str:
        fails, unver = [], []
        inputs = self.data["provenance"]["inputs"]
        if not isinstance(inputs, dict) or not inputs:
            raise _Fail("provenance.inputs ausente ou vazio")
        for key, sha in sorted(inputs.items()):
            try:
                if provenance.sha256_file(self.path(key, "provenance.inputs")) != sha:
                    fails.append(f"{key}: sha256 diverge do gravado")
            except _NotVerifiable as exc:
                unver.append(str(exc))
        return _aggregate(fails, unver, f"{len(inputs)} arquivos de entrada conferem")

    def check_eval(self) -> str:
        st = self.eval_state()
        stored = {k: v for k, v in self.data["eval"].items() if k != "manifest"}
        _compare("eval", stored, _norm(st["section"]))
        s = st["section"]
        return (
            f"média {s['candidate']} - {s['baseline']} = {s['mean_diff']:+.4f}, "
            f"IC 95% [{s['ci95_low']:+.4f}; {s['ci95_high']:+.4f}], p = {s['p_value']:.4f}, "
            f"semente {s['seed']}"
        )

    def check_manifest(self) -> str:
        st = self.eval_state()
        _compare("eval.manifest", self.data["eval"].get("manifest"), _norm(st["manifest"]))
        return "manifesto das respostas confere com o gravado"

    def check_agent(self) -> str:
        st = self.eval_state()
        ev = self.data["eval"]
        config = load_config(str(self.file("config")))
        _compare("agent", self.data["agent"], build.agent_block(config, st["manifest"], ev["candidate"]))
        return "agente (nome, versão do prompt, modelo) confere com agent.yaml e o manifesto"

    def _redteam_part(self, names: tuple[str, ...]) -> None:
        fresh = _norm(self.redteam_state()["numbers"])
        stored = self.data["redteam"]
        _compare("redteam", {k: stored.get(k, _MISSING) for k in names}, {k: fresh[k] for k in names})

    def check_asr(self) -> str:
        self._redteam_part(("asr",))
        t = self.data["redteam"]["asr"]
        parts = []
        for name in ("baseline", "guardrails"):
            r = (t.get(name) or {}).get("total")
            if r:
                parts.append(f"{name}: {r['successes']}/{r['n']} (IC 95% [{r['ci95_low']:.3f}; {r['ci95_high']:.3f}])")
        return "ASR e ICs de Wilson por categoria recalculados; " + "; ".join(parts)

    def check_mcnemar(self) -> str:
        self._redteam_part(("mcnemar",))
        mc = self.data["redteam"]["mcnemar"]
        if not mc.get("applicable"):
            return f"não aplicável (reproduzido): {mc.get('reason')}"
        return f"b = {mc['b']}, c = {mc['c']}, p exato = {mc['p_value']:.3g}"

    def check_fp(self) -> str:
        self._redteam_part(("false_positives",))
        fp = self.data["redteam"]["false_positives"]
        return (
            f"dataset {fp['dataset']['blocked']}/{fp['dataset']['n']}, "
            f"benignas {fp['benign']['blocked']}/{fp['benign']['n']} bloqueadas"
        )

    def check_counts(self) -> str:
        self._redteam_part(("n_attacks", "n_blind_attacks", "runs_per_config", "n_legit_questions"))
        fresh = self.redteam_state()["numbers"]
        if bad := build.not_evaluated_mismatches(fresh, self.data["provenance"].get("executions") or {}):
            raise _Fail("casos não avaliados: " + "; ".join(bad))
        return "contagens (ataques, suíte cega, execuções, perguntas legítimas) conferem"

    def check_policy_sha(self) -> str:
        pol = self.data["policy"]
        loaded = policy_mod.load_policy(self.path(pol.get("path_relative"), "política"))
        if loaded["sha256"] != pol.get("sha256"):
            raise _Fail(
                f"sha256 da política em disco ({loaded['sha256'][:12]}...) difere do gravado "
                f"({str(pol.get('sha256'))[:12]}...): {pol.get('path_relative')}"
            )
        return f"política {loaded['id']} (versão {loaded['version']}): sha256 {loaded['sha256'][:12]}... confere"

    def _view(self) -> dict:
        stored = self.data
        ev_state = self.or_stored("eval", self.eval_state, None)
        rt_state = self.or_stored("redteam", self.redteam_state, None)
        ev = _norm({**ev_state["section"], "manifest": ev_state["manifest"]}) if ev_state else stored["eval"]
        rt = _norm(rt_state["numbers"]) if rt_state else stored["redteam"]
        au = self.or_stored("audit", self.audit_state, stored.get("audit"))
        return {"eval": ev, "redteam": rt, "audit": au, "indicators": build.indicators(ev, rt, au)}

    def check_semaphore(self) -> str:
        pol = self.data["policy"]
        loaded = policy_mod.load_policy(self.path(pol.get("path_relative"), "política"))
        view = self._view()
        sem, results = policy_mod.evaluate(loaded, view)
        block = policy_mod.policy_block(loaded, results)
        block["path_relative"] = pol.get("path_relative")
        _compare("semáforo", self.data["semaphore"], sem)
        _compare("indicadores", self.data["indicators"], view["indicators"])
        _compare("regras da política", pol, block)
        return f"cor {sem['color']} e {len(results)} regras reavaliadas com a política gravada"

    def check_findings(self) -> str:
        found = self.data["findings"]
        if not isinstance(found, list):
            raise _Fail("findings não é uma lista")
        paths: dict[str, Path] = {}
        unver = []
        for f in found:
            for ev in (f.get("evidence"), f.get("baseline_evidence")):
                if ev is None or ev["file"] in paths:
                    continue
                try:
                    paths[ev["file"]] = self.path(ev["file"], f"achado {f.get('id')}")
                except _NotVerifiable as exc:
                    unver.append(str(exc))
        if unver:
            raise _NotVerifiable("; ".join(sorted(set(unver))))
        findings_mod.verify(found, paths)  # linha, sha256 do registro e do arquivo de cada achado
        # Achado omitido ou inventado: recoleta pelos mesmos arquivos e compara a lista inteira.
        st = self.eval_state()
        ev = self.data["eval"]
        ctx = {
            "baseline": ev["baseline"], "candidate": ev["candidate"],
            "baseline_path": self.file(f"eval_answers_{ev['baseline']}"),
            "candidate_path": self.file(f"eval_answers_{ev['candidate']}"),
            "scores_baseline": st["scores"][ev["baseline"]],
            "scores_candidate": st["scores"][ev["candidate"]],
            "categories": {c.id: c.category for c in st["dataset"]},
        }
        fresh, _ = findings_mod.collect(
            redteam={"baseline": self.file("redteam_baseline"), "guardrails": self.file("redteam_guardrails")},
            false_positives={"dataset": self.file("fp_dataset"), "benign": self.file("fp_benign")},
            eval_ctx=ctx, base=self.root,
        )
        if _canon(found) != _canon(_norm(fresh)):
            raise _Fail(f"a lista de achados difere da recoletada ({len(found)} gravados, {len(fresh)} recalculados)")
        return f"{len(found)} achados: linha e sha256 de cada evidência conferem; lista completa reproduzida"

    def check_coverage(self) -> str:
        stored = self.data.get("coverage")
        if stored is None:
            raise _NotVerifiable("o pacote não traz o bloco coverage (gerado antes da ADR-027)")
        meta = stored.get("map") if isinstance(stored, dict) else None
        if not isinstance(meta, dict):
            raise _Fail("coverage.map ausente ou inválido")
        try:
            cmap = coverage_mod.load_map(self.path(meta.get("path_relative"), "mapa de cobertura"))
        except coverage_mod.CoverageError as exc:
            raise _Fail(str(exc)) from exc
        if cmap["sha256"] != meta.get("sha256"):
            raise _Fail(
                f"sha256 do mapa em disco ({cmap['sha256'][:12]}...) difere do gravado "
                f"({str(meta.get('sha256'))[:12]}...): {meta.get('path_relative')}"
            )
        fresh = coverage_mod.compute(cmap, self.redteam_state()["numbers"])
        fresh["map"]["path_relative"] = meta.get("path_relative")
        _compare("coverage", stored, _norm(fresh))
        by = {}
        for c in fresh["categories"]:
            by[c["status"]] = by.get(c["status"], 0) + 1
        return "mapa OWASP LLM 2025 recalculado: " + ", ".join(f"{n} {k}" for k, n in sorted(by.items()))

    def check_audit(self) -> str:
        stored = self.data.get("audit")
        if stored is None:
            return "log de auditoria não informado no pacote: nada a verificar (a regra no_audit da política já o considera)"
        fresh = self.audit_state()
        _compare("auditoria", stored, fresh)
        sig = fresh.get("signature")
        sig_txt = ""
        if isinstance(sig, dict) and sig.get("checked"):
            sig_txt = f", assinatura {sig.get('algorithm')} {'válida' if sig.get('ok') else 'INVÁLIDA'}"
        chain = "íntegra" if fresh["ok"] else f"QUEBRADA ({fresh['reason']})"
        return f"cadeia {chain} ({fresh['n_events']} eventos, âncora {str(fresh['anchor'])[:12]}...){sig_txt}"

    def check_executions(self) -> str:
        prov = self.data["provenance"]
        if not self.files:
            raise _NotVerifiable("o pacote não referencia os sidecars (provenance.files)")
        st = self.eval_state()
        variants = [self.data["eval"]["baseline"], self.data["eval"]["candidate"]]

        def meta(role: str, label: str) -> dict | None:
            return build._load_meta(self.file(role), label) if role in self.files else None

        metas = {
            "baseline": meta("redteam_baseline_meta", "baseline"),
            "guardrails": meta("redteam_guardrails_meta", "guardrails"),
        }
        fp_meta = meta("fp_meta", "falsos positivos")
        fresh_exec = {
            "eval": {v: build._pick(st["manifest_raw"][v], build._EXEC_KEYS, self.root) for v in variants},
            "redteam": {
                **{k: build._pick(m, build._RT_META_KEYS, self.root) for k, m in metas.items()},
                "false_positives": build._pick(fp_meta, build._FP_META_KEYS, self.root),
            },
        }
        fresh_seeds = {
            "eval_ab_bootstrap": self.data["eval"]["seed"],
            "eval_generation": {v: st["manifest"][v]["seed"] for v in variants},
            "redteam": {k: (m or {}).get("seed") for k, m in metas.items()},
            "false_positives": (fp_meta or {}).get("seed"),
        }
        _compare("provenance.executions", prov.get("executions"), _norm(fresh_exec))
        _compare("provenance.seeds", prov.get("seeds"), _norm(fresh_seeds))
        return "execuções (modelo, digest, commit da execução) e sementes conferem com manifesto e sidecars"

    def check_limitations(self) -> str:
        _compare("limitations", {"v": self.data.get("limitations")}, {"v": _norm(build.limitations(self.data))})
        return "limitações e ressalvas estatísticas reproduzidas dos dados do pacote"

    def check_previous(self) -> str:
        prev = self.data["previous"]
        after = {r["metric"]: r["after"] for r in prev["rows"]}
        _compare("comparação anterior (coluna 'depois')", after, build.summary_values(self.data))
        return "coluna 'depois' reproduzida; a coluna 'antes' vem de outro relatório, fora do pacote (informativa)"

    def check_render(self) -> str:
        from agent_ops_kit.report import render

        blocks = render.build_blocks(self.data)
        title = f"Relatório de teste do agente {self.data['agent']['name']}"
        fresh = {"relatorio.md": render.to_markdown(blocks), "relatorio.html": render.to_html(blocks, title)}
        bad = []
        for name, text in fresh.items():
            f = self.package / name
            if not f.is_file():
                raise _NotVerifiable(f"{name} ausente do pacote")
            if f.read_text(encoding="utf-8") != text:
                bad.append(name)
        if bad:
            raise _Fail(f"{' e '.join(bad)} não correspondem à renderização do relatorio.json")
        return "relatorio.md e relatorio.html são a renderização exata do relatorio.json"

    def run(self) -> list[dict]:
        for cid, label, fn in (
            ("hashes", "hashes dos arquivos de evidência (bloco hashes)", self.check_hashes),
            ("inputs", "hashes das entradas (provenance.inputs)", self.check_inputs),
            ("eval", "eval: médias, IC 95%, p-valor (recalculado)", self.check_eval),
            ("manifest", "eval: manifesto das respostas", self.check_manifest),
            ("agent", "agente (agent.yaml + manifesto)", self.check_agent),
            ("asr", "red team: ASR e ICs de Wilson (recalculado)", self.check_asr),
            ("mcnemar", "red team: McNemar exato (recalculado)", self.check_mcnemar),
            ("false_positives", "falsos positivos e ICs (recalculado)", self.check_fp),
            ("counts", "red team: contagens", self.check_counts),
            ("policy_sha", "política: sha256 em disco = gravado", self.check_policy_sha),
            ("semaphore", "semáforo: cor, indicadores e regras reavaliados", self.check_semaphore),
            ("findings", "achados: evidência por linha e lista completa", self.check_findings),
            ("coverage", "cobertura OWASP LLM Top 10 (mapa e números)", self.check_coverage),
            ("audit", "auditoria: cadeia de hashes e assinatura", self.check_audit),
            ("executions", "execuções e sementes (manifesto e sidecars)", self.check_executions),
            ("limitations", "limitações e ressalvas estatísticas", self.check_limitations),
            ("render", "relatorio.md e relatorio.html = renderização do json", self.check_render),
        ):
            self.step(cid, label, fn)
        if self.data.get("previous") is not None:
            self.step("previous", "comparação com o relatório anterior", self.check_previous)
        return self.checks


def load_package(package: str | Path) -> dict:
    """Lê o relatorio.json do pacote. Levanta PackageError se ausente, ilegível ou fora do formato."""
    p = Path(package) / PACKAGE_FILE
    if not p.is_file():
        raise PackageError(f"{PACKAGE_FILE} não encontrado em {package}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        raise PackageError(f"{p} ilegível ou JSON inválido: {exc}") from exc
    if not isinstance(data, dict):
        raise PackageError(f"{p} não é um objeto JSON")
    return data


def _structure(data: dict) -> str:
    missing = [k for k in _REQUIRED if k not in data]
    if missing:
        raise _Fail(f"campos obrigatórios ausentes: {', '.join(missing)}")
    if data.get("schema_version") != build.SCHEMA_VERSION:
        raise _Fail(f"schema_version {data.get('schema_version')!r} não suportado (esperado {build.SCHEMA_VERSION})")
    shape = {
        "semaphore": dict, "policy": dict, "indicators": dict, "eval": dict, "redteam": dict,
        "hashes": dict, "findings": list, "provenance": dict,
    }
    bad = [k for k, t in shape.items() if not isinstance(data[k], t)]
    if bad:
        raise _Fail(f"tipo inválido em: {', '.join(bad)}")
    for k, keys in (
        ("eval", ("baseline", "candidate", "seed")), ("policy", ("path_relative", "sha256")),
        ("provenance", ("inputs",)),
    ):
        absent = [x for x in keys if x not in data[k]]
        if absent:
            raise _Fail(f"{k}: campos ausentes: {', '.join(absent)}")
    return f"schema_version {data['schema_version']} e campos obrigatórios presentes"


def _check_signature(package: Path, public_key: str | Path | None) -> str:
    """Confere relatorio.json.sig contra os bytes exatos do relatorio.json (ADR-029)."""
    sig_path = package / SIG_FILE
    if not sig_path.is_file():
        raise _Fail("pacote sem assinatura (exigida por --require-signature)")
    try:
        receipt = json.loads(sig_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        raise _Fail(f"{SIG_FILE} ilegível ou JSON inválido") from None
    fp = receipt.get("key_fingerprint") if isinstance(receipt, dict) else None
    if public_key is None:
        raise _NotVerifiable(f"assinada (chave {fp}), mas sem --public-key para verificar")
    try:
        pub = Path(public_key).read_bytes()
    except OSError:
        raise _Fail("chave pública ilegível") from None
    res = audit_sign.verify_bytes((package / PACKAGE_FILE).read_bytes(), receipt, pub)
    if not res.ok:
        raise _Fail(res.reason or "assinatura inválida")
    return f"assinatura Ed25519 válida (chave {res.key_fingerprint})"


def verify_package(
    package: str | Path,
    repo_root: str | Path = ".",
    hmac_key: str | None = None,
    public_key: str | Path | None = None,
    require_signature: bool = False,
) -> dict:
    """Resultado da verificação: {ok, package, checks, summary, signed, not_covered}. Determinístico."""
    data = load_package(package)
    root = Path(repo_root)
    if not root.is_dir():
        raise PackageError(f"--repo-root não é uma pasta: {repo_root}")
    checks = [_run_step("structure", "estrutura mínima do relatorio.json", lambda: _structure(data))]
    if checks[0]["status"] == OK:
        checks += _Verifier(data, Path(package), root, hmac_key).run()
    signed = (Path(package) / SIG_FILE).is_file()
    if signed or require_signature:  # sem .sig e sem exigência: só informativo, não entra nas checagens
        checks.append(_run_step("signature", "assinatura do relatorio.json", lambda: _check_signature(Path(package), public_key)))
    summary = {s: sum(c["status"] == s for c in checks) for s in (OK, FAIL, NOT_VERIFIABLE)}
    return {
        "ok": summary[FAIL] == 0 and summary[NOT_VERIFIABLE] == 0,
        "package": Path(package).as_posix(),
        "checks": checks,
        "summary": summary,
        "signed": signed,
        "not_covered": list(NOT_COVERED),
    }


_LABEL = {OK: "ok", FAIL: "FALHA", NOT_VERIFIABLE: "NÃO VERIFICÁVEL"}


def format_table(result: dict) -> str:
    lines = [f"Verificação do pacote {result['package']}/", ""]
    for c in result["checks"]:
        lines.append(f"[{_LABEL[c['status']]}] {c['label']}")
        if c["detail"]:
            lines.append(f"    {c['detail']}")
    s = result["summary"]
    if not result.get("signed"):
        lines += ["", "Assinatura: não assinado (informativo; use --require-signature para exigir)"]
    lines += [
        "",
        (
            f"Resultado: {s[OK]} ok, {s[FAIL]} falha(s), {s[NOT_VERIFIABLE]} não verificável(is) "
            f"-> {'ÍNTEGRO' if result['ok'] else 'NÃO CONFIRMADO'}"
        ),
        "Fora do escopo (não há evidência que o comprove):",
        *[f"  - {t}" for t in result["not_covered"]],
    ]
    return "\n".join(lines)
