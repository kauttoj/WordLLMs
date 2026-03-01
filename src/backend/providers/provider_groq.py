from typing import Any
from langchain_groq import ChatGroq


def create_groq_model(
    model: str,
    credentials: dict[str, Any],
    temperature: float,
    timeout: int | None = None,
    max_retries: int = 3,
) -> ChatGroq:
    """Create a Groq chat model."""
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": credentials["api_key"],
        "temperature": temperature,
        "max_retries": max_retries,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return ChatGroq(**kwargs)
