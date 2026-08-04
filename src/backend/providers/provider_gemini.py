from typing import Any
from langchain_google_genai import ChatGoogleGenerativeAI

try:
    from .effort import resolve_effort, gemini_thinking_budget
except ImportError:  # direct execution (python main.py)
    from effort import resolve_effort, gemini_thinking_budget


def create_gemini_model(
    model: str,
    credentials: dict[str, Any],
    temperature: float,
    timeout: int | None = None,
    max_retries: int = 3,
    reasoning_effort: str = "medium",
) -> ChatGoogleGenerativeAI:
    """Create a Google Gemini chat model. Legacy path (WORDLLMS_USE_LEGACY=1)."""
    kwargs: dict[str, Any] = {
        "model": model,
        "google_api_key": credentials["api_key"],
        "temperature": temperature,
        "max_retries": max_retries,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    resolved = resolve_effort("gemini", f"gemini/{model}", model, reasoning_effort)
    if model.startswith("gemini-2.5"):
        # gemini_thinking_budget replaces the old budget_map[reasoning_effort]
        # KeyError landmine (budget_map only held low/medium/high).
        budget = gemini_thinking_budget(resolved.effective)
        if budget is not None:
            kwargs["thinking_budget"] = budget
    elif resolved.effective is not None:
        kwargs["thinking_level"] = resolved.effective
    return ChatGoogleGenerativeAI(**kwargs)
