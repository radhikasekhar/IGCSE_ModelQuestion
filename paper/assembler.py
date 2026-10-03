"""Assemble selected questions into a model paper. Question text is copied verbatim from the catalog."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import config
from store import catalog

SECTION_TITLES = {
    "A": "SECTION A – Short Answers",
    "B": "SECTION B – Long Answers",
    "C": "SECTION C – Application / Case-Based Questions",
}
_DIFF_ORDER = {"easy": 0, "medium": 1, "hard": 2}


@dataclass
class PaperQuestion:
    number: int
    question_id: str
    stem_context: str
    text: str
    marks: int
    image_paths: list[str]
    source_ref: str
    topic: str
    difficulty: str
    ms_answer: str | None
    paper_key: str | None


@dataclass
class PaperSection:
    title: str
    questions: list[PaperQuestion]


@dataclass
class Paper:
    title: str
    subtitle: str
    duration_minutes: int
    total_marks: int
    instructions: list[str]
    sections: list[PaperSection]
    seed: int
    show_sources: bool
    inserts: dict[str, str] = field(default_factory=dict)  # paper source ref -> insert text
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))

    @property
    def all_questions(self) -> list[PaperQuestion]:
        return [q for s in self.sections for q in s.questions]


def source_ref(q: dict[str, Any]) -> str:
    """CAIE-style reference, e.g. (0625/42/M/J/23 Q3(b)) or (file.pdf Q3) for non-CAIE files."""
    if q.get("subject_code") and q.get("paper") and q.get("year") and q.get("session"):
        sess = config.SESSION_SHORT.get(q["session"], q["session"])
        return f"({q['subject_code']}/{q['paper']}{q.get('variant') or ''}/{sess}/{str(q['year'])[-2:]} Q{q['number']})"
    return f"({q['source_file']} Q{q['number']})"


def _order(questions: list[dict[str, Any]], ordering: str, rng: random.Random) -> list[dict[str, Any]]:
    if ordering == "difficulty":
        return sorted(questions, key=lambda q: (_DIFF_ORDER.get(q["difficulty"], 1), q["question_id"]))
    if ordering == "topic":
        return sorted(questions, key=lambda q: (q["topic"] or "", q["question_id"]))
    shuffled = list(questions)
    rng.shuffle(shuffled)
    return shuffled


def assemble(
    questions: list[dict[str, Any]],
    *,
    subject: str,
    seed: int,
    use_sections: bool = True,
    ordering: str = "shuffle",  # shuffle | difficulty | topic
    show_sources: bool = False,
    instructions: list[str] | None = None,
    duration_minutes: int | None = None,
) -> Paper:
    rng = random.Random(seed)
    if use_sections:
        groups = [
            (SECTION_TITLES[s], _order([q for q in questions if q["section"] == s], ordering, rng))
            for s in ("A", "B", "C")
        ]
        groups = [g for g in groups if g[1]]
    else:
        groups = [("", _order(questions, ordering, rng))]

    sections: list[PaperSection] = []
    inserts: dict[str, str] = {}
    n = 0
    for title, qs in groups:
        items = []
        for q in qs:
            n += 1
            items.append(
                PaperQuestion(
                    number=n,
                    question_id=q["question_id"],
                    stem_context=q.get("stem_context") or "",
                    text=q["text"],
                    marks=int(q.get("marks") or 0),
                    image_paths=[str(config.resolve_data_path(p)) for p in q.get("image_paths") or []],
                    source_ref=source_ref(q),
                    topic=q.get("topic") or "",
                    difficulty=q.get("difficulty") or "",
                    ms_answer=catalog.mark_scheme_answer(q.get("paper_key"), q["number"]),
                    paper_key=q.get("paper_key"),
                )
            )
            insert = catalog.get_insert(q.get("paper_key"))
            if insert and q.get("paper_key") not in inserts:
                inserts[q["paper_key"]] = insert
        sections.append(PaperSection(title, items))

    total = sum(q.marks for s in sections for q in s.questions)
    code = catalog.subject_code_for(subject)
    return Paper(
        title=f"Model Question Paper – {subject}",
        subtitle=f"Cambridge IGCSE ({code})" if code else "Cambridge IGCSE",
        duration_minutes=duration_minutes if duration_minutes else max(total, 15),  # default: 1 minute per mark
        total_marks=total,
        instructions=list(instructions if instructions is not None else config.DEFAULT_INSTRUCTIONS),
        sections=sections,
        seed=seed,
        show_sources=show_sources,
        inserts=inserts,
    )


def format_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} hour{'s' if h > 1 else ''} {m} minutes"
    if h:
        return f"{h} hour{'s' if h > 1 else ''}"
    return f"{m} minutes"


def md_escape(text: str) -> str:
    """Escape characters Streamlit markdown would interpret ($ starts LaTeX, * and _ emphasis)."""
    for ch in ("\\", "$", "*", "_", "#", "`"):
        text = text.replace(ch, "\\" + ch)
    return text.replace("\n", "  \n")


def to_markdown(paper: Paper, include_answers: bool = False) -> str:
    """Preview text for the UI."""
    lines = [f"## {paper.title}", f"**{paper.subtitle}**", "",
             f"**Duration:** {format_duration(paper.duration_minutes)} &nbsp;&nbsp; **Total marks:** {paper.total_marks}", ""]
    if paper.instructions and not include_answers:
        lines += ["**INSTRUCTIONS**", *[f"- {i}" for i in paper.instructions], ""]
    for sec in paper.sections:
        if sec.title:
            lines += [f"### {sec.title}", ""]
        for q in sec.questions:
            ref = f" _{q.source_ref}_" if paper.show_sources else ""
            body = (q.stem_context + "\n\n" if q.stem_context else "") + q.text
            body = md_escape(body)
            lines.append(f"**{q.number}.** {body} **[{q.marks}]**{ref}")
            if include_answers:
                ans = md_escape(q.ms_answer) if q.ms_answer else "_Mark scheme not available in source documents._"
                lines.append(f"> **Answer:** {ans}")
            lines.append("")
    return "\n".join(lines)
