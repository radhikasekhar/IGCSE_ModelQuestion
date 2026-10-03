"""Remove exam-paper noise (headers, footers, page numbers, barcodes, answer lines) and normalise text."""
from __future__ import annotations

import hashlib
import re
import unicodedata

_LINE_NOISE = [
    re.compile(r"^\s*©\s*UCLES.*$", re.I),
    re.compile(r"^\s*©\s*Cambridge University Press.*$", re.I),
    re.compile(r"^\s*\d{4}/\d{2}/[A-Z]/[A-Z]/\d{2}\s*$"),  # 0625/42/M/J/23
    re.compile(r"^\s*\[?\s*Turn over\s*\]?\s*$", re.I),
    re.compile(r"^\s*BLANK PAGE\s*$", re.I),
    re.compile(r"^\s*DO NOT WRITE (IN|OUTSIDE) TH(IS|E) MARGIN.*$", re.I),
    re.compile(r"^\s*(PMT|www\.\S+)\s*$", re.I),
    re.compile(r"^\s*\*\s*[\d\s]{6,}\*\s*$"),  # * 0123456789 * barcode
    re.compile(r"^\s*[.…_\s]{8,}\s*$"),  # dotted / underscored answer lines
    re.compile(r"^\s*(Page \d+ of \d+)\s*$", re.I),
    re.compile(r"^\s*For Examiner'?s Use\s*$", re.I),
]

_PAGE_NUMBER = re.compile(r"^\s*\d{1,3}\s*$")
_MARKS_RE =re.compile(r"\[\s*(\d{1,2})\s*(?:marks?)?\s*\]", re.I)
_TOTAL_RE = re.compile(r"\[\s*Total\s*:\s*\d+\s*\]", re.I)


def clean_page(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace(" ", " ").replace(" ", " ").replace(" ", " ")
    lines = []
    for line in text.splitlines():
        if any(p.match(line) for p in _LINE_NOISE):
            continue
        # Trim trailing answer dots that share a line with text: "Name the gas ........"
        line = re.sub(r"[.…_]{5,}", " ", line)
        lines.append(line.rstrip())
    # A bare number on the first or last line is a page number. Elsewhere it may be a
    # question number on its own line, so keep it.
    content = [i for i, ln in enumerate(lines) if ln.strip()]
    for i in {content[0], content[-1]} if content else set():
        if _PAGE_NUMBER.match(lines[i]):
            lines[i] = ""
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def strip_marks(text: str) -> str:
    """Remove '[2]' and '[Total: 8]' annotations; marks are stored as metadata instead."""
    text = _TOTAL_RE.sub("", text)
    text = _MARKS_RE.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def normalise_for_hash(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalise_for_hash(text).encode("utf-8")).hexdigest()


def file_hash(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()
