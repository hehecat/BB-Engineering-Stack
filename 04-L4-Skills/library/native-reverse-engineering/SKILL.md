---
name: native-reverse-engineering
description: Analyze ELF, PE, Mach-O, shared libraries, firmware, native bytecode, stripped Go or Rust binaries, JNI libraries, and custom native protocols. Use for static triage, disassembly, debugging, emulation, anti-analysis identification, binary behavior recovery, or patch comparison.
---

# Native Reverse Engineering

Preserve the supplied artifact and recover behavior through the smallest
reproducible experiment. Keep every generated file inside the active
Engagement.

## Establish The Boundary

1. Read `engagement.yaml`, `notes/SCOPE.md`, `STATUS.md`, and
   `SESSION-HANDOFF.md` for context.
2. Treat the supplied artifact as the active work unit. Related components,
   libraries, and services discovered from it are active by default.
3. Treat local, CTF, and standalone-analysis artifacts as passive inputs until
   dynamic analysis is useful.
4. Never execute an untrusted artifact on the host during triage.
5. Preserve the original byte-for-byte; write copies, patches, databases, and
   traces under the Engagement only.

## Run Deterministic Triage

Run the bundled script before selecting a decompiler or debugger (add
`--extract` when the artifact may wrap an ASAR, PyInstaller, or ZIP/APK/IPA/VSIX
container so members land directly under `extracted/`):

```bash
python3 "$BB_STACK_ROOT/04-L4-Skills/library/native-reverse-engineering/scripts/triage_native.py" \
  --input PATH_TO_ARTIFACT \
  --output "$PWD/artifacts/native-triage" \
  --extract
```

Read `summary.json` first (`artifact` reports ELF, PE/.NET, Mach-O/Universal,
WASM, ASAR, PyInstaller, and ZIP/APK signing metadata without host binutils).
Use the generated `file`, `readelf`, `otool`, `codesign`, `objdump`, `nm`,
`strings`, `rabin2`, and `checksec` outputs only when the corresponding probe
reports `available=true`. Do not interpret a missing optional tool as an
artifact property.

Record at minimum:

- SHA256, size, format, architecture, endianness, and entry point.
- Sections or segments, imports, exports, symbols, relocations, and embedded
  strings.
- NX, PIE, RELRO, stack canary, signing, packing, stripping, and obvious
  anti-analysis indicators when observable.
- Tool versions and exact commands used after the deterministic triage.

## Select One Analysis Path

- Use `radare2` (`r2_query.py` caches JSON `functions`, `disasm --pseudo`, and
  `xrefs` under `--cache-dir "$PWD/artifacts/r2-cache"`) or `objdump` for
  portable CLI-first static analysis.
- Use Ghidra headless only when its command is already registered and ready.
- Use IDA only when the operator has supplied a licensed installation; never
  download, modify, or bypass a commercial license.
- Use `gdb` (Linux) or `lldb` (macOS) only for a trusted local fixture or inside
  an approved isolated execution environment.
- Use QEMU user/system emulation for foreign architectures; record the emulator,
  sysroot, CPU model, arguments, and input.
- Route APK/XAPK/JAR/AAR Java or Kotlin code to
  `android-reverse-engineering`. Keep `.so` and JNI work in this Skill.
- Route exploit construction to the CTF methodology only when the Engagement
  workflow is `ctf`. Do not import CTF exploit policy into standalone analysis
  or assessment.

Read `references/platform-patterns.md` after identifying the language,
framework, format, or firmware layout. Read
`references/dynamic-analysis.md` when static evidence cannot separate the
leading hypotheses.

## Recover Behavior

1. Identify the smallest set of functions that consume controlled input or
   produce the requested output.
2. Build a call graph from entry points, imports, cross-references, strings, and
   error paths.
3. Rename symbols from evidence, not intuition; retain original addresses.
4. Translate only the relevant algorithm or protocol into a script under
   `scripts/`.
5. Compare recovered behavior against at least one observed input/output pair.
6. Re-run from a clean copy and verify the artifact hash remains unchanged.

For stripped Go, Rust, C++, JNI, ARM64, firmware, or custom protocols, apply the
specific checklist in `references/platform-patterns.md`.

## Dynamic Work

1. State the exact hypothesis that runtime observation will distinguish.
2. Prefer an isolated disposable environment with no credentials, shared home,
   host network, or writable source mount.
3. Record hashes for the original and any execution copy.
4. Capture process arguments, environment, loader, architecture, sysroot,
   debugger or emulator version, and input.
5. Record unexpected network access, persistence, privilege change, destructive
   behavior, or target drift, then adapt the experiment and continue safely.
6. Preserve traces and debugger scripts; do not rely on interactive history.

## Deliver Evidence

Write outputs to these Engagement locations:

- `artifacts/native-triage/`: deterministic inventory and raw probe output.
- `artifacts/native-analysis/`: disassembly excerpts, traces, recovered data,
  and comparison results.
- `scripts/`: extraction, decoding, emulation, debugger, and verification
  scripts.
- `notes/analysis-log.md`: hypotheses, evidence references, discarded paths,
  and next action.

Before claiming completion, verify all of the following:

- [ ] Keep the original SHA256 unchanged.
- [ ] Identify the format and architecture from tool output.
- [ ] Tie every recovered behavior to an offset, symbol, trace, or script.
- [ ] Reproduce the requested algorithm, protocol, secret, flag, or security
      impact from a clean input.
- [ ] Record uncertainty explicitly when decompilation or emulation is
      incomplete.
- [ ] Keep CTF-only exploitation outside analysis and assessment workflows.
