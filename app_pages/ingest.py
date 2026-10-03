"""Ingest tab: point at a folder, watch progress, see a summary per file and per subject."""
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st

import config
from ingest.pipeline import IngestError, ingest_folder
from store import catalog

st.title("Ingest documents")
st.write(
    "Reads past papers, mark schemes, inserts and notes, extracts questions and topic notes with OpenAI, "
    "and stores them in Pinecone and the local catalog. Keep Cambridge file names (e.g. `0625_s23_qp_42.pdf`) "
    "so subject, year, session and paper are detected automatically."
)

def run_ingestion(folder, force: bool) -> None:
    log_box = st.status("Ingesting… don't click anything on this page until it finishes.", expanded=True)

    def on_event(level: str, msg: str) -> None:
        icon = {"warning": ":material/warning:", "error": ":material/error:"}.get(level, "")
        log_box.write(f"{icon} {msg}".strip())

    try:
        summary = ingest_folder(folder, force=force, on_event=on_event)
    except IngestError as exc:
        log_box.update(label="Ingestion stopped", state="error")
        st.error(str(exc), icon=":material/error:")
    except Exception as exc:  # unexpected (network, Pinecone) errors
        log_box.update(label="Ingestion failed", state="error")
        st.exception(exc)
    else:
        failed = summary.status_count("failed")
        log_box.update(
            label=f"Ingestion finished: {summary.status_count('ingested')} ingested, "
            f"{summary.status_count('skipped')} skipped, {failed} failed",
            state="error" if failed and not summary.status_count("ingested") else "complete",
            expanded=False,
        )
        st.session_state.last_summary = summary


DEST = {"Papers, mark schemes & inserts": config.PAPERS_DIR, "Notes": config.NOTES_DIR}

with st.form("upload", clear_on_submit=True):
    st.markdown("**Upload files**")
    kind = st.segmented_control("These files are", list(DEST), default=list(DEST)[0])
    uploads = st.file_uploader(
        "Drop files here",
        type=sorted(e.lstrip(".") for e in config.SUPPORTED_EXTS),
        accept_multiple_files=True,
    )
    upload_submitted = st.form_submit_button("Upload and ingest", icon=":material/upload:", type="primary")

if upload_submitted:
    if not uploads:
        st.warning("Choose at least one file to upload.", icon=":material/warning:")
    else:
        dest = DEST[kind or list(DEST)[0]]
        for f in uploads:
            (dest / Path(f.name).name).write_bytes(f.getvalue())  # .name drops any folder part
        st.success(f"Saved {len(uploads)} file(s) to {dest.relative_to(config.STORAGE_DIR)}.", icon=":material/check:")
        # Only new or changed files are processed; everything else is skipped.
        run_ingestion(config.DATA_DIR, force=False)

with st.expander("Re-scan the whole data folder"):
    with st.form("ingest"):
        folder = st.text_input("Folder to ingest", value=str(config.DATA_DIR))
        force = st.checkbox("Force re-ingest (process files even if unchanged)")
        submitted = st.form_submit_button("Start ingestion", icon=":material/play_arrow:")
    if submitted:
        run_ingestion(folder, force)

summary = st.session_state.get("last_summary")
if summary:
    st.subheader("Last run")
    cols = st.columns(6)
    cols[0].metric("Files found", len(summary.files))
    cols[1].metric("Processed", summary.status_count("ingested"))
    cols[2].metric("Skipped", summary.status_count("skipped"))
    cols[3].metric("Failed", summary.status_count("failed"))
    cols[4].metric("Questions", summary.count("questions"))
    cols[5].metric("Chunks", summary.count("chunks"))
    df = pd.DataFrame([asdict(f) for f in summary.files])
    st.dataframe(
        df,
        hide_index=True,
        column_config={
            "file_name": "File", "doc_type": "Type", "subject": "Subject", "status": "Status",
            "questions": "Questions", "notes": "Note chunks", "ms_entries": "MS answers", "chunks": "Vectors",
            "diagrams": "Diagrams", "duplicates": "Duplicates dropped", "message": "Message",
        },
    )
    st.caption(f"Log file: `{summary.log_path}`")

st.subheader("Catalog by subject")
breakdown = catalog.subject_breakdown()
if breakdown:
    st.dataframe(
        pd.DataFrame(breakdown),
        hide_index=True,
        column_config={
            "subject": "Subject", "questions": "Questions", "easy": "Easy", "medium": "Medium", "hard": "Hard",
            "section_a": "Section A", "section_b": "Section B", "section_c": "Section C",
        },
    )
else:
    st.info("Nothing ingested yet.", icon=":material/info:")
