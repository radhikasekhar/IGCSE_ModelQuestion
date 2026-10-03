"""Central configuration: paths, API keys, models, thresholds and the CAIE subject map."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


# --- Paths -----------------------------------------------------------------
# Everything the app writes lives under STORAGE_DIR. Locally that's the project folder;
# on Railway set STORAGE_DIR to the volume's mount path (e.g. /storage) so data survives redeploys.
STORAGE_DIR = Path(_env("STORAGE_DIR") or BASE_DIR).resolve()
DATA_DIR = STORAGE_DIR / "data"
PAPERS_DIR = DATA_DIR / "papers"
NOTES_DIR = DATA_DIR / "notes"
IMAGES_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "catalog.db"
OUTPUT_DIR = STORAGE_DIR / "output"
LOG_DIR = STORAGE_DIR / "logs"

for _d in (PAPERS_DIR, NOTES_DIR, IMAGES_DIR, OUTPUT_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def resolve_data_path(stored: str) -> Path:
    """Turn a stored image path back into a file path.

    New paths are stored relative to DATA_DIR ("images/x.png"); older ones relative to the
    project folder ("data/images/x.png").
    """
    p = Path(stored)
    if p.is_absolute():
        return p
    if p.parts and p.parts[0] == "data":
        return STORAGE_DIR / p
    return DATA_DIR / p


# --- Access control (used when deployed) -------------------------------------
# Sign-in with Google/Microsoft is enabled when .streamlit/secrets.toml has an [auth] section
# (the Docker entrypoint writes it from AUTH_* environment variables).
# Comma-separated allow-lists; empty = any signed-in account.
ALLOWED_EMAILS = {e.strip().lower() for e in _env("ALLOWED_EMAILS").split(",") if e.strip()}
ALLOWED_EMAIL_DOMAINS = {d.strip().lower().lstrip("@") for d in _env("ALLOWED_EMAIL_DOMAINS").split(",") if d.strip()}
# Simple shared password, used only when sign-in isn't configured.
APP_PASSWORD = _env("APP_PASSWORD")

# --- API keys --------------------------------------------------------------
OPENAI_API_KEY = _env("OPENAI_API_KEY")
PINECONE_API_KEY = _env("PINECONE_API_KEY")
TAVILY_API_KEY = _env("TAVILY_API_KEY")

# --- OpenAI models -----------------------------------------------------------
EXTRACTION_MODEL = _env("EXTRACTION_MODEL", "gpt-5.5")
CHAT_MODEL = _env("CHAT_MODEL", "gpt-5.5")
CLASSIFIER_MODEL = _env("CLASSIFIER_MODEL", "gpt-5.4-mini")
# reasoning_effort for GPT-5 / o-series models: none | minimal | low | medium | high
EXTRACTION_EFFORT = _env("EXTRACTION_EFFORT", "medium")
CHAT_EFFORT = _env("CHAT_EFFORT", "low")

# --- Pinecone --------------------------------------------------------------
PINECONE_INDEX = _env("PINECONE_INDEX", "igcse-rag")
PINECONE_CLOUD = _env("PINECONE_CLOUD", "aws")
PINECONE_REGION = _env("PINECONE_REGION", "us-east-1")
EMBED_MODEL = "llama-text-embed-v2"
RERANK_MODEL = "bge-reranker-v2-m3"
NS_QUESTIONS = "questions"
NS_NOTES = "notes"
UPSERT_BATCH = 96

# --- Thresholds ------------------------------------------------------------
RELEVANCE_THRESHOLD = _env_float("RELEVANCE_THRESHOLD", 0.35)
DEDUP_SIMILARITY = _env_float("DEDUP_SIMILARITY", 0.92)
PAPER_DIVERSITY_SIMILARITY = _env_float("PAPER_DIVERSITY_SIMILARITY", 0.85)
MMR_LAMBDA = 0.7
CHUNK_MIN_TOKENS = _env_int("CHUNK_MIN_TOKENS", 200)
CHUNK_MAX_TOKENS = _env_int("CHUNK_MAX_TOKENS", 400)
CHUNK_OVERLAP = _env_int("CHUNK_OVERLAP", 40)
MAX_CONCURRENCY = _env_int("MAX_CONCURRENCY", 5)
MAX_QUESTIONS_PER_PAPER = 60
CHAT_HISTORY_TURNS = 10

# --- Documents -------------------------------------------------------------
SUPPORTED_EXTS = {".pdf", ".docx", ".txt", ".html", ".htm", ".png", ".jpg", ".jpeg"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
# A PDF page with less extractable text than this is treated as scanned and sent to the vision model as an image.
SCANNED_PAGE_MIN_CHARS = 40
PAGES_PER_EXTRACTION_CALL = 24

SESSION_CODES = {"s": "May/June", "w": "Oct/Nov", "m": "Feb/March", "y": "Specimen"}
SESSION_SHORT = {"May/June": "M/J", "Oct/Nov": "O/N", "Feb/March": "F/M", "Specimen": "SP"}

SUBJECT_CODES = {
    "0580": "Mathematics",
    "0606": "Additional Mathematics",
    "0625": "Physics",
    "0620": "Chemistry",
    "0610": "Biology",
    "0654": "Co-ordinated Sciences",
    "0455": "Economics",
    "0450": "Business Studies",
    "0452": "Accounting",
    "0478": "Computer Science",
    "0500": "First Language English",
    "0510": "English as a Second Language",
}

DEFAULT_INSTRUCTIONS = [
    "Answer all questions.",
    "Write your answers in the spaces provided.",
    "Show all working where calculations are required.",
    "The number of marks is given in brackets [ ] at the end of each question.",
]


def missing_keys() -> list[str]:
    """Names of required API keys that are not configured."""
    return [
        name
        for name, value in (
            ("OPENAI_API_KEY", OPENAI_API_KEY),
            ("PINECONE_API_KEY", PINECONE_API_KEY),
            ("TAVILY_API_KEY", TAVILY_API_KEY),
        )
        if not value
    ]
