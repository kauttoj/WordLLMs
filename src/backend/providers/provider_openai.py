from typing import Any
from langchain_openai import ChatOpenAI


def _needs_responses_api(model: str) -> bool:
    return model.startswith("gpt-5.")


def create_openai_model(
    model: str,
    credentials: dict[str, Any],
    temperature: float,
    timeout: int | None = None,
    max_retries: int = 3,
    reasoning_effort: str = "medium",
) -> ChatOpenAI:
    """Create an OpenAI chat model."""
    api_key = credentials["api_key"]
    base_url = credentials.get("base_url")

    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
        "temperature": temperature,
        "max_retries": max_retries,
        "reasoning_effort": reasoning_effort,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    if base_url:
        kwargs["base_url"] = base_url
    elif _needs_responses_api(model):
        kwargs["use_responses_api"] = True

    return ChatOpenAI(**kwargs)
