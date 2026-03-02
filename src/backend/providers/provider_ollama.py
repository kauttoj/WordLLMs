from typing import Any
from langchain_ollama import ChatOllama

try:
    from .base import fix_localhost_for_docker
except ImportError:
    from base import fix_localhost_for_docker


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
        "base_url": fix_localhost_for_docker(credentials.get("base_url", "http://localhost:11434")),
        "temperature": temperature,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return ChatOllama(**kwargs)
