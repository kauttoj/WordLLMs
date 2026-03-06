import os
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse

from langchain_core.language_models.chat_models import BaseChatModel

_IN_DOCKER = os.environ.get("RUNNING_IN_DOCKER") == "1"


def fix_localhost_for_docker(url: str) -> str:
    """Rewrite localhost/127.0.0.1 to host.docker.internal when in Docker."""
    if not _IN_DOCKER:
        return url
    parsed = urlparse(url)
    if parsed.hostname in ("localhost", "127.0.0.1"):
        replaced = parsed._replace(netloc=parsed.netloc.replace(parsed.hostname, "host.docker.internal"))
        return urlunparse(replaced)
    return url


def get_model_name(model: BaseChatModel) -> str:
    """Extract the model name from a LangChain model object.

    Different providers store the name in different attributes:
    - ChatOpenAI/ChatGroq: model_name
    - ChatGoogleGenerativeAI/ChatOllama: model
    - AzureChatOpenAI: model_name is None, uses deployment_name
    """
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
    return name


def _import_provider(name: str):
    """Import a provider module, handling both package and direct execution."""
    module_name = f"provider_{name}"
    try:
        return __import__(f".{module_name}", globals(), locals(), [f"create_{name}_model"], 1)
    except ImportError:
        return __import__(module_name, globals(), locals(), [f"create_{name}_model"], 0)


def create_model(
    provider: Literal["openai", "azure", "gemini", "groq", "ollama", "lmstudio", "anthropic"],
    model: str,
    credentials: dict[str, Any],
    temperature: float = 1.0,
    timeout: int | None = None,
    max_retries: int = 0,
) -> BaseChatModel:
    """Factory function to create a chat model based on provider."""
    if provider == "openai":
        mod = _import_provider("openai")
        return mod.create_openai_model(model, credentials, temperature, timeout, max_retries)
    elif provider == "azure":
        mod = _import_provider("azure")
        return mod.create_azure_model(model, credentials, temperature, timeout, max_retries)
    elif provider == "gemini":
        mod = _import_provider("gemini")
        return mod.create_gemini_model(model, credentials, temperature, timeout, max_retries)
    elif provider == "groq":
        mod = _import_provider("groq")
        return mod.create_groq_model(model, credentials, temperature, timeout, max_retries)
    elif provider == "ollama":
        mod = _import_provider("ollama")
        return mod.create_ollama_model(model, credentials, temperature, timeout, max_retries)
    elif provider == "lmstudio":
        mod = _import_provider("lmstudio")
        return mod.create_lmstudio_model(model, credentials, temperature, timeout, max_retries)
    elif provider == "anthropic":
        mod = _import_provider("anthropic")
        return mod.create_anthropic_model(model, credentials, temperature, timeout, max_retries)
    else:
        raise ValueError(f"Unknown provider: {provider}")
