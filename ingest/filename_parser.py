"""Parse Cambridge IGCSE file names, e.g. 0625_s23_qp_42.pdf -> Physics, 2023, May/June, paper 4 variant 2."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import config

# 0625_s23_qp_42 | 0580_w22_ms_21 | 0620_m24_qp_32 | 0610_y25_sp_2 | 0625_s23_in_42
_PATTERN = re.compile(
    r"^(?P<code>\d{4})_(?P<session>[smwy])(?P<yy>\d{2})_(?P<type>[a-z]{2})(?:_(?P<paper>\d)(?P<variant>\d)?)?",
    re.IGNORECASE,
)

# CAIE document type codes -> our doc_type
_DOC_TYPES = {
    "qp": "qp",  # question paper
    "sp": "qp",  # specimen paper
    "ms": "ms",  # mark scheme
    "sm": "ms",  # specimen mark scheme
    "in": "in",  # insert / source booklet
    "ci": "in",  # confidential instructions
}


@dataclass
class ParsedName:
    matched: bool
    subject_code: str | None = None
    subject: str | None = None
    year: int | None = None
    session: str | None = None
    doc_type: str | None = None  # qp | ms | in | notes | None (unknown)
    paper: str | None = None
    variant: str | None = None

    @property
    def paper_key(self) -> str | None:
        """Identifies one sitting of one paper, shared by its qp, ms and insert files."""
        if not (self.subject_code and self.year and self.session and self.paper):
            return None
        return f"{self.subject_code}_{self.session}_{self.year}_{self.paper}{self.variant or ''}"


def parse(path: str | Path) -> ParsedName:
    stem = Path(path).stem
    m = _PATTERN.match(stem)
    if not m:
        return ParsedName(matched=False)
    code = m["code"]
    return ParsedName(
        matched=True,
        subject_code=code,
        subject=config.SUBJECT_CODES.get(code),
        year=2000 + int(m["yy"]),
        session=config.SESSION_CODES.get(m["session"].lower()),
        doc_type=_DOC_TYPES.get(m["type"].lower()),
        paper=m["paper"],
        variant=m["variant"],
    )


def subject_from_text(name: str | None) -> tuple[str | None, str | None]:
    """Map a subject name or code (e.g. from the LLM) to (subject, code) using the configured map."""
    if not name:
        return None, None
    name = name.strip()
    if name in config.SUBJECT_CODES:
        return config.SUBJECT_CODES[name], name
    for code, subject in config.SUBJECT_CODES.items():
        if subject.lower() == name.lower():
            return subject, code
    return name, None
