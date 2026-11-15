import hashlib
import json
import threading

import pytest

from agent_ops_kit.audit import (
    GENESIS_HASH,
    AuditChainError,
    AuditLog,
    anchor,
    canonical,
    compute_hash,
    report,
    verify,
)


def make_log(tmp_path, n=5):
    p = tmp_path / "audit.jsonl"
    log = AuditLog(p)
    for i in range(n):
        log.append("tool_call" if i % 2 else "question", {"i": i, "texto": "olá"})
    return p


def read(p):
    return p.read_text(encoding="utf-8").splitlines()


def write(p, lines):
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def forge(seq, prev, event="x", data=None):
    e = {"seq": seq, "ts": "2026-01-01T00:00:00+00:00", "event": event,
         "data": data or {}, "prev_hash": prev}
    e["hash"] = compute_hash(e)
    return json.dumps(e)


def test_valid_chain_n_events(tmp_path):
    p = make_log(tmp_path, 6)
    res = verify(p)
    assert res.ok and res.n_lines == 6 and res.first_bad_line is None
    first = json.loads(read(p)[0])
    assert first["prev_hash"] == GENESIS_HASH and first["seq"] == 0
    assert list(first) == sorted(first)  # escrita canônica


def test_hash_matches_documented_schema(tmp_path):
    p = make_log(tmp_path, 1)
    e = json.loads(read(p)[0])
    body = {k: e[k] for k in ("seq", "ts", "event", "data", "prev_hash")}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert e["hash"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_reopen_continues_chain(tmp_path):
    p = make_log(tmp_path, 3)
    log = AuditLog(p)
    e = log.append("answer", {"ok": True})
    assert e["seq"] == 3
    assert e["prev_hash"] == json.loads(read(p)[2])["hash"]
    assert verify(p).ok and verify(p).n_lines == 4


def test_empty_file_ok_and_missing_file_error(tmp_path):
    p = tmp_path / "vazio.jsonl"
    p.write_text("")
    res = verify(p)
    assert res.ok and res.n_lines == 0
    assert anchor(p) == GENESIS_HASH
    with pytest.raises(FileNotFoundError, match="não encontrado"):
        verify(tmp_path / "nao_existe.jsonl")


def test_tamper_content_detected_on_right_line(tmp_path):
    p = make_log(tmp_path, 5)
    lines = read(p)
    e = json.loads(lines[2])
    e["data"]["i"] = 999
    lines[2] = json.dumps(e)
    write(p, lines)
    res = verify(p)
    assert not res.ok and res.first_bad_line == 3
    assert res.reason == "hash não confere"


def test_remove_middle_line(tmp_path):
    p = make_log(tmp_path, 5)
    lines = read(p)
    del lines[2]
    write(p, lines)
    res = verify(p)
    assert not res.ok and res.first_bad_line == 3
    assert res.reason == "seq fora de ordem"


def test_swap_order(tmp_path):
    p = make_log(tmp_path, 5)
    lines = read(p)
    lines[1], lines[2] = lines[2], lines[1]
    write(p, lines)
    res = verify(p)
    assert not res.ok and res.first_bad_line == 2


def test_forged_insertion_breaks_following_chain(tmp_path):
    p = make_log(tmp_path, 4)
    lines = read(p)
    prev = json.loads(lines[1])["hash"]
    lines.insert(2, forge(2, prev))  # válida em si; a próxima linha não fecha
    write(p, lines)
    res = verify(p)
    assert not res.ok and res.first_bad_line == 4


def test_forged_insertion_same_seq_chain_prev_mismatch(tmp_path):
    p = make_log(tmp_path, 3)
    lines = read(p)
    # troca a última linha por uma forjada com seq correto mas prev errado
    lines[2] = forge(2, "a" * 64)
    write(p, lines)
    res = verify(p)
    assert res.first_bad_line == 3
    assert res.reason == "prev_hash não confere com a linha anterior"


def test_invalid_and_truncated_line(tmp_path):
    p = make_log(tmp_path, 3)
    lines = read(p)
    lines[1] = lines[1][:20]
    write(p, lines)
    res = verify(p)
    assert not res.ok and res.first_bad_line == 2
    assert res.reason == "linha não é JSON válido"


def test_missing_field(tmp_path):
    p = make_log(tmp_path, 2)
    lines = read(p)
    e = json.loads(lines[1])
    del e["data"]
    lines[1] = json.dumps(e)
    write(p, lines)
    res = verify(p)
    assert res.first_bad_line == 2 and "campo ausente" in res.reason


def test_tail_truncation_needs_anchor(tmp_path):
    p = make_log(tmp_path, 5)
    anc = anchor(p)
    lines = read(p)[:3]
    write(p, lines)
    # sem âncora: NÃO detecta (limitação documentada)
    assert verify(p).ok
    # com âncora: detecta
    res = verify(p, expected_last_hash=anc)
    assert not res.ok and "âncora" in res.reason
    res = verify(p, expected_n=5)
    assert not res.ok and "truncamento" in res.reason
    assert res.first_bad_line is None


def test_anchor_matches_when_intact(tmp_path):
    p = make_log(tmp_path, 4)
    assert verify(p, expected_last_hash=anchor(p), expected_n=4).ok


def test_refuse_to_continue_broken_chain(tmp_path):
    p = make_log(tmp_path, 4)
    lines = read(p)
    e = json.loads(lines[1])
    e["event"] = "outro"
    lines[1] = json.dumps(e)
    write(p, lines)
    before = p.read_text(encoding="utf-8")
    with pytest.raises(AuditChainError, match="linha 2"):
        AuditLog(p)
    assert p.read_text(encoding="utf-8") == before


def test_append_never_rewrites_previous_lines(tmp_path):
    p = make_log(tmp_path, 3)
    before = p.read_bytes()
    AuditLog(p).append("answer")
    assert p.read_bytes().startswith(before)


def test_continue_after_missing_final_newline(tmp_path):
    p = make_log(tmp_path, 2)
    p.write_bytes(p.read_bytes().rstrip(b"\n"))
    AuditLog(p).append("answer")
    assert verify(p).ok and verify(p).n_lines == 3


def test_canonical_hash_stable_across_key_order():
    a = {"seq": 0, "ts": "t", "event": "e", "data": {"a": 1, "b": "ç"},
         "prev_hash": GENESIS_HASH}
    b = {"prev_hash": GENESIS_HASH, "data": {"b": "ç", "a": 1}, "event": "e",
         "ts": "t", "seq": 0}
    assert canonical(a) == canonical(b)
    assert compute_hash(a) == compute_hash(b)
    assert "ç" in canonical(a)  # ensure_ascii=False
    assert compute_hash(a) == compute_hash(a)


def test_non_serializable_data_raises_and_writes_nothing(tmp_path):
    p = tmp_path / "a.jsonl"
    log = AuditLog(p)
    with pytest.raises(TypeError):
        log.append("x", {"obj": object()})
    log.append("ok")
    assert verify(p).ok and verify(p).n_lines == 1


def test_thread_safe_appends(tmp_path):
    p = tmp_path / "t.jsonl"
    log = AuditLog(p)
    ts = [threading.Thread(target=lambda: [log.append("e", {"k": 1}) for _ in range(20)])
          for _ in range(5)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    res = verify(p)
    assert res.ok and res.n_lines == 100


def test_report_intact(tmp_path):
    p = tmp_path / "r.jsonl"
    log = AuditLog(p)
    log.append("question", {"q": "a" * 5000})
    log.append("answer", {"a": "ok | com pipe\nquebra"})
    md = report(p)
    assert md.startswith("# Relatório de auditoria")
    assert "Eventos (linhas): 2" in md
    assert "íntegra" in md
    assert "| question | 1 |" in md
    assert "Linha do tempo" in md
    assert "a" * 200 not in md  # truncado
    assert "caracteres)" in md
    assert "ok \\| com pipe quebra" in md


def test_report_flags_broken_chain(tmp_path):
    p = make_log(tmp_path, 4)
    lines = read(p)
    lines[2] = lines[2].replace('"i":2', '"i":7')
    write(p, lines)
    md = report(p, title="Meu título")
    assert md.startswith("# Meu título")
    assert "QUEBRADA" in md and "linha 3" in md
    assert "hash não confere" in md


def test_report_empty_and_missing(tmp_path):
    p = tmp_path / "e.jsonl"
    p.write_text("")
    assert "Nenhum evento" in report(p)
    with pytest.raises(FileNotFoundError):
        report(tmp_path / "nada.jsonl")


def test_huge_int_and_deep_nesting_lines_do_not_crash(tmp_path):
    for bad in (
        '{"seq":' + "9" * 5000 + "}",
        "[" * 5000 + "]" * 5000,
    ):
        p = make_log(tmp_path, 3)
        lines = read(p)
        lines[1] = bad
        write(p, lines)
        res = verify(p)
        assert not res.ok and res.first_bad_line == 2
        assert res.reason == "linha não é JSON válido"
        assert "QUEBRADA" in report(p)
        with pytest.raises(AuditChainError):
            AuditLog(p)
        p.unlink()


def test_report_truncates_huge_event_and_ts(tmp_path):
    p = tmp_path / "g.jsonl"
    AuditLog(p).append("e" * 5000, {"k": "v"})
    md = report(p)
    assert max(len(line) for line in md.splitlines()) < 300
    assert "caracteres)" in md


def test_report_truncates_huge_seq(tmp_path):
    p = tmp_path / "s.jsonl"
    AuditLog(p).append("e", {"k": "v"})
    entry = json.loads(read(p)[0])
    entry["seq"] = 10**3000  # seq adulterado enorme; a linha continua parseável
    p.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    md = report(p)
    assert max(len(line) for line in md.splitlines()) < 300
