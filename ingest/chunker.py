"""Token-based recursive chunking (200-400 tokens, 40 overlap)."""
from __future__ import annotations

from functools import lru_cache

import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config


@lru_cache(maxsize=1)
def _encoder():
    # cl100k_base approximates token counts for chunk sizing.
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_encoder().encode(text))


@lru_cache(maxsize=1)
def _splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base",
        chunk_size=config.CHUNK_MAX_TOKENS,
        chunk_overlap=config.CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", "; ", ", ", " ", ""],
    )


def split(text: str) -> list[str]:
    """Split text into chunks of at most CHUNK_MAX_TOKENS. Short text stays as one chunk."""
    text = text.strip()
    if not text:
        return []
    if count_tokens(text) <= config.CHUNK_MAX_TOKENS:
        return [text]
    return [c for c in _splitter().split_text(text) if c.strip()]


def merge_small(sections: list[dict], key: str = "topic") -> list[dict]:
    """Join consecutive same-topic note sections until each reaches CHUNK_MIN_TOKENS.

    Never merges across topics, and never grows a merged section past CHUNK_MAX_TOKENS.
    """
    merged: list[dict] = []
    for sec in sections:
        prev = merged[-1] if merged else None
        if (
            prev is not None
            and prev[key] == sec[key]
            and count_tokens(prev["text"]) < config.CHUNK_MIN_TOKENS
            and count_tokens(prev["text"]) + count_tokens(sec["text"]) <= config.CHUNK_MAX_TOKENS
        ):
            prev["text"] = f"{prev['text']}\n\n{sec['text']}"
            prev["keywords"] = sorted(set(prev["keywords"]) | set(sec["keywords"]))
            if prev["content_type"] != sec["content_type"]:
                prev["content_type"] = "summary" if prev["content_type"] == "summary" else prev["content_type"]
        else:
            merged.append(dict(sec))
    return merged
