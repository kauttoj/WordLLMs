"""Context window management: model-specific token counting and message trimming."""

import json
from typing import Sequence
from litellm import token_counter
from langchain_core.messages import BaseMessage, SystemMessage, AIMessage, ToolMessage


def count_tokens(model_name: str, messages: Sequence[BaseMessage]) -> int:
    """Count tokens using litellm's model-specific tokenizer."""
    return token_counter(model=model_name, messages=_to_litellm_messages(messages))


_DEPRECATED_DOC_CONTENT = "[content deprecated, see the updated content or re-read]"


def _deprecate_stale_document_reads(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Keep only the most recent get_document_content result; deprecate older ones.

    When the agent reads the document multiple times (across turns or within a turn),
    only the latest snapshot is relevant.  Older ToolMessage results are replaced with
    a short marker so the LLM knows the content existed but doesn't waste tokens on it.
    """
    # Build map: tool_call_id -> tool_name from AIMessages
    call_id_to_name: dict[str, str] = {}
    for msg in messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                call_id_to_name[tc["id"]] = tc["name"]

    # Find indices of all get_document_content ToolMessages
    doc_indices: list[int] = []
    for i, msg in enumerate(messages):
        if isinstance(msg, ToolMessage) and call_id_to_name.get(msg.tool_call_id) == "get_document_content":
            doc_indices.append(i)

    if len(doc_indices) <= 1:
        return messages  # Nothing to deduplicate

    # Replace all but the last (most recent) with deprecation marker
    for idx in doc_indices[:-1]:
        old = messages[idx]
        messages[idx] = ToolMessage(content=_DEPRECATED_DOC_CONTENT, tool_call_id=old.tool_call_id)
    return messages


def trim_to_fit(
    messages: Sequence[BaseMessage],
    model_name: str,
    max_context_tokens: int,
    protected_tail: int = 1,
) -> list[BaseMessage]:
    """Trim oldest history messages to fit within context window.

    Preserves: first message (if SystemMessage), last `protected_tail` messages.
    Trims tool-interaction pairs as atomic units.
    Raises ValueError if protected messages alone exceed the budget.
    Only logs when trimming actually occurs.
    """
    # Deprecate stale document reads before any budget calculations
    messages = _deprecate_stale_document_reads(list(messages))

    # Reserve 20% for output
    budget = int(max_context_tokens * 0.80)

    current = count_tokens(model_name, messages)
    if current <= budget:
        return list(messages)

    # Protected regions
    has_system = messages and isinstance(messages[0], SystemMessage)
    head = messages[:1] if has_system else []
    tail = messages[-protected_tail:] if protected_tail > 0 else []
    mid_start = 1 if has_system else 0
    mid_end = len(messages) - protected_tail
    middle = list(messages[mid_start:mid_end])

    protected_tokens = count_tokens(model_name, head + tail)
    if protected_tokens > budget:
        raise ValueError(
            f"Context budget exceeded with system prompt + current turn alone: "
            f"~{protected_tokens} tokens, budget: {budget}."
        )

    # Group middle into segments (tool-call pairs stay together)
    segments = _group_tool_segments(middle)

    # Remove oldest segments until it fits
    removed_count = 0
    while segments and count_tokens(model_name, head + _flatten(segments) + tail) > budget:
        segments.pop(0)
        removed_count += 1

    result = head + _flatten(segments) + tail
    trimmed_tokens = count_tokens(model_name, result)
    print(
        f"[context] Trimmed {len(messages) - len(result)} message(s) "
        f"({removed_count} segment(s)): "
        f"{current} -> {trimmed_tokens} tokens "
        f"(budget: {budget}, model: {model_name})"
    )
    return result


def _to_litellm_messages(messages: Sequence[BaseMessage]) -> list[dict]:
    """Convert LangChain messages to litellm-compatible dict format."""
    role_map = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}
    result = []
    for msg in messages:
        role = role_map.get(msg.type, "user")
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        entry: dict = {"role": role, "content": content}
        if isinstance(msg, AIMessage) and msg.tool_calls:
            entry["tool_calls"] = [
                {"id": tc.get("id", ""), "type": "function",
                 "function": {"name": tc["name"], "arguments": json.dumps(tc.get("args", {}))}}
                for tc in msg.tool_calls
            ]
        if isinstance(msg, ToolMessage):
            entry["tool_call_id"] = getattr(msg, "tool_call_id", "")
        result.append(entry)
    return result


def _group_tool_segments(messages: list[BaseMessage]) -> list[list[BaseMessage]]:
    """Group AIMessage+ToolMessages into atomic segments for trimming."""
    segments: list[list[BaseMessage]] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            group = [msg]
            j = i + 1
            while j < len(messages) and isinstance(messages[j], ToolMessage):
                group.append(messages[j])
                j += 1
            segments.append(group)
            i = j
        else:
            segments.append([msg])
            i += 1
    return segments


def _flatten(segments: list[list[BaseMessage]]) -> list[BaseMessage]:
    return [msg for seg in segments for msg in seg]
