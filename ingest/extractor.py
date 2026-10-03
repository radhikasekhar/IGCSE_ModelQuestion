"""LLM structured extraction (OpenAI) of questions, notes, mark schemes and document type."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

import config
import llm
from ingest.loaders import LoadedDocument, Page

QuestionType = Literal[
    "mcq", "short_answer", "calculation", "structured", "extended_response", "data_analysis", "case_study", "practical"
]
ContentType = Literal["definition", "explanation", "formula", "worked_example", "diagram_caption", "summary"]


# --- Schemas -----------------------------------------------------------------
class ExtractedQuestion(BaseModel):
    number: str = Field(description="Full question number as printed, e.g. '3(b)(ii)' or '12'.")
    parent_number: str = Field(description="Top-level question number, e.g. '3'.")
    stem_context: str = Field(
        description="Shared introductory text/data from the parent question needed to answer this part. Empty if none."
    )
    text: str = Field(description="The question text, verbatim, without the marks annotation. MCQ options A-D included.")
    marks: int = Field(description="Marks shown in brackets, e.g. [2] -> 2. 0 if not shown.")
    question_type: QuestionType
    command_word: str = Field(description="Cambridge command word, lower case, e.g. 'state', 'explain', 'calculate'.")
    topic: str = Field(description="Syllabus topic as 'Main topic - Subtopic', e.g. 'Electricity - Electric circuits'.")
    has_diagram: bool = Field(description="True if the question refers to or relies on a diagram, graph, table or image.")
    page: int = Field(description="Page number (from the === PAGE n === markers) where this question part starts.")


class QuestionExtraction(BaseModel):
    subject: str = Field(description="Subject name, e.g. 'Physics'. 'unknown' if not determinable.")
    year: int = Field(description="Exam year, 0 if unknown.")
    questions: list[ExtractedQuestion]


class NoteSection(BaseModel):
    topic: str = Field(description="Syllabus topic as 'Main topic - Subtopic'.")
    content_type: ContentType
    keywords: list[str] = Field(description="3-8 key terms from this section, lower case.")
    page: int = Field(description="Page number from the === PAGE n === markers.")
    text: str = Field(description="The section content, cleaned but otherwise verbatim.")


class NotesExtraction(BaseModel):
    subject: str = Field(description="Subject name, e.g. 'Biology'. 'unknown' if not determinable.")
    sections: list[NoteSection]


class MarkSchemeEntry(BaseModel):
    number: str = Field(description="Question number as printed, e.g. '3(b)(ii)'.")
    answer: str = Field(description="Accepted answer(s) and marking points, concise but complete.")
    marks: int


class MarkSchemeExtraction(BaseModel):
    entries: list[MarkSchemeEntry]


class DocTypeGuess(BaseModel):
    doc_type: Literal["qp", "ms", "in", "notes", "other"]
    subject: str
    year: int = Field(description="Exam year, 0 if unknown or not an exam document.")


# --- Prompts -----------------------------------------------------------------
QUESTION_SYSTEM = """You extract exam questions from Cambridge IGCSE question papers.

Rules:
- Extract ONLY questions. Skip cover pages, instructions to candidates, formula sheets, "BLANK PAGE", answer spaces and copyright notices.
- Split structured questions into their lowest answerable parts: 3(a), 3(b)(i), 3(b)(ii). Each part is one entry.
- Copy question wording verbatim. Never rephrase, complete, correct or invent text.
- Put the shared stem of a multi-part question (scenario, data, "Fig. 3.1 shows...") in stem_context for each part that needs it.
- Read the marks from the bracket at the end, e.g. [2], and remove that bracket from the text.
- Multiple-choice questions: keep options A, B, C, D in the text on separate lines; question_type "mcq"; marks 1.
- question_type guide: short_answer (recall, 1-3 marks), calculation (numeric working), structured (multi-step explanation), extended_response (6+ mark prose), data_analysis (interpret given data/graph/table), case_study (scenario/context-based), practical (experimental method).
- topic: use Cambridge IGCSE syllabus topic names for the subject.
- Page markers look like "=== PAGE n ===". Report the page where each part starts."""

NOTES_SYSTEM = """You structure Cambridge IGCSE study notes for a retrieval system.

Rules:
- Split the content into coherent sections, each about one concept (one definition, one explanation, one formula with its terms, one worked example).
- Keep the wording faithful to the source. Clean OCR/formatting noise but do not add facts that are not in the text.
- Ignore headers, footers, page numbers, tables of contents and copyright lines.
- topic: use Cambridge IGCSE syllabus topic names, as "Main topic - Subtopic".
- Page markers look like "=== PAGE n ===". Report the page each section comes from."""

MS_SYSTEM = """You extract answers from Cambridge IGCSE mark schemes.

Rules:
- One entry per question part as numbered in the mark scheme, e.g. 1(a), 3(b)(ii). For MCQ papers, one entry per question with the letter.
- answer: the accepted answer and key marking points, verbatim where possible. Include alternatives (allow/accept) briefly. Skip generic marking guidance pages.
- marks: the marks for that part."""

DOCTYPE_SYSTEM = """Classify a document from an IGCSE study folder.
qp = exam question paper, ms = mark scheme, in = insert/source booklet for a paper, notes = study/revision notes or textbook content, other = anything else."""


# --- Helpers -----------------------------------------------------------------
def _content_blocks(pages: list[Page]) -> list[dict]:
    """Interleave page markers with page text, or the page image for scanned pages."""
    blocks: list[dict] = []
    text_buf: list[str] = []
    for p in pages:
        if p.image_b64:
            if text_buf:
                blocks.append({"type": "text", "text": "\n\n".join(text_buf)})
                text_buf = []
            blocks.append({"type": "text", "text": f"=== PAGE {p.number} === (scanned image follows)"})
            blocks.append(
                {"type": "image", "source": {"type": "base64", "media_type": p.image_media_type, "data": p.image_b64}}
            )
        else:
            text_buf.append(f"=== PAGE {p.number} ===\n{p.text}")
    if text_buf:
        blocks.append({"type": "text", "text": "\n\n".join(text_buf)})
    return blocks


def _batches(pages: list[Page], size: int = config.PAGES_PER_EXTRACTION_CALL) -> list[list[Page]]:
    return [pages[i : i + size] for i in range(0, len(pages), size)] or [[]]


def _hint(name: str, subject: str | None) -> str:
    return f"Source file: {name}" + (f"\nSubject: {subject}" if subject else "")


# --- Public API ----------------------------------------------------------------
def classify_document(doc: LoadedDocument) -> DocTypeGuess:
    sample = doc.pages[:2]
    content = [{"type": "text", "text": f"File name: {doc.path.name}"}, *_content_blocks(sample)]
    return llm.structured(
        model=config.CLASSIFIER_MODEL, system=DOCTYPE_SYSTEM, content=content, schema=DocTypeGuess,
        max_tokens=2000, effort="low",
    )


def extract_questions(doc: LoadedDocument, subject: str | None) -> QuestionExtraction:
    result = QuestionExtraction(subject=subject or "unknown", year=0, questions=[])
    for batch in _batches(doc.pages):
        content = [
            {"type": "text", "text": _hint(doc.path.name, subject)},
            *_content_blocks(batch),
            {"type": "text", "text": "Extract every question part from the pages above."},
        ]
        part = llm.structured(
            model=config.EXTRACTION_MODEL,
            system=QUESTION_SYSTEM,
            content=content,
            schema=QuestionExtraction,
            effort=config.EXTRACTION_EFFORT,
        )
        result.questions.extend(part.questions)
        if result.subject == "unknown" and part.subject:
            result.subject = part.subject
        result.year = result.year or part.year
    return result


def extract_notes(doc: LoadedDocument, subject: str | None) -> NotesExtraction:
    result = NotesExtraction(subject=subject or "unknown", sections=[])
    for batch in _batches(doc.pages, size=12):
        content = [
            {"type": "text", "text": _hint(doc.path.name, subject)},
            *_content_blocks(batch),
            {"type": "text", "text": "Split the notes above into sections."},
        ]
        part = llm.structured(
            model=config.EXTRACTION_MODEL,
            system=NOTES_SYSTEM,
            content=content,
            schema=NotesExtraction,
            effort=config.EXTRACTION_EFFORT,
        )
        result.sections.extend(part.sections)
        if result.subject == "unknown" and part.subject:
            result.subject = part.subject
    return result


def extract_mark_scheme(doc: LoadedDocument) -> MarkSchemeExtraction:
    result = MarkSchemeExtraction(entries=[])
    for batch in _batches(doc.pages):
        content = [
            {"type": "text", "text": _hint(doc.path.name, None)},
            *_content_blocks(batch),
            {"type": "text", "text": "Extract the answer for every question part."},
        ]
        part = llm.structured(
            model=config.EXTRACTION_MODEL,
            system=MS_SYSTEM,
            content=content,
            schema=MarkSchemeExtraction,
            effort="low",
        )
        result.entries.extend(part.entries)
    return result
