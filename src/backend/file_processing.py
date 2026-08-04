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
    ".tex", ".bib", ".cls", ".sty",
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


def parse_file(filename: str, data_b64: str, char_limit: int = 0) -> tuple[str, dict | None]:
    """Parse a base64-encoded file into markdown text via MarkItDown.

    Args:
        filename: Original filename with extension.
        data_b64: Base64-encoded file content.
        char_limit: Max characters in output. 0 means unlimited.

    Returns:
        (text, truncation_info) where truncation_info is None or
        {"filename": str, "original_chars": int, "truncated_chars": int}.

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

    truncation_info = None
    if char_limit > 0 and len(text) > char_limit:
        truncation_info = {
            "filename": filename,
            "original_chars": len(text),
            "truncated_chars": char_limit,
        }
        text = text[:char_limit] + f"\n\n[Content truncated at {char_limit} characters]"

    return text, truncation_info


def compose_user_content(
    base_text: str, items: list[dict], char_limit: int,
) -> tuple[str | list[dict], list[dict]]:
    """Build the exact content a user message carries when it has attachments.

    This is the single code path that composes attachment content into a user
    message — used identically by the send path (fresh upload, resolved via
    `attachment_store.load_for_injection`) and the edit path, so a message
    restored from history is byte-for-byte identical to a freshly sent one.

    Args:
        base_text: The user's typed message text.
        items: Resolved attachment content, in order — each either
            {"filename","kind":"text","text"} or
            {"filename","kind":"image","data_b64"}.
        char_limit: Per-file character limit for text items. 0 = unlimited.
            Applied here (not at storage time) so changing the setting
            affects previously-stored attachments too.

    Returns:
        (content, truncation_warnings) where content is a plain string when
        there are no images, or a multimodal content list (text part first,
        then image_url parts) when there is at least one image. If `items` is
        empty, content is `base_text` unchanged and truncation_warnings is [].
    """
    if not items:
        return base_text, []

    text_parts: list[str] = []
    image_parts: list[dict] = []
    truncation_warnings: list[dict] = []

    for item in items:
        filename = item["filename"]
        if item["kind"] == "image":
            mime = _get_mime_type(filename)
            image_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{item['data_b64']}"},
            })
        else:
            text = item["text"]
            if char_limit > 0 and len(text) > char_limit:
                truncation_warnings.append({
                    "filename": filename,
                    "original_chars": len(text),
                    "truncated_chars": char_limit,
                })
                text = text[:char_limit] + f"\n\n[Content truncated at {char_limit} characters]"
            text_parts.append(
                f'<attachment filename="{filename}">\n{text}\n</attachment>'
            )

    text_block = ""
    if text_parts:
        text_block = "\n\n---\n**Attached Files:**\n\n" + "\n\n".join(text_parts)

    if image_parts:
        return [{"type": "text", "text": base_text + text_block}, *image_parts], truncation_warnings
    return base_text + text_block, truncation_warnings
