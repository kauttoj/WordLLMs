from typing import Any
from langchain_ollama import ChatOllama


def create_ollama_model(
    model: str,
    credentials: dict[str, Any],
    temperature: float,
    timeout: int | None = None,
    max_retries: int = 3,
) -> ChatOllama:
    """Create an Ollama chat model."""
    kwargs: dict[str, Any] = {
        "model": model,
        "base_url": credentials.get("base_url", "http://localhost:11434"),
        "temperature": temperature,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return ChatOllama(**kwargs)
