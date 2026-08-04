"""Reasoning-effort capability resolution — single source of truth for both
"what tiers may the UI offer for this model?" (``supported_ladder``, backing
``GET /api/model-capabilities``) and "what do we actually send at runtime?"
(``resolve_effort``, called from ``providers/base.py``). Both share one
internal capability lookup so the dropdown and the runtime clamp cannot
diverge.

Why this exists: litellm resolves reasoning-effort support by looking the
model string up in its own capability map. For any name it doesn't recognize
(custom models, Azure deployment names that don't match the canonical model
id) the lookup misses, ``reasoning_effort`` drops out of litellm's supported
params, and because ``litellm.drop_params = True`` is set globally
(``providers/base.py``), the param is silently discarded — the call succeeds
and the user's setting is quietly ignored. This module makes that failure
visible (via ``source``/``warnings``) and forces the param through
(``force_param``) instead of letting it vanish.

User overrides (``model_efforts.json`` in the profile folder, mirroring
``model_costs.json``) always win over litellm's map — litellm lags vendor
releases and simply doesn't know about custom/partner deployments.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import litellm

EFFORT_LADDER: tuple[str, ...] = ("none", "low", "medium", "high", "xhigh", "max")
# Shown when nothing is known about a model's reasoning capability: the
# smallest set that virtually every reasoning-capable model accepts.
CONSERVATIVE: tuple[str, ...] = ("none", "low", "medium", "high")

# litellm tracks no reasoning-capability data for together_ai at all (verified:
# even together_ai/Qwen/Qwen3-235B-A22B-Thinking-2507, a "Thinking" model, has
# no supports_reasoning flag, and together_ai/zai-org/GLM-5.1 is missing from
# litellm.model_cost entirely). A miss/absent-flag there is therefore not
# evidence the model lacks reasoning tiers -- it's a confirmed litellm gap
# (BerriAI/litellm#27439). So togetherai always gets the conservative ladder
# with the param forced through, never a real litellm-sourced verdict.
_TOGETHER_PROVIDERS = frozenset({"together_ai", "togetherai"})

# WordLLMs provider -> litellm custom_llm_provider prefix, for the read-only
# capabilities endpoint which has no credentials and must guess a plausible
# litellm model id from the bare model name alone. `resolve_effort` (called
# from the real model factory in base.py) is instead given the exact litellm
# model id already built there -- this guess only feeds `supported_ladder`.
_PROVIDER_LITELLM_PREFIX = {
    "openai": "openai",
    "gemini": "gemini",
    "groq": "groq",
    "anthropic": "anthropic",
    "togetherai": "together_ai",
}

_GEMINI_THINKING_BUDGET = {
    "none": 0,
    "low": 2048,
    "medium": 8192,
    "high": 24576,
    "xhigh": 24576,
    "max": 24576,
}


@dataclass(frozen=True)
class ResolvedEffort:
    """Result of resolving a requested effort tier against a model's ladder."""
    requested: str
    effective: str | None   # None => caller omits the param entirely
    status: str             # applied | clamped | unsupported
    force_param: bool       # push past litellm's drop_params via allowed_openai_params
    base_model: str | None  # resolved alias/inference target, if any
    source: str             # override | litellm | inferred | fallback
    reason: str


_MODEL_EFFORTS_PATH: Path | None = None

# The override file is re-read on every lookup (so hand-edits apply with no
# restart), which means naive logging would repeat the same line on every single
# request. Instead we track a cheap file signature: whenever it changes we log
# one status line and clear the set of already-reported problems, so each
# distinct problem is logged once per version of the file and a fixed file is
# announced as fixed. _UNSET (not None) is the initial value so that "no file
# configured" is still a state worth logging once.
_UNSET = object()
_file_sig: Any = _UNSET
_reported: set[str] = set()


def configure_model_efforts_path(path: Any) -> None:
    """Point this module at the active profile's model_efforts.json (called from main)."""
    global _MODEL_EFFORTS_PATH, _file_sig
    _MODEL_EFFORTS_PATH = Path(path)
    # Force the next read to log its status -- the profile (and so the file)
    # may have changed even if the new file happens to have the same mtime/size.
    _file_sig = _UNSET


def _warn(msg: str) -> None:
    """Log an override-file problem once per version of the file."""
    if msg not in _reported:
        _reported.add(msg)
        print(f"[effort] WARNING: {msg}")


def _reject(warnings: list[str], msg: str) -> None:
    """Record a bad override entry for the Settings UI and log it once."""
    warnings.append(msg)
    _warn(msg)


def _load_overrides() -> tuple[dict[str, Any], list[str]]:
    """Read the override file fresh (so hand-edits apply without a restart).

    Returns ({}, []) when absent. Unlike ``pricing._load_overrides`` (which is
    allowed to crash because its callers wrap pricing in try/except), a
    malformed file here must NOT crash LLM calls -- a parse failure is caught,
    logged loudly, and surfaced as a warning string so it shows up in Settings.
    """
    global _file_sig
    path = _MODEL_EFFORTS_PATH
    try:
        st = path.stat() if path is not None else None
    except OSError:
        st = None
    sig = (str(path), st.st_mtime_ns, st.st_size) if st is not None else (str(path), None, None)
    changed = sig != _file_sig
    if changed:
        _file_sig = sig
        _reported.clear()

    if path is None or st is None:
        if changed:
            where = f" ({path})" if path is not None else ""
            print(
                f"[effort] no model_efforts.json{where} -- effort tiers come from "
                "litellm's built-in capability data only"
            )
        return {}, []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object at the top level")
    except Exception as e:
        msg = f"model_efforts.json is malformed and was ignored: {type(e).__name__}: {e}"
        _warn(f"{msg} [{path}]")
        return {}, [msg]

    if changed:
        # Keys starting with '_' or '/' are the documented way to comment an
        # entry out (no provider is named that), so they aren't real overrides.
        keys = [k for k in data if isinstance(k, str) and not k.startswith(("_", "/"))]
        print(
            f"[effort] loaded model_efforts.json ({path}): {len(keys)} user override(s) "
            f"-- these win over litellm's built-in data" + (f": {', '.join(sorted(keys))}" if keys else "")
        )
    return data, []


def log_override_status() -> None:
    """Log where effort data currently comes from. Called at startup and profile switch."""
    _load_overrides()


def _capability_lookup(litellm_model_id: str | None, bare_model: str | None) -> dict[str, Any] | None:
    """Try litellm_model_id then bare_model; exact model_cost hit first, then get_model_info.

    The single internal capability probe shared by every resolution path, so
    ``supported_ladder`` and ``resolve_effort`` can never look at different data.

    model_cost is checked first purely to keep the logs clean: it is a plain
    dict lookup, whereas ``get_model_info`` prints a red "Provider List" banner
    to stderr on every miss. Only when both exact keys miss do we pay that cost
    for get_model_info's extra name normalization.
    """
    for key in (litellm_model_id, bare_model):
        if key and litellm.model_cost.get(key):
            return litellm.model_cost[key]
    for key in (litellm_model_id, bare_model):
        if not key:
            continue
        try:
            info = litellm.get_model_info(model=key)
        except Exception:
            info = None
        if info:
            return info
    return None


def _order(tiers: Any) -> list[str]:
    """Order an arbitrary tier collection per EFFORT_LADDER."""
    return [t for t in EFFORT_LADDER if t in tiers]


def _ladder_from_entry(entry: dict[str, Any] | None) -> list[str]:
    """Derive a supported-tiers ladder from a litellm model_cost/get_model_info entry."""
    if not entry or not entry.get("supports_reasoning"):
        return []
    tiers = {"low", "medium", "high"}
    # Anthropic/Gemini entries omit supports_none_reasoning_effort but do accept
    # "none" (disables reasoning); only models that explicitly say False (e.g.
    # OpenAI's gpt-5) must exclude it.
    if entry.get("supports_none_reasoning_effort") is not False:
        tiers.add("none")
    if entry.get("supports_xhigh_reasoning_effort"):
        tiers.add("xhigh")
    # litellm's _validate_effort_for_model also accepts "max" on adaptive-thinking
    # models (e.g. claude-sonnet-5) even without an explicit max flag.
    if entry.get("supports_max_reasoning_effort") or entry.get("supports_adaptive_thinking"):
        tiers.add("max")
    return _order(tiers)


_BASE_MODEL_CANDIDATES: list[str] | None = None
_MIN_BASE_MODEL_LEN = 4


def _base_model_candidates() -> list[str]:
    """Memoized, longest-first list of bare (unprefixed) litellm model_cost keys."""
    global _BASE_MODEL_CANDIDATES
    if _BASE_MODEL_CANDIDATES is None:
        candidates = [
            k for k in litellm.model_cost.keys()
            if isinstance(k, str) and "/" not in k and len(k) >= _MIN_BASE_MODEL_LEN
        ]
        candidates.sort(key=len, reverse=True)
        _BASE_MODEL_CANDIDATES = candidates
    return _BASE_MODEL_CANDIDATES


def _infer_base_model(name: str) -> str | None:
    """Longest known bare model key occurring case-insensitively as a substring of `name`.

    E.g. "haagahelia-gpt-5.5-prod" -> "gpt-5.5". Longest-first ordering means a
    more specific match (e.g. "gpt-5.5") wins over a shorter one ("gpt-5").
    """
    if not name:
        return None
    lowered = name.lower()
    for cand in _base_model_candidates():
        if cand.lower() in lowered:
            return cand
    return None


def _fallback_via_inference(
    name: str, warnings: list[str]
) -> tuple[list[str], str, str | None, list[str], bool, str | None]:
    """Base-model name inference, or the conservative ladder if nothing matches."""
    inferred = _infer_base_model(name)
    if inferred:
        cap = _capability_lookup(inferred, inferred)
        ladder = _ladder_from_entry(cap) if cap else []
        return ladder, "inferred", inferred, warnings, True, None
    print(f"[effort] no capability data found for model='{name}'; using conservative fallback")
    return list(CONSERVATIVE), "fallback", None, warnings, True, None


def _resolve_capability(
    provider: str, litellm_model_id: str | None, bare_model: str,
) -> tuple[list[str], str, str | None, list[str], bool, str | None]:
    """Core precedence chain shared by ``supported_ladder`` and ``resolve_effort``.

    Returns (ladder, source, base_model, warnings, force_param, override_default_effort).
    Precedence: model_efforts.json override (explicit ladder, then base_model
    alias) -> togetherai carve-out -> litellm map hit -> name-based inference
    -> conservative fallback.
    """
    overrides, warnings = _load_overrides()
    key = f"{provider}:{bare_model}"
    entry = overrides.get(key)

    # An override tells us what the model supports, but litellm still decides
    # whether the param survives drop_params. If litellm doesn't recognize the
    # real model name, the param must be forced through or the override would
    # be silently discarded -- precisely the bug this module exists to fix.
    def _override_force() -> bool:
        return _capability_lookup(litellm_model_id, bare_model) is None

    if isinstance(entry, dict) and "supported_efforts" in entry:
        raw = entry["supported_efforts"]
        if isinstance(raw, list) and all(isinstance(t, str) and t in EFFORT_LADDER for t in raw):
            # [] is a meaningful, valid declaration of "no reasoning tiers".
            return _order(raw), "override", None, warnings, _override_force(), entry.get("default_effort")
        _reject(warnings, f"model_efforts.json entry '{key}' has an invalid supported_efforts list; ignored")

    elif isinstance(entry, dict) and "base_model" in entry:
        alias = entry.get("base_model")
        if isinstance(alias, str) and alias:
            cap = _capability_lookup(alias, alias)
            if cap is not None:
                return _ladder_from_entry(cap), "override", alias, warnings, _override_force(), entry.get("default_effort")
            _reject(
                warnings,
                f"model_efforts.json base_model alias '{alias}' for '{key}' is unknown to "
                "litellm; falling back to name inference",
            )
            return _fallback_via_inference(bare_model or litellm_model_id or "", warnings)
        _reject(warnings, f"model_efforts.json entry '{key}' has an invalid base_model; ignored")

    elif entry is not None:
        _reject(warnings, f"model_efforts.json entry '{key}' has neither supported_efforts nor base_model; ignored")

    if provider in _TOGETHER_PROVIDERS:
        return list(CONSERVATIVE), "fallback", None, warnings, True, None

    cap = _capability_lookup(litellm_model_id, bare_model)
    if cap is not None:
        return _ladder_from_entry(cap), "litellm", None, warnings, False, None

    return _fallback_via_inference(bare_model or litellm_model_id or "", warnings)


def _pick_default(ladder: list[str], override_default: str | None) -> str:
    """The dropdown's default selection for a given ladder."""
    if override_default and override_default in ladder:
        return override_default
    if "medium" in ladder:
        return "medium"
    if ladder:
        return ladder[len(ladder) // 2]
    return "medium"


def _guess_litellm_model_id(provider: str, model: str) -> str | None:
    """Best-effort litellm model id for the credential-free capabilities endpoint.

    Mirrors only the name-based part of ``providers/base.py``'s Azure 3-way
    dispatch (it can't replicate the deployment_name-dependent part without
    credentials, but that doesn't affect capability data).
    """
    if not model:
        return None
    if provider == "azure":
        return f"azure/{model}" if model.startswith("gpt-") else f"azure_ai/{model}"
    prefix = _PROVIDER_LITELLM_PREFIX.get(provider)
    return f"{prefix}/{model}" if prefix else None


def supported_ladder(provider: str, model: str) -> dict[str, Any]:
    """What effort tiers may the UI offer for (provider, model)?

    Pure, credential-free, no upstream call. Backs GET /api/model-capabilities.
    """
    litellm_model_id = _guess_litellm_model_id(provider, model)
    ladder, source, base_model, warnings, _force, override_default = _resolve_capability(
        provider, litellm_model_id, model
    )
    return {
        "provider": provider,
        "model": model,
        "base_model": base_model,
        "supported_efforts": list(ladder),
        "default_effort": _pick_default(ladder, override_default),
        "source": source,
        "warnings": warnings,
    }


# Human-readable gloss for the terse `source` token, so a log reader can tell
# at a glance whether a tier came from the user's JSON or from litellm, and
# whether it is trustworthy (the last two force the param through but cannot be
# confirmed as honored -- see display_effort).
_SOURCE_LABEL = {
    "override": "from user model_efforts.json",
    "litellm": "from litellm built-in data",
    "inferred": "INFERRED from model name, unconfirmed",
    "fallback": "conservative FALLBACK, unconfirmed",
}


def _log_resolution(
    provider: str, bare_model: str, base_model: str | None,
    source: str, requested: str, effective: str | None, status: str,
) -> None:
    """Emit exactly one log line per resolve_effort() call."""
    base_part = base_model or bare_model
    label = _SOURCE_LABEL.get(source, source)
    print(
        f"[effort] provider={provider} model={bare_model} base={base_part} "
        f"src={source} ({label}) requested={requested} effective={effective} status={status}"
    )


def resolve_effort(
    provider: str, litellm_model_id: str, bare_model: str, requested: str,
) -> ResolvedEffort:
    """What do we actually send at runtime? Clamps `requested` to what the model supports.

    Called once per model construction in ``providers/base.py``. Never raises:
    a stale/garbage `requested` value (e.g. leftover localStorage) is treated
    as "medium" rather than propagated.
    """
    ladder, source, base_model, warnings, force_param, _override_default = _resolve_capability(
        provider, litellm_model_id, bare_model
    )

    reason_bits = list(warnings)
    stale = requested not in EFFORT_LADDER
    working = "medium" if stale else requested
    if stale:
        reason_bits.append(f"requested tier '{requested}' is not a recognized effort value; substituted 'medium'")

    if not ladder:
        result = ResolvedEffort(
            requested=requested, effective=None, status="unsupported", force_param=False,
            base_model=base_model, source=source,
            reason="; ".join(reason_bits) or "model has no reasoning-effort tiers",
        )
        _log_resolution(provider, bare_model, base_model, source, requested, None, "unsupported")
        return result

    if working == "max":
        if "max" in ladder:
            effective = "max"
        elif "xhigh" in ladder:
            effective = "xhigh"
        else:
            effective = "high"
    elif working == "xhigh":
        effective = "xhigh" if "xhigh" in ladder else "high"
    elif working in ladder:
        effective = working
    else:
        # Nearest lower tier present, else the lowest tier present.
        idx = EFFORT_LADDER.index(working)
        lower_tiers = [t for t in EFFORT_LADDER[:idx] if t in ladder]
        effective = lower_tiers[-1] if lower_tiers else ladder[0]

    status = "applied" if (not stale and effective == working) else "clamped"
    result = ResolvedEffort(
        requested=requested, effective=effective, status=status, force_param=force_param,
        base_model=base_model, source=source, reason="; ".join(reason_bits) or "resolved",
    )
    _log_resolution(provider, bare_model, base_model, source, requested, effective, status)
    return result


def display_effort(r: ResolvedEffort) -> str | None:
    """The effort label for the cost footer -- only when we KNOW it was honored.

    `inferred`/`fallback` force the param through but we can never confirm the
    target actually applied it (unknown model to litellm); the footer must not
    label a cost with an effort we can't confirm was honored.
    """
    if r.status in ("applied", "clamped") and r.source in ("override", "litellm"):
        return r.effective
    return None


def gemini_thinking_budget(effective: str | None) -> int | None:
    """Map a resolved effort tier to a Gemini 2.5 thinking_budget token count.

    Replaces the old ``budget_map[reasoning_effort]`` KeyError landmine
    (budget_map only held low/medium/high): never raises, defaults to the
    "high" budget for any unrecognized non-None value.
    """
    if effective is None:
        return None
    budget = _GEMINI_THINKING_BUDGET.get(effective)
    if budget is None:
        print(f"[effort] unexpected gemini effort '{effective}'; defaulting to 'high' budget")
        return _GEMINI_THINKING_BUDGET["high"]
    return budget
