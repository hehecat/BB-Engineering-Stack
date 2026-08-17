#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        requests: list[object] = []

        def open_request(request: object, timeout: int) -> FakeResponse:
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
        self.assertNotIn("fixture-secret", repr(requests[0]))

    def test_tavily_and_brave_use_their_own_credentials(self) -> None:
        responses = [
            FakeResponse(
                {"results": [{"title": "T", "url": "https://example.invalid/t", "content": "t"}]}
            ),
            FakeResponse(
                {"web": {"results": [{"title": "B", "url": "https://example.invalid/b", "description": "b"}]}}
            ),
        ]

        def open_request(*_: object, **__: object) -> FakeResponse:
            return responses.pop(0)

        with patch.dict(
            os.environ,
            {"TAVILY_API_KEY": "tavily-secret", "BRAVE_SEARCH_API_KEY": "brave-secret"},
            clear=False,
        ):
            with patch("bb_stack.search.urlopen", side_effect=open_request):
                tavily = search("tavily", "example.invalid")
                brave = search("brave", "example.invalid")

        self.assertEqual(tavily[0]["title"], "T")
        self.assertEqual(brave[0]["title"], "B")


if __name__ == "__main__":
    unittest.main(verbosity=2)
