"""Select questions for a model paper: validate filters, fetch candidates, enforce variety."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from rapidfuzz import process

import config
from store import catalog, pinecone_store


class ValidationError(Exception):
    pass


@dataclass
class PaperRequest:
    subject: str
    num_questions: int
    topics: list[str] = field(default_factory=list)
    difficulty: str = "mixed"  # mixed | easy | medium | hard
    year_from: int | None = None
    year_to: int | None = None
    focus: str = ""  # optional free text for semantic search
    use_sections: bool = True
    section_counts: dict[str, int] | None = None  # e.g. {"A": 8, "B": 8, "C": 4}
    seed: int | None = None


@dataclass
class Selection:
    questions: list[dict[str, Any]]
    seed: int
    warnings: list[str]
    steps: list[str]


def default_section_counts(n: int) -> dict[str, int]:
    """40% / 40% / 20% split, rounding so the counts add up to n."""
    a = round(n * 0.4)
    b = round(n * 0.4)
    c = max(0, n - a - b)
    return {"A": a, "B": b, "C": c}


def validate(req: PaperRequest) -> PaperRequest:
    subjects = catalog.list_question_subjects()
    if not subjects:
        raise ValidationError("No questions have been ingested yet. Ingest some question papers first.")
    if req.subject not in subjects:
        match = process.extractOne(req.subject, subjects)
        hint = f" Did you mean '{match[0]}'?" if match and match[1] >= 60 else ""
        raise ValidationError(f"Subject '{req.subject}' has no ingested questions.{hint} Available: {', '.join(subjects)}.")
    if not isinstance(req.num_questions, int) or not 1 <= req.num_questions <= config.MAX_QUESTIONS_PER_PAPER:
        raise ValidationError(f"Number of questions must be a whole number from 1 to {config.MAX_QUESTIONS_PER_PAPER}.")
    if req.difficulty not in ("mixed", "easy", "medium", "hard"):
        raise ValidationError("Difficulty must be easy, medium, hard or mixed.")
    known_topics = set(catalog.list_topics(req.subject))
    unknown = [t for t in req.topics if t not in known_topics]
    if unknown:
        raise ValidationError(f"Unknown topic(s) for {req.subject}: {', '.join(unknown)}.")
    if req.year_from and req.year_to and req.year_from > req.year_to:
        raise ValidationError("'Year from' must not be after 'Year to'.")
    if req.use_sections:
        counts = req.section_counts or default_section_counts(req.num_questions)
        if any(v < 0 for v in counts.values()):
            raise ValidationError("Section counts cannot be negative.")
        if sum(counts.values()) != req.num_questions:
            raise ValidationError(
                f"Section counts add up to {sum(counts.values())}, but {req.num_questions} questions were requested."
            )
        req.section_counts = counts
    return req


def _filters(req: PaperRequest, sections: list[str] | None = None) -> dict[str, Any]:
    return {
        "subject": req.subject,
        "topics": req.topics,
        "difficulty": req.difficulty,
        "year_from": req.year_from,
        "year_to": req.year_to,
        "sections": sections,
    }


def _pinecone_filter(req: PaperRequest, sections: list[str] | None) -> dict[str, Any]:
    f: dict[str, Any] = {"subject": {"$eq": req.subject}}
    if req.topics:
        f["topic"] = {"$in": req.topics}
    if req.difficulty != "mixed":
        f["difficulty"] = {"$eq": req.difficulty}
    if sections:
        f["section"] = {"$in": sections}
    if req.year_from or req.year_to:
        f["year"] = {k: v for k, v in (("$gte", req.year_from), ("$lte", req.year_to)) if v}
    return f


def _candidates(req: PaperRequest, sections: list[str] | None, n: int, seed: int) -> list[tuple[str, float]]:
    """Return (question_id, relevance) pairs. Random sampling unless a focus query is given."""
    want = n * 3
    if req.focus.strip():
        hits = pinecone_store.search(
            config.NS_QUESTIONS, req.focus, top_k=min(want * 2, 200),
            filter=_pinecone_filter(req, sections), fields=["question_id"],
        )
        best: dict[str, float] = {}
        for h in hits:  # several chunks can belong to one question
            qid = h.get("question_id")
            if qid and h["score"] > best.get(qid, -1):
                best[qid] = h["score"]
        return sorted(best.items(), key=lambda kv: -kv[1])[:want]
    ids = catalog.sample_question_ids(_filters(req, sections), want, seed)
    return [(qid, 1.0) for qid in ids]


def _mmr(
    cands: list[dict[str, Any]], rel: dict[str, float], k: int, used_parents: set[str], chosen_vecs: list[np.ndarray]
) -> list[dict[str, Any]]:
    """Maximal marginal relevance with hard limits: no near-duplicates, no two parts of one parent question."""
    picked: list[dict[str, Any]] = []
    pool = list(cands)
    while pool and len(picked) < k:
        best, best_score = None, -1e9
        for q in pool:
            parent = f"{q.get('paper_key') or q['source_file']}::{q['parent_number']}"
            if parent in used_parents:
                continue
            v = q.get("embedding")
            max_sim = max((float(v @ c) for c in chosen_vecs), default=0.0) if v is not None else 0.0
            if max_sim >= config.PAPER_DIVERSITY_SIMILARITY:
                continue
            score = config.MMR_LAMBDA * rel.get(q["question_id"], 0.0) - (1 - config.MMR_LAMBDA) * max_sim
            if score > best_score:
                best, best_score = q, score
        if best is None:
            break
        pool.remove(best)
        picked.append(best)
        used_parents.add(f"{best.get('paper_key') or best['source_file']}::{best['parent_number']}")
        if best.get("embedding") is not None:
            chosen_vecs.append(best["embedding"])
    return picked


def select(req: PaperRequest) -> Selection:
    req = validate(req)
    seed = req.seed if req.seed is not None else random.SystemRandom().randint(1, 999_999)
    steps = [f"Validated request: {req.num_questions} {req.subject} questions, difficulty {req.difficulty}."]
    warnings: list[str] = []
    used_parents: set[str] = set()
    chosen_vecs: list[np.ndarray] = []
    chosen: list[dict[str, Any]] = []

    groups = (
        [([s], c) for s, c in req.section_counts.items() if c > 0]
        if req.use_sections and req.section_counts
        else [(None, req.num_questions)]
    )
    mode = f"semantic search for '{req.focus}'" if req.focus.strip() else f"random sampling (seed {seed})"
    steps.append(f"Retrieving candidates by {mode}.")

    for sections, count in groups:
        available = catalog.count_questions(_filters(req, sections))
        label = f"Section {sections[0]}" if sections else "Paper"
        cands = _candidates(req, sections, count, seed)
        rel = dict(cands)
        rows = catalog.get_questions([qid for qid, _ in cands])
        picked = _mmr(rows, rel, count, used_parents, chosen_vecs)
        steps.append(f"{label}: {available} matching questions, {len(cands)} candidates, {len(picked)} selected.")
        if len(picked) < count:
            if available < count:
                why = f"only {available} ingested question(s) match the filters"
            else:
                why = (f"{available} match the filters, but the rest were near-duplicates or other parts "
                       f"of questions already chosen")
            warnings.append(
                f"{label}: generated {len(picked)} of {count} requested questions — {why}. "
                f"Relax the filters or ingest more papers for a fuller paper."
            )
        chosen.extend(picked)

    if not chosen:
        raise ValidationError("No questions match these filters. Try removing a topic, widening the years, "
                              "or choosing 'mixed' difficulty.")
    steps.append(f"Removed near-duplicates (similarity ≥ {config.PAPER_DIVERSITY_SIMILARITY}).")
    return Selection(chosen, seed, warnings, steps)
