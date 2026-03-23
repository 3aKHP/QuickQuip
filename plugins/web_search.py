from quickquip.search import web_search as _impl
from quickquip.search.web_search import (
    SearchResponse,
    SearchResult,
    SearXNGSearchClient,
    SearXNGSearchError,
    TavilySearchClient,
    TavilySearchError,
    WebSearchError,
    build_search_client,
    format_search_response,
    get_search_backend_name,
)

request = _impl.request
parse = _impl.parse
error = _impl.error


__all__ = [
    "SearchResponse",
    "SearchResult",
    "SearXNGSearchClient",
    "SearXNGSearchError",
    "TavilySearchClient",
    "TavilySearchError",
    "WebSearchError",
    "build_search_client",
    "error",
    "format_search_response",
    "get_search_backend_name",
    "parse",
    "request",
]
