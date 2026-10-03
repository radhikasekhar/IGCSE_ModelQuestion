"""Generate Paper tab: filters -> retrieval -> exam-ready paper with PDF/DOCX and mark-scheme downloads."""
import re
from datetime import datetime
from pathlib import Path

import streamlit as st

import config
from paper import assembler, export_docx, export_pdf
from paper.assembler import md_escape
from paper.retriever import PaperRequest, ValidationError, select
from store import catalog

st.title("Generate a model question paper")

subjects = catalog.list_question_subjects()
if not subjects:
    st.info("No questions ingested yet. Go to **Ingest** and add some question papers first.", icon=":material/info:")
    st.stop()

subject = st.selectbox("Subject", subjects)
topics_available = catalog.list_topics(subject)
years = catalog.year_range(subject)

with st.form("paper"):
    c1, c2, c3 = st.columns(3)
    num = c1.number_input("Number of questions", min_value=1, max_value=config.MAX_QUESTIONS_PER_PAPER, value=20)
    difficulty = c2.segmented_control("Difficulty", ["mixed", "easy", "medium", "hard"], default="mixed")
    ordering = c3.selectbox(
        "Ordering", ["shuffle", "difficulty", "topic"],
        format_func={"shuffle": "Random (shuffled)", "difficulty": "Easy → hard", "topic": "By topic"}.get,
    )
    topics = st.multiselect("Chapters / topics (optional)", topics_available)
    focus = st.text_input(
        "Focus (optional)", placeholder="e.g. moments and levers - uses semantic search instead of random sampling"
    )
    if years and years[0] != years[1]:
        year_from, year_to = st.slider("Years", years[0], years[1], (years[0], years[1]))
    else:
        year_from = year_to = None

    st.markdown("**Sections**")
    use_sections = st.toggle("Group into Sections A (short), B (long), C (application)", value=True)
    s1, s2, s3 = st.columns(3)
    count_a = s1.number_input("Section A questions", 0, 60, 0)
    count_b = s2.number_input("Section B questions", 0, 60, 0)
    count_c = s3.number_input("Section C questions", 0, 60, 0)
    st.caption("Leave all three at 0 for the default 40% / 40% / 20% split. "
               "Otherwise the counts must add up to the number of questions.")

    with st.expander("Paper details"):
        instructions = st.text_area("Instructions (one per line, leave empty for none)",
                                    "\n".join(config.DEFAULT_INSTRUCTIONS))
        d1, d2, d3 = st.columns(3)
        duration = d1.number_input("Duration in minutes (0 = 1 minute per mark)", 0, 300, 0)
        seed_text = d2.text_input("Seed (optional, to reproduce a paper)")
        show_sources = d3.toggle("Show source references", value=False)

    submitted = st.form_submit_button("Generate paper", icon=":material/auto_awesome:", type="primary")

if submitted:
    counts = {"A": int(count_a), "B": int(count_b), "C": int(count_c)}
    if sum(counts.values()) == 0:
        counts = None
    seed = None
    if seed_text.strip():
        if not seed_text.strip().isdigit():
            st.error("Seed must be a whole number.", icon=":material/error:")
            st.stop()
        seed = int(seed_text.strip())
    req = PaperRequest(
        subject=subject, num_questions=int(num), topics=topics, difficulty=difficulty or "mixed",
        year_from=year_from, year_to=year_to, focus=focus, use_sections=use_sections,
        section_counts=counts, seed=seed,
    )
    with st.status("Building paper…", expanded=True) as status:
        try:
            selection = select(req)
        except ValidationError as exc:
            status.update(label="Couldn't build the paper", state="error")
            st.error(str(exc), icon=":material/error:")
            st.stop()
        for step in selection.steps:
            st.write(step)
        st.write("Assembling sections, numbering and marks…")
        paper = assembler.assemble(
            selection.questions, subject=subject, seed=selection.seed, use_sections=use_sections,
            ordering=ordering, show_sources=show_sources,
            instructions=[ln.strip() for ln in instructions.splitlines() if ln.strip()],
            duration_minutes=int(duration) or None,
        )
        st.write("Rendering PDF and Word files…")
        stamp = f"{re.sub(r'[^A-Za-z0-9]+', '_', subject)}_{datetime.now():%Y%m%d_%H%M%S}"
        files = {
            "paper.pdf": export_pdf.build(paper),
            "paper.docx": export_docx.build(paper),
            "ms.pdf": export_pdf.build(paper, answers=True),
            "ms.docx": export_docx.build(paper, answers=True),
        }
        for name, data in files.items():
            kind, ext = name.split(".")
            suffix = "" if kind == "paper" else "_mark_scheme"
            (config.OUTPUT_DIR / f"{stamp}{suffix}.{ext}").write_bytes(data)
        status.update(label=f"Paper ready: {len(paper.all_questions)} questions, {paper.total_marks} marks",
                      state="complete", expanded=False)
    st.session_state.generated_paper = {"paper": paper, "files": files, "stamp": stamp, "warnings": selection.warnings}

result = st.session_state.get("generated_paper")
if result:
    paper = result["paper"]
    for w in result["warnings"]:
        st.warning(w, icon=":material/warning:")

    stamp = result["stamp"]
    b1, b2, b3, b4 = st.columns(4)
    b1.download_button("Paper (PDF)", result["files"]["paper.pdf"], f"{stamp}.pdf", "application/pdf",
                       icon=":material/picture_as_pdf:", type="primary")
    docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    b2.download_button("Paper (DOCX)", result["files"]["paper.docx"], f"{stamp}.docx", docx_mime,
                       icon=":material/article:")
    b3.download_button("Mark scheme (PDF)", result["files"]["ms.pdf"], f"{stamp}_mark_scheme.pdf",
                       "application/pdf", icon=":material/fact_check:")
    b4.download_button("Mark scheme (DOCX)", result["files"]["ms.docx"], f"{stamp}_mark_scheme.docx", docx_mime,
                       icon=":material/fact_check:")
    missing_ms = sum(1 for q in paper.all_questions if not q.ms_answer)
    if missing_ms:
        st.caption(f"{missing_ms} question(s) have no mark-scheme answer in the source documents.")
    st.caption(f"Saved to `{config.OUTPUT_DIR}` · seed {paper.seed} (enter it again to reproduce this paper)")

    tab_paper, tab_ms = st.tabs(["Paper preview", "Mark scheme preview"])
    with tab_paper, st.container(border=True):
        st.markdown(f"### {paper.title}")
        st.markdown(f"**{paper.subtitle}**")
        st.markdown(f"**Duration:** {assembler.format_duration(paper.duration_minutes)} · "
                    f"**Total marks:** {paper.total_marks}")
        if paper.instructions:
            st.markdown("**INSTRUCTIONS**\n" + "\n".join(f"- {md_escape(i)}" for i in paper.instructions))
        for sec in paper.sections:
            if sec.title:
                st.markdown(f"#### {sec.title}")
            for q in sec.questions:
                if q.stem_context:
                    st.markdown(f"**{q.number}.** {md_escape(q.stem_context)}")
                for img in q.image_paths:
                    if Path(img).exists():
                        st.image(img, width=480)
                prefix = "" if q.stem_context else f"**{q.number}.** "
                ref = f"  \n:gray[{md_escape(q.source_ref)}]" if paper.show_sources else ""
                st.markdown(f"{prefix}{md_escape(q.text)} **\\[{q.marks}\\]**{ref}")
    with tab_ms:
        st.markdown(assembler.to_markdown(paper, include_answers=True))
