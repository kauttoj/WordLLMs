import httpx
from langchain_core.tools import tool
from langchain_tavily._utilities import TavilySearchAPIWrapper
from typing import Literal

# ~5000 tokens ≈ 20000 chars for search results, ~15000 chars for URL fetch
MAX_SEARCH_RESULT_CHARS = 20000
MAX_FETCH_CHARS = 15000


def _format_search_results(raw: dict) -> str:
    """Format raw Tavily API response into a concise string for the LLM."""
    results = raw.get("results", [])
    if not results:
        return "No search results found."

    parts = []
    for r in results:
        title = r.get("title", "")
        url = r.get("url", "")
        content = r.get("content", "")
        parts.append(f"[{title}]({url})\n{content}")

    output = "\n\n".join(parts)
    if len(output) > MAX_SEARCH_RESULT_CHARS:
        output = output[:MAX_SEARCH_RESULT_CHARS] + "\n... (truncated)"
    return output


def create_web_search_tool(api_key: str):
    """Create a web search tool configured with the given API key.

    Returns a simple @tool-wrapped function whose schema is strict-compatible
    with OpenAI function calling (no optional params, no additionalProperties).
    Uses TavilySearchAPIWrapper (plain Pydantic model) instead of TavilySearch
    (BaseTool subclass) to avoid LangGraph emitting nested on_tool_start events.
    """
    if not api_key:
        raise ValueError("Search API key is required but was empty")

    _api = TavilySearchAPIWrapper(tavily_api_key=api_key)

    @tool
    def web_search(query: str, time_range: Literal['week', 'month', 'year'] | None = None, topic: Literal['general', 'news'] | None = None) -> str:
        """Search the web for current information.

        Args:
            query: The natural language search query.
            time_range: Optional time filter back from the current date to filter results based on publish date or last updated date. Useful when looking for sources that have published or updated data. Use ONLY when the user asks for recent events or specifies a timeframe. Valid: 'week', 'month', 'year'. Leave as None otherwise.
            topic: Optional category of the search. 'news' is useful for retrieving real-time updates, particularly about politics, sports, and major current events covered by mainstream media sources. 'general' is for broader, more general-purpose searches that may include a wide range of sources. Valid: 'general', 'news'.

        Returns:
            Search results with snippets.
        """
        raw = _api.raw_results(
            query=query,
            max_results=3,
            search_depth="basic",
            topic=topic or "general",
            time_range=time_range,
            include_domains=None,
            exclude_domains=None,
            include_answer=False,
            include_raw_content=False,
            include_images=False,
            include_image_descriptions=False,
            include_favicon=False,
            country=None,
            auto_parameters=False,
            start_date=None,
            end_date=None,
            include_usage=False,
        )
        return _format_search_results(raw)

    return web_search


@tool
def fetch_url_tool(url: str) -> str:
    """Fetch content from a URL.

    Args:
        url: The URL to fetch content from.

    Returns:
        The text content of the URL, truncated if necessary.
    """
    max_chars = MAX_FETCH_CHARS
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "text/html" in content_type:
                # Basic HTML to text extraction
                text = response.text
                # Remove script and style tags
                import re
                text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
                # Remove HTML tags
                text = re.sub(r"<[^>]+>", " ", text)
                # Clean up whitespace
                text = re.sub(r"\s+", " ", text).strip()
            else:
                text = response.text

            if len(text) > max_chars:
                text = text[:max_chars] + "... (truncated)"

            return text

    except Exception as e:
        return f"Failed to fetch URL: {e}"
