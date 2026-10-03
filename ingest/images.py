"""Crop diagrams, graphs and tables from PDF pages and attach them to questions.

Heuristic: on each page, find image and vector-drawing regions, merge nearby ones into
figures, then give each figure to the diagram question that starts closest above it.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pymupdf as fitz

import config

log = logging.getLogger(__name__)

MIN_W, MIN_H = 60, 40  # points; smaller regions are rules, boxes or bullets
MERGE_GAP = 12  # points between regions that belong to the same figure


def _figure_regions(page: fitz.Page) -> list[fitz.Rect]:
    rects: list[fitz.Rect] = []
    for info in page.get_image_info():
        rects.append(fitz.Rect(info["bbox"]))
    for d in page.get_drawings():
        r = fitz.Rect(d["rect"])
        if r.width < 2 and r.height < 2:
            continue
        # Skip long thin lines: answer lines and page rules.
        if r.height < 3 or r.width < 3:
            continue
        rects.append(r)
    page_rect = page.rect
    rects = [r & page_rect for r in rects if not r.is_empty]
    # Ignore page borders / margin frames that cover most of the page.
    rects = [r for r in rects if r.get_area() < 0.8 * page_rect.get_area()]

    merged: list[fitz.Rect] = []
    for r in sorted(rects, key=lambda x: (x.y0, x.x0)):
        grown = fitz.Rect(r.x0 - MERGE_GAP, r.y0 - MERGE_GAP, r.x1 + MERGE_GAP, r.y1 + MERGE_GAP)
        for m in merged:
            if m.intersects(grown):
                m |= r
                break
        else:
            merged.append(fitz.Rect(r))
    # A second pass joins figures that grew into each other.
    changed = True
    while changed:
        changed = False
        for i in range(len(merged)):
            for j in range(i + 1, len(merged)):
                if merged[i].intersects(merged[j]):
                    merged[i] |= merged[j]
                    del merged[j]
                    changed = True
                    break
            if changed:
                break
    return [m for m in merged if m.width >= MIN_W and m.height >= MIN_H]


def _question_y(page: fitz.Page, q: dict) -> float | None:
    """Vertical position where the question starts on the page: its stem if present, else its own text.

    Figures usually sit between the stem ("Fig. 2.1 shows...") and the part text, so the earliest match wins.
    """
    ys: list[float] = []
    for probe in (q.get("stem_context") or "", q["text"]):
        snippet = " ".join(probe.split()[:6])
        if len(snippet) < 8:
            continue
        hits = page.search_for(snippet)
        if hits:
            ys.append(hits[0].y0)
    return min(ys) if ys else None


def crop_diagrams(pdf_path: Path, questions: list[dict]) -> int:
    """Set q['image_paths'] for questions with has_diagram. Returns the number of images saved."""
    wanted = [q for q in questions if q.get("has_diagram")]
    if not wanted or pdf_path.suffix.lower() != ".pdf":
        return 0
    saved = 0
    with fitz.open(pdf_path) as pdf:
        by_page: dict[int, list[dict]] = {}
        for q in wanted:
            by_page.setdefault(q["page"], []).append(q)
        for page_no, qs in by_page.items():
            # A figure for a question can sit on the same page or the next one.
            for pno in (page_no, page_no + 1):
                if not 1 <= pno <= pdf.page_count:
                    continue
                page = pdf[pno - 1]
                figures = _figure_regions(page)
                if not figures:
                    continue
                ys = [(q, _question_y(page, q) if pno == page_no else -1.0) for q in qs]
                for fig in figures:
                    # Owner: the question whose start is the closest above the figure's bottom edge.
                    candidates = [(q, y) for q, y in ys if y is not None and y <= fig.y1]
                    if candidates:
                        owner = max(candidates, key=lambda t: t[1])[0]
                    elif all(y is None for _, y in ys):
                        owner = qs[0]  # couldn't locate any question text; best guess
                    else:
                        continue  # figure sits above every diagram question: belongs to another question
                    if pno != page_no and owner.get("image_paths"):
                        continue  # already found its figure on its own page
                    out = config.IMAGES_DIR / f"{owner['question_id']}_{len(owner.setdefault('image_paths', [])) + 1}.png"
                    clip = fitz.Rect(fig.x0 - 4, fig.y0 - 4, fig.x1 + 4, fig.y1 + 4) & page.rect
                    page.get_pixmap(clip=clip, dpi=150).save(out)
                    owner["image_paths"].append(out.relative_to(config.DATA_DIR).as_posix())
                    saved += 1
                if any(q.get("image_paths") for q in qs):
                    break
    return saved
