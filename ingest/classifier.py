"""Difficulty (heuristics + a small OpenAI model) and section (A/B/C) assignment."""
from __future__ import annotations

import logging
import math
from typing import Literal

from pydantic import BaseModel

import config
import llm

log = logging.getLogger(__name__)

Difficulty = Literal["easy", "medium", "hard"]

EASY_WORDS = {"state", "name", "identify", "define", "give", "write", "label", "list", "circle", "tick", "complete"}
MEDIUM_WORDS = {"describe", "explain", "calculate", "suggest", "compare", "determine", "show", "outline", "sketch",
                "draw", "measure", "plot", "work out", "find", "estimate"}
HARD_WORDS = {"evaluate", "discuss", "justify", "deduce", "predict", "analyse", "analyze", "assess", "prove",
              "derive", "comment", "examine", "consider"}

_LEVEL = {"easy": 0, "medium": 1, "hard": 2}
_NAME = {0: "easy", 1: "medium", 2: "hard"}


def heuristic_difficulty(marks: int, command_word: str, question_type: str, paper: str | None) -> str:
    """Rule-based first guess: marks, command word, question type and paper tier."""
    score = 0 if marks <= 2 else 1 if marks <= 4 else 2
    cw = (command_word or "").lower().strip()
    if cw in HARD_WORDS:
        score += 1
    elif cw in EASY_WORDS:
        score -= 1
    if question_type in ("extended_response", "case_study", "data_analysis"):
        score += 1
    if question_type == "mcq":
        score = min(score, 1)
    # CAIE: papers 1/3 are Core and 2/4 Extended for most sciences (convention varies by subject).
    # A small nudge only: it breaks ties but never moves a question a whole level on its own.
    if paper in ("2", "4", "6"):
        score += 0.4
    return _NAME[max(0, min(2, math.floor(score + 0.5)))]


class _Item(BaseModel):
    id: int
    difficulty: Difficulty
    reason: str


class _Batch(BaseModel):
    items: list[_Item]


_SYSTEM = """You rate the difficulty of Cambridge IGCSE exam questions for a model-paper generator.

easy = single-step recall (state/name/define), 1-2 marks.
medium = explanation or standard calculation, 2-4 marks, one or two concepts.
hard = multi-step reasoning, evaluation, unfamiliar context, or 5+ marks.

Each question has a rule-based first guess. Keep it unless the content clearly justifies a change.
Give a one-line reason for each rating. Return one item per question id."""


def classify_difficulty(questions: list[dict], subject: str) -> list[tuple[str, str]]:
    """Return (difficulty, reason) per question, in order. Falls back to heuristics if the LLM call fails."""
    heur = [
        heuristic_difficulty(q["marks"], q["command_word"], q["question_type"], q.get("paper")) for q in questions
    ]
    results: list[tuple[str, str]] = [(h, "heuristic: marks/command word") for h in heur]
    for start in range(0, len(questions), 25):
        chunk = questions[start : start + 25]
        listing = "\n\n".join(
            f"id={start + i} | marks={q['marks']} | command={q['command_word']} | type={q['question_type']}"
            f" | first guess={heur[start + i]}\n{(q.get('stem_context') or '')[:400]}\n{q['text'][:800]}"
            for i, q in enumerate(chunk)
        )
        try:
            batch = llm.structured(
                model=config.CLASSIFIER_MODEL,
                system=_SYSTEM,
                content=f"Subject: {subject}\n\n{listing}",
                schema=_Batch,
                max_tokens=8000,
                effort="low",
            )
        except llm.LLMError as exc:
            log.warning("Difficulty classifier fell back to heuristics: %s", exc)
            continue
        for item in batch.items:
            if start <= item.id < start + len(chunk):
                results[item.id] = (item.difficulty, item.reason)
    return results


def assign_section(question_type: str, marks: int, stem_context: str) -> str:
    """A = short answers, B = long answers, C = application / case-based (spec section 4.5.2)."""
    if question_type in ("data_analysis", "case_study", "practical"):
        return "C"
    if question_type in ("mcq", "short_answer") or marks <= 3:
        return "A"
    # A long prose answer built on a substantial given scenario counts as application.
    if question_type == "extended_response" and len(stem_context or "") >= 250:
        return "C"
    return "B"
