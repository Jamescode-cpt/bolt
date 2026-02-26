"""BOLT custom tool — web search via DuckDuckGo.

Safe, no API key needed, won't get you banned.
Uses the ddgs library (formerly duckduckgo-search).

Install: pip install ddgs
"""

TOOL_NAME = "web_search"
TOOL_DESC = "Search the web via DuckDuckGo. Usage: <tool name=\"web_search\">your search query</tool>"


def run(args):
    """Search DuckDuckGo and return top results.

    Args is the search query string.
    Returns formatted results or an error message.
    """
    query = args.strip()
    if not query:
        return "No search query provided. Usage: <tool name=\"web_search\">your query here</tool>"

    # Try the ddgs library (current name)
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return (
                "Web search package not installed.\n"
                "Install it with: pip install ddgs\n"
                "Then try your search again."
            )

    try:
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=5):
                title = r.get("title", "No title")
                url = r.get("href", "")
                body = r.get("body", "")
                if len(body) > 200:
                    body = body[:200] + "..."
                results.append(f"  {title}\n  {url}\n  {body}")

        if results:
            header = f"Search results for: {query}\n{'=' * 50}\n"
            return header + "\n\n".join(results)
        else:
            return f"No results found for: {query}"

    except Exception as e:
        return f"Search error: {e}"
