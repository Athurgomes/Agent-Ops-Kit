"""Indexador do agente RAG de referência: corpus markdown -> chunks -> Chroma."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

EmbedFn = Callable[[list[str]], list[list[float]]]

EMBED_MODEL = "nomic-embed-text"
COLLECTION = "lumina_docs"
CORPUS_DIR = Path(__file__).resolve().parents[1] / "corpus"
PERSIST_DIR = Path(__file__).resolve().parents[1] / "chroma"


def ollama_embed(texts: list[str]) -> list[list[float]]:
    """Embeddings via Ollama local (nomic-embed-text)."""
    import ollama

    return [list(e) for e in ollama.embed(model=EMBED_MODEL, input=texts)["embeddings"]]


def chunk_text(text: str, max_chars: int = 800, overlap: int = 100) -> list[str]:
    """Agrupa parágrafos até max_chars; cada chunk repete os últimos `overlap` chars do anterior.

    Parágrafos maiores que max_chars são cortados em janelas de tamanho fixo com sobreposição.
    """
    paras: list[str] = []
    for p in (p.strip() for p in text.split("\n\n")):
        if not p:
            continue
        step = max_chars - overlap
        if len(p) <= max_chars:
            paras.append(p)
        else:
            paras.extend(p[i : i + max_chars] for i in range(0, len(p), step))

    chunks: list[str] = []
    cur = ""
    for p in paras:
        if cur and len(cur) + len(p) + 2 > max_chars:
            chunks.append(cur)
            cur = cur[-overlap:] + "\n\n" + p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    return chunks


def build_index(
    corpus_dir: str | Path = CORPUS_DIR,
    persist_dir: str | Path = PERSIST_DIR,
    embed_fn: EmbedFn = ollama_embed,
    max_chars: int = 800,
    overlap: int = 100,
) -> int:
    """Indexa todos os .md do corpus (recria a coleção). Retorna o número de chunks."""
    import chromadb

    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict] = []
    for path in sorted(Path(corpus_dir).glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for i, chunk in enumerate(chunk_text(text, max_chars, overlap)):
            ids.append(f"{path.name}#{i}")
            docs.append(chunk)
            metas.append({"source": path.name, "chunk": i})

    client = chromadb.PersistentClient(path=str(persist_dir))
    if COLLECTION in [c if isinstance(c, str) else c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION)
    col = client.create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
    if docs:
        col.add(ids=ids, documents=docs, embeddings=embed_fn(docs), metadatas=metas)
    return len(docs)


def query_index(
    question: str,
    k: int = 3,
    persist_dir: str | Path = PERSIST_DIR,
    embed_fn: EmbedFn = ollama_embed,
) -> list[dict]:
    """Retorna os k chunks mais próximos: [{"text", "source", "distance"}]."""
    import chromadb

    col = chromadb.PersistentClient(path=str(persist_dir)).get_collection(COLLECTION)
    res = col.query(query_embeddings=embed_fn([question]), n_results=k)
    return [
        {"text": t, "source": m["source"], "distance": d}
        for t, m, d in zip(res["documents"][0], res["metadatas"][0], res["distances"][0])
    ]


if __name__ == "__main__":
    print(f"{build_index()} chunks indexados em {PERSIST_DIR}")
