"""Export a Paper (or its mark scheme) to a print-ready PDF with ReportLab."""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from paper.assembler import Paper, format_duration

_TEXT_WIDTH = A4[0] - 4.4 * cm


@lru_cache(maxsize=1)
def _fonts() -> tuple[str, str]:
    """A Unicode font (symbols like ², √, Ω, θ): Arial on Windows, DejaVu Sans on Linux/Docker, else Helvetica."""
    candidates = [
        (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
         Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
    ]
    for regular, bold in candidates:
        if regular.exists() and bold.exists():
            pdfmetrics.registerFont(TTFont("PaperSans", str(regular)))
            pdfmetrics.registerFont(TTFont("PaperSans-Bold", str(bold)))
            pdfmetrics.registerFontFamily("PaperSans", normal="PaperSans", bold="PaperSans-Bold")
            return "PaperSans", "PaperSans-Bold"
    return "Helvetica", "Helvetica-Bold"


def _styles() -> dict[str, ParagraphStyle]:
    reg, bold = _fonts()
    return {
        "title": ParagraphStyle("title", fontName=bold, fontSize=16, leading=20, alignment=TA_CENTER),
        "subtitle": ParagraphStyle("subtitle", fontName=reg, fontSize=11, leading=14, alignment=TA_CENTER),
        "body": ParagraphStyle("body", fontName=reg, fontSize=10.5, leading=14),
        "bold": ParagraphStyle("bold", fontName=bold, fontSize=10.5, leading=14),
        "marks": ParagraphStyle("marks", fontName=bold, fontSize=10.5, leading=14, alignment=TA_RIGHT),
        "section": ParagraphStyle("section", fontName=bold, fontSize=12.5, leading=16, spaceBefore=12, spaceAfter=6,
                                  keepWithNext=1),
        "ref": ParagraphStyle("ref", fontName=reg, fontSize=7.5, leading=9, textColor=colors.grey),
        "answer": ParagraphStyle("answer", fontName=reg, fontSize=10, leading=13, textColor=colors.HexColor("#1f3b6f")),
    }


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def _image(path: str, max_w: float = 12 * cm, max_h: float = 9 * cm) -> Image | None:
    if not Path(path).exists():
        return None
    w, h = ImageReader(path).getSize()
    if not w or not h:
        return None
    scale = min(max_w / w, max_h / h)
    img = Image(path, width=w * scale, height=h * scale)
    img.hAlign = "CENTER"
    return img


def build(paper: Paper, answers: bool = False) -> bytes:
    st = _styles()
    buf = io.BytesIO()
    reg, _ = _fonts()

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(reg, 7.5)
        canvas.setFillColor(colors.grey)
        canvas.drawCentredString(
            A4[0] / 2, 1.2 * cm, f"{paper.title} · Generated {paper.created_at} · Seed {paper.seed} · Page {doc.page}"
        )
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
        title=("Mark Scheme – " if answers else "") + paper.title,
    )
    story: list = [
        _p(("Mark Scheme – " if answers else "") + paper.title, st["title"]),
        Spacer(1, 4),
        _p(paper.subtitle, st["subtitle"]),
        Spacer(1, 10),
        Table(
            [[_p(f"Duration: {format_duration(paper.duration_minutes)}", st["bold"]),
              _p(f"Total marks: {paper.total_marks}", st["marks"])]],
            colWidths=[_TEXT_WIDTH / 2] * 2,
            style=TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black), ("LEFTPADDING", (0, 0), (-1, -1), 0)]),
        ),
        Spacer(1, 10),
    ]
    if paper.instructions and not answers:
        story.append(_p("INSTRUCTIONS", st["bold"]))
        story.append(
            ListFlowable([ListItem(_p(i, st["body"]), leftIndent=12) for i in paper.instructions],
                         bulletType="bullet", start="•", leftIndent=12)
        )
        story.append(Spacer(1, 8))

    num_w, marks_w = 1.0 * cm, 1.4 * cm
    for sec in paper.sections:
        if sec.title:
            story.append(_p(sec.title, st["section"]))
        for q in sec.questions:
            body = [_p(q.stem_context, st["body"]), Spacer(1, 4)] if q.stem_context else []
            if not answers:
                for path in q.image_paths:
                    img = _image(path)
                    if img:
                        body += [img, Spacer(1, 4)]
            body.append(_p(q.text, st["body"]))
            if paper.show_sources:
                body.append(_p(q.source_ref, st["ref"]))
            if answers:
                body += [Spacer(1, 3), _p("Answer: " + (q.ms_answer or "Mark scheme not available in source documents."),
                                          st["answer"])]
            row = Table(
                [[_p(str(q.number), st["bold"]), body, _p(f"[{q.marks}]", st["marks"])]],
                colWidths=[num_w, _TEXT_WIDTH - num_w - marks_w, marks_w],
                splitInRow=1,  # long stems may run over a page boundary
                style=TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("VALIGN", (2, 0), (2, 0), "BOTTOM"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ]),
            )
            story.append(KeepTogether([row]) if len(body) < 8 else row)

    if paper.inserts and not answers:
        story += [PageBreak(), _p("INSERT – Source material", st["section"])]
        for text in paper.inserts.values():
            story += [_p(text, st["body"]), Spacer(1, 8)]

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
