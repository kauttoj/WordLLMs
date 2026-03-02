from typing import Any

from langchain_openai import ChatOpenAI

try:
    from .base import fix_localhost_for_docker
except ImportError:
    from base import fix_localhost_for_docker


def _normalize_base_url(url: str) -> str:
    """Ensure base_url points to OpenAI-compatible /v1 endpoint.

    Strips LMStudio's native /api/v1/... prefix and any extra path
    segments (e.g. /v1/chat) that would cause the OpenAI SDK to
    produce a doubled path like /v1/chat/chat/completions.
    """
    url = url.rstrip("/")
    for marker in ["/api/v1", "/v1"]:
        idx = url.find(marker)
        if idx != -1:
            return url[:idx] + "/v1"
    return url + "/v1"


def create_lmstudio_model(
    model: str,
    credentials: dict[str, Any],
    temperature: float,
    timeout: int | None = None,
    max_retries: int = 3,
) -> ChatOpenAI:
    """Create an LM Studio chat model via OpenAI-compatible API."""
    kwargs: dict[str, Any] = {
        "model": model or "default",
        "api_key": "not-needed",
        "base_url": fix_localhost_for_docker(_normalize_base_url(credentials.get("base_url", "http://localhost:1234/v1"))),
        "temperature": temperature,
        "max_retries": max_retries,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return ChatOpenAI(**kwargs)
