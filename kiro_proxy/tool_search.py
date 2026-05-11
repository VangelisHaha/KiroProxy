"""Tool Search implementation for proxy-side tool discovery.

Implements Anthropic's Tool Search Tool specification, supporting:
- Regex-based search (tool_search_tool_regex_20251119)
- BM25-based search (tool_search_tool_bm25_20251119)
- "select:Name1,Name2" syntax for exact tool selection
- defer_loading for on-demand tool discovery

When a client sends many tools with defer_loading, only a subset
is sent to the model per request. The model uses the tool_search
tool to discover additional tools as needed.

Inspired by kirocc's toolsearch/search.go.
"""

import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

from .logger import get_logger

logger = get_logger("tool_search")

DEFAULT_MAX_RESULTS = 5


class ToolSearchError(Exception):
    """Error during tool search."""
    def __init__(self, message: str, code: str = "unavailable"):
        super().__init__(message)
        self.code = code


def _tokenize(text: str) -> List[str]:
    """Simple tokenization for BM25: lowercase, split on non-alphanumeric."""
    return re.findall(r'[a-z0-9_]+', text.lower())


def _build_tool_text(tool: Dict[str, Any]) -> str:
    """Build searchable text from a tool definition."""
    parts = [
        tool.get("name", ""),
        tool.get("description", ""),
    ]
    # Include parameter names and descriptions from input_schema
    schema = tool.get("input_schema", {})
    props = schema.get("properties", {})
    for prop_name, prop_def in props.items():
        parts.append(prop_name)
        if isinstance(prop_def, dict):
            parts.append(prop_def.get("description", ""))

    return " ".join(parts)


def search_regex(
    query: str,
    tools: Dict[str, Dict[str, Any]],
    max_results: int = DEFAULT_MAX_RESULTS,
) -> List[str]:
    """Search tools using regex pattern matching.

    Args:
        query: Regex pattern to match against tool names and descriptions.
        tools: Map of tool name -> tool definition.
        max_results: Maximum number of results to return.

    Returns:
        List of matching tool names.

    Raises:
        ToolSearchError: If the pattern is invalid or too long.
    """
    if len(query) > 1000:
        raise ToolSearchError("Pattern too long (max 1000 chars)", "pattern_too_long")

    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error as e:
        raise ToolSearchError(f"Invalid regex pattern: {e}", "invalid_pattern")

    results: List[Tuple[str, float]] = []
    for name, tool in tools.items():
        text = _build_tool_text(tool)
        matches = pattern.findall(text)
        if matches:
            # Score based on number of matches, prioritize name matches
            name_matches = pattern.findall(name)
            score = len(matches) + len(name_matches) * 10
            results.append((name, score))

    # Sort by score descending
    results.sort(key=lambda x: x[1], reverse=True)
    return [name for name, _ in results[:max_results]]


def search_bm25(
    query: str,
    tools: Dict[str, Dict[str, Any]],
    max_results: int = DEFAULT_MAX_RESULTS,
) -> List[str]:
    """Search tools using BM25 ranking.

    Args:
        query: Search query text.
        tools: Map of tool name -> tool definition.
        max_results: Maximum number of results to return.

    Returns:
        List of matching tool names, ranked by relevance.
    """
    k1 = 1.2
    b = 0.75

    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    # Build document collection
    docs: Dict[str, List[str]] = {}
    for name, tool in tools.items():
        text = _build_tool_text(tool)
        docs[name] = _tokenize(text)

    n = len(docs)
    if n == 0:
        return []

    # Average document length
    avg_dl = sum(len(tokens) for tokens in docs.values()) / n

    # Document frequency for each query term
    df: Dict[str, int] = Counter()
    for tokens in docs.values():
        unique_tokens = set(tokens)
        for qt in query_tokens:
            if qt in unique_tokens:
                df[qt] += 1

    # Calculate BM25 scores
    scores: List[Tuple[str, float]] = []
    for name, tokens in docs.items():
        score = 0.0
        tf_counter = Counter(tokens)
        dl = len(tokens)

        for qt in query_tokens:
            tf = tf_counter.get(qt, 0)
            if tf == 0:
                continue

            idf = math.log((n - df[qt] + 0.5) / (df[qt] + 0.5) + 1)
            tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl))
            score += idf * tf_norm

        if score > 0:
            scores.append((name, score))

    scores.sort(key=lambda x: x[1], reverse=True)
    return [name for name, _ in scores[:max_results]]


def search(
    query: str,
    tools: Dict[str, Dict[str, Any]],
    search_type: str = "bm25",
    max_results: int = DEFAULT_MAX_RESULTS,
) -> List[str]:
    """Search tools by query.

    Supports "select:Tool1,Tool2" syntax for exact selection.

    Args:
        query: Search query or "select:..." exact selection.
        tools: Map of tool name -> tool definition.
        search_type: "regex" or "bm25".
        max_results: Maximum number of results.

    Returns:
        List of matching tool names.
    """
    if max_results <= 0:
        max_results = DEFAULT_MAX_RESULTS

    # Handle exact selection syntax
    if query.startswith("select:"):
        selected = query[7:].split(",")
        return [name.strip() for name in selected if name.strip() in tools]

    if search_type == "regex":
        return search_regex(query, tools, max_results)
    else:
        return search_bm25(query, tools, max_results)


def extract_tool_references(messages: List[Dict[str, Any]]) -> List[str]:
    """Extract tool names referenced in conversation history.

    Scans for tool_reference blocks in tool_result and
    tool_search_tool_result content.

    Args:
        messages: Anthropic-format message list.

    Returns:
        List of unique tool names referenced.
    """
    seen: Set[str] = set()
    names: List[str] = []

    def add(name: str) -> None:
        if name and name not in seen:
            seen.add(name)
            names.append(name)

    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            continue

        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict):
                continue

            block_type = block.get("type", "")

            if block_type == "tool_reference":
                add(block.get("tool_name", "") or block.get("name", ""))

            elif block_type in ("tool_result", "tool_search_tool_result"):
                inner_content = block.get("content", [])
                if isinstance(inner_content, list):
                    for inner in inner_content:
                        if isinstance(inner, dict):
                            if inner.get("type") == "tool_reference":
                                add(inner.get("tool_name", "") or inner.get("name", ""))
                            # Check nested tool_references
                            for ref in inner.get("tool_references", []):
                                if isinstance(ref, dict):
                                    add(ref.get("tool_name", "") or ref.get("name", ""))

    return names
