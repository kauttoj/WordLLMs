import os
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse

import litellm
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_litellm import ChatLiteLLM

try:
    from .effort import resolve_effort, gemini_thinking_budget, display_effort
except ImportError:  # direct execution (python main.py)
    from effort import resolve_effort, gemini_thinking_budget, display_effort

# CLAUDE.md says "crash hard and often when assumptions are not met".
# drop_params is the ONE explicit exception: litellm silently drops params
# unsupported by the target provider (e.g. reasoning_effort on Groq, thinking_*
# on non-reasoning models, use_responses_api on non-OpenAI). This eliminates
# the per-provider parameter switch logic we used to maintain. Do NOT replicate
# silent fallbacks anywhere else in the codebase.
litellm.drop_params = True

_IN_DOCKER = os.environ.get("RUNNING_IN_DOCKER") == "1"
# Default ON: route all LLM calls through ChatLiteLLM so drop_params handles
# unsupported provider params. Set WORDLLMS_USE_LEGACY=1 to fall back to the
# old per-provider LangChain classes (e.g. for emergency rollback).
_USE_LITELLM = os.environ.get("WORDLLMS_USE_LEGACY") != "1"


class _TaggedChatLiteLLM(ChatLiteLLM):
    """ChatLiteLLM subclass that allows attaching WordLLMs provider metadata.

    `extra="allow"` permits assigning `_wordllms_provider` and `_wordllms_raw_model`
    on the instance, which downstream code reads via `get_provider()` and
    `get_model_name()` instead of `isinstance` checks against per-provider classes.
    """
    model_config = {"extra": "allow", "arbitrary_types_allowed": True}


def fix_localhost_for_docker(url: str) -> str:
    """Rewrite localhost/127.0.0.1 to host.docker.internal when in Docker."""
    if not _IN_DOCKER:
        return url
    parsed = urlparse(url)
    if parsed.hostname in ("localhost", "127.0.0.1"):
        replaced = parsed._replace(netloc=parsed.netloc.replace(parsed.hostname, "host.docker.internal"))
        return urlunparse(replaced)
    return url


def _normalize_lmstudio_base_url(url: str) -> str:
    """Ensure base_url points to OpenAI-compatible /v1 endpoint.

    Strips LMStudio's native /api/v1/... prefix and any extra path
    segments (e.g. /v1/chat) that would cause the OpenAI SDK to
    produce a doubled path like /v1/chat/chat/completions.
    """
    url = url.rstrip("/")
    for marker in ["/api/v1", "/v1"]:
        idx = url.find(marker)
        if idx != -1:
            return url[:idx] + "/v1"
    return url + "/v1"


def _extract_azure_resource_name(endpoint: str) -> str:
    """Extract Azure resource name from any Azure endpoint URL."""
    host = urlparse(endpoint).hostname
    if not host:
        raise ValueError(f"Cannot parse Azure endpoint URL: {endpoint}")
    return host.split(".")[0]


def get_provider(model: BaseChatModel) -> str:
    """Read the WordLLMs provider tag attached to the model.

    All models constructed via `create_model()` are tagged with
    `_wordllms_provider`. Code that branches on provider should call this
    helper instead of `isinstance(model, ChatOpenAI/...)` so behavior works
    uniformly across the legacy per-provider path and the ChatLiteLLM path.
    """
    p = getattr(model, "_wordllms_provider", None)
    if not p:
        legacy = _LEGACY_TAGS.get(id(model))
        if legacy:
            return legacy[0]
        raise AttributeError(
            f"Model {type(model).__name__} missing _wordllms_provider tag. "
            "All models must be created via providers.base.create_model()."
        )
    return p


def get_model_name(model: BaseChatModel) -> str:
    """Extract the bare model name (without litellm provider prefix).

    For ChatLiteLLM, `model.model` is the prefixed string like "openai/gpt-4o";
    we strip the prefix for clean logs and `litellm.token_counter` (which
    accepts both forms but bare is cleaner).
    """
    raw = getattr(model, "_wordllms_raw_model", None)
    if raw:
        return raw
    legacy = _LEGACY_TAGS.get(id(model))
    if legacy:
        return legacy[1]
    name = (
        getattr(model, 'model_name', None)
        or getattr(model, 'model', None)
        or getattr(model, 'deployment_name', None)
    )
    if not name:
        raise AttributeError(
            f"{model.__class__.__name__} has no usable model name "
            f"(model_name={getattr(model, 'model_name', 'MISSING')}, "
            f"model={getattr(model, 'model', 'MISSING')}, "
            f"deployment_name={getattr(model, 'deployment_name', 'MISSING')})"
        )
    return name.split("/", 1)[1] if "/" in name else name


def get_effective_effort(model: BaseChatModel) -> str | None:
    """Read the WordLLMs effort tag attached to the model, for the cost footer.

    Returns None (never raises) when the tag is absent -- e.g. legacy-path
    models, or providers that never carry a reasoning effort (groq) -- so the
    footer degrades to "no label" rather than lying about what was applied.
    """
    return getattr(model, "_wordllms_effort", None)


def _is_litellm_model(model: BaseChatModel) -> bool:
    """Return whether this model is the unified ChatLiteLLM wrapper."""
    return isinstance(model, _TaggedChatLiteLLM)


def bind_tools_compat(
    model: BaseChatModel,
    tools: list[Any],
    *,
    tool_choice: Any | None = None,
):
    """Bind tools without leaking `strict` as a top-level LiteLLM param.

    ChatLiteLLM.bind_tools() forwards unknown kwargs into the eventual model
    request. OpenAI strict tool schemas therefore need to be injected into each
    function definition before binding, not passed as bind_tools(strict=True).
    """
    provider = get_provider(model)
    kwargs: dict[str, Any] = {}
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice

    if provider == "openai":
        if _is_litellm_model(model):
            formatted_tools = [
                convert_to_openai_tool(tool, strict=True)
                for tool in tools
            ]
            return model.bind_tools(formatted_tools, **kwargs)
        return model.bind_tools(tools, strict=True, **kwargs)

    return model.bind_tools(tools, **kwargs)


def with_structured_output_compat(model: BaseChatModel, schema: Any, include_raw: bool = False):
    """Structured output binding that avoids non-OpenAI `strict` payloads.

    ChatLiteLLM.with_structured_output(method="json_schema") inserts
    response_format.json_schema.strict by default. Some providers reject that
    nested field, so non-OpenAI LiteLLM models use function-calling structured
    output instead. When `include_raw=True`, the returned runnable yields a
    dict of `{"raw", "parsed", "parsing_error"}` so the caller can recover
    token usage from the raw AIMessage for cost accounting.
    """
    if _is_litellm_model(model) and get_provider(model) != "openai":
        return model.with_structured_output(schema, method="function_calling", include_raw=include_raw)
    return model.with_structured_output(schema, include_raw=include_raw)


def _tag_legacy(model: BaseChatModel, provider: str, raw_model: str) -> BaseChatModel:
    """Attach WordLLMs metadata to a legacy per-provider model object.

    Uses object.__setattr__ to bypass Pydantic's strict attribute checks on
    the legacy LangChain provider classes. The litellm path uses the
    `_TaggedChatLiteLLM` subclass instead.
    """
    try:
        object.__setattr__(model, "_wordllms_provider", provider)
        object.__setattr__(model, "_wordllms_raw_model", raw_model)
    except (AttributeError, TypeError):
        # Fallback: stash in a module-level WeakKeyDictionary if direct set fails.
        _LEGACY_TAGS[id(model)] = (provider, raw_model)
    return model


_LEGACY_TAGS: dict[int, tuple[str, str]] = {}


def _import_provider(name: str):
    """Import a legacy provider module, handling both package and direct execution."""
    module_name = f"provider_{name}"
    try:
        return __import__(f".{module_name}", globals(), locals(), [f"create_{name}_model"], 1)
    except ImportError:
        return __import__(module_name, globals(), locals(), [f"create_{name}_model"], 0)


# --- LiteLLM unified factory -------------------------------------------------

def _create_model_litellm(
    provider: str,
    model: str,
    credentials: dict[str, Any],
    temperature: float,
    timeout: int | None,
    max_retries: int,
    reasoning_effort: str,
) -> _TaggedChatLiteLLM:
    """Build a single ChatLiteLLM covering all 8 providers.

    Provider-specific quirks (Azure 3-way dispatch, gemini-2.5 thinking_budget,
    Anthropic max_tokens, LMStudio dummy api_key + URL normalization, Docker
    localhost rewriting) are handled here. `litellm.drop_params=True` strips
    any params the target provider doesn't support.
    """
    kwargs: dict[str, Any] = {"temperature": temperature, "max_retries": max_retries}
    if timeout is not None:
        kwargs["timeout"] = timeout

    # effort_kind selects how the resolved effort (computed once, below, after
    # litellm_model is known) gets injected: "reasoning_effort" is the normal
    # OpenAI-shaped param; "gemini_budget" is Gemini 2.5's separate
    # thinking_budget field; None means this provider never takes an effort
    # param (groq/ollama/lmstudio -- not in litellm's reasoning-capability map,
    # so forcing it through would just be noise).
    effort_kind: str | None = None

    if provider == "openai":
        litellm_model = f"openai/{model}"
        kwargs["api_key"] = credentials["api_key"]
        if credentials.get("base_url"):
            kwargs["api_base"] = credentials["base_url"]
        effort_kind = "reasoning_effort"

    elif provider == "azure":
        endpoint = credentials.get("endpoint", "")
        if not endpoint:
            raise ValueError("Azure endpoint is required. Set it in Settings.")
        resource = _extract_azure_resource_name(endpoint)
        kwargs["api_key"] = credentials["api_key"]
        if model.startswith("gpt-"):
            litellm_model = f"azure/{credentials.get('deployment_name') or model}"
            kwargs["api_base"] = f"https://{resource}.openai.azure.com"
            kwargs["api_version"] = credentials.get("api_version", "2024-02-15-preview")
        elif model.startswith("claude-"):
            litellm_model = f"azure_ai/{model}"
            kwargs["api_base"] = f"https://{resource}.services.ai.azure.com/anthropic"
            # Anthropic's extended/adaptive thinking counts thinking tokens against
            # this same ceiling, so a low value can let high-effort reasoning consume
            # the whole budget before any visible text/tool call is emitted.
            kwargs["max_tokens"] = 65536
        else:
            litellm_model = f"azure_ai/{model}"
            kwargs["api_base"] = f"https://{resource}.services.ai.azure.com/openai/v1/"
        effort_kind = "reasoning_effort"

    elif provider == "gemini":
        litellm_model = f"gemini/{model}"
        kwargs["api_key"] = credentials["api_key"]
        effort_kind = "gemini_budget" if model.startswith("gemini-2.5") else "reasoning_effort"

    elif provider == "groq":
        litellm_model = f"groq/{model}"
        kwargs["api_key"] = credentials["api_key"]
        # reasoning_effort intentionally NOT set; drop_params would drop it anyway

    elif provider == "ollama":
        litellm_model = f"ollama_chat/{model}"
        kwargs["api_base"] = fix_localhost_for_docker(
            credentials.get("base_url", "http://localhost:11434")
        )

    elif provider == "lmstudio":
        litellm_model = f"lm_studio/{model or 'default'}"
        kwargs["api_key"] = "not-needed"
        kwargs["api_base"] = fix_localhost_for_docker(
            _normalize_lmstudio_base_url(credentials.get("base_url", "http://localhost:1234/v1"))
        )

    elif provider == "anthropic":
        litellm_model = f"anthropic/{model}"
        kwargs["api_key"] = credentials["api_key"]
        # See the azure_ai/claude- branch above: thinking tokens draw from the
        # same max_tokens ceiling, so this must leave headroom for high-effort
        # reasoning plus visible output.
        kwargs["max_tokens"] = 65536
        effort_kind = "reasoning_effort"

    elif provider == "togetherai":
        litellm_model = f"together_ai/{model}"
        kwargs["api_key"] = credentials["api_key"]
        # litellm keeps a static allowlist of together_ai models it believes support
        # function calling. Models not on it (e.g. zai-org/GLM-5.1,
        # nvidia/nemotron-3-ultra-550b-a55b, and any user custom model) have their
        # tools/tool_choice SILENTLY dropped under drop_params=True, so the model
        # only sees tool descriptions in the system prompt and "calls" them as text.
        # Force these params through; Together's API supports them natively. No-op for
        # plain chat (tools absent) and for already-supported models like Qwen.
        kwargs["model_kwargs"] = {"allowed_openai_params": ["tools", "tool_choice"]}
        # litellm also has NO reasoning_effort support data for together_ai at all
        # (see providers/effort.py's togetherai carve-out), so that param would be
        # silently dropped the same way without forcing it through below.
        effort_kind = "reasoning_effort"

    else:
        raise ValueError(f"Unknown provider: {provider}")

    resolved = None
    if effort_kind is not None:
        resolved = resolve_effort(provider, litellm_model, model, reasoning_effort)
        if effort_kind == "gemini_budget":
            budget = gemini_thinking_budget(resolved.effective)
            if budget is not None:
                kwargs["thinking_budget"] = budget
        elif resolved.effective is not None:
            kwargs["reasoning_effort"] = resolved.effective
        if resolved.force_param:
            # Append, never overwrite -- togetherai's model_kwargs above (the
            # tools/tool_choice workaround) must survive intact.
            model_kwargs = kwargs.setdefault("model_kwargs", {})
            allowed = model_kwargs.setdefault("allowed_openai_params", [])
            if "reasoning_effort" not in allowed:
                allowed.append("reasoning_effort")

    chat = _TaggedChatLiteLLM(model=litellm_model, **kwargs)
    chat._wordllms_provider = provider
    chat._wordllms_raw_model = model
    chat._wordllms_effort = display_effort(resolved) if resolved is not None else None
    return chat


# --- Legacy per-provider factory dispatch -----------------------------------

def _create_model_legacy(
    provider: str,
    model: str,
    credentials: dict[str, Any],
    temperature: float,
    timeout: int | None,
    max_retries: int,
    reasoning_effort: str,
) -> BaseChatModel:
    """Original per-provider dispatch path. Tags the returned model so
    downstream `get_provider(model)` works regardless of which path built it."""
    if provider == "openai":
        mod = _import_provider("openai")
        m = mod.create_openai_model(model, credentials, temperature, timeout, max_retries, reasoning_effort)
    elif provider == "azure":
        mod = _import_provider("azure")
        m = mod.create_azure_model(model, credentials, temperature, timeout, max_retries, reasoning_effort)
    elif provider == "gemini":
        mod = _import_provider("gemini")
        m = mod.create_gemini_model(model, credentials, temperature, timeout, max_retries, reasoning_effort)
    elif provider == "groq":
        mod = _import_provider("groq")
        m = mod.create_groq_model(model, credentials, temperature, timeout, max_retries)
    elif provider == "ollama":
        mod = _import_provider("ollama")
        m = mod.create_ollama_model(model, credentials, temperature, timeout, max_retries)
    elif provider == "lmstudio":
        mod = _import_provider("lmstudio")
        m = mod.create_lmstudio_model(model, credentials, temperature, timeout, max_retries)
    elif provider == "anthropic":
        mod = _import_provider("anthropic")
        m = mod.create_anthropic_model(model, credentials, temperature, timeout, max_retries, reasoning_effort)
    elif provider == "togetherai":
        mod = _import_provider("togetherai")
        m = mod.create_togetherai_model(model, credentials, temperature, timeout, max_retries)
    else:
        raise ValueError(f"Unknown provider: {provider}")

    return _tag_legacy(m, provider, model)


def create_model(
    provider: Literal["openai", "azure", "gemini", "groq", "ollama", "lmstudio", "anthropic", "togetherai"],
    model: str,
    credentials: dict[str, Any],
    temperature: float = 1.0,
    timeout: int | None = None,
    max_retries: int = 3,
    reasoning_effort: str = "medium",
) -> BaseChatModel:
    """Factory function to create a chat model based on provider.

    Phase A: dispatches on env var `WORDLLMS_USE_LITELLM=1` to the new
    ChatLiteLLM-based factory. Default (unset/0) keeps the legacy per-provider
    code path intact for safe rollout.

    `max_retries` defaults to 3 -- no call site should assume an LLM call
    succeeds on the first try. This only feeds langchain_litellm's own retry
    decorator, which covers Timeout/APIError/APIConnectionError/RateLimitError;
    it does NOT cover litellm.InternalServerError (e.g. upstream 500s), so
    `agents/llm_retry.py`'s wrappers separately retry on that class of error.
    """
    if _USE_LITELLM:
        return _create_model_litellm(
            provider, model, credentials, temperature, timeout, max_retries, reasoning_effort
        )
    return _create_model_legacy(
        provider, model, credentials, temperature, timeout, max_retries, reasoning_effort
    )
