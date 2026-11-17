"""Approved-document RAG: ChromaDB (embedded, persistent) + fastembed (ONNX, no PyTorch).

Only APPROVED, CURRENT, LATEST-VERSION documents are embedded. Drafts, superseded
versions and expired documents are recorded in PostgreSQL but never reach the vector
store, so they can never be retrieved. No patient transcripts are ever stored here.
RAG never decides triage urgency.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.config import Settings

log = logging.getLogger("rag")

MODEL_NAME = "BAAI/bge-small-en-v1.5"

_STOP = {
    "a", "an", "the", "is", "are", "do", "does", "you", "your", "i", "me", "my", "we", "our", "can", "could", "what", "which", "who", "how",
    "where", "when", "to", "of", "for", "on", "in", "at", "and", "or", "about", "tell", "have", "any", "there", "it", "this", "that", "please",
    "need", "know", "want", "wanted", "ask", "information", "hospital", "have", "get", "give", "hello", "hi", "hania", "um", "sorry", "listen",
    "quickly", "excuse", "right", "now", "today", "urgently", "immediately", "be", "with", "if", "so", "us", "from",
}
_SUFFIXES = ("ing", "ors", "or", "ers", "er", "es", "s")


def _stem(w: str) -> str:
    for suf in _SUFFIXES:
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _terms(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 1}


@dataclass
class DocVersion:
    doc_id: str
    title: str
    version: int
    approval_status: str
    approved_by: str
    category: str
    expires: str | None
    chunks: list[tuple[str, str]] = field(default_factory=list)  # (heading, text)
    included: bool = False
    exclusion_reason: str | None = None


def parse_markdown(path: Path) -> DocVersion:
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    meta: dict[str, str] = {}
    body = raw
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, flags=re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = m.group(2)
    chunks: list[tuple[str, str]] = []
    for block in re.split(r"^## ", body, flags=re.M)[1:]:
        heading, _, text = block.partition("\n")
        text = " ".join(text.split())
        if text:
            chunks.append((heading.strip(), text))
    return DocVersion(
        doc_id=meta.get("doc_id", path.stem), title=meta.get("title", path.stem),
        version=int(meta.get("version", "1")), approval_status=meta.get("approval_status", "draft"),
        approved_by=meta.get("approved_by", ""), category=meta.get("category", "general"),
        expires=meta.get("expires") or None, chunks=chunks,
    )


def select_eligible(docs: list[DocVersion], today: date) -> list[DocVersion]:
    """Mark which versions may be embedded. Pure function (unit-tested)."""
    latest: dict[str, int] = {}
    for d in docs:
        if d.approval_status == "approved":
            latest[d.doc_id] = max(latest.get(d.doc_id, 0), d.version)
    for d in docs:
        d.included, d.exclusion_reason = False, None
        if d.approval_status != "approved":
            d.exclusion_reason = f"not approved ({d.approval_status})"
        elif d.expires and date.fromisoformat(d.expires) < today:
            d.exclusion_reason = f"expired {d.expires}"
        elif d.version < latest.get(d.doc_id, d.version):
            d.exclusion_reason = "superseded by a newer approved version"
        else:
            d.included = True
    return docs


class RAG:
    def __init__(self, settings: Settings):
        self.s = settings
        self.ready = False
        self.error: str | None = None
        self.docs: list[DocVersion] = []
        self._embedder = None
        self._col = None
        self.chunk_count = 0

    async def init(self, today: date) -> list[DocVersion]:
        try:
            return await asyncio.to_thread(self._init_sync, today)
        except Exception as e:
            self.error = f"{type(e).__name__}: {str(e)[:200]}"
            log.exception("rag init failed")
            return self.docs

    def _init_sync(self, today: date) -> list[DocVersion]:
        import chromadb
        from fastembed import TextEmbedding

        files = sorted(Path(self.s.knowledge_dir).glob("*.md"))
        docs = select_eligible([parse_markdown(f) for f in files], today)
        self.docs = docs
        self._embedder = TextEmbedding(model_name=MODEL_NAME, cache_dir=f"{self.s.data_dir}/models")
        client = chromadb.PersistentClient(path=f"{self.s.data_dir}/chroma")
        try:
            client.delete_collection("approved_docs")
        except Exception:
            pass
        col = client.create_collection("approved_docs", metadata={"hnsw:space": "cosine"})
        ids, texts, metas = [], [], []
        for d in docs:
            if not d.included:
                continue
            for i, (heading, text) in enumerate(d.chunks):
                ids.append(f"{d.doc_id}:v{d.version}:{i}")
                texts.append(f"{d.title}. {heading}. {text}")
                metas.append({"title": d.title, "version": d.version, "doc_id": d.doc_id, "answer": text, "heading": heading, "category": d.category})
        if texts:
            vecs = [v.tolist() for v in self._embedder.embed(texts)]
            col.add(ids=ids, embeddings=vecs, documents=texts, metadatas=metas)
        self._col = col
        self.chunk_count = len(texts)
        self.ready = True
        log.info("rag ready: %d chunks from %d approved documents", len(texts), sum(d.included for d in docs))
        return docs

    async def search(self, query: str, k: int = 3, category: str | None = None) -> list[dict]:
        """General information search never returns symptom guidance; pass category='symptom_guidance' for that."""
        if not self.ready or not query.strip():
            return []
        return await asyncio.to_thread(self._search_sync, query, k, category)

    def _search_sync(self, query: str, k: int, category: str | None = None) -> list[dict]:
        qv = next(iter(self._embedder.query_embed([query]))).tolist()
        where = {"category": category} if category else {"category": {"$ne": "symptom_guidance"}}
        res = self._col.query(query_embeddings=[qv], n_results=max(k, 8), where=where)
        qterms = _terms(query)
        out: list[dict] = []
        for cid, meta, dist in zip(res["ids"][0], res["metadatas"][0], res["distances"][0]):
            cos = 1.0 - float(dist)
            if cos < self.s.rag_min_score:  # relevance floor stays on the semantic score
                continue
            # light keyword re-rank: query terms that appear in the passage's title/heading (stemmed)
            target = _terms(f"{meta['title']} {meta.get('heading', '')}")
            lex = (len(qterms & target) / len(qterms)) if qterms else 0.0
            out.append({"chunk_id": cid, "text": meta["answer"], "title": meta["title"], "version": meta["version"],
                        "score": min(1.0, cos + 0.30 * lex), "cosine": cos})
        out.sort(key=lambda x: -x["score"])
        return out[:k]
