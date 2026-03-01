from typing import Any
from langchain_anthropic import ChatAnthropic


def create_anthropic_model(
    model: str,
    credentials: dict[str, Any],
    temperature: float,
    timeout: int | None = None,
    max_retries: int = 3,
) -> ChatAnthropic:
    """Create an Anthropic chat model. Hardcodes max_tokens=16384 (Anthropic API requires it)."""
    api_key = credentials["api_key"]

    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
        "temperature": temperature,
        "max_tokens": 16384,
        "max_retries": max_retries,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return ChatAnthropic(**kwargs)
