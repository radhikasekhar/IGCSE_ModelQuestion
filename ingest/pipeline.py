"""Ingestion orchestrator: discover -> load -> clean -> extract -> classify -> dedup -> crop -> chunk -> store.

Run from the command line:  python -m ingest.pipeline [folder] [--force]
"""
from __future__ import annotations

import argparse
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np

import config
from ingest import chunker, classifier, cleaner, extractor, filename_parser, images, loaders
from ingest.filename_parser import ParsedName
from store import catalog, pinecone_store

log = logging.getLogger("ingest")

EventCallback = Callable[[str, str], None]  # (level, message)


class IngestError(Exception):
    """Raised for problems that stop the whole run (bad folder, no files, missing keys)."""


@dataclass
class FileResult:
    file_name: str
    doc_type: str = ""
    subject: str = ""
    status: str = "pending"  # ingested | skipped | failed
    questions: int = 0
    notes: int = 0
    ms_entries: int = 0
    chunks: int = 0
    diagrams: int = 0
    duplicates: int = 0
    message: str = ""


@dataclass
class RunSummary:
    run_id: int
    folder: str
    log_path: str
    files: list[FileResult] = field(default_factory=list)

    def count(self, attr: str) -> int:
        return sum(getattr(f, attr) for f in self.files)

    def status_count(self, status: str) -> int:
        return sum(1 for f in self.files if f.status == status)


@dataclass
class _Analysis:
    """Everything produced by the (network-bound, thread-safe) analysis phase of one file."""

    path: Path
    file_id: str
    parsed: ParsedName
    doc_type: str
    subject: str
    subject_code: str | None
    year: int | None
    doc: loaders.LoadedDocument | None = None
    questions: list[dict] = field(default_factory=list)
    notes: list[dict] = field(default_factory=list)
    ms_entries: list[dict] = field(default_factory=list)
    insert_text: str = ""


# --- Discovery -------------------------------------------------------------------
def discover(folder: str | Path) -> list[Path]:
    folder = Path(folder).expanduser()
    if not folder.exists():
        raise IngestError(f"Folder `{folder}` does not exist. Check the path and retry.")
    if not folder.is_dir():
        raise IngestError(f"`{folder}` is a file, not a folder. Point ingestion at the folder that contains it.")
    try:
        all_files = [p for p in folder.rglob("*") if p.is_file()]
    except PermissionError as exc:
        raise IngestError(f"Folder `{folder}` is not readable: {exc}. Check its permissions.") from exc
    files = [
        p
        for p in all_files
        if p.suffix.lower() in config.SUPPORTED_EXTS
        and not p.name.startswith(("~$", "."))
        and config.IMAGES_DIR not in p.parents  # never re-ingest our own cropped diagrams
    ]
    if not all_files:
        raise IngestError(
            f"Folder `{folder}` is empty: add PDF, DOCX, TXT, HTML or image files and retry."
        )
    if not files:
        raise IngestError(
            f"Folder `{folder}` has {len(all_files)} file(s) but none in a supported format "
            f"({', '.join(sorted(config.SUPPORTED_EXTS))})."
        )
    return sorted(files)


def _is_notes_path(path: Path) -> bool:
    return any(part.lower() in ("notes", "note", "revision") for part in path.parts[:-1])


def _resolve_subject(parsed: ParsedName, guess: str | None) -> tuple[str, str | None]:
    if parsed.subject:
        return parsed.subject, parsed.subject_code
    subject, code = filename_parser.subject_from_text(guess)
    if parsed.subject_code and not code:
        code = parsed.subject_code
    if not subject or subject.lower() == "unknown":
        return "unknown", code
    return subject, code


def _safe_id(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")[:80]


# --- Phase 1: analysis (runs in worker threads) ------------------------------------
def _analyse(path: Path, file_id: str) -> _Analysis:
    parsed = filename_parser.parse(path)
    doc = loaders.load(path)
    for page in doc.pages:
        page.text = cleaner.clean_page(page.text)
    if doc.total_chars == 0 and not any(p.image_b64 for p in doc.pages):
        raise ValueError("No readable text found in the file.")

    doc_type = parsed.doc_type
    guess_subject: str | None = None
    guess_year: int | None = None
    if not doc_type:
        if _is_notes_path(path):
            doc_type = "notes"
        else:
            guess = extractor.classify_document(doc)
            doc_type, guess_subject, guess_year = guess.doc_type, guess.subject, guess.year or None
    if doc_type == "other":
        raise ValueError("Not recognised as a question paper, mark scheme, insert or notes. Skipped.")

    subject, code = _resolve_subject(parsed, guess_subject)
    a = _Analysis(path, file_id, parsed, doc_type, subject, code, parsed.year or guess_year, doc)

    if doc_type == "qp":
        ex = extractor.extract_questions(doc, subject if subject != "unknown" else None)
        if a.subject == "unknown":
            a.subject, a.subject_code = _resolve_subject(parsed, ex.subject)
        a.year = a.year or (ex.year or None)
        a.questions = [
            {
                "number": q.number.strip(),
                "parent_number": q.parent_number.strip(),
                "stem_context": cleaner.strip_marks(q.stem_context),
                "text": cleaner.strip_marks(q.text),
                "marks": max(0, q.marks),
                "question_type": q.question_type,
                "command_word": q.command_word.lower().strip(),
                "topic": q.topic.strip(),
                "has_diagram": q.has_diagram,
                "page": q.page,
                "paper": parsed.paper,
            }
            for q in ex.questions
            if q.text.strip()
        ]
        if a.questions:
            ratings = classifier.classify_difficulty(a.questions, a.subject)
            for q, (difficulty, reason) in zip(a.questions, ratings):
                q["difficulty"], q["difficulty_reason"] = difficulty, reason
                q["section"] = classifier.assign_section(q["question_type"], q["marks"], q["stem_context"])
    elif doc_type == "ms":
        a.ms_entries = [e.model_dump() for e in extractor.extract_mark_scheme(doc).entries]
    elif doc_type == "in":
        a.insert_text = "\n\n".join(p.text for p in doc.pages if p.text)
    else:  # notes
        ex = extractor.extract_notes(doc, subject if subject != "unknown" else None)
        if a.subject == "unknown":
            a.subject, a.subject_code = _resolve_subject(parsed, ex.subject)
        a.notes = [s.model_dump() for s in ex.sections if s.text.strip()]
    return a


# --- Phase 2: storage (main thread) -------------------------------------------------
def _unit(v: list[float]) -> np.ndarray:
    arr = np.asarray(v, dtype=np.float32)
    n = np.linalg.norm(arr)
    return arr / n if n else arr


def _store_questions(a: _Analysis, res: FileResult, emit: EventCallback) -> None:
    stem = _safe_id(a.path.stem)
    paper_key = a.parsed.paper_key
    used_ids: set[str] = set()
    rows: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    for q in a.questions:
        full = f"{q['stem_context']}\n{q['text']}".strip()
        h = cleaner.content_hash(full)
        if h in seen_hashes or catalog.question_hash_exists(h):
            res.duplicates += 1
            continue
        seen_hashes.add(h)
        qid = f"{stem}_q{catalog.norm_number(q['number']) or 'x'}"
        base, n = qid, 2
        while qid in used_ids:
            qid, n = f"{base}_{n}", n + 1
        used_ids.add(qid)
        rows.append({**q, "question_id": qid, "full": full, "content_hash": h})

    if not rows:
        return

    # Near-duplicate check against this subject's existing questions (cosine >= DEDUP_SIMILARITY).
    vectors = pinecone_store.embed([r["full"] for r in rows])
    existing_ids, existing = catalog.subject_embeddings(a.subject)
    kept: list[dict[str, Any]] = []
    kept_vecs: list[np.ndarray] = []
    for r, v in zip(rows, vectors):
        u = _unit(v)
        if existing.size and float(np.max(existing @ u)) >= config.DEDUP_SIMILARITY:
            res.duplicates += 1
            continue
        # Within one file, sibling parts share a stem, so only compare across different parent questions.
        if any(
            float(kv @ u) >= config.DEDUP_SIMILARITY and k["parent_number"] != r["parent_number"]
            for k, kv in zip(kept, kept_vecs)
        ):
            res.duplicates += 1
            continue
        r["embedding"] = u
        kept.append(r)
        kept_vecs.append(u)

    res.diagrams += images.crop_diagrams(a.path, kept)

    has_ms = catalog.has_mark_scheme(paper_key)
    records: list[dict[str, Any]] = []
    db_rows: list[dict[str, Any]] = []
    for r in kept:
        meta = {
            "question_id": r["question_id"],
            "question_text": r["full"][:1000],
            "subject": a.subject,
            "subject_code": a.subject_code,
            "topic": r["topic"],
            "difficulty": r["difficulty"],
            "question_type": r["question_type"],
            "section": r["section"],
            "marks": r["marks"],
            "year": a.year,
            "session": a.parsed.session,
            "paper": a.parsed.paper,
            "variant": a.parsed.variant,
            "source_file": a.path.name,
            "page": r["page"],
            "has_diagram": bool(r.get("image_paths")),
            "image_paths": r.get("image_paths") or [],
            "has_mark_scheme": has_ms,
        }
        for i, chunk in enumerate(chunker.split(f"{a.subject} | {r['topic']}\n{r['full']}")):
            records.append({"_id": f"{r['question_id']}#c{i}", "chunk_text": chunk, **meta})
        db_rows.append(
            {
                "question_id": r["question_id"],
                "file_id": a.file_id,
                "source_file": a.path.name,
                "paper_key": paper_key,
                "number": r["number"],
                "number_norm": catalog.norm_number(r["number"]),
                "parent_number": r["parent_number"],
                "stem_context": r["stem_context"],
                "text": r["text"],
                "marks": r["marks"],
                "question_type": r["question_type"],
                "command_word": r["command_word"],
                "subject": a.subject,
                "subject_code": a.subject_code,
                "topic": r["topic"],
                "difficulty": r["difficulty"],
                "difficulty_reason": r["difficulty_reason"],
                "section": r["section"],
                "year": a.year,
                "session": a.parsed.session,
                "paper": a.parsed.paper,
                "variant": a.parsed.variant,
                "page": r["page"],
                "image_paths": r.get("image_paths") or [],
                "content_hash": r["content_hash"],
                "embedding": r["embedding"],
            }
        )
    res.chunks += pinecone_store.upsert(config.NS_QUESTIONS, records)
    catalog.insert_questions(db_rows)
    res.questions = len(db_rows)


def _store_notes(a: _Analysis, res: FileResult) -> None:
    stem = _safe_id(a.path.stem)
    sections = chunker.merge_small(a.notes)
    records: list[dict[str, Any]] = []
    db_rows: list[dict[str, Any]] = []
    for s_idx, sec in enumerate(sections):
        for c_idx, chunk in enumerate(chunker.split(sec["text"])):
            cid = f"notes_{stem}_p{sec['page']}_s{s_idx}_c{c_idx}"
            meta = {
                "chunk_id": cid,
                "subject": a.subject,
                "topic": sec["topic"],
                "content_type": sec["content_type"],
                "keywords": sec["keywords"],
                "source_file": a.path.name,
                "page": sec["page"],
            }
            records.append({"_id": cid, "chunk_text": f"{a.subject} | {sec['topic']}\n{chunk}", **meta})
            db_rows.append(
                {**meta, "file_id": a.file_id, "text": chunk, "content_hash": cleaner.content_hash(chunk)}
            )
    res.chunks += pinecone_store.upsert(config.NS_NOTES, records)
    catalog.insert_notes(db_rows)
    res.notes = len(db_rows)


def _store(a: _Analysis, res: FileResult, emit: EventCallback) -> None:
    res.doc_type, res.subject = a.doc_type, a.subject
    if a.doc_type == "qp":
        _store_questions(a, res, emit)
    elif a.doc_type == "ms":
        if not a.parsed.paper_key:
            raise ValueError("Mark scheme file name doesn't follow the CAIE pattern, so it can't be linked to its paper.")
        res.ms_entries = catalog.insert_mark_scheme(a.parsed.paper_key, a.file_id, a.ms_entries)
    elif a.doc_type == "in":
        if not a.parsed.paper_key:
            raise ValueError("Insert file name doesn't follow the CAIE pattern, so it can't be linked to its paper.")
        catalog.save_insert(a.parsed.paper_key, a.file_id, a.insert_text)
    else:
        _store_notes(a, res)


# --- Run -----------------------------------------------------------------------------
def _setup_file_log() -> tuple[logging.Handler, Path]:
    path = config.LOG_DIR / f"ingest_{datetime.now():%Y%m%d_%H%M%S}.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    return handler, path


_run_lock = threading.Lock()


def ingest_folder(folder: str | Path, force: bool = False, on_event: EventCallback | None = None) -> RunSummary:
    """Ingest a folder. Only one run at a time: a second call while one is running raises IngestError."""
    if not _run_lock.acquire(blocking=False):
        raise IngestError(
            "An ingestion run is already in progress (perhaps in another browser tab). "
            "Wait for it to finish, then retry."
        )
    try:
        return _ingest_folder(folder, force, on_event)
    finally:
        _run_lock.release()


def _ingest_folder(folder: str | Path, force: bool, on_event: EventCallback | None) -> RunSummary:
    def emit(level: str, msg: str) -> None:
        getattr(log, level if level in ("info", "warning", "error") else "info")(msg)
        if on_event:
            on_event(level, msg)

    files = discover(folder)
    missing = [k for k in config.missing_keys() if k != "TAVILY_API_KEY"]
    if missing:
        raise IngestError(f"Missing API key(s): {', '.join(missing)}. Add them to the .env file.")
    catalog.init_db()
    handler, log_path = _setup_file_log()
    run_id = catalog.start_run(str(folder))
    summary = RunSummary(run_id, str(folder), str(log_path))
    try:
        emit("info", f"Found {len(files)} supported file(s) in `{folder}`.")
        emit("info", "Connecting to Pinecone index…")
        pinecone_store.index()

        # Work out which files need processing.
        todo: list[tuple[Path, str, FileResult]] = []
        for path in files:
            res = FileResult(path.name)
            summary.files.append(res)
            fid = cleaner.file_hash(path)
            existing = catalog.get_file(fid)
            if existing and existing["status"] == "ingested" and not force:
                res.status, res.doc_type, res.subject = "skipped", existing["doc_type"] or "", existing["subject"] or ""
                res.message = "Unchanged since last ingestion."
                emit("info", f"Skipping {path.name}: unchanged since last ingestion.")
                continue
            # Changed or forced: remove previous versions of this file everywhere.
            removed = catalog.delete_files_by_path(str(path))
            if existing:
                catalog.delete_file(fid)
            if removed or existing:
                pinecone_store.delete_by_source(path.name)
                emit("info", f"Re-ingesting {path.name}: removed its previous records.")
            todo.append((path, fid, res))

        # Mark schemes and inserts go last so question papers in the same run see them.
        order = {"qp": 0, "notes": 1, None: 1, "ms": 2, "in": 2}
        todo.sort(key=lambda t: order.get(filename_parser.parse(t[0]).doc_type, 1))
        emit("info", f"{len(todo)} file(s) to process, {len(files) - len(todo)} skipped.")

        with ThreadPoolExecutor(max_workers=max(1, config.MAX_CONCURRENCY)) as pool:
            futures = {}
            for path, fid, res in todo:
                parsed = filename_parser.parse(path)
                if parsed.matched:
                    emit(
                        "info",
                        f"Parsing {path.name}: detected {parsed.subject or parsed.subject_code}, "
                        f"{parsed.session} {parsed.year}, paper {parsed.paper or '?'}"
                        f"{(' variant ' + parsed.variant) if parsed.variant else ''} ({parsed.doc_type}).",
                    )
                else:
                    emit("info", f"Parsing {path.name}: name isn't a CAIE code; the LLM will infer the details.")
                futures[pool.submit(_analyse, path, fid)] = (path, fid, res)

            for fut in as_completed(futures):
                path, fid, res = futures[fut]
                try:
                    a = fut.result()
                    # The file row must exist before questions/notes reference it (foreign key).
                    catalog.upsert_file(
                        file_id=fid, path=str(path), file_name=path.name, doc_type=a.doc_type,
                        subject=a.subject, subject_code=a.subject_code, year=a.year,
                        session=a.parsed.session, paper=a.parsed.paper, variant=a.parsed.variant,
                        paper_key=a.parsed.paper_key, status="processing", error=None,
                    )
                    _store(a, res, emit)
                    res.status = "ingested"
                    catalog.upsert_file(
                        file_id=fid, status="ingested", questions=res.questions, notes=res.notes, chunks=res.chunks,
                        path=str(path), file_name=path.name,
                    )
                    detail = {
                        "qp": f"{res.questions} questions, {res.duplicates} duplicates dropped, {res.diagrams} diagrams",
                        "ms": f"{res.ms_entries} mark-scheme answers",
                        "in": "insert linked to its paper",
                        "notes": f"{res.notes} note chunks",
                    }[a.doc_type]
                    emit("info", f"✓ {path.name} ({a.subject}): {detail}, {res.chunks} chunks.")
                    if a.subject == "unknown":
                        emit("warning", f"{path.name}: subject could not be detected; stored as 'unknown'.")
                except Exception as exc:  # one bad file never stops the run
                    res.status, res.message = "failed", str(exc)
                    res.questions = res.notes = res.chunks = res.diagrams = 0
                    log.exception("Failed: %s", path)
                    # Roll back anything partly stored so a retry starts clean.
                    catalog.delete_file(fid)
                    pinecone_store.delete_by_source(path.name)
                    catalog.upsert_file(
                        file_id=fid, path=str(path), file_name=path.name, status="failed", error=str(exc)
                    )
                    emit("error", f"✗ {path.name}: {exc}")
    finally:
        catalog.finish_run(
            run_id,
            {
                "files_found": len(summary.files),
                "files_processed": summary.status_count("ingested"),
                "files_skipped": summary.status_count("skipped"),
                "files_failed": summary.status_count("failed"),
                "questions_extracted": summary.count("questions"),
                "notes_extracted": summary.count("notes"),
                "chunks_created": summary.count("chunks"),
                "diagrams_cropped": summary.count("diagrams"),
                "duplicates_dropped": summary.count("duplicates"),
            },
        )
        logging.getLogger().removeHandler(handler)
        handler.close()
    emit(
        "info",
        f"Done. {summary.status_count('ingested')} ingested, {summary.status_count('skipped')} skipped, "
        f"{summary.status_count('failed')} failed; {summary.count('questions')} questions, "
        f"{summary.count('notes')} note chunks, {summary.count('chunks')} vectors.",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest IGCSE papers and notes into Pinecone.")
    parser.add_argument("folder", nargs="?", default=str(config.DATA_DIR))
    parser.add_argument("--force", action="store_true", help="Re-ingest files even if unchanged.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        summary = ingest_folder(args.folder, force=args.force)
    except IngestError as exc:
        raise SystemExit(f"Error: {exc}")
    print(f"Log written to {summary.log_path}")


if __name__ == "__main__":
    main()
