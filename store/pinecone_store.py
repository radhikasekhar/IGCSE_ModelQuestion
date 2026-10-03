"""Pinecone access: integrated-embedding index, search, rerank and embeddings for de-duplication."""
from __future__ import annotations

import logging
import threading
import time
from functools import lru_cache
from typing import Any, Sequence

from pinecone import ConflictError, Pinecone
from tenacity import retry, stop_after_attempt, wait_exponential

import config

log = logging.getLogger(__name__)
_retry = retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20), reraise=True)


@lru_cache(maxsize=1)
def client() -> Pinecone:
    if not config.PINECONE_API_KEY:
        raise RuntimeError("PINECONE_API_KEY is not set. Add it to the .env file.")
    return Pinecone(api_key=config.PINECONE_API_KEY)


def ensure_index() -> None:
    """Create the integrated-embedding index on first use, then wait until it is ready."""
    pc = client()
    if not pc.has_index(config.PINECONE_INDEX):
        log.info("Creating Pinecone index %s", config.PINECONE_INDEX)
        try:
            pc.create_index_for_model(
                name=config.PINECONE_INDEX,
                cloud=config.PINECONE_CLOUD,
                region=config.PINECONE_REGION,
                embed={"model": config.EMBED_MODEL, "field_map": {"text": "chunk_text"}, "metric": "cosine"},
            )
        except ConflictError:
            # Another process created it between our check and our create call: that's fine.
            log.info("Pinecone index %s already exists", config.PINECONE_INDEX)
    for _ in range(60):
        if pc.describe_index(config.PINECONE_INDEX).status.ready:
            return
        time.sleep(2)
    raise RuntimeError(f"Pinecone index {config.PINECONE_INDEX} is still not ready after 2 minutes. Retry shortly.")


_index_lock = threading.Lock()


@lru_cache(maxsize=1)
def _index():
    ensure_index()
    return client().Index(config.PINECONE_INDEX)


def index():
    # Streamlit serves every browser tab from one process; the lock stops tabs racing to create the index.
    with _index_lock:
        return _index()


def _clean_metadata(record: dict[str, Any]) -> dict[str, Any]:
    """Pinecone metadata accepts str, number, bool and list[str] only, never None."""
    out: dict[str, Any] = {}
    for k, v in record.items():
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            out[k] = [str(x) for x in v if x is not None]
        elif isinstance(v, (str, bool, int, float)):
            out[k] = v
        else:
            out[k] = str(v)
    return out


@_retry
def _upsert_batch(namespace: str, batch: list[dict[str, Any]]) -> None:
    index().upsert_records(namespace=namespace, records=batch)


def upsert(namespace: str, records: Sequence[dict[str, Any]]) -> int:
    """Each record needs `_id` and `chunk_text`; every other key becomes filterable metadata."""
    cleaned = [_clean_metadata(r) for r in records]
    for i in range(0, len(cleaned), config.UPSERT_BATCH):
        _upsert_batch(namespace, cleaned[i : i + config.UPSERT_BATCH])
    return len(cleaned)


@_retry
def search(
    namespace: str,
    text: str,
    top_k: int,
    filter: dict[str, Any] | None = None,
    fields: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    resp = index().search(
        namespace=namespace,
        top_k=top_k,
        inputs={"text": text},
        filter=filter or None,
        fields=list(fields) if fields else None,
    )
    return [{"id": h.id, "score": h.score, **(h.fields or {})} for h in resp.result.hits]


@_retry
def rerank(query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
    """Returns (original index, score) pairs, best first."""
    if not documents:
        return []
    result = client().inference.rerank(
        model=config.RERANK_MODEL,
        query=query,
        documents=[{"text": d[:4000]} for d in documents],
        rank_fields=["text"],
        top_n=min(top_n, len(documents)),
        return_documents=False,
        parameters={"truncate": "END"},
    )
    return [(d.index, d.score) for d in result.data]


@_retry
def _embed_batch(texts: list[str], input_type: str) -> list[list[float]]:
    res = client().inference.embed(
        model=config.EMBED_MODEL, inputs=texts, parameters={"input_type": input_type, "truncate": "END"}
    )
    return [list(e.values) for e in res.data]


def embed(texts: Sequence[str], input_type: str = "passage") -> list[list[float]]:
    """Embeddings from the same model the index uses (for duplicate and diversity checks)."""
    out: list[list[float]] = []
    for i in range(0, len(texts), config.UPSERT_BATCH):
        out.extend(_embed_batch(list(texts[i : i + config.UPSERT_BATCH]), input_type))
    return out


def delete_by_source(source_file: str) -> None:
    """Remove every record from one source file (used when a file is re-ingested)."""
    for ns in (config.NS_QUESTIONS, config.NS_NOTES):
        try:
            index().delete(filter={"source_file": {"$eq": source_file}}, namespace=ns)
        except Exception as exc:  # namespace may not exist yet
            log.debug("delete_by_source(%s, %s): %s", source_file, ns, exc)
