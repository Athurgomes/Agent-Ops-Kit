import hashlib
import itertools
import math

import pytest

pytest.importorskip("chromadb")

from examples.rag_agent.indexer import CORPUS_DIR, build_index, chunk_text, query_index

DIM = 256


def fake_embed(texts: list[str]) -> list[list[float]]:
    """Bag-of-words hashing determinístico, normalizado (sem Ollama)."""
    out = []
    for t in texts:
        v = [0.0] * DIM
        for w in t.lower().split():
            w = w.strip(".,:;()#-*|")
            if len(w) > 3:
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


def test_chunk_short_text_is_single_chunk():
    assert chunk_text("um\n\ndois") == ["um\n\ndois"]


def test_chunk_respects_size_and_overlap():
    paras = [f"paragrafo{i} " + "x" * 90 for i in range(10)]
    chunks = chunk_text("\n\n".join(paras), max_chars=250, overlap=30)
    assert len(chunks) > 1
    assert all(len(c) <= 250 + 30 for c in chunks)
    # sobreposição: o início de cada chunk repete o fim do anterior
    for prev, nxt in itertools.pairwise(chunks):
        assert nxt.startswith(prev[-30:])


def test_chunk_splits_long_paragraph():
    chunks = chunk_text("a" * 1000, max_chars=300, overlap=50)
    assert len(chunks) >= 4
    assert all(len(c) <= 300 + 50 + 2 for c in chunks)


def test_chunk_empty():
    assert chunk_text("  \n\n ") == []


@pytest.fixture(scope="module")
def index_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("chroma")
    build_index(CORPUS_DIR, d, embed_fn=fake_embed)
    return d


def test_build_index_counts_and_source(index_dir):
    import chromadb

    from examples.rag_agent.indexer import COLLECTION

    col = chromadb.PersistentClient(path=str(index_dir)).get_collection(COLLECTION)
    data = col.get(include=["metadatas"])
    sources = {m["source"] for m in data["metadatas"]}
    assert sources == {p.name for p in CORPUS_DIR.glob("*.md")}
    assert len(sources) == 15
    assert col.count() >= 15


def test_build_index_is_idempotent(tmp_path):
    n1 = build_index(CORPUS_DIR, tmp_path, embed_fn=fake_embed)
    n2 = build_index(CORPUS_DIR, tmp_path, embed_fn=fake_embed)
    assert n1 == n2


def test_query_returns_expected_doc(index_dir):
    res = query_index(
        "Quantos dias de férias o colaborador tem direito?",
        k=3,
        persist_dir=index_dir,
        embed_fn=fake_embed,
    )
    assert len(res) == 3
    assert res[0]["source"] == "01_politica_de_ferias.md"
    assert {"text", "source", "distance"} <= res[0].keys()


def test_query_other_topic(index_dir):
    res = query_index(
        "Qual o SLA de primeira resposta e resolução para prioridade crítica P1?",
        k=3,
        persist_dir=index_dir,
        embed_fn=fake_embed,
    )
    assert "05_sla_atendimento.md" in [r["source"] for r in res]
