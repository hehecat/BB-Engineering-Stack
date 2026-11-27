#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["BB_STACK_ROOT"] = str(ROOT)

from bb_stack.capabilities import CapabilityRegistry
from bb_stack.paths import StackPaths
from bb_stack.runtime import RuntimeManager
from bb_stack.skills import SkillRegistry


class NativeReverseSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bb-native-skill-")
        self.workspace = Path(self.temporary.name)
        self.skill = ROOT / "04-L4-Skills/library/native-reverse-engineering"
        self.script = self.skill / "scripts/triage_native.py"
        self.paths = StackPaths(
            ROOT,
            self.workspace / "home",
            self.workspace / "work",
            self.workspace / "config",
            self.workspace / ".claude",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_registry_profiles_and_tool_contracts(self) -> None:
        skills = SkillRegistry(self.paths)
        self.assertEqual(
            skills._frontmatter(self.skill / "SKILL.md")["name"],
            "native-reverse-engineering",
        )
        self.assertIn(
            "native-reverse-engineering", skills.profile("reverse")["required"]
        )
        self.assertIn(
            "native-reverse-engineering",
            skills.profile("analysis-reverse")["required"],
        )
        assessment = skills.profile("assessment-reverse")
        self.assertEqual(assessment["orchestrator"], "security-orchestrator")
        self.assertNotIn("solve-challenge", assessment["required"])

        capabilities = CapabilityRegistry(self.paths)
        for profile_name in ("reverse", "analysis-reverse", "assessment-reverse"):
            profile = capabilities.profile(profile_name)
            self.assertIn("native.triage", profile["required"])
            self.assertIn("native.static", profile["required"])
        registry = capabilities.registry()
        self.assertEqual(registry["capabilities"]["native.triage"]["strategy"], "all")
        self.assertNotIn("jadx", registry["capabilities"]["native.static"]["providers"])

        tools = RuntimeManager(self.paths).validate_config()["tool_profiles"]
        self.assertIn("assessment-reverse", tools)

    @unittest.skipUnless(
        all(shutil.which(command) for command in ("file", "readelf", "objdump")),
        "native triage requires file and binutils",
    )
    def test_real_elf_triage_is_read_only_and_structured(self) -> None:
        source = Path(sys.executable).resolve()
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        output = self.workspace / "triage"
        completed = subprocess.run(
            [
                sys.executable,
                str(self.script),
                "--input",
                str(source),
                "--output",
                str(output),
            ],
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        summary = json.loads((output / "summary.json").read_text())
        self.assertEqual(summary["schema_version"], 1)
        self.assertEqual(summary["input"]["sha256"], before)
        self.assertTrue(summary["input"]["unchanged"])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        self.assertEqual(summary["probes"]["file"]["exit_code"], 0)
        self.assertEqual(summary["tools"]["file"]["path"], shutil.which("file"))
        self.assertTrue(summary["tools"]["file"]["version"])
        self.assertIn("ELF", (output / "file.txt").read_text())
        self.assertIn(
            "Entry point address", (output / "readelf-header.txt").read_text()
        )

    def test_triage_rejects_nonempty_output(self) -> None:
        output = self.workspace / "existing"
        output.mkdir()
        (output / "owned.txt").write_text("keep", encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                str(self.script),
                "--input",
                str(Path(sys.executable).resolve()),
                "--output",
                str(output),
            ],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("not empty", completed.stderr)
        self.assertEqual((output / "owned.txt").read_text(), "keep")

    def test_triage_never_executes_the_input(self) -> None:
        marker = self.workspace / "executed"
        source = self.workspace / "untrusted-fixture"
        source.write_text(
            f"#!/bin/sh\nprintf executed > {marker}\n",
            encoding="utf-8",
        )
        source.chmod(0o755)
        completed = subprocess.run(
            [
                sys.executable,
                str(self.script),
                "--input",
                str(source),
                "--output",
                str(self.workspace / "script-triage"),
            ],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(marker.exists())

    def test_binary_headers_cover_pe_dotnet_macho_universal_and_wasm(self) -> None:
        import struct
        from bb_stack.artifact import inspect_artifact

        # Synthetic PE32+ x86_64 with Authenticode and CLR (.NET) data directories.
        pe_path = self.workspace / "sample.exe"
        dos = bytearray(0x80)
        dos[:2] = b"MZ"
        struct.pack_into("<I", dos, 0x3C, 0x80)
        opt = bytearray(240)
        struct.pack_into("<H", opt, 0, 0x20B)  # PE32+
        struct.pack_into("<I", opt, 16, 0x1000)  # entry RVA
        struct.pack_into("<Q", opt, 24, 0x140000000)  # image base
        struct.pack_into("<H", opt, 68, 3)  # windows-cui
        struct.pack_into("<I", opt, 108, 16)  # NumberOfRvaAndSizes
        struct.pack_into("<II", opt, 112 + 4 * 8, 0x4000, 0x200)  # Authenticode
        struct.pack_into("<II", opt, 112 + 14 * 8, 0x2000, 0x48)  # CLR (.NET)
        coff = b"PE\x00\x00" + struct.pack(
            "<HHIIIHH", 0x8664, 1, 0, 0, 0, len(opt), 0x0022
        )
        sec = bytearray(40)
        sec[:5] = b".text"
        struct.pack_into("<IIII", sec, 8, 0x500, 0x1000, 0x200, 0x400)
        pe_path.write_bytes(bytes(dos + coff + opt + sec))
        pe_info = inspect_artifact(pe_path)
        self.assertEqual(pe_info["primary_format"], "pe")
        self.assertEqual(pe_info["binary"]["variant"], "pe32+")
        self.assertEqual(pe_info["binary"]["machine"], "x86_64")
        self.assertTrue(pe_info["binary"]["is_dotnet"])
        self.assertTrue(pe_info["binary"]["has_authenticode"])
        self.assertEqual(pe_info["binary"]["sections"][0]["name"], ".text")

        # Universal Mach-O with x86_64 + arm64 slices (and LC_CODE_SIGNATURE), vs Java .class.
        macho_path = self.workspace / "universal-bin"
        slice_x64 = struct.pack(
            "<IiiIIIII", 0xFEEDFACF, 0x01000007, 3, 2, 1, 16, 0, 0
        ) + struct.pack("<IIII", 0x1D, 16, 0, 0)
        slice_arm = struct.pack(
            "<IiiIIIII", 0xFEEDFACF, 0x0100000C, 0, 2, 0, 0, 0, 0
        )
        fat_hdr = (
            struct.pack(">II", 0xCAFEBABE, 2)
            + struct.pack(">iiIII", 0x01000007, 3, 64, len(slice_x64), 12)
            + struct.pack(">iiIII", 0x0100000C, 0, 128, len(slice_arm), 14)
        )
        blob = bytearray(200)
        blob[: len(fat_hdr)] = fat_hdr
        blob[64 : 64 + len(slice_x64)] = slice_x64
        blob[128 : 128 + len(slice_arm)] = slice_arm
        macho_path.write_bytes(bytes(blob))
        macho_info = inspect_artifact(macho_path)
        self.assertEqual(macho_info["primary_format"], "macho")
        self.assertTrue(macho_info["binary"]["universal"])
        self.assertEqual(
            [s["cpu"] for s in macho_info["binary"]["slices"]], ["x86_64", "arm64"]
        )
        self.assertTrue(macho_info["binary"]["slices"][0]["has_code_signature"])

        java_class = self.workspace / "Demo.class"
        java_class.write_bytes(b"\xca\xfe\xba\xbe\x00\x00\x00\x3d" + b"\x00" * 32)
        self.assertEqual(inspect_artifact(java_class)["primary_format"], "unknown")

        # WASM binary with a custom section and a code section.
        wasm_path = self.workspace / "module.wasm"
        custom_payload = b"\x09producers\x00"
        wasm_bytes = (
            b"\x00asm\x01\x00\x00\x00"
            + bytes([0, len(custom_payload)])
            + custom_payload
            + bytes([10, 2, 0, 0])
        )
        wasm_path.write_bytes(wasm_bytes)
        wasm_info = inspect_artifact(wasm_path)
        self.assertEqual(wasm_info["primary_format"], "wasm")
        self.assertEqual(wasm_info["binary"]["sections"][0]["name"], "producers")
        self.assertEqual(wasm_info["binary"]["sections"][1]["kind"], "code")

    def test_asar_and_pyinstaller_and_apk_unpacking_and_guards(self) -> None:
        import struct
        import zipfile
        import zlib
        from bb_stack.artifact import inspect_artifact
        from bb_stack.errors import ValidationError

        # 1. Valid Electron ASAR unpacks cleanly; traversal ASAR is rejected.
        def build_asar(tree: dict[str, object], payload: bytes) -> bytes:
            raw_json = json.dumps(tree).encode("utf-8")
            pad = (4 - (len(raw_json) % 4)) % 4
            aligned_len = len(raw_json) + pad
            header_total = 8 + aligned_len
            return (
                struct.pack("<IIII", 4, header_total, 4 + aligned_len, len(raw_json))
                + raw_json
                + (b"\x00" * pad)
                + payload
            )

        js_code = b"export const sign = (x) => x + ':ok';\n"
        asar_path = self.workspace / "app.asar"
        asar_path.write_bytes(
            build_asar(
                {
                    "files": {
                        "src": {
                            "files": {
                                "preload.js": {
                                    "size": len(js_code),
                                    "offset": "0",
                                }
                            }
                        }
                    }
                },
                js_code,
            )
        )
        asar_out = self.workspace / "asar-out"
        asar_report = inspect_artifact(asar_path, output_dir=asar_out, extract=True)
        self.assertEqual(asar_report["primary_format"], "asar")
        self.assertEqual(
            (asar_out / "extracted" / "src" / "preload.js").read_bytes(), js_code
        )

        evil_asar = self.workspace / "evil.asar"
        evil_asar.write_bytes(
            build_asar(
                {"files": {"..": {"files": {"pwn.js": {"size": 2, "offset": "0"}}}}},
                b"no",
            )
        )
        with self.assertRaisesRegex(ValidationError, "escapes extraction root"):
            inspect_artifact(
                evil_asar, output_dir=self.workspace / "evil-out", extract=True
            )

        # 2. PyInstaller CArchive appended to an ELF stub reports both binary & container.
        elf_stub = bytearray(64)
        elf_stub[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<HHIQQQIHHHHHH", elf_stub, 16, 3, 0x3E, 1, 0x1040, 0, 0, 0, 64, 0, 0, 0, 0, 0)
        entry_body = b"print('recovered entry')\n"
        compressed_entry = zlib.compress(entry_body)
        member_name = b"main_app\x00"
        pad = (4 - ((18 + len(member_name)) % 4)) % 4
        toc_entry = (
            struct.pack(
                "!iiiiBc",
                18 + len(member_name) + pad,
                0,
                len(compressed_entry),
                len(entry_body),
                1,
                b"s",
            )
            + member_name
            + (b"\x00" * pad)
        )
        pylib = b"libpython3.12.so.1.0".ljust(64, b"\x00")
        pkg_len = len(compressed_entry) + len(toc_entry) + 88
        cookie = struct.pack(
            "!8siiii64s",
            b"MEI\x0c\x0b\x0a\x0b\x0e",
            pkg_len,
            len(compressed_entry),
            len(toc_entry),
            312,
            pylib,
        )
        pyi_path = self.workspace / "bundled-elf"
        pyi_path.write_bytes(bytes(elf_stub) + compressed_entry + toc_entry + cookie)
        triage_out = self.workspace / "pyi-triage"
        completed = subprocess.run(
            [
                sys.executable,
                str(self.script),
                "--input",
                str(pyi_path),
                "--output",
                str(triage_out),
                "--extract",
            ],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        summary = json.loads((triage_out / "summary.json").read_text())
        self.assertEqual(summary["artifact"]["binary"]["format"], "elf")
        self.assertEqual(summary["artifact"]["container"]["kind"], "pyinstaller")
        self.assertEqual(
            summary["artifact"]["container"]["entry_scripts"], ["main_app"]
        )
        self.assertEqual(
            (triage_out / "extracted" / "scripts" / "main_app.pyc_stream").read_bytes(),
            entry_body,
        )

        # 3. APK with v2 + v3 signing block IDs is classified and schemes are detected.
        raw_zip = self.workspace / "unsigned.zip"
        with zipfile.ZipFile(raw_zip, "w") as zf:
            zf.writestr("AndroidManifest.xml", "<manifest/>")
            zf.writestr("classes.dex", "dex\n035\x00")
        zip_bytes = raw_zip.read_bytes()
        eocd = zip_bytes.rfind(b"PK\x05\x06")
        cd_offset = struct.unpack_from("<I", zip_bytes, eocd + 16)[0]
        pair_v2 = struct.pack("<QI", 8, 0x7109871A) + b"ABCD"
        pair_v3 = struct.pack("<QI", 8, 0xF05368C0) + b"EFGH"
        pairs = pair_v2 + pair_v3
        block_size = len(pairs) + 24
        sig_block = (
            struct.pack("<Q", block_size)
            + pairs
            + struct.pack("<Q16s", block_size, b"APK Sig Block 42")
        )
        new_eocd = bytearray(zip_bytes[eocd:])
        struct.pack_into("<I", new_eocd, 16, cd_offset + len(sig_block))
        apk_path = self.workspace / "signed.apk"
        apk_path.write_bytes(
            zip_bytes[:cd_offset] + sig_block + zip_bytes[cd_offset:eocd] + bytes(new_eocd)
        )
        apk_info = inspect_artifact(apk_path)
        self.assertEqual(apk_info["container"]["kind"], "apk")
        self.assertEqual(apk_info["container"]["apk_signature_schemes"], ["v2", "v3"])

    def test_r2_query_helper_caches_json_and_blocks_command_injection(self) -> None:
        r2_script = self.skill / "scripts/r2_query.py"
        stub_bin = self.workspace / "stub-bin"
        stub_bin.mkdir()
        calls_log = self.workspace / "r2-calls.log"
        r2_stub = stub_bin / "r2"
        r2_stub.write_text(
            "#!/usr/bin/env python3\n"
            "import json, pathlib, sys\n"
            f"pathlib.Path({str(calls_log)!r}).open('a').write(' '.join(sys.argv[1:]) + '\\n')\n"
            "cmd = sys.argv[sys.argv.index('-c') + 1]\n"
            "if 'aflj' in cmd:\n"
            "    print(json.dumps([{'name': 'sym.verify_sig', 'offset': 4198400, 'size': 128, 'nbbs': 5, 'callrefs': [1, 2]}]))\n"
            "elif 'pdfj' in cmd:\n"
            "    print(json.dumps({'name': 'sym.verify_sig', 'ops': [{'offset': 4198400, 'disasm': 'push rbp'}]}))\n"
            "elif 'pdc' in cmd:\n"
            "    print('int sym.verify_sig() { return 1; }')\n"
            "else:\n"
            "    print(json.dumps([{'from': 4198500, 'type': 'CALL'}]))\n",
            encoding="utf-8",
        )
        r2_stub.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = f"{stub_bin}:{env.get('PATH', '')}"
        cache_dir = self.workspace / "r2-cache"
        target_bin = Path(sys.executable).resolve()

        # Injection attempt in --target must fail before touching r2.
        injected = subprocess.run(
            [
                sys.executable,
                str(r2_script),
                "--input",
                str(target_bin),
                "disasm",
                "--target",
                "main; !touch /tmp/pwn",
            ],
            text=True,
            capture_output=True,
            env=env,
            timeout=15,
            check=False,
        )
        self.assertNotEqual(injected.returncode, 0)
        self.assertFalse(calls_log.exists())

        # First call runs r2 and populates cache; second call hits cache without spawning r2.
        for _ in range(2):
            ok = subprocess.run(
                [
                    sys.executable,
                    str(r2_script),
                    "--input",
                    str(target_bin),
                    "--cache-dir",
                    str(cache_dir),
                    "functions",
                    "--filter",
                    "verify",
                ],
                text=True,
                capture_output=True,
                env=env,
                timeout=15,
                check=False,
            )
            self.assertEqual(ok.returncode, 0, ok.stderr)
            parsed = json.loads(ok.stdout)
            self.assertEqual(parsed["functions"][0]["name"], "sym.verify_sig")
        self.assertEqual(len(calls_log.read_text().splitlines()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
