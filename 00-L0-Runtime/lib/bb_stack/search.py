from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from .io import atomic_write

SEARCH_PROVIDERS: dict[str, str] = {
    "exa": "EXA_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "brave": "BRAVE_SEARCH_API_KEY",
}
DEFAULT_LIMIT = 20
DEFAULT_TIMEOUT = 30


class SearchProviderError(RuntimeError):
    """A provider request failed without exposing credentials."""


def _host(target: str) -> str:
    value = target if target.startswith(("http://", "https://")) else f"https://{target}"
    return (urlparse(value).hostname or target).lower().strip()


def _query(target: str) -> str:
    return f'"{_host(target)}"'


def _json_request(
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None,
    timeout: int,
) -> dict[str, Any]:
    body = None
    request_headers = {"Accept": "application/json", **headers}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as error:
        raise SearchProviderError(f"provider returned HTTP {error.code}") from error
    except (TimeoutError, URLError) as error:
        raise SearchProviderError(f"provider request failed: {error.reason if isinstance(error, URLError) else error}") from error
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SearchProviderError("provider returned invalid JSON") from error
    if not isinstance(document, dict):
        raise SearchProviderError("provider returned a non-object JSON response")
    return document


def _result(
    provider: str,
    query: str,
    item: dict[str, Any],
) -> dict[str, Any] | None:
    url = item.get("url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    title = item.get("title")
    snippet = item.get("snippet") or item.get("description") or item.get("content")
    if isinstance(item.get("highlights"), list) and item["highlights"]:
        snippet = item["highlights"][0]
    return {
        "provider": provider,
        "query": query,
        "title": title if isinstance(title, str) else None,
        "url": url,
        "snippet": snippet if isinstance(snippet, str) else None,
        "score": item.get("score") if isinstance(item.get("score"), (int, float)) else None,
        "published_at": (
            item.get("publishedDate")
            or item.get("published_date")
            or item.get("page_age")
        ),
    }


def search(provider: str, target: str, *, limit: int = DEFAULT_LIMIT, timeout: int = DEFAULT_TIMEOUT) -> list[dict[str, Any]]:
    if provider not in SEARCH_PROVIDERS:
        raise SearchProviderError(f"unsupported search provider: {provider}")
    api_key = os.environ.get(SEARCH_PROVIDERS[provider], "").strip()
    if not api_key:
        raise SearchProviderError(
            f"missing {SEARCH_PROVIDERS[provider]} environment variable"
        )
    query = _query(target)
    bounded_limit = max(1, min(limit, 100))
    if provider == "exa":
        document = _json_request(
            "https://api.exa.ai/search",
            method="POST",
            headers={"x-api-key": api_key},
            payload={
                "query": query,
                "type": "auto",
                "numResults": bounded_limit,
                "contents": {"highlights": {"maxCharacters": 1000}},
            },
            timeout=timeout,
        )
        items = document.get("results", [])
    elif provider == "tavily":
        document = _json_request(
            "https://api.tavily.com/search",
            method="POST",
            headers={},
            payload={
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": bounded_limit,
                "include_answer": False,
            },
            timeout=timeout,
        )
        items = document.get("results", [])
    else:
        document = _json_request(
            "https://api.search.brave.com/res/v1/web/search"
            f"?q={quote(query)}&count={bounded_limit}",
            method="GET",
            headers={"X-Subscription-Token": api_key},
            payload=None,
            timeout=timeout,
        )
        items = document.get("web", {}).get("results", [])
    if not isinstance(items, list):
        raise SearchProviderError("provider returned an invalid result list")
    return [
        normalized
        for item in items
        if isinstance(item, dict)
        if (normalized := _result(provider, query, item)) is not None
    ]


def write_results(provider: str, target: str, output: Path, *, limit: int = DEFAULT_LIMIT) -> int:
    results = search(provider, target, limit=limit)
    content = "".join(
        json.dumps(item, ensure_ascii=True, sort_keys=True) + "\n" for item in results
    )
    atomic_write(output, content)
    return len(results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bb-search")
    parser.add_argument("--provider", choices=sorted(SEARCH_PROVIDERS), required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args(argv)
    try:
        write_results(args.provider, args.target, args.output, limit=args.limit)
    except SearchProviderError as error:
        print(f"bb-search: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"bb-search: output failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
