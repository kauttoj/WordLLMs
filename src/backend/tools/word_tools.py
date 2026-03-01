"""Client-side Word tool schemas for LLM agent.

These tools interact with the Word document via Office.js and CANNOT run in Python.
The backend defines their schemas so the LLM knows about them, but execution is
delegated to the frontend via the RPC pattern (client_tool_call SSE event).

The @tool-decorated functions here are NEVER executed server-side — they exist
only to generate JSON schemas for LangChain's tool binding.
"""

from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool


def _client_only() -> str:
    raise RuntimeError("Client-side tool — cannot execute on server. Must be executed via frontend Office.js.")


# --- Document Reading Tools ---

@tool
def get_selected_text() -> str:
    """Get the currently selected text in the Word document. Returns the selected text or empty string if nothing is selected."""
    _client_only()


@tool
def get_document_content() -> str:
    """Get the full content of the Word document body as plain text."""
    _client_only()


@tool
def get_document_properties() -> str:
    """Get document properties including paragraph count, word count, and character count."""
    _client_only()


@tool
def get_range_info() -> str:
    """Get detailed information about the current selection including text, formatting, and position. Returns an error if no text is currently selected."""
    _client_only()


@tool
def get_table_info() -> str:
    """Get information about tables in the document, including row and column counts."""
    _client_only()


@tool
def find_text(searchText: str, matchCase: bool = False) -> str:
    """Find text in the document and return information about matches including surrounding context. Does not modify the document.

    Args:
        searchText: The text to search for.
        matchCase: Whether to match case (default: false).
    """
    _client_only()


@tool
def find_and_select_text(searchText: str, matchCase: bool = False) -> str:
    """Find text in the document and select the first occurrence. Use this for SHORT selections (few sentences). After selection, the user will see the text highlighted in Word.

    Args:
        searchText: The text to search for and select.
        matchCase: Whether to match case (default: false).

    Returns:
        JSON string with success status, message, and match count.
    """
    _client_only()


@tool
def select_between_text(startText: str, endText: str, matchCase: bool = False) -> str:
    """Select a range between two text markers. Use this for LARGE selections (over a page/20+ sentences).

    Args:
        startText: The text marking the start of the selection (unique piece of text), included itself in selection.
        endText: The text marking the end of the selection (unique piece of text), included itself in selection.
        matchCase: Whether to match case (default: false).

    Returns:
        JSON string with success status and message.
    """
    _client_only()


# --- Text Insertion / Modification Tools ---

@tool
def insert_text(text: str, location: str = "End") -> str:
    """Insert text at the current cursor position in the Word document.

    Args:
        text: The text to insert.
        location: Where to insert: "Start", "End", "Before", "After", or "Replace".
    """
    _client_only()


@tool
def replace_selected_text(newText: str) -> str:
    """Replace ALL currently selected text with entirely new content. This replaces the entire selection -- for small edits (typos, grammar), use search_and_replace instead.

    Args:
        newText: The new text to replace the entire selection with.
    """
    _client_only()


@tool
def append_text(text: str) -> str:
    """Append text to the end of the document.

    Args:
        text: The text to append.
    """
    _client_only()


@tool
def insert_paragraph(text: str, location: str = "After", style: Optional[str] = None) -> str:
    """Insert a new paragraph at the specified location.

    Args:
        text: The paragraph text.
        location: Where to insert: "After" (after cursor/selection), "Before" (before cursor), "Start" (start of doc), or "End" (end of doc). Default is "After".
        style: Optional Word built-in style: Normal, Heading1, Heading2, Heading3, Heading4, Quote, IntenseQuote, Title, Subtitle.
    """
    _client_only()


@tool
def delete_text(direction: str = "After") -> str:
    """Delete the currently selected text or a specific range. If no text is selected, this will delete at the cursor position.

    Args:
        direction: Direction to delete if nothing selected: "Before" (backspace) or "After" (delete key).
    """
    _client_only()


@tool
def search_and_replace(searchText: str, replaceText: str, matchCase: bool = False) -> str:
    """Search for text in the document and replace it with new text. This is the preferred tool for targeted edits -- use it for proofreading fixes, correcting typos, grammar, or any task that changes specific words or phrases.

    Args:
        searchText: The exact text to find (must match document content precisely).
        replaceText: The corrected or replacement text.
        matchCase: Whether to match case (default: false).
    """
    _client_only()


@tool
def search_and_replace_in_selection(searchText: str, replaceText: str, matchCase: bool = False) -> str:
    """Search for text within the current selection and replace it. Same as search_and_replace but scoped to the active selection only.

    Args:
        searchText: The exact text to find within the selection.
        replaceText: The corrected or replacement text.
        matchCase: Whether to match case (default: false).
    """
    _client_only()


# --- Formatting Tools ---

@tool
def format_text(
    bold: Optional[bool] = None,
    italic: Optional[bool] = None,
    underline: Optional[str] = None,
    fontSize: Optional[float] = None,
    fontName: Optional[str] = None,
    fontColor: Optional[str] = None,
    highlightColor: Optional[str] = None,
) -> str:
    """Apply formatting to the currently selected text.

    Args:
        bold: Make text bold.
        italic: Make text italic.
        underline: Underline style: None, Single, Double, Dotted, Thick, or Wave.
        fontSize: Font size in points.
        fontName: Font family name (e.g., "Arial", "Times New Roman", "Calibri", "Consolas").
        fontColor: Font color as hex (e.g., "#FF0000" for red).
        highlightColor: Highlight color: Yellow, Green, Cyan, Pink, Blue, Red, DarkBlue, Teal, Lime, Purple, Orange, White, or Black.
    """
    _client_only()


@tool
def clear_formatting() -> str:
    """Clear all formatting from the selected text, returning it to default style."""
    _client_only()


@tool
def set_paragraph_format(
    alignment: Optional[str] = None,
    lineSpacing: Optional[float] = None,
    spaceBefore: Optional[float] = None,
    spaceAfter: Optional[float] = None,
    firstLineIndent: Optional[float] = None,
    leftIndent: Optional[float] = None,
    rightIndent: Optional[float] = None,
) -> str:
    """Apply paragraph formatting (alignment, spacing, indentation) to the currently selected paragraphs.

    Args:
        alignment: Paragraph alignment: Left, Centered, Right, or Justified.
        lineSpacing: Line spacing in points (e.g., 12 for single, 24 for double with 12pt font).
        spaceBefore: Space before paragraph in points.
        spaceAfter: Space after paragraph in points.
        firstLineIndent: First line indent in points (negative for hanging indent).
        leftIndent: Left indent in points.
        rightIndent: Right indent in points.
    """
    _client_only()


@tool
def set_style(style: str) -> str:
    """Apply a built-in Word style to the currently selected text or paragraphs.

    Args:
        style: The built-in style: Normal, Heading1, Heading2, Heading3, Heading4, Title, Subtitle, Quote, IntenseQuote, ListParagraph, or NoSpacing.
    """
    _client_only()


# --- Structure / Layout Tools ---

@tool
def insert_table(rows: int, columns: int, data: Optional[list[list[str]]] = None) -> str:
    """Insert a table at the current cursor position.

    Args:
        rows: Number of rows.
        columns: Number of columns.
        data: Optional 2D array of cell values.
    """
    _client_only()


@tool
def insert_list(items: list[str], listType: str) -> str:
    """Insert a bulleted or numbered list at the current position.

    Args:
        items: Array of list item texts.
        listType: Type of list: "bullet" or "number".
    """
    _client_only()


@tool
def insert_page_break(location: str = "After") -> str:
    """Insert a page break at the current cursor position.

    Args:
        location: Where to insert: "Before", "After", "Start", or "End".
    """
    _client_only()


@tool
def insert_image(imageUrl: str, width: Optional[float] = None, height: Optional[float] = None, location: str = "After") -> str:
    """Insert an image at the current cursor position. Accepts an image URL (http/https) or a base64-encoded image string.

    Args:
        imageUrl: Image URL (http/https) or base64-encoded image string.
        width: Optional width in points.
        height: Optional height in points.
        location: Where to insert: "Before", "After", "Start", "End", or "Replace".
    """
    _client_only()


# --- Selection / Navigation Tools ---

@tool
def select_text(scope: str) -> str:
    """Select all text in the document or specific location.

    Args:
        scope: What to select: "All" for entire document.
    """
    _client_only()


@tool
def insert_bookmark(name: str) -> str:
    """Insert a bookmark at the current selection to mark a location in the document.

    Args:
        name: The name of the bookmark (must be unique, no spaces allowed).
    """
    _client_only()


@tool
def go_to_bookmark(name: str) -> str:
    """Navigate to a previously created bookmark in the document.

    Args:
        name: The name of the bookmark to navigate to.
    """
    _client_only()


@tool
def insert_content_control(title: str, tag: Optional[str] = None, appearance: str = "BoundingBox") -> str:
    """Insert a content control (a container for content) at the current selection. Useful for creating structured documents.

    Args:
        title: The title of the content control.
        tag: Optional tag for programmatic identification.
        appearance: Visual appearance of the control: "BoundingBox", "Tags", or "Hidden".
    """
    _client_only()


# --- Registry ---

CLIENT_TOOLS = [
    get_selected_text,
    get_document_content,
    get_document_properties,
    get_range_info,
    get_table_info,
    find_text,
    find_and_select_text,
    select_between_text,
    insert_text,
    replace_selected_text,
    append_text,
    insert_paragraph,
    delete_text,
    search_and_replace,
    search_and_replace_in_selection,
    format_text,
    clear_formatting,
    set_paragraph_format,
    set_style,
    insert_table,
    insert_list,
    insert_page_break,
    insert_image,
    select_text,
    insert_bookmark,
    go_to_bookmark,
    insert_content_control,
]

CLIENT_TOOL_NAMES: set[str] = {t.name for t in CLIENT_TOOLS}
