from typing import Any
from langchain_anthropic import ChatAnthropic

try:
    from .effort import resolve_effort
except ImportError:  # direct execution (python main.py)
    from effort import resolve_effort


def create_anthropic_model(
    model: str,
    credentials: dict[str, Any],
    temperature: float,
    timeout: int | None = None,
    max_retries: int = 3,
    reasoning_effort: str = "medium",
) -> ChatAnthropic:
    """Create an Anthropic chat model. Hardcodes max_tokens=65536 (Anthropic API requires it).

    Legacy path (WORDLLMS_USE_LEGACY=1). langchain_anthropic forwards `effort`
    straight into `output_config.effort` with no per-model gating, and
    Anthropic's API hard-400s on a tier the model doesn't support -- clamp via
    resolve_effort first and omit the key entirely when unsupported.
    """
    api_key = credentials["api_key"]

    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
        "temperature": temperature,
        # Thinking tokens draw from this same ceiling (see providers/base.py), so it
        # must leave headroom for high-effort reasoning plus visible output.
        "max_tokens": 65536,
        "max_retries": max_retries,
    }
    resolved = resolve_effort("anthropic", f"anthropic/{model}", model, reasoning_effort)
    if resolved.effective is not None:
        kwargs["effort"] = resolved.effective
    if timeout is not None:
        kwargs["timeout"] = timeout
    return ChatAnthropic(**kwargs)
