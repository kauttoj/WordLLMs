"""LLM cost estimation via litellm's built-in pricing and token counting.

No bespoke pricing math or token database: ``litellm.cost_per_token`` and
``litellm.token_counter`` do the work. Per-model overrides for models litellm
cannot price (custom models, local Ollama/LMStudio) live in
``<profile_dir>/model_costs.json`` and are applied through litellm's
``custom_cost_per_token`` parameter.

Pricing is best-effort: ``compute_cost`` / ``aggregate_costs`` never raise. A
pricing failure must not break a working LLM response — a deliberate, narrow
exception to the project's fail-loud policy (mirrors ``litellm.drop_params``).

Currency: litellm prices in USD. A manual override entry may declare its own
``currency`` (default ``USD``); its native currency is reported as-is and the
frontend converts to the user's chosen display currency.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import litellm
from litellm.types.utils import CostPerToken
from langchain_core.messages import BaseMessage

try:
    from .agents.context import count_tokens
    from .providers.base import get_provider, get_model_name
except ImportError:  # direct execution (python main.py)
    from agents.context import count_tokens
    from providers.base import get_provider, get_model_name


# WordLLMs provider -> litellm custom_llm_provider for automatic cost lookups.
_LITELLM_PROVIDER = {
    "openai": "openai",
    "azure": "azure",
    "gemini": "gemini",
    "groq": "groq",
    "anthropic": "anthropic",
    "togetherai": "together_ai",
}
# Local providers have no API cost; require an explicit override to show a price.
_LOCAL_PROVIDERS = {"ollama", "lmstudio"}


_MODEL_COSTS_PATH: Path | None = None


def configure_model_costs_path(path: Any) -> None:
    """Point pricing at the active profile's model_costs.json (called from main)."""
    global _MODEL_COSTS_PATH
    _MODEL_COSTS_PATH = Path(path)


def _load_overrides() -> dict[str, Any]:
    """Read the override file fresh (so edits apply without restart).

    Returns {} when absent. Crashes if present-but-malformed, but callers wrap
    pricing in try/except so a broken file degrades to "no price", not a crash.
    """
    if _MODEL_COSTS_PATH is None or not _MODEL_COSTS_PATH.exists():
        return {}
    return json.loads(_MODEL_COSTS_PATH.read_text(encoding="utf-8"))


def _price_one(
    provider: str,
    bare_model: str,
    litellm_model_id: str | None,
    input_tokens: int,
    output_tokens: int,
) -> tuple[float | None, str, str]:
    """Price a single LLM call. Returns (amount, currency, source).

    amount is None when no price is known (source="unknown").
    """
    entry = _load_overrides().get(f"{provider}:{bare_model}")
    if entry is not None:
        cpt = CostPerToken(
            input_cost_per_token=float(entry["input_per_1m"]) / 1_000_000.0,
            output_cost_per_token=float(entry["output_per_1m"]) / 1_000_000.0,
        )
        pin, pout = litellm.cost_per_token(
            model=bare_model or "custom",
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            custom_cost_per_token=cpt,
        )
        return pin + pout, (entry.get("currency") or "USD").upper(), "manual"

    if provider in _LOCAL_PROVIDERS:
        return None, "USD", "unknown"

    llm_provider = _LITELLM_PROVIDER.get(provider)
    for model_arg, prov_arg in ((bare_model, llm_provider), (litellm_model_id, None)):
        if not model_arg:
            continue
        try:
            pin, pout = litellm.cost_per_token(
                model=model_arg,
                custom_llm_provider=prov_arg,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
            )
            return pin + pout, "USD", "auto"
        except Exception:
            continue
    return None, "USD", "unknown"


def usage_from_message(msg: Any) -> tuple[int | None, int | None]:
    """Extract (input_tokens, output_tokens) from an AIMessage / chunk."""
    um = getattr(msg, "usage_metadata", None)
    if um:
        return um.get("input_tokens"), um.get("output_tokens")
    rm = getattr(msg, "response_metadata", None) or {}
    tu = rm.get("token_usage") or rm.get("usage") or {}
    return (
        tu.get("prompt_tokens") or tu.get("input_tokens"),
        tu.get("completion_tokens") or tu.get("output_tokens"),
    )


def compute_cost(
    model: Any,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    lc_messages: Sequence[BaseMessage] | None = None,
    output_text: str | None = None,
) -> dict[str, Any] | None:
    """Build the cost payload for an SSE 'done' event. Never raises.

    Prefer real ``usage_metadata`` token counts; fall back to
    ``litellm.token_counter`` over ``lc_messages``/``output_text`` (flagged
    estimated=True). Returns None when no tokens can be determined.
    """
    try:
        provider = get_provider(model)
        bare_model = get_model_name(model)
        litellm_model_id = getattr(model, "model", None) or bare_model

        estimated = False
        if not input_tokens and lc_messages is not None:
            input_tokens = count_tokens(bare_model, lc_messages)
            estimated = True
        if not output_tokens and output_text:
            output_tokens = litellm.token_counter(model=bare_model, text=output_text)
            estimated = True

        if not input_tokens and not output_tokens:
            return None

        amount, currency, source = _price_one(
            provider, bare_model, litellm_model_id,
            int(input_tokens or 0), int(output_tokens or 0),
        )
        return {
            "amount": None if amount is None else float(amount),
            "currency": currency,
            "model": bare_model,
            "provider": provider,
            "source": source,
            "estimated": estimated,
        }
    except Exception as e:
        print(f"[pricing] cost computation failed (ignored): {type(e).__name__}: {e}")
        return None


def unknown_cost(model: Any) -> dict[str, Any]:
    """A no-price cost payload, so a completed response always renders something.

    ``compute_cost`` returns None when no tokens can be determined; the SSE
    'done' emitters fall back to this so the UI shows "-" rather than nothing.
    Never raises. Not used by aggregate_costs, which must keep ignoring
    usage-less calls.
    """
    try:
        bare_model = get_model_name(model)
        provider = get_provider(model)
    except Exception:
        bare_model, provider = "unknown", "unknown"
    return {
        "amount": None,
        "currency": "USD",
        "model": bare_model,
        "provider": provider,
        "source": "unknown",
        "estimated": False,
    }


def aggregate_costs(parts: list[dict[str, Any] | None]) -> dict[str, Any] | None:
    """Sum per-call cost dicts into one response cost (for multiagent).

    Sums same-currency known amounts. If any priced part is unknown the total is
    still summed but flagged estimated. Mixed currencies (rare) -> unknown.
    """
    parts = [p for p in parts if p]
    if not parts:
        return None

    known = [p for p in parts if p["amount"] is not None]
    any_unknown = len(known) < len(parts)
    estimated = any(p["estimated"] for p in parts) or any_unknown

    if not known:
        return {"amount": None, "currency": "USD", "model": "multiple",
                "provider": "multiple", "source": "unknown", "estimated": estimated}

    currencies = {p["currency"] for p in known}
    if len(currencies) > 1:
        return {"amount": None, "currency": "USD", "model": "multiple",
                "provider": "multiple", "source": "unknown", "estimated": estimated}

    return {
        "amount": sum(p["amount"] for p in known),
        "currency": next(iter(currencies)),
        "model": "multiple",
        "provider": "multiple",
        "source": "manual" if any(p["source"] == "manual" for p in known) else "auto",
        "estimated": estimated,
    }
