"""File attachment processing: decode, parse, and format files for LLM context."""

import base64
import io
import mimetypes
from pathlib import Path

from markitdown import MarkItDown, StreamInfo

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
PLAIN_TEXT_EXTENSIONS = {
    ".txt", ".log", ".md", ".csv", ".tsv", ".json", ".jsonl",
    ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".sh", ".bash", ".zsh", ".bat", ".cmd", ".ps1",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".vue", ".svelte",
    ".html", ".htm", ".css", ".scss", ".less", ".sass",
    ".java", ".kt", ".scala", ".c", ".cpp", ".h", ".hpp", ".cs",
    ".go", ".rs", ".rb", ".php", ".swift", ".m", ".r",
    ".sql", ".graphql", ".proto",
    ".env", ".gitignore", ".dockerignore", ".editorconfig",
    ".dockerfile", ".makefile",
}

# Single stateless converter instance — just a registry of format handlers.
_converter = MarkItDown(enable_plugins=False)


def is_image(filename: str) -> bool:
    """Check if filename has an image extension."""
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS


def _get_mime_type(filename: str) -> str:
    """Guess MIME type from filename, defaulting to application/octet-stream."""
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


def parse_file(filename: str, data_b64: str, char_limit: int = 0) -> str:
    """Parse a base64-encoded file into markdown text via MarkItDown.

    Args:
        filename: Original filename with extension.
        data_b64: Base64-encoded file content.
        char_limit: Max characters in output. 0 means unlimited.

    Returns:
        Parsed markdown text content.

    Raises:
        ValueError: On unsupported file types or parse failures.
    """
    raw = base64.b64decode(data_b64)
    ext = Path(filename).suffix.lower()

    if ext in IMAGE_EXTENSIONS:
        raise ValueError(f"Image files should not be parsed as text: {filename}")

    # For known plain-text formats, decode directly to avoid MarkItDown ASCII issues.
    if ext in PLAIN_TEXT_EXTENSIONS or ext.lstrip(".") in PLAIN_TEXT_EXTENSIONS:
        for encoding in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                text = raw.decode(encoding)
                break
            except (UnicodeDecodeError, ValueError):
                continue
        else:
            raise ValueError(f"Failed to decode '{filename}' as text (tried utf-8, utf-8-sig, latin-1)")
    else:
        try:
            result = _converter.convert_stream(
                io.BytesIO(raw),
                stream_info=StreamInfo(extension=ext, filename=filename),
            )
        except Exception as e:
            raise ValueError(f"Failed to parse '{filename}': {e}") from e
        text = result.text_content

    if char_limit > 0 and len(text) > char_limit:
        text = text[:char_limit] + f"\n\n[Content truncated at {char_limit} characters]"

    return text


def format_attachments_for_message(
    attachments: list[dict],
    char_limit: int = 0,
) -> tuple[str, list[dict]]:
    """Parse all attachments and split into text block + image parts.

    Args:
        attachments: List of dicts with 'filename' and 'data' (base64) keys.
        char_limit: Per-file character limit for parsed text. 0 = unlimited.

    Returns:
        (text_block, image_parts) where:
        - text_block: formatted text for non-image files
        - image_parts: list of multimodal image_url content parts for images
    """
    text_parts: list[str] = []
    image_parts: list[dict] = []

    for att in attachments:
        filename = att["filename"]
        data_b64 = att["data"]

        if is_image(filename):
            mime = _get_mime_type(filename)
            image_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{data_b64}"},
            })
        else:
            content = parse_file(filename, data_b64, char_limit)
            text_parts.append(
                f'<attachment filename="{filename}">\n{content}\n</attachment>'
            )

    text_block = ""
    if text_parts:
        text_block = "\n\n---\n**Attached Files:**\n\n" + "\n\n".join(text_parts)

    return text_block, image_parts
