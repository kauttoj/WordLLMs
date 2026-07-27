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
    """Get the currently selected text. Text deleted under track-changes is excluded.
    Returns an explicit "(nothing is selected...)" message when the cursor is collapsed rather than an empty string.
    """
    _client_only()


@tool
def get_document_content() -> str:
    """Get the full content of the Word document body as plain text, one line per paragraph and per table cell.

    Formatting is NOT included: bullets, numbering, list nesting, styles, fonts, colours,
    page breaks and images are all invisible here. Two paragraphs read identically whether
    or not they are list items. Do not use this tool to verify formatting -- it cannot show it.
    """
    _client_only()


@tool
def get_document_properties() -> str:
    """Get document statistics: paragraph count, word count, and character count.
    Counts include empty paragraphs. Page count is not available.
    """
    _client_only()


@tool
def get_range_info() -> str:
    """Get information about the current selection: whether anything is selected (hasSelection),
    the selected text, the paragraph style, and the character formatting.
    When nothing is selected the formatting describes the cursor position.
    """
    _client_only()


@tool
def get_table_info() -> str:
    """Get information about tables in the document: how many there are, and each one's row and column counts.
    Cell contents are not returned -- use get_document_content for those.
    """
    _client_only()


@tool
def find_text(searchText: str, matchCase: bool = False) -> str:
    """Find text in the document and report every match with surrounding context. Does not modify the document.

    Returns matchCount, and for each match its character offset plus ~30 characters of context
    on either side. Also returns "resolvable": when false, the text exists but Word cannot
    address it directly, so search_and_replace may not be able to change it.

    Args:
        searchText: The text to search for. Must be plain text on a single line -- tabs and
            non-breaking spaces are rejected because Word's search cannot match them.
        matchCase: Whether to match case (default: false).
    """
    _client_only()


@tool
def find_and_select_text(searchText: str, matchCase: bool = False) -> str:
    """Find text in the document and select the first occurrence. Use this for SHORT selections (few sentences). After selection, the user will see the text highlighted in Word.
    The selection covers exactly the matched text, so a following insert_paragraph or insert_list is still placed after the whole paragraph containing it, not inside it.

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
    Both markers must occur exactly once in the document, and endText must come after startText.

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
def insert_text(text: str, location: str = "End", keepStyle: bool = False) -> str:
    """Insert plain text at the current cursor position. Do not use markdown.
    Use \\n for paragraph breaks. The cursor moves to the end of the inserted text, so
    consecutive calls stack top to bottom.

    This writes into the paragraph the cursor is in, it does not start a new one. If the
    cursor sits at the end of an existing paragraph or list item, the first line continues
    that paragraph and keeps its formatting -- inserting after a bullet "Epsilon" produces
    "EpsilonTEXT". Use insert_paragraph when the text must be its own block, and insert_list
    for list items. Any further \\n-separated lines do become new plain paragraphs.

    Args:
        text: The text to insert. Use \\n for paragraph breaks.
        location: Where to insert relative to the cursor: "Start", "End", "Before", "After", or "Replace".
        keepStyle: Keep the source paragraph style for inserted paragraphs. Default false, which resets subsequent paragraphs to Normal to prevent heading style bleed.
    """
    _client_only()


@tool
def replace_selected_text(newText: str, keepStyle: bool = False) -> str:
    """Replace the entire selection with new content. Requires a selection -- fails if nothing is selected.
    For small targeted edits, use search_and_replace instead. Do not use markdown. Use \\n for paragraph breaks.
    The replacement is recorded as a tracked change.

    Args:
        newText: The replacement text. Use \\n for paragraph breaks.
        keepStyle: Keep the source paragraph style for inserted paragraphs. Default false, which resets subsequent paragraphs to Normal to prevent heading style bleed.
    """
    _client_only()


@tool
def append_text(text: str, keepStyle: bool = False) -> str:
    """Append plain text to the very end of the document, ignoring the cursor position.
    Do not use markdown. Use \\n for paragraph breaks. The cursor is left at the end of the
    appended text. The text always starts its own paragraph rather than continuing the
    document's last one, and is detached from any list it lands next to.

    Args:
        text: The text to append. Use \\n for paragraph breaks.
        keepStyle: Keep the source paragraph style for inserted paragraphs. Default false, which resets subsequent paragraphs to Normal to prevent heading style bleed.
    """
    _client_only()


@tool
def insert_paragraph(text: str, location: str = "After", style: Optional[str] = None) -> str:
    """Insert one or more whole paragraphs. Use the style parameter for headings, quotes, etc.
    Do not use markdown. The cursor advances to the last inserted paragraph, so consecutive
    calls produce correct top-to-bottom order.

    "After"/"Before" mean after/before the whole paragraph the cursor is in, never in the
    middle of it -- a partial selection is never split. New paragraphs are plain: if they land
    next to a list they are detached from it rather than joining it.

    Args:
        text: The paragraph text. Use \\n to insert several paragraphs at once.
        location: "After" (default, after the cursor's paragraph), "Before", "Start" (start of doc), or "End" (end of doc).
        style: Optional built-in style: Normal, Heading1, Heading2, Heading3, Heading4, Quote, IntenseQuote, Title, Subtitle.
    """
    _client_only()


@tool
def delete_text() -> str:
    """Delete the currently selected text, including its paragraph breaks. Requires a selection -- select text first with find_and_select_text or select_between_text.
    Note that select_between_text includes both markers, so they are deleted too.
    """
    _client_only()


@tool
def search_and_replace(searchText: str, replaceText: str, matchCase: bool = False, keepStyle: bool = False) -> str:
    """Search the whole document and replace every occurrence. This is the preferred tool for targeted edits -- use it for proofreading fixes, correcting typos, grammar, or any task that changes specific words or phrases.
    Replacements are recorded as tracked changes. The reply states how many occurrences were
    replaced, and how many were found but could not be addressed.

    Args:
        searchText: The exact text to find (must match document content precisely, on a single line).
        replaceText: The corrected or replacement text.
        matchCase: Whether to match case (default: false).
        keepStyle: Keep the source paragraph style for inserted paragraphs. Default false, which resets subsequent paragraphs to Normal to prevent heading style bleed.
    """
    _client_only()


@tool
def search_and_replace_in_selection(searchText: str, replaceText: str, matchCase: bool = False, keepStyle: bool = False) -> str:
    """Search for text within the current selection and replace it. Same as search_and_replace but scoped to the active selection only. Requires a selection.

    Args:
        searchText: The exact text to find within the selection.
        replaceText: The corrected or replacement text.
        matchCase: Whether to match case (default: false).
        keepStyle: Keep the source paragraph style for inserted paragraphs. Default false, which resets subsequent paragraphs to Normal to prevent heading style bleed.
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
    """Apply character formatting to the currently selected text. Only the arguments you pass are changed; the rest are left alone. Requires a selection -- with nothing selected this silently affects nothing visible.

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
    """Reset the selected text to the Normal style with no bold, italic, underline, strikethrough, subscript, superscript or highlight.
    Font name, size and colour follow the Normal style. Requires a selection.
    """
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
    """Apply paragraph formatting (alignment, spacing, indentation) to every paragraph the selection touches.
    Only the arguments you pass are changed. Applies to whole paragraphs even if only part of one is selected.

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
    """Insert a table after the paragraph the cursor is in, styled as a light grid.
    The cursor is moved past the table afterwards, so the next insertion lands below it
    rather than inside the last cell.

    Args:
        rows: Number of rows, including the header row if data supplies one.
        columns: Number of columns.
        data: Optional 2D array of cell values, outer list = rows. Omit for an empty table.
    """
    _client_only()


@tool
def insert_list(items: list[str], listType: str) -> str:
    """Insert a bulleted or numbered list after the paragraph the cursor is in.
    The list is always a new top-level list: numbering restarts at 1 and it is never nested
    inside a list above it. The cursor is moved past the last item afterwards.
    One call per list -- call it again for a second list rather than trying to extend one.

    Args:
        items: Array of list item texts, one per item. Do not include bullets or numbers in the text.
        listType: Type of list: "bullet" or "number".
    """
    _client_only()


@tool
def insert_page_break(location: str = "After") -> str:
    """Insert a page break so that following content starts on a new page.

    With "After" (the default) the break is placed after the paragraph the cursor is in and
    the cursor moves onto the new page, so the next insertion lands there. This costs one
    empty paragraph at the top of the new page, exactly as pressing Ctrl+Enter does.
    With "Before"/"Start" the break is placed before the cursor's paragraph and the cursor
    does not move.

    Args:
        location: Where to insert: "After" (default) or "Before". "Start" behaves as "Before" and "End" as "After".
    """
    _client_only()


@tool
def insert_image(imageUrl: str, width: Optional[float] = None, height: Optional[float] = None, location: str = "After") -> str:
    """Insert an image. Accepts a direct image URL (http/https) or a base64-encoded image string.

    A URL is fetched by the add-in first and, if that is blocked, retried by the backend, so
    hosts that reject cross-origin requests and hosts that reject server-side requests both
    work. Formats Word cannot display (WEBP, AVIF) are converted to PNG automatically. The URL
    must point straight at an image file, not at a web page containing one.

    Args:
        imageUrl: Direct image URL (http/https) or base64-encoded image string.
        width: Optional width in points. Height scales with it when height is omitted.
        height: Optional height in points.
        location: "Before"/"After" (default) put the image in its own paragraph next to the cursor's paragraph. "Start"/"End"/"Replace" place it inline within the selection.
    """
    _client_only()


# --- Selection / Navigation Tools ---

@tool
def select_text(scope: str) -> str:
    """Select the entire document body. The only supported scope is "All".

    Args:
        scope: What to select: "All" for entire document.
    """
    _client_only()


@tool
def insert_bookmark(name: str) -> str:
    """Mark the currently selected text with a named bookmark so it can be found again with go_to_bookmark.
    Requires a selection -- a bookmark wraps existing text and cannot be placed at a bare cursor.
    The cursor is moved past the bookmark afterwards, so later insertions do not get pulled inside it.

    Args:
        name: The name of the bookmark. Must be unique; any spaces are replaced with underscores.
    """
    _client_only()


@tool
def go_to_bookmark(name: str) -> str:
    """Select the text previously marked by insert_bookmark, so it can be read, formatted or replaced.
    If the bookmark does not exist the reply lists the bookmarks that do.

    Args:
        name: The name of the bookmark to navigate to.
    """
    _client_only()


@tool
def insert_content_control(title: str, tag: Optional[str] = None, appearance: str = "BoundingBox") -> str:
    """Wrap the current selection in a content control -- a named container marking a region of the document.
    Requires a selection. The cursor is moved past the control afterwards, so later insertions do not get pulled inside it.
    The selection must not already be inside another content control or a bookmark: Word cannot nest them and
    the call fails rather than leaving an empty control behind. Move the selection elsewhere first.

    Args:
        title: The title of the content control.
        tag: Optional tag for programmatic identification.
        appearance: Visual appearance of the control: "BoundingBox", "Tags", or "Hidden".
    """
    _client_only()


@tool
def insert_comment(comment: str) -> str:
    """Attach a review comment to the currently selected text. Requires a non-empty selection.
    The comment appears in Word's review pane anchored to that text; the document text itself is unchanged.

    Args:
        comment: The comment text to add to the selected text.
    """
    _client_only()


# --- Registry ---

READ_TOOLS = [
    get_selected_text, get_document_content, get_document_properties,
    get_range_info, get_table_info, find_text,
]
SELECT_TOOLS = [
    find_and_select_text, select_between_text, select_text, go_to_bookmark,
]
WRITE_TOOLS = [
    insert_text, replace_selected_text, append_text, insert_paragraph,
    delete_text, search_and_replace, search_and_replace_in_selection,
    format_text, clear_formatting, set_paragraph_format, set_style,
    insert_table, insert_list, insert_page_break, insert_image,
    insert_bookmark, insert_content_control, insert_comment,
]

CLIENT_TOOLS = READ_TOOLS + SELECT_TOOLS + WRITE_TOOLS
CLIENT_TOOL_CATEGORY = {
    t.name: cat
    for cat, ts in (("read", READ_TOOLS), ("select", SELECT_TOOLS), ("write", WRITE_TOOLS))
    for t in ts
}

# Hard-coding 28 is deliberate: a tool added later must be a conscious edit
# here, not a silent slip. Update the number in the same commit that adds a tool.
assert len(CLIENT_TOOL_CATEGORY) == len(CLIENT_TOOLS) == 28
