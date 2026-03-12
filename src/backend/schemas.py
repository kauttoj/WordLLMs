from typing import Any, Literal
from pydantic import BaseModel, Field

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
)

class Attachment(BaseModel):
    """A file attachment sent with a chat message."""
    filename: str
    data: str  # base64-encoded file content


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str | list[dict[str, Any]]  # str for text, list for multimodal (images)


class OpenAICredentials(BaseModel):
    api_key: str
    base_url: str | None = None


class AzureCredentials(BaseModel):
    api_key: str
    endpoint: str = ""
    api_version: str = "2024-02-15-preview"
    deployment_name: str = ""


class GeminiCredentials(BaseModel):
    api_key: str


class GroqCredentials(BaseModel):
    api_key: str


class OllamaCredentials(BaseModel):
    base_url: str = "http://localhost:11434"


class LmstudioCredentials(BaseModel):
    base_url: str = "http://localhost:1234/v1"


class AnthropicCredentials(BaseModel):
    api_key: str


Credentials = OpenAICredentials | AzureCredentials | GeminiCredentials | GroqCredentials | OllamaCredentials | LmstudioCredentials | AnthropicCredentials


def to_langchain_messages(messages: list[Message]) -> list[BaseMessage]:
    """Convert API Message schema objects to LangChain BaseMessage objects."""
    converted: list[BaseMessage] = []

    for msg in messages:
        if msg.role == "user":
            converted.append(HumanMessage(content=msg.content))

        elif msg.role == "assistant":
            converted.append(AIMessage(content=msg.content))

        elif msg.role == "system":
            converted.append(SystemMessage(content=msg.content))

        else:
            raise ValueError(f"Unsupported message role: {msg.role}")

    return converted


def from_langchain_message(msg: BaseMessage) -> Message:
    """Convert LangChain BaseMessage back to API Message schema."""
    role_map = {
        "human": "user",
        "ai": "assistant",
        "system": "system",
    }

    role = role_map.get(msg.type)
    if not role:
        raise ValueError(f"Unsupported LangChain message type: {msg.type}")

    return Message(role=role, content=msg.content)


class ChatRequest(BaseModel):
    messages: list[Message]
    provider: Literal["openai", "azure", "gemini", "groq", "ollama", "lmstudio", "anthropic"]
    model: str
    credentials: dict[str, Any]
    temperature: float = Field(default=1.0, ge=0, le=2)
    max_context_tokens: int = Field(default=128000, ge=4000)
    llm_timeout: int = Field(default=90, ge=5)  # Seconds per LLM API call
    filter_thinking: bool = Field(default=True)
    language: str | None = None  # If provided, backend generates default system prompt
    additional_system_prompt: str | None = None  # Appended to system prompt as behavioral instructions
    conversation_id: str | None = None  # Enables unified cross-mode conversation history
    attachments: list[Attachment] = Field(default_factory=list)
    attachment_char_limit: int = Field(default=100000, ge=500)  # Per-file char limit


class AgentRequest(BaseModel):
    messages: list[Message]
    provider: Literal["openai", "azure", "gemini", "groq", "ollama", "lmstudio", "anthropic"]
    model: str
    credentials: dict[str, Any]
    tools: list[str] = Field(default_factory=list)
    thread_id: str | None = None
    conversation_id: str | None = None  # Enables unified cross-mode conversation history
    recursion_limit: int = Field(default=120, ge=1)
    temperature: float = Field(default=1.0, ge=0, le=2)
    max_context_tokens: int = Field(default=128000, ge=4000)
    llm_timeout: int = Field(default=90, ge=5)  # Seconds per LLM API call
    filter_thinking: bool = Field(default=True)
    language: str | None = None  # If provided, backend generates default system prompt
    additional_system_prompt: str | None = None  # Appended to system prompt as behavioral instructions
    attachments: list[Attachment] = Field(default_factory=list)
    attachment_char_limit: int = Field(default=100000, ge=500)  # Per-file char limit
    tavily_api_key: str | None = None  # API key for Tavily web search (cross-provider)


class ClientToolResult(BaseModel):
    call_id: str
    name: str
    result: str


class AgentContinueRequest(BaseModel):
    session_id: str
    tool_results: list[ClientToolResult]
    provider: Literal["openai", "azure", "gemini", "groq", "ollama", "lmstudio", "anthropic"]
    model: str
    credentials: dict[str, Any]
    temperature: float = Field(default=1, ge=0, le=2)
    max_context_tokens: int = Field(default=128000, ge=4000)
    llm_timeout: int = Field(default=90, ge=5)  # Seconds per LLM API call
    filter_thinking: bool = Field(default=True)
    recursion_limit: int = Field(default=120, ge=1)
    tavily_api_key: str | None = None
    tools: list[str] = Field(default_factory=list)


class AgentSessionInfo(BaseModel):
    tool_names: list[str]


class SSEEvent(BaseModel):
    event: Literal["text", "tool_call", "tool_result", "client_tool_call", "error", "done"]
    data: dict[str, Any]


class MultiAgentExpertConfig(BaseModel):
    """Configuration for one expert model."""
    provider: Literal["openai", "azure", "gemini", "groq", "ollama", "lmstudio", "anthropic"]
    model: str
    credentials: dict[str, Any]
    temperature: float = Field(default=1, ge=0, le=2)
    max_context_tokens: int = Field(default=128000, ge=4000)


class MultiAgentRequest(BaseModel):
    """Request for multiagent processing."""
    messages: list[Message]
    mode: Literal["parallel", "collaborative"]
    operating_mode: Literal["combined", "legacy"] = Field(default="combined")
    max_rounds: int = Field(default=3, ge=1, le=50)
    use_expert_memory: bool = Field(default=True)
    expert_full_history: bool = Field(default=False)  # Give experts cross-turn conversation history
    use_expert_parallelization: bool = Field(default=True)  # True = async parallel, False = sequential LangGraph
    conversation_id: str | None = None  # Enables unified cross-mode conversation history

    experts: list[MultiAgentExpertConfig] = Field(min_length=2, max_length=4)
    overseer: MultiAgentExpertConfig
    synthesizer: MultiAgentExpertConfig | None = None  # If None, use overseer
    formatter: MultiAgentExpertConfig | None = None  # Cheap model for legacy mode tag extraction fallback

    expert_tools: list[str] = Field(default_factory=list)
    supervisor_tools: list[str] = Field(default_factory=list)

    recursion_limit: int = Field(default=120, ge=1)
    llm_timeout: int = Field(default=90, ge=5)  # Seconds per LLM API call
    filter_thinking: bool = Field(default=True)
    language: str | None = None  # If provided, used for system prompt language
    additional_system_prompt: str | None = None  # Appended to system prompt as behavioral instructions
    attachments: list[Attachment] = Field(default_factory=list)
    attachment_char_limit: int = Field(default=100000, ge=500)  # Per-file char limit
    tavily_api_key: str | None = None


class MultiAgentContinueRequest(BaseModel):
    """Resume multiagent after client tool execution."""
    session_id: str
    tool_results: list[ClientToolResult]


# --- Thread & History Path Models ---

class SerializedMessage(BaseModel):
    """A single message in a thread's display history."""
    role: Literal["user", "assistant", "system", "tool_call"]
    content: str
    timestamp: float
    metadata: dict[str, Any] | None = None
    toolName: str | None = None
    attachments: list[dict[str, str]] | None = None  # [{"filename": "..."}]


class ThreadSaveRequest(BaseModel):
    """Save or update a GUI display thread."""
    id: str
    title: str
    messages: list[SerializedMessage]
    mode: str
    provider: str | None = None
    model: str | None = None
    messageCount: int = 0
    createdAt: str | None = None
    updatedAt: str | None = None


class HistoryPathRequest(BaseModel):
    """Request to switch the conversation history database path."""
    path: str


class EditMessageRequest(BaseModel):
    """Edit a user message in-place at a specific turn."""
    conversation_id: str
    turn: int = Field(ge=1)
    new_content: str


class TruncateRequest(BaseModel):
    """Truncate conversation entries from a given turn onward."""
    conversation_id: str
    from_turn: int = Field(ge=1)


class ForkRequest(BaseModel):
    """Fork conversation entries up to a given turn into a new conversation."""
    source_conversation_id: str
    target_conversation_id: str
    up_to_turn: int = Field(ge=1)


# --- MCP Server Models ---

class MCPServerAddRequest(BaseModel):
    """Add a new MCP server configuration."""
    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class MCPServerUpdateRequest(BaseModel):
    """Update an existing MCP server configuration."""
    name: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
