from typing import Any

from langchain_openai import ChatOpenAI


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
        "base_url": credentials.get("base_url", "http://localhost:1234/v1"),
        "temperature": temperature,
        "max_retries": max_retries,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return ChatOpenAI(**kwargs)
