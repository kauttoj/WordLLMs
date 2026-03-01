import sys
from pathlib import Path

_THIS_DIR = Path(__file__).parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

try:
    from .base import create_model
    from .provider_openai import create_openai_model
    from .provider_anthropic import create_anthropic_model
    from .provider_azure import create_azure_model
    from .provider_gemini import create_gemini_model
    from .provider_groq import create_groq_model
    from .provider_ollama import create_ollama_model
except ImportError:
    from base import create_model
    from provider_openai import create_openai_model
    from provider_anthropic import create_anthropic_model
    from provider_azure import create_azure_model
    from provider_gemini import create_gemini_model
    from provider_groq import create_groq_model
    from provider_ollama import create_ollama_model

__all__ = [
    "create_model",
    "create_openai_model",
    "create_anthropic_model",
    "create_azure_model",
    "create_gemini_model",
    "create_groq_model",
    "create_ollama_model",
]
