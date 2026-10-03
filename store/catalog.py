"""SQLite catalog: the source of truth for question text, mark schemes, images and ingestion history."""
from __future__ import annotations

import json
import random
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterable, Iterator

import numpy as np

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  file_id        TEXT PRIMARY KEY,
  path           TEXT NOT NULL,
  file_name      TEXT NOT NULL,
  doc_type       TEXT,
  subject        TEXT, subject_code TEXT,
  year INTEGER, session TEXT, paper TEXT, variant TEXT,
  paper_key      TEXT,
  status         TEXT,
  error          TEXT,
  questions      INTEGER DEFAULT 0,
  notes          INTEGER DEFAULT 0,
  chunks         INTEGER DEFAULT 0,
  ingested_at    TEXT
);

CREATE TABLE IF NOT EXISTS questions (
  question_id    TEXT PRIMARY KEY,
  file_id        TEXT REFERENCES files(file_id) ON DELETE CASCADE,
  source_file    TEXT,
  paper_key      TEXT,
  number         TEXT, number_norm TEXT, parent_number TEXT,
  stem_context   TEXT,
  text           TEXT NOT NULL,
  marks          INTEGER,
  question_type  TEXT, command_word TEXT,
  subject        TEXT, subject_code TEXT,
  topic          TEXT, difficulty TEXT, difficulty_reason TEXT,
  section        TEXT,
  year INTEGER, session TEXT, paper TEXT, variant TEXT,
  page           INTEGER,
  image_paths    TEXT,
  content_hash   TEXT UNIQUE,
  embedding      BLOB
);
CREATE INDEX IF NOT EXISTS ix_q_subject ON questions(subject);
CREATE INDEX IF NOT EXISTS ix_q_paper ON questions(paper_key);

CREATE TABLE IF NOT EXISTS mark_schemes (
  paper_key      TEXT,
  number         TEXT,
  number_norm    TEXT,
  answer         TEXT,
  marks          INTEGER,
  file_id        TEXT REFERENCES files(file_id) ON DELETE CASCADE,
  PRIMARY KEY (paper_key, number_norm)
);

CREATE TABLE IF NOT EXISTS inserts (
  paper_key      TEXT PRIMARY KEY,
  text           TEXT,
  file_id        TEXT REFERENCES files(file_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notes (
  chunk_id       TEXT PRIMARY KEY,
  file_id        TEXT REFERENCES files(file_id) ON DELETE CASCADE,
  source_file    TEXT,
  subject TEXT, topic TEXT, content_type TEXT,
  keywords TEXT, page INTEGER, text TEXT,
  content_hash   TEXT
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  folder TEXT,
  started_at TEXT, finished_at TEXT,
  files_found INTEGER, files_processed INTEGER, files_skipped INTEGER, files_failed INTEGER,
  questions_extracted INTEGER, notes_extracted INTEGER,
  chunks_created INTEGER, diagrams_cropped INTEGER, duplicates_dropped INTEGER
);
"""


def norm_number(number: str) -> str:
    """'3(b)(ii)' / '3 b ii' / '3bii' -> '3bii' so question and mark-scheme numbers line up."""
    return re.sub(r"[^0-9a-z]", "", (number or "").lower())


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


# --- Files -----------------------------------------------------------------
def get_file(file_id: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM files WHERE file_id = ?", (file_id,)).fetchone()


def delete_file(file_id: str) -> None:
    """Remove a file and (via cascade) everything extracted from it."""
    with connect() as conn:
        conn.execute("DELETE FROM files WHERE file_id = ?", (file_id,))


def delete_files_by_path(path: str) -> list[str]:
    """Remove older versions of a file at the same path. Returns the removed file_names."""
    with connect() as conn:
        rows = conn.execute("SELECT file_id, file_name FROM files WHERE path = ?", (path,)).fetchall()
        conn.execute("DELETE FROM files WHERE path = ?", (path,))
    return [r["file_name"] for r in rows]


def upsert_file(**fields: Any) -> None:
    """Insert or update a file row in place.

    A true upsert, not INSERT OR REPLACE: REPLACE deletes the old row first, which would
    cascade-delete the questions and notes already stored for this file.
    """
    fields.setdefault("ingested_at", datetime.now().isoformat(timespec="seconds"))
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    updates = ", ".join(f"{c} = excluded.{c}" for c in fields if c != "file_id")
    with connect() as conn:
        conn.execute(
            f"INSERT INTO files ({cols}) VALUES ({marks}) ON CONFLICT(file_id) DO UPDATE SET {updates}",
            tuple(fields.values()),
        )


# --- Questions ---------------------------------------------------------------
def question_hash_exists(content_hash: str) -> bool:
    with connect() as conn:
        return conn.execute("SELECT 1 FROM questions WHERE content_hash = ?", (content_hash,)).fetchone() is not None


def insert_questions(rows: Iterable[dict[str, Any]]) -> None:
    with connect() as conn:
        for row in rows:
            row = dict(row)
            row["image_paths"] = json.dumps(row.get("image_paths") or [])
            emb = row.pop("embedding", None)
            row["embedding"] = np.asarray(emb, dtype=np.float32).tobytes() if emb is not None else None
            cols = ", ".join(row)
            marks = ", ".join("?" for _ in row)
            conn.execute(f"INSERT OR REPLACE INTO questions ({cols}) VALUES ({marks})", tuple(row.values()))


def subject_embeddings(subject: str) -> tuple[list[str], np.ndarray]:
    """IDs and an (n, d) matrix of stored question embeddings for one subject."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT question_id, embedding FROM questions WHERE subject = ? AND embedding IS NOT NULL", (subject,)
        ).fetchall()
    if not rows:
        return [], np.zeros((0, 0), dtype=np.float32)
    return [r["question_id"] for r in rows], np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])


def _question_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["image_paths"] = json.loads(d.get("image_paths") or "[]")
    emb = d.pop("embedding", None)
    d["embedding"] = np.frombuffer(emb, dtype=np.float32) if emb else None
    return d


def get_questions(question_ids: list[str]) -> list[dict[str, Any]]:
    if not question_ids:
        return []
    with connect() as conn:
        marks = ",".join("?" for _ in question_ids)
        rows = conn.execute(f"SELECT * FROM questions WHERE question_id IN ({marks})", question_ids).fetchall()
    by_id = {r["question_id"]: _question_dict(r) for r in rows}
    return [by_id[q] for q in question_ids if q in by_id]


def _filter_sql(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses, params = [], []
    if filters.get("subject"):
        clauses.append("subject = ?")
        params.append(filters["subject"])
    if filters.get("topics"):
        clauses.append(f"topic IN ({','.join('?' for _ in filters['topics'])})")
        params.extend(filters["topics"])
    if filters.get("difficulty") and filters["difficulty"] != "mixed":
        clauses.append("difficulty = ?")
        params.append(filters["difficulty"])
    if filters.get("sections"):
        clauses.append(f"section IN ({','.join('?' for _ in filters['sections'])})")
        params.extend(filters["sections"])
    if filters.get("year_from"):
        clauses.append("year >= ?")
        params.append(filters["year_from"])
    if filters.get("year_to"):
        clauses.append("year <= ?")
        params.append(filters["year_to"])
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def count_questions(filters: dict[str, Any]) -> int:
    where, params = _filter_sql(filters)
    with connect() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM questions{where}", params).fetchone()[0]


def sample_question_ids(filters: dict[str, Any], n: int, seed: int) -> list[str]:
    """Reproducible random sample of question IDs matching the filters."""
    where, params = _filter_sql(filters)
    with connect() as conn:
        ids = [r[0] for r in conn.execute(f"SELECT question_id FROM questions{where} ORDER BY question_id", params)]
    rng = random.Random(seed)
    rng.shuffle(ids)
    return ids[:n]


# --- Mark schemes & inserts ---------------------------------------------------
def insert_mark_scheme(paper_key: str, file_id: str, entries: Iterable[dict[str, Any]]) -> int:
    count = 0
    with connect() as conn:
        for e in entries:
            conn.execute(
                "INSERT OR REPLACE INTO mark_schemes (paper_key, number, number_norm, answer, marks, file_id)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (paper_key, e["number"], norm_number(e["number"]), e["answer"], e.get("marks"), file_id),
            )
            count += 1
    return count


def mark_scheme_answer(paper_key: str | None, number: str) -> str | None:
    """Exact match on the question number, else every sub-part under it joined together."""
    if not paper_key:
        return None
    n = norm_number(number)
    with connect() as conn:
        row = conn.execute(
            "SELECT answer FROM mark_schemes WHERE paper_key = ? AND number_norm = ?", (paper_key, n)
        ).fetchone()
        if row:
            return row["answer"]
        rows = conn.execute(
            "SELECT number, answer FROM mark_schemes WHERE paper_key = ? AND number_norm LIKE ? ORDER BY number_norm",
            (paper_key, n + "%"),
        ).fetchall()
    # Guard against '1' matching '10', '11', ...: the next character after the prefix must be a letter.
    rows = [r for r in rows if len(norm_number(r["number"])) == len(n) or not norm_number(r["number"])[len(n)].isdigit()]
    if not rows:
        return None
    return "\n".join(f"{r['number']}: {r['answer']}" for r in rows)


def has_mark_scheme(paper_key: str | None) -> bool:
    if not paper_key:
        return False
    with connect() as conn:
        return conn.execute("SELECT 1 FROM mark_schemes WHERE paper_key = ? LIMIT 1", (paper_key,)).fetchone() is not None


def save_insert(paper_key: str, file_id: str, text: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO inserts (paper_key, text, file_id) VALUES (?, ?, ?)", (paper_key, text, file_id)
        )


def get_insert(paper_key: str | None) -> str | None:
    if not paper_key:
        return None
    with connect() as conn:
        row = conn.execute("SELECT text FROM inserts WHERE paper_key = ?", (paper_key,)).fetchone()
    return row["text"] if row else None


# --- Notes -------------------------------------------------------------------
def insert_notes(rows: Iterable[dict[str, Any]]) -> None:
    with connect() as conn:
        for row in rows:
            row = dict(row)
            row["keywords"] = json.dumps(row.get("keywords") or [])
            cols = ", ".join(row)
            marks = ", ".join("?" for _ in row)
            conn.execute(f"INSERT OR REPLACE INTO notes ({cols}) VALUES ({marks})", tuple(row.values()))


# --- Lookups for the UI --------------------------------------------------------
def list_subjects() -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT subject FROM questions WHERE subject IS NOT NULL AND subject != 'unknown'"
            " UNION SELECT DISTINCT subject FROM notes WHERE subject IS NOT NULL AND subject != 'unknown'"
            " ORDER BY 1"
        ).fetchall()
    return [r[0] for r in rows]


def list_question_subjects() -> list[str]:
    with connect() as conn:
        rows = conn.execute("SELECT DISTINCT subject FROM questions WHERE subject IS NOT NULL ORDER BY 1").fetchall()
    return [r[0] for r in rows]


def list_topics(subject: str) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT topic FROM questions WHERE subject = ? AND topic IS NOT NULL AND topic != '' ORDER BY 1",
            (subject,),
        ).fetchall()
    return [r[0] for r in rows]


def year_range(subject: str) -> tuple[int, int] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT MIN(year), MAX(year) FROM questions WHERE subject = ? AND year IS NOT NULL", (subject,)
        ).fetchone()
    return (row[0], row[1]) if row and row[0] else None


def subject_code_for(subject: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT subject_code FROM questions WHERE subject = ? AND subject_code IS NOT NULL LIMIT 1", (subject,)
        ).fetchone()
    return row[0] if row else None


def stats() -> dict[str, int]:
    with connect() as conn:
        return {
            "files": conn.execute("SELECT COUNT(*) FROM files WHERE status = 'ingested'").fetchone()[0],
            "questions": conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0],
            "notes": conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0],
            "mark_schemes": conn.execute("SELECT COUNT(DISTINCT paper_key) FROM mark_schemes").fetchone()[0],
        }


def subject_breakdown() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT subject, COUNT(*) AS questions,"
            " SUM(difficulty='easy') AS easy, SUM(difficulty='medium') AS medium, SUM(difficulty='hard') AS hard,"
            " SUM(section='A') AS section_a, SUM(section='B') AS section_b, SUM(section='C') AS section_c"
            " FROM questions GROUP BY subject ORDER BY subject"
        ).fetchall()
    return [dict(r) for r in rows]


# --- Ingestion runs -------------------------------------------------------------
def start_run(folder: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO ingestion_runs (folder, started_at) VALUES (?, ?)",
            (folder, datetime.now().isoformat(timespec="seconds")),
        )
        return int(cur.lastrowid)


def finish_run(run_id: int, counts: dict[str, int]) -> None:
    sets = ", ".join(f"{k} = ?" for k in counts)
    with connect() as conn:
        conn.execute(
            f"UPDATE ingestion_runs SET finished_at = ?, {sets} WHERE run_id = ?",
            (datetime.now().isoformat(timespec="seconds"), *counts.values(), run_id),
        )
