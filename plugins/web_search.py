from quickquip.search import web_search as _impl
from quickquip.search.web_search import (
    SearchResponse,
    SearchResult,
    SearXNGSearchClient,
    SearXNGSearchError,
    WebSearchError,
    format_search_response,
)

request = _impl.request
parse = _impl.parse
error = _impl.error


__all__ = [
    "SearchResponse",
    "SearchResult",
    "SearXNGSearchClient",
    "SearXNGSearchError",
    "WebSearchError",
    "error",
    "format_search_response",
    "parse",
    "request",
]
