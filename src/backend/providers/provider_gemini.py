from typing import Any
from langchain_google_genai import ChatGoogleGenerativeAI


def create_gemini_model(
    model: str,
    credentials: dict[str, Any],
    temperature: float,
    timeout: int | None = None,
    max_retries: int = 3,
    reasoning_effort: str = "medium",
) -> ChatGoogleGenerativeAI:
    """Create a Google Gemini chat model."""
    kwargs: dict[str, Any] = {
        "model": model,
        "google_api_key": credentials["api_key"],
        "temperature": temperature,
        "max_retries": max_retries,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    if model.startswith("gemini-2.5"):
        budget_map = {"low": 2048, "medium": 8192, "high": 24576}
        kwargs["thinking_budget"] = budget_map[reasoning_effort]
    else:
        kwargs["thinking_level"] = reasoning_effort
    return ChatGoogleGenerativeAI(**kwargs)
