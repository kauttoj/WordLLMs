from typing import Any
from urllib.parse import urlparse

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import AzureChatOpenAI, ChatOpenAI


def _detect_model_type(model: str) -> str:
    """Auto-detect Azure model type from model name."""
    if model.startswith("gpt-"):
        return "azure_openai"
    if model.startswith("claude-"):
        return "anthropic"
    return "ai_services"


def _extract_resource_name(endpoint: str) -> str:
    """Extract Azure resource name from any Azure endpoint URL.

    Handles:
      - https://X.openai.azure.com/...
      - https://X.services.ai.azure.com/...
    """
    host = urlparse(endpoint).hostname
    if not host:
        raise ValueError(f"Cannot parse Azure endpoint URL: {endpoint}")
    return host.split(".")[0]


def create_azure_model(
    model: str,
    credentials: dict[str, Any],
    temperature: float,
    timeout: int | None = None,
    max_retries: int = 3,
) -> BaseChatModel:
    """Create an Azure chat model, auto-detecting type from model name."""
    endpoint = credentials.get("endpoint", "")
    if not endpoint:
        raise ValueError("Azure endpoint is required. Set it in Settings.")

    resource = _extract_resource_name(endpoint)
    model_type = _detect_model_type(model)

    if model_type == "anthropic":
        return _create_anthropic_model(model, resource, credentials, temperature, timeout, max_retries)
    elif model_type == "ai_services":
        return _create_ai_services_model(model, resource, credentials, temperature, timeout, max_retries)
    else:
        return _create_azure_openai_model(model, resource, credentials, temperature, timeout, max_retries)


def _create_azure_openai_model(
    model: str,
    resource: str,
    credentials: dict[str, Any],
    temperature: float,
    timeout: int | None = None,
    max_retries: int = 3,
) -> AzureChatOpenAI:
    """Azure OpenAI models (GPT series) via AzureChatOpenAI."""
    kwargs: dict[str, Any] = {
        "azure_deployment": credentials.get("deployment_name", model),
        "azure_endpoint": f"https://{resource}.openai.azure.com",
        "api_key": credentials["api_key"],
        "api_version": credentials.get("api_version", "2024-02-15-preview"),
        "temperature": temperature,
        "max_retries": max_retries,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return AzureChatOpenAI(**kwargs)


def _create_ai_services_model(
    model: str,
    resource: str,
    credentials: dict[str, Any],
    temperature: float,
    timeout: int | None = None,
    max_retries: int = 3,
) -> ChatOpenAI:
    """Azure AI Services models (DeepSeek, Llama, Mistral, etc.) via OpenAI-compatible endpoint."""
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": credentials["api_key"],
        "base_url": f"https://{resource}.services.ai.azure.com/openai/v1/",
        "temperature": temperature,
        "max_retries": max_retries,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return ChatOpenAI(**kwargs)


def _create_anthropic_model(
    model: str,
    resource: str,
    credentials: dict[str, Any],
    temperature: float,
    timeout: int | None = None,
    max_retries: int = 3,
) -> BaseChatModel:
    """Anthropic Foundry models (Claude series) hosted on Azure."""
    from langchain_anthropic import ChatAnthropic

    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": credentials["api_key"],
        "anthropic_api_url": f"https://{resource}.openai.azure.com/anthropic",
        "temperature": temperature,
        "max_tokens": 16384,
        "max_retries": max_retries,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return ChatAnthropic(**kwargs)
