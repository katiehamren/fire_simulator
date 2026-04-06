"""web_search tool — U.S. government-domain lookup via OpenAI Responses API (Phase 4)."""

from urllib.parse import urlparse

from openai import APIConnectionError, APIError, AuthenticationError, OpenAI, RateLimitError

from chatbot.env import resolve_openai_api_key

# Allowed domains (no scheme), per spec / workplan — subdomains match automatically.
GOV_ALLOWED_DOMAINS = [
    "irs.gov",
    "ssa.gov",
    "healthcare.gov",
    "congress.gov",
    "treasury.gov",
    "bls.gov",
]

_WEB_SEARCH_TOOL = {
    "type": "web_search",
    "filters": {"allowed_domains": GOV_ALLOWED_DOMAINS},
}


def _host_allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    for d in GOV_ALLOWED_DOMAINS:
        d = d.lower()
        if host == d or host.endswith("." + d):
            return True
    return False


def _get(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _parse_response_results(response) -> list[dict]:
    """Build {title, snippet, url} from message url_citation annotations."""
    results = []
    seen = set()
    output = _get(response, "output") or []
    for item in output:
        if _get(item, "type") != "message":
            continue
        for block in _get(item, "content") or []:
            if _get(block, "type") != "output_text":
                continue
            text = _get(block, "text") or ""
            for ann in _get(block, "annotations") or []:
                if _get(ann, "type") != "url_citation":
                    continue
                url = (_get(ann, "url") or "").strip()
                if not url or url in seen:
                    continue
                if not _host_allowed(url):
                    continue
                seen.add(url)
                title = _get(ann, "title") or ""
                start = _get(ann, "start_index")
                end = _get(ann, "end_index")
                if start is not None and end is not None:
                    snippet = text[int(start) : int(end)].strip()
                else:
                    snippet = ""
                results.append({"title": title, "snippet": snippet, "url": url})
    return results


def web_search(query: str, context: str = None, *, api_key: str) -> dict:
    """Search government domains for tax/policy information using OpenAI hosted web search.

    Returns ``{"results": [{"title", "snippet", "url"}, ...], "query": ...}`` or
    ``{"error": "..."}``.
    """
    if not query or not str(query).strip():
        return {"error": "Search query is required."}
    key = resolve_openai_api_key(api_key)
    if not key:
        return {
            "error": "OpenAI API key is required for web search (OPENAI_API_KEY or tool caller must supply a key).",
        }

    q = query.strip()
    lines = [
        "You are fetching facts from the indexed U.S. government sites only (domain filter is applied). "
        "Answer in a short paragraph and cite official sources.",
        f"Question: {q}",
    ]
    if context and str(context).strip():
        lines.append(f"Context: {context.strip()}")
    user_input = "\n\n".join(lines)

    client = OpenAI(api_key=key)
    if not hasattr(client, "responses"):
        return {
            "error": "OpenAI Python SDK does not expose the Responses API (`client.responses`). Upgrade `openai`.",
        }

    try:
        response = client.responses.create(
            model="gpt-4o-mini",
            input=user_input,
            tools=[_WEB_SEARCH_TOOL],
        )
    except AuthenticationError as e:
        return {"error": f"Authentication failed (check API key): {e}"}
    except RateLimitError as e:
        return {"error": f"OpenAI rate limit: {e}"}
    except APIConnectionError as e:
        return {"error": f"Network error calling OpenAI: {e}"}
    except APIError as e:
        return {"error": f"OpenAI API error: {e}"}
    except Exception as e:
        return {"error": f"Web search failed: {e}"}

    results = _parse_response_results(response)
    return {"results": results, "query": q}


WEB_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search trusted U.S. government websites (IRS, SSA, Treasury, etc.) for current tax rules, "
            "contribution limits, AFR rates, ACA/MAGI references, and similar official information. "
            "Use only when the simulator cannot answer (external facts). Results are domain-filtered; "
            "synthesize an answer from the returned snippets and URLs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to look up, e.g. current IRS mid-term AFR or 2026 HSA family limit.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional: why this search is needed (improves relevance).",
                },
            },
            "required": ["query"],
        },
    },
}
