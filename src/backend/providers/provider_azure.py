from typing import Any
from langchain_openai import AzureChatOpenAI


def create_azure_model(
    model: str,
    credentials: dict[str, Any],
    temperature: float,
    timeout: int | None = None,
    max_retries: int = 3,
) -> AzureChatOpenAI:
    """Create an Azure OpenAI chat model."""
    kwargs: dict[str, Any] = {
        "azure_deployment": credentials.get("deployment_name", model),
        "azure_endpoint": credentials["endpoint"],
        "api_key": credentials["api_key"],
        "api_version": credentials.get("api_version", "2024-02-15-preview"),
        "temperature": temperature,
        "max_retries": max_retries,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return AzureChatOpenAI(**kwargs)
