"""Shared utility functions for agent modules."""


def extract_text_from_content(content) -> str:
    """Extract text string from message content (handles both string and list formats).

    Anthropic models return content as either:
    - str: Simple text response
    - list[dict]: List of content blocks like [{"type": "text", "text": "..."}]

    This helper normalizes both formats to a plain string, following LangChain's
    recommended approach for handling provider differences.

    Args:
        content: Either a string or a list of content blocks from an AI message

    Returns:
        Extracted text as a string. Empty string if no text content found.
    """
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict) and block.get('type') == 'text':
                text_parts.append(block.get('text', ''))
        return ''.join(text_parts)
    return ""
