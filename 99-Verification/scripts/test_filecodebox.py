#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.configuration import ConfigurationManager
from bb_stack.errors import CommandError
from bb_stack.filecodebox import run_filecodebox_command, upload_file
from bb_stack.io import load_yaml
from bb_stack.paths import StackPaths


class Completed:
    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: str | None = None,
        stderr: str = "",
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout or json.dumps(
            {"code": 200, "detail": {"code": "654321", "name": "artifact.zip"}}
        )
        self.stderr = stderr


class FileCodeBoxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-filecodebox-")
        base = Path(self.temporary.name)
        self.paths = StackPaths(
            ROOT,
            base / "home",
            base / "work",
            base / "config",
            base / "home" / ".claude",
        )
        self.source = base / "artifact.zip"
        self.source.write_bytes(b"fixture")
        ConfigurationManager(self.paths).configure(
            {"BB_FILECODEBOX_URL": "https://filebox.example"}
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_upload_uses_share_file_api_and_returns_code(self) -> None:
        with patch(
            "bb_stack.filecodebox.subprocess.run", return_value=Completed()
        ) as run:
            result = upload_file(
                self.paths,
                self.source,
                expire_value=7,
                expire_style="day",
                token="private-token",
            )
        command = run.call_args.args[0]
        self.assertIn("https://filebox.example/share/file/", command)
        self.assertIn('file=@"' + str(self.source) + '"', command)
        self.assertIn("expire_value=7", command)
        self.assertIn("expire_style=day", command)
        self.assertNotIn("private-token", json.dumps(command))
        self.assertEqual(command[-2:], ["--config", "-"])
        self.assertIn(
            "Authorization: Bearer private-token", run.call_args.kwargs["input"]
        )
        self.assertEqual(result["share_code"], "654321")
        self.assertEqual(
            result["share_url"], "https://filebox.example/share/select/?code=654321"
        )

    def test_upload_rejects_missing_source(self) -> None:
        with self.assertRaisesRegex(Exception, "not a file"):
            upload_file(self.paths, self.source.with_name("missing.zip"))

    def test_upload_applies_direct_and_mihomo_proxy_modes(self) -> None:
        inherited = {
            "HTTP_PROXY": "http://stale.example:8080",
            "HTTPS_PROXY": "http://stale.example:8080",
            "ALL_PROXY": "socks5://stale.example:1080",
            "http_proxy": "http://lower.example:8080",
            "https_proxy": "http://lower.example:8080",
            "all_proxy": "socks5://lower.example:1080",
        }
        with (
            patch.dict(os.environ, inherited, clear=False),
            patch(
                "bb_stack.filecodebox.subprocess.run", return_value=Completed()
            ) as run,
        ):
            upload_file(self.paths, self.source)
        direct_env = run.call_args.kwargs["env"]
        for name in inherited:
            self.assertNotIn(name, direct_env)

        ConfigurationManager(self.paths).configure(
            {
                "BB_PROXY_MODE": "mihomo",
                "BB_HTTP_PROXY": "http://127.0.0.1:17890",
                "BB_SOCKS_PROXY": "socks5://127.0.0.1:17891",
            }
        )
        with patch(
            "bb_stack.filecodebox.subprocess.run", return_value=Completed()
        ) as run:
            upload_file(self.paths, self.source)
        proxy_env = run.call_args.kwargs["env"]
        self.assertEqual(proxy_env["HTTP_PROXY"], "http://127.0.0.1:17890")
        self.assertEqual(proxy_env["HTTPS_PROXY"], "http://127.0.0.1:17890")
        self.assertEqual(proxy_env["ALL_PROXY"], "socks5://127.0.0.1:17891")
        for name in ("http_proxy", "https_proxy", "all_proxy"):
            self.assertNotIn(name, proxy_env)

    def test_upload_normalizes_invalid_response_failures(self) -> None:
        cases = (
            (Completed(stdout="[]"), "not an object"),
            (Completed(stdout="not-json"), "invalid JSON"),
            (Completed(stdout='{"code": 403, "detail": "disabled"}'), "disabled"),
            (Completed(stdout='{"code": 200, "detail": {}}'), "share code"),
            (
                Completed(
                    returncode=22,
                    stdout='{"code": 403, "detail": "guest upload disabled"}',
                    stderr="curl: (22) HTTP 403",
                ),
                "guest upload disabled",
            ),
        )
        for completed, message in cases:
            with (
                self.subTest(message=message),
                patch("bb_stack.filecodebox.subprocess.run", return_value=completed),
                self.assertRaisesRegex(CommandError, message),
            ):
                upload_file(self.paths, self.source)

    def test_cli_reads_token_from_stdin_without_printing_it(self) -> None:
        args = SimpleNamespace(
            filecodebox_command="upload",
            source=self.source,
            expire_value=1,
            expire_style="day",
            token_stdin=True,
            json=True,
        )
        output = StringIO()
        with (
            patch("sys.stdin", StringIO("private-token\n")),
            patch("bb_stack.filecodebox.upload_file") as upload,
            redirect_stdout(output),
        ):
            upload.return_value = {"share_code": "654321"}
            self.assertEqual(run_filecodebox_command(args, self.paths), 0)
        self.assertNotIn("private-token", output.getvalue())
        self.assertEqual(upload.call_args.kwargs["token"], "private-token")

    def test_real_curl_upload_sends_multipart_and_private_header(self) -> None:
        captured: dict[str, object] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                captured.update(
                    {
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "content_type": self.headers.get("Content-Type"),
                        "body": self.rfile.read(length),
                    }
                )
                body = json.dumps(
                    {
                        "code": 200,
                        "detail": {"code": "123456", "name": "artifact.zip"},
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            special_source = self.source.with_name('artifact;quoted".zip')
            special_source.write_bytes(b"fixture")
            ConfigurationManager(self.paths).configure(
                {"BB_FILECODEBOX_URL": f"http://127.0.0.1:{server.server_port}"}
            )
            result = upload_file(self.paths, special_source, token="private-token")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(result["share_code"], "123456")
        self.assertEqual(captured["path"], "/share/file/")
        self.assertEqual(captured["authorization"], "Bearer private-token")
        self.assertIn("multipart/form-data", str(captured["content_type"]))
        self.assertIn(b"fixture", captured["body"])

    def test_l5_provider_and_workspace_expose_dedicated_command(self) -> None:
        registry = load_yaml(ROOT / "05-L5-MCP-CLI" / "capabilities.yaml")
        provider = registry["providers"]["filecodebox"]
        self.assertEqual(provider["kind"], "cli")
        self.assertEqual(
            provider["locator"], {"type": "command", "value": "filecodebox-upload"}
        )
        wrapper = ROOT / "00-L0-Runtime" / "bin" / "filecodebox-upload"
        self.assertTrue(wrapper.is_file())
        self.assertTrue(os.access(wrapper, os.X_OK))
        router = (
            ROOT / "02-L2-Workflow-Profiles" / "workspace" / "CLAUDE.md"
        ).read_text(encoding="utf-8")
        self.assertIn("filecodebox-upload <path> --json", router)


if __name__ == "__main__":
    unittest.main(verbosity=2)
