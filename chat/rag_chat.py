"""Local-first chatbot: answer from ingested notes and questions, fall back to the web when nothing relevant is found."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterator

import config
import llm
from chat import web_fallback
from store import pinecone_store

log = logging.getLogger(__name__)

EXTERNAL_NOTICE = (
    "⚠ **Related information was not found in the ingested documents. "
    "The answer below is sourced from external web sources:**\n\n"
)

LOCAL_SYSTEM = """You are an IGCSE subject tutor. Answer the student's question using ONLY the numbered sources provided from the school's ingested notes and past papers.

- Cite sources inline as [S1], [S2] after the sentences they support.
- If the sources only partly answer the question, answer that part and say clearly what the documents do not cover. Do not fill gaps from general knowledge.
- When the student asks for past-paper questions, list the matching questions from the sources verbatim with their references. Never invent or rephrase exam questions.
- Use an academic tone and Cambridge IGCSE terminology. Keep answers concise and well structured. Use LaTeX ($...$) for formulas."""

WEB_SYSTEM = """You are an IGCSE subject tutor. The school's own documents did not cover this question, so answer using ONLY the numbered web results provided.

- Cite results inline as [W1], [W2].
- Pitch the answer at Cambridge IGCSE level, in an academic tone. Use LaTeX ($...$) for formulas.
- If the web results don't answer the question, say so instead of guessing."""


@dataclass
class Source:
    tag: str
    label: str
    text: str
    url: str | None = None


@dataclass
class Retrieval:
    sources: list[Source]
    best_score: float
    local: bool


def _safe_search(namespace: str, query: str, top_k: int, flt: dict | None, fields: list[str]) -> list[dict[str, Any]]:
    try:
        return pinecone_store.search(namespace, query, top_k=top_k, filter=flt, fields=fields)
    except Exception as exc:  # e.g. the namespace doesn't exist yet because nothing was ingested into it
        log.warning("Search in %s failed: %s", namespace, exc)
        return []


def _local_candidates(query: str, subject: str | None) -> list[dict[str, Any]]:
    flt = {"subject": {"$eq": subject}} if subject else None
    notes = _safe_search(config.NS_NOTES, query, 10, flt, ["chunk_text", "source_file", "page", "topic", "subject"])
    questions = _safe_search(
        config.NS_QUESTIONS, query, 5, flt,
        ["chunk_text", "source_file", "page", "topic", "subject", "question_id", "marks", "year", "session"],
    )
    for h in notes:
        h["kind"] = "notes"
    for h in questions:
        h["kind"] = "question"
    return notes + questions


def _label(h: dict[str, Any]) -> str:
    page = f", p.{int(h['page'])}" if h.get("page") else ""
    kind = "past paper" if h["kind"] == "question" else "notes"
    return f"{h.get('source_file', 'unknown')}{page} ({kind})"


def retrieve(query: str, subject: str | None = None) -> Retrieval:
    hits = _local_candidates(query, subject)
    ranked = pinecone_store.rerank(query, [h.get("chunk_text", "") for h in hits], top_n=6)
    best = ranked[0][1] if ranked else 0.0
    if ranked and best >= config.RELEVANCE_THRESHOLD:
        # Keep everything reasonably close to the best hit.
        keep = [(i, s) for i, s in ranked if s >= config.RELEVANCE_THRESHOLD * 0.6]
        sources = [
            Source(f"S{n}", _label(hits[i]), hits[i].get("chunk_text", ""))
            for n, (i, _) in enumerate(keep, start=1)
        ]
        return Retrieval(sources, best, local=True)
    web = web_fallback.search(query, subject)
    sources = [Source(f"W{n}", r["title"], r["content"], r["url"]) for n, r in enumerate(web, start=1)]
    return Retrieval(sources, best, local=False)


def _history_messages(history: list[dict[str, str]]) -> list[dict[str, Any]]:
    turns = history[-config.CHAT_HISTORY_TURNS * 2 :]
    msgs = [{"role": m["role"], "content": m["content"]} for m in turns if m.get("content")]
    while msgs and msgs[0]["role"] != "user":  # the API requires the first message to be from the user
        msgs.pop(0)
    return msgs


def _sources_footer(r: Retrieval) -> str:
    if not r.sources:
        return ""
    if r.local:
        seen: list[str] = []
        for s in r.sources:
            if s.label not in seen:
                seen.append(s.label)
        return "\n\n---\n**Sources (ingested documents):**\n" + "\n".join(f"- {label}" for label in seen)
    return "\n\n---\n**External sources:**\n" + "\n".join(f"- [{s.label}]({s.url})" for s in r.sources)


def answer(query: str, history: list[dict[str, str]], subject: str | None = None) -> tuple[Retrieval, Iterator[str]]:
    """Retrieve, then return (retrieval, text stream). The stream already includes the notice and source list."""
    r = retrieve(query, subject)

    def gen() -> Iterator[str]:
        if not r.local:
            yield EXTERNAL_NOTICE
            if not r.sources:
                yield "No relevant web results were found either. Try rephrasing the question."
                return
        context = "\n\n".join(f"[{s.tag}] {s.label}\n{s.text}" for s in r.sources)
        system = LOCAL_SYSTEM if r.local else WEB_SYSTEM
        messages = _history_messages(history) + [
            {"role": "user", "content": f"<sources>\n{context}\n</sources>\n\nQuestion: {query}"}
        ]
        yield from llm.stream_text(model=config.CHAT_MODEL, system=system, messages=messages,
                                   effort=config.CHAT_EFFORT)
        yield _sources_footer(r)

    return r, gen()
