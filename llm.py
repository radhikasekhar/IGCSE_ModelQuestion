"""Shared OpenAI client and helpers for structured output and streaming.

Callers pass content blocks in a provider-neutral shape:
  {"type": "text", "text": ...}
  {"type": "image", "source": {"type": "base64", "media_type": ..., "data": ...}}
and they are converted to OpenAI's chat format here.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Iterator, TypeVar

import openai
from pydantic import BaseModel

import config

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    pass


@lru_cache(maxsize=1)
def client() -> openai.OpenAI:
    if not config.OPENAI_API_KEY:
        raise LLMError("OPENAI_API_KEY is not set. Add it to the .env file.")
    return openai.OpenAI(api_key=config.OPENAI_API_KEY, max_retries=4, timeout=600)


def _is_reasoning_model(model: str) -> bool:
    return model.startswith(("gpt-5", "o1", "o3", "o4"))


def _effort_kwargs(model: str, effort: str | None) -> dict[str, Any]:
    return {"reasoning_effort": effort} if effort and _is_reasoning_model(model) else {}


def _to_openai_content(content: list[dict[str, Any]] | str) -> list[dict[str, Any]] | str:
    if isinstance(content, str):
        return content
    out: list[dict[str, Any]] = []
    for block in content:
        if block["type"] == "text":
            out.append({"type": "text", "text": block["text"]})
        elif block["type"] == "image":
            src = block["source"]
            out.append({"type": "image_url", "image_url": {"url": f"data:{src['media_type']};base64,{src['data']}"}})
        else:
            raise ValueError(f"Unsupported content block type: {block['type']}")
    return out


def _api_error(exc: Exception) -> LLMError:
    if isinstance(exc, openai.AuthenticationError):
        return LLMError("OpenAI rejected the API key. Check OPENAI_API_KEY in .env.")
    if isinstance(exc, openai.NotFoundError):
        return LLMError(f"OpenAI model not found or not available to this key: {exc.message}")
    if isinstance(exc, openai.BadRequestError):
        return LLMError(f"OpenAI request was invalid: {exc.message}")
    if isinstance(exc, openai.RateLimitError):
        return LLMError("OpenAI rate limit or quota reached after retries. Lower MAX_CONCURRENCY, check billing, "
                        "or retry later.")
    if isinstance(exc, openai.APIStatusError):
        return LLMError(f"OpenAI API error {exc.status_code}: {exc.message}")
    if isinstance(exc, openai.APIConnectionError):
        return LLMError("Could not reach the OpenAI API. Check your internet connection.")
    return LLMError(str(exc))


def structured(
    *,
    model: str,
    system: str,
    content: list[dict[str, Any]] | str,
    schema: type[T],
    max_tokens: int = 32000,
    effort: str | None = None,
) -> T:
    """One model call whose reply is validated against a Pydantic schema (OpenAI structured outputs)."""
    try:
        completion = client().chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": _to_openai_content(content)},
            ],
            response_format=schema,
            max_completion_tokens=max_tokens,
            **_effort_kwargs(model, effort),
        )
    except openai.LengthFinishReasonError as exc:
        raise LLMError("The model's output was cut off (token limit). Try a smaller batch of pages.") from exc
    except openai.ContentFilterFinishReasonError as exc:
        raise LLMError("OpenAI's content filter blocked this content.") from exc
    except openai.OpenAIError as exc:
        raise _api_error(exc) from exc

    message = completion.choices[0].message
    if message.refusal:
        raise LLMError(f"The model declined to process this content: {message.refusal}")
    if message.parsed is None:
        raise LLMError("The model returned no structured output.")
    return message.parsed


def stream_text(
    *, model: str, system: str, messages: list[dict[str, Any]], max_tokens: int = 8000, effort: str | None = None
) -> Iterator[str]:
    """Yield text deltas from a streamed reply."""
    try:
        stream = client().chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system},
                      *({"role": m["role"], "content": _to_openai_content(m["content"])} for m in messages)],
            max_completion_tokens=max_tokens,
            stream=True,
            **_effort_kwargs(model, effort),
        )
    except openai.OpenAIError as exc:
        raise _api_error(exc) from exc

    finish = None
    for chunk in stream:
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        if choice.delta and choice.delta.content:
            yield choice.delta.content
        if choice.finish_reason:
            finish = choice.finish_reason
    if finish == "content_filter":
        yield "\n\n_The response was blocked by OpenAI's content filter._"
    elif finish == "length":
        yield "\n\n_(Answer truncated.)_"
