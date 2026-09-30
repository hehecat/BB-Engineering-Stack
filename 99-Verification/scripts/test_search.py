#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.search import SearchProviderError, search, write_results


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class SearchProviderTests(unittest.TestCase):
    def test_missing_key_is_explicit_and_does_not_call_network(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=False),
            patch("bb_stack.search.urlopen") as opener,
        ):
            os.environ.pop("EXA_API_KEY", None)
            with self.assertRaisesRegex(SearchProviderError, "EXA_API_KEY"):
                search("exa", "example.invalid")
        opener.assert_not_called()

    def test_exa_normalizes_results_and_writes_jsonl(self) -> None:
        requests: list[Request] = []

        def open_request(request: Request, timeout: int) -> FakeResponse:
            requests.append(request)
            return FakeResponse(
                {
                    "results": [
                        {
                            "title": "Example",
                            "url": "https://example.invalid/docs",
                            "highlights": ["public docs"],
                            "score": 0.9,
                            "publishedDate": "2026-08-07",
                        }
                    ]
                }
            )

        with patch.dict(os.environ, {"EXA_API_KEY": "fixture-secret"}, clear=False):
            with patch("bb_stack.search.urlopen", side_effect=open_request):
                with tempfile.TemporaryDirectory() as temporary:
                    output = Path(temporary) / "exa.jsonl"
                    self.assertEqual(
                        write_results("exa", "https://example.invalid", output), 1
                    )
                    document = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(document["provider"], "exa")
        self.assertEqual(document["url"], "https://example.invalid/docs")
        self.assertEqual(document["snippet"], "public docs")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].get_header("X-api-key"), "fixture-secret")
        self.assertEqual(requests[0].full_url, "https://api.exa.ai/search")

    def _credential_opener(self, requests: list[Request]) -> Callable[..., FakeResponse]:
        """Fake transport that only accepts the credential on the right channel."""

        def open_request(request: Request, timeout: int) -> FakeResponse:
            requests.append(request)
            if "api.tavily.com" in request.full_url:
                payload = json.loads((request.data or b"{}").decode("utf-8"))
                if payload.get("api_key") != "tavily-secret":
                    raise HTTPError(request.full_url, 401, "Unauthorized", {}, None)
                return FakeResponse(
                    {
                        "results": [
                            {
                                "title": "T",
                                "url": "https://example.invalid/t",
                                "content": "t",
                            }
                        ]
                    }
                )
            if "api.search.brave.com" in request.full_url:
                if request.get_header("X-subscription-token") != "brave-secret":
                    raise HTTPError(request.full_url, 401, "Unauthorized", {}, None)
                return FakeResponse(
                    {
                        "web": {
                            "results": [
                                {
                                    "title": "B",
                                    "url": "https://example.invalid/b",
                                    "description": "b",
                                }
                            ]
                        }
                    }
                )
            raise AssertionError(f"unexpected provider endpoint: {request.full_url}")

        return open_request

    def test_tavily_and_brave_carry_credentials_on_their_own_channel(self) -> None:
        requests: list[Request] = []
        with patch.dict(
            os.environ,
            {
                "TAVILY_API_KEY": "tavily-secret",
                "BRAVE_SEARCH_API_KEY": "brave-secret",
            },
            clear=False,
        ):
            with patch(
                "bb_stack.search.urlopen", side_effect=self._credential_opener(requests)
            ):
                tavily = search("tavily", "example.invalid")
                brave = search("brave", "example.invalid")

        tavily_request, brave_request = requests
        self.assertEqual(tavily_request.get_header("X-subscription-token"), None)
        self.assertIsNone(brave_request.data)
        self.assertEqual(brave_request.get_header("X-api-key"), None)
        self.assertEqual(
            json.loads(tavily_request.data.decode("utf-8"))["api_key"], "tavily-secret"
        )
        self.assertEqual(
            brave_request.get_header("X-subscription-token"), "brave-secret"
        )
        self.assertNotIn("brave-secret", tavily_request.data.decode("utf-8"))
        self.assertEqual(
            json.loads(tavily_request.data.decode("utf-8"))["query"],
            '"example.invalid"',
        )
        self.assertEqual(tavily[0]["title"], "T")
        self.assertEqual(brave[0]["title"], "B")

    def test_swapped_credentials_are_rejected(self) -> None:
        requests: list[Request] = []
        with patch.dict(
            os.environ,
            {
                "TAVILY_API_KEY": "brave-secret",
                "BRAVE_SEARCH_API_KEY": "tavily-secret",
            },
            clear=False,
        ):
            with patch(
                "bb_stack.search.urlopen", side_effect=self._credential_opener(requests)
            ):
                with self.assertRaisesRegex(SearchProviderError, "HTTP 401"):
                    search("tavily", "example.invalid")
                with self.assertRaisesRegex(SearchProviderError, "HTTP 401"):
                    search("brave", "example.invalid")
        self.assertEqual(len(requests), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
