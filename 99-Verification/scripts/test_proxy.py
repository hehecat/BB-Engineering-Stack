#!/usr/bin/env python3
"""Contract tests for `bb_stack.proxy`, the one place proxy routing is decided.

Three call sites read this module -- the generated `env.sh`, the workspace
settings handed to a launched agent, and recon's per-provider command lines --
so the tests pin the shared answer as much as the individual functions. The
interesting failures are silent: a proxy variable that is set but ignored, or a
tool handed a `-proxy` flag it does not understand, both look like success.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack import proxy
from bb_stack.errors import ValidationError
from bb_stack.paths import StackPaths

MACHINE = {
    "BB_PROXY_MODE": "mihomo",
    "BB_HTTP_PROXY": "http://127.0.0.1:7890",
    "BB_SOCKS_PROXY": "socks5://127.0.0.1:7891",
}


class ProxyEnvironmentTests(unittest.TestCase):
    def active(self, mode: str) -> dict[str, str]:
        return proxy.environment({**MACHINE, "BB_PROXY_MODE": mode})

    def test_environment_sets_only_the_uppercase_spelling(self) -> None:
        self.assertEqual(set(self.active("http")), {"HTTP_PROXY", "HTTPS_PROXY"})
        self.assertEqual(set(self.active("socks")), {"ALL_PROXY"})
        self.assertEqual(set(self.active("mihomo")), set(proxy.UPPERCASE_VARIABLES))
        self.assertEqual(self.active("direct"), {})

    def test_apply_clears_both_spellings_then_sets_the_uppercase_ones(self) -> None:
        target = {
            "HTTP_PROXY": "http://stale.invalid",
            "http_proxy": "http://stale.invalid",
            "https_proxy": "http://stale.invalid",
            "all_proxy": "socks5://stale.invalid",
            "UNRELATED": "kept",
        }
        proxy.apply(target, MACHINE)
        self.assertEqual(target["HTTP_PROXY"], MACHINE["BB_HTTP_PROXY"])
        self.assertEqual(target["ALL_PROXY"], MACHINE["BB_SOCKS_PROXY"])
        for name in ("http_proxy", "https_proxy", "all_proxy"):
            self.assertNotIn(name, target)
        self.assertEqual(target["UNRELATED"], "kept")

    def test_apply_in_direct_mode_removes_every_spelling(self) -> None:
        target = {
            "HTTP_PROXY": "http://stale.invalid",
            "http_proxy": "http://stale.invalid",
            "UNRELATED": "kept",
        }
        proxy.apply(target, {**MACHINE, "BB_PROXY_MODE": "direct"})
        self.assertEqual(
            [name for name in target if "proxy" in name.lower()], []
        )
        self.assertEqual(target["UNRELATED"], "kept")

    def test_an_unknown_mode_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            proxy.environment({**MACHINE, "BB_PROXY_MODE": "tor"})

    def test_active_url_follows_the_mode(self) -> None:
        self.assertEqual(proxy.active_url(MACHINE, "http"), MACHINE["BB_HTTP_PROXY"])
        self.assertEqual(proxy.active_url(MACHINE, "socks"), MACHINE["BB_SOCKS_PROXY"])
        socks_only = {**MACHINE, "BB_PROXY_MODE": "socks"}
        self.assertEqual(proxy.active_url(socks_only, "http"), "")


class ProviderArgumentTests(unittest.TestCase):
    def args(self, provider: str, mode: str = "mihomo") -> list[str]:
        return proxy.provider_args(provider, {**MACHINE, "BB_PROXY_MODE": mode})

    def test_each_tool_gets_the_flag_and_kind_it_actually_accepts(self) -> None:
        # Verified against each tool's own -h: subfinder takes only http, naabu
        # and dnsx only socks5, ffuf short-forms it as -x.
        self.assertEqual(self.args("httpx"), ["-http-proxy", MACHINE["BB_HTTP_PROXY"]])
        self.assertEqual(self.args("naabu"), ["-proxy", MACHINE["BB_SOCKS_PROXY"]])
        self.assertEqual(self.args("dnsx"), ["-proxy", MACHINE["BB_SOCKS_PROXY"]])
        self.assertEqual(self.args("ffuf"), ["-x", MACHINE["BB_HTTP_PROXY"]])
        self.assertEqual(self.args("subfinder"), ["-proxy", MACHINE["BB_HTTP_PROXY"]])

    def test_direct_mode_yields_no_arguments_at_all(self) -> None:
        for name in proxy.PROVIDER_FLAGS:
            with self.subTest(provider=name):
                self.assertEqual(self.args(name, "direct"), [])

    def test_a_socks_only_profile_still_routes_http_tools(self) -> None:
        args = self.args("httpx", "socks")
        self.assertEqual(args, ["-http-proxy", MACHINE["BB_SOCKS_PROXY"]])

    def test_tools_with_no_flag_are_named_rather_than_silently_direct(self) -> None:
        for name in ("nmap", "amass", "waybackurls", "arjun"):
            with self.subTest(provider=name):
                self.assertEqual(self.args(name), [])
                self.assertIn(name, proxy.PROXY_BLIND_TOOLS)

    def test_a_provider_is_never_both_routed_and_listed_blind(self) -> None:
        self.assertEqual(set(proxy.PROVIDER_FLAGS) & set(proxy.PROXY_BLIND_TOOLS), set())


class CheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-proxy-")
        base = Path(self.temporary.name)
        self.paths = StackPaths(
            ROOT,
            base / "home",
            base / "work",
            base / "config",
            base / "home" / ".claude",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def with_machine(self, machine: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        seen: list[dict[str, str]] = []

        def fetch(environment: dict[str, str], _timeout: int) -> dict[str, Any]:
            seen.append(environment)
            routed = any(environment.values())
            return {"ip": "10.0.0.2" if routed else "203.0.113.9", "error": None}

        with patch(
            "bb_stack.configuration.ConfigurationManager.effective", return_value=machine
        ):
            result = proxy.check(self.paths, fetch=fetch, **kwargs)
        result["_probes"] = seen
        return result

    def test_direct_mode_probes_once_and_says_nothing_is_routed(self) -> None:
        result = self.with_machine({**MACHINE, "BB_PROXY_MODE": "direct"})
        self.assertIsNone(result["proxied"])
        self.assertEqual(len(result["_probes"]), 1)
        self.assertFalse(result["differs"])

    def test_differing_addresses_mean_the_proxy_is_in_the_path(self) -> None:
        result = self.with_machine(MACHINE)
        self.assertTrue(result["differs"])
        self.assertEqual(result["direct"]["ip"], "203.0.113.9")
        self.assertEqual(result["proxied"]["ip"], "10.0.0.2")
        self.assertEqual(len(result["_probes"]), 2)

    def test_identical_addresses_mean_it_is_not(self) -> None:
        def fetch(_environment: dict[str, str], _timeout: int) -> dict[str, Any]:
            return {"ip": "203.0.113.9", "error": None}

        with patch(
            "bb_stack.configuration.ConfigurationManager.effective", return_value=MACHINE
        ):
            result = proxy.check(self.paths, fetch=fetch)
        self.assertFalse(result["differs"])

    def test_a_failed_probe_does_not_read_as_success(self) -> None:
        def fetch(_environment: dict[str, str], _timeout: int) -> dict[str, Any]:
            return {"ip": None, "error": "URLError: refused"}

        with patch(
            "bb_stack.configuration.ConfigurationManager.effective", return_value=MACHINE
        ):
            result = proxy.check(self.paths, fetch=fetch)
        self.assertFalse(result["differs"])
        self.assertIn("refused", result["proxied"]["error"])

    def test_the_report_names_both_the_routed_and_the_blind_tools(self) -> None:
        result = self.with_machine(MACHINE)
        self.assertIn("httpx", result["routed_tools"])
        self.assertIn("nmap", result["blind_tools"])


class ShellGenerationTests(unittest.TestCase):
    def test_the_generated_case_block_covers_every_mode(self) -> None:
        lines = "\n".join(
            __import__(
                "bb_stack.runtime", fromlist=["RuntimeManager"]
            ).RuntimeManager._proxy_shell_lines()
        )
        self.assertIn('case "${BB_PROXY_MODE:-direct}" in', lines)
        for mode in proxy.PROXY_MODES:
            with self.subTest(mode=mode):
                self.assertIn(f"  {mode})", lines)
        # A mode that exists in the module but not in the shell (or the reverse)
        # is how a shell ends up claiming routing the tools do not have.
        for name in proxy.PROXY_VARIABLES:
            with self.subTest(variable=name):
                self.assertIn(name, lines)


if __name__ == "__main__":
    unittest.main(verbosity=2)
