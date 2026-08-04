"""Timeout enforcement and retry utilities for LLM calls.

Provides:
- invoke_with_timeout: sync timeout for LangGraph node .invoke() calls
- ainvoke_with_timeout: async timeout + tenacity retry for .ainvoke() calls
- astream_with_timeout: async timeout + tenacity retry for .astream() calls
- LLM_RETRY_POLICY: pre-built LangGraph RetryPolicy for LLM-calling nodes
"""

import asyncio
import concurrent.futures
import contextvars
import logging
from typing import Any, Sequence

from langchain_core.messages import BaseMessage
from langgraph.types import RetryPolicy
from langgraph._internal._retry import default_retry_on
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_fixed,
)

logger = logging.getLogger(__name__)


# --- Retry-on predicate ---

def retry_on_timeout(exc: Exception) -> bool:
    """Like default_retry_on but also retries on TimeoutError.

    Needed because TimeoutError inherits from OSError, and LangGraph's
    default_retry_on explicitly blocks OSError.
    """
    if isinstance(exc, TimeoutError):
        return True
    return default_retry_on(exc)


# --- Pre-built RetryPolicy for LangGraph add_node() ---

LLM_RETRY_POLICY = RetryPolicy(
    initial_interval=1.0,
    backoff_factor=1.0,
    max_interval=2.0,
    max_attempts=4,  # 1 initial attempt + 3 retries
    jitter=False,
    retry_on=retry_on_timeout,
)


# --- Sync timeout (for LangGraph node functions) ---

def invoke_with_timeout(
    model_or_chain: Any,
    messages: Sequence[BaseMessage],
    timeout_seconds: int,
    label: str = "LLM",
) -> Any:
    """Synchronous invoke() with hard timeout enforcement.

    Submits model.invoke() to a thread pool and waits up to timeout_seconds.
    Raises TimeoutError if the call exceeds the deadline.

    Retry is NOT handled here — use LangGraph RetryPolicy on the node instead.
    """
    # A bare executor.submit() does NOT copy contextvars into the worker
    # thread, so LangChain's callback/config contextvar is missing there --
    # this silently disables callbacks and tracing for every graph LLM call
    # (e.g. on_chat_model_end never fires, breaking astream_events consumers).
    ctx = contextvars.copy_context()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(ctx.run, model_or_chain.invoke, list(messages))
    try:
        result = future.result(timeout=timeout_seconds)
        executor.shutdown(wait=False)
        return result
    except concurrent.futures.TimeoutError:
        future.cancel()
        executor.shutdown(wait=False)
        raise TimeoutError(
            f"[{label}] LLM call timed out after {timeout_seconds}s"
        )


# --- Async timeout + tenacity retry (for non-graph paths) ---

async def ainvoke_with_timeout(
    model: Any,
    messages: Sequence[BaseMessage],
    timeout_seconds: int,
    max_retries: int = 3,
    label: str = "LLM",
) -> Any:
    """Async ainvoke() with hard timeout and tenacity retry.

    For use outside LangGraph (e.g. stream_chat, chat_complete, and the
    out-of-graph parallel multiagent experts). Retries on timeouts AND on
    the same transient-failure predicate LangGraph's LLM_RETRY_POLICY uses
    (retry_on_timeout) -- e.g. litellm.InternalServerError from an upstream
    5xx, which langchain_litellm's own internal retry decorator does not
    cover regardless of the model's `max_retries` setting.
    """
    total_attempts = max_retries + 1

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(total_attempts),
        wait=wait_fixed(1),
        retry=retry_if_exception(retry_on_timeout),
        reraise=True,
    ):
        with attempt:
            try:
                result = await asyncio.wait_for(
                    model.ainvoke(list(messages)),
                    timeout=timeout_seconds,
                )
                attempt_num = attempt.retry_state.attempt_number
                if attempt_num > 1:
                    logger.info(f"[{label}] Succeeded on attempt {attempt_num}/{total_attempts}")
                return result
            except asyncio.TimeoutError:
                attempt_num = attempt.retry_state.attempt_number
                logger.warning(
                    f"[{label}] ainvoke() timed out after {timeout_seconds}s "
                    f"(attempt {attempt_num}/{total_attempts})"
                )
                raise TimeoutError(
                    f"[{label}] LLM call timed out after {timeout_seconds}s"
                )


async def astream_with_timeout(
    model: Any,
    messages: Sequence[BaseMessage],
    timeout_seconds: int,
    max_retries: int = 3,
    label: str = "LLM",
):
    """Async stream with timeout on each chunk and retry.

    Retries on timeouts and on transient upstream failures (per
    retry_on_timeout, e.g. litellm.InternalServerError) as long as zero
    chunks have been yielded yet -- once output has started, a mid-stream
    failure can't be retried without duplicating content, so it's raised
    immediately regardless of type.
    """
    total_attempts = max_retries + 1
    last_exception = None

    for attempt_num in range(1, total_attempts + 1):
        chunks_yielded = 0
        try:
            aiter = model.astream(list(messages))
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        aiter.__anext__(),
                        timeout=timeout_seconds,
                    )
                    chunks_yielded += 1
                    yield chunk
                except StopAsyncIteration:
                    if attempt_num > 1:
                        logger.info(f"[{label}] Stream succeeded on attempt {attempt_num}/{total_attempts}")
                    return
                except asyncio.TimeoutError:
                    raise TimeoutError(
                        f"[{label}] Stream timed out after {timeout_seconds}s "
                        f"({chunks_yielded} chunks received)"
                    )
        except Exception as exc:
            if chunks_yielded > 0 or not retry_on_timeout(exc):
                # Already yielded data, or a non-retryable error — no retry
                raise
            last_exception = exc
            logger.warning(
                f"[{label}] {type(exc).__name__} before first chunk "
                f"(attempt {attempt_num}/{total_attempts}): {exc}"
            )
            if attempt_num < total_attempts:
                await asyncio.sleep(1)

    raise last_exception  # type: ignore[misc]
