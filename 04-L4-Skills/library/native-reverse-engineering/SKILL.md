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
   `SESSION-HANDOFF.md`.
2. Confirm that the artifact path is in Scope.
3. Treat local, CTF, and standalone-analysis artifacts as passive inputs.
4. Require verified authorization before interacting with a protected device,
   service, account, or remote target.
5. Never execute an untrusted artifact on the host during triage.
6. Preserve the original byte-for-byte; write copies, patches, databases, and
   traces under the Engagement only.

## Run Deterministic Triage

Run the bundled script before selecting a decompiler or debugger:

```bash
python3 "$BB_STACK_ROOT/04-L4-Skills/library/native-reverse-engineering/scripts/triage_native.py" \
  --input PATH_TO_ARTIFACT \
  --output "$PWD/artifacts/native-triage"
```

Read `summary.json` first. Use the generated `file`, `readelf`, `objdump`,
`nm`, `strings`, `rabin2`, and `checksec` outputs only when the corresponding
probe reports `available=true`. Do not interpret a missing optional tool as an
artifact property.

Record at minimum:

- SHA256, size, format, architecture, endianness, and entry point.
- Sections or segments, imports, exports, symbols, relocations, and embedded
  strings.
- NX, PIE, RELRO, stack canary, signing, packing, stripping, and obvious
  anti-analysis indicators when observable.
- Tool versions and exact commands used after the deterministic triage.

## Select One Analysis Path

- Use `radare2` or `objdump` for portable CLI-first static analysis.
- Use Ghidra headless only when its command is already registered and ready.
- Use IDA only when the operator has supplied a licensed installation; never
  download, modify, or bypass a commercial license.
- Use `gdb` only for a trusted local fixture or inside an approved isolated
  execution environment.
- Use QEMU user emulation for foreign Linux architectures; record the emulator,
  sysroot, CPU model, arguments, and input.
- Route APK/XAPK/JAR/AAR Java or Kotlin code to
  `android-reverse-engineering`. Keep `.so` and JNI work in this Skill.
- Route exploit construction to the CTF methodology only when the Engagement
  workflow is `ctf`. Do not import CTF exploit policy into standalone analysis
  or authorized assessment.

Read `references/platform-patterns.md` after identifying the language,
framework, format, or firmware layout. Read
`references/dynamic-analysis.md` only when static evidence cannot separate the
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

## Gate Dynamic Work

1. State the exact hypothesis that runtime observation will distinguish.
2. Prefer an isolated disposable environment with no credentials, shared home,
   host network, or writable source mount.
3. Record hashes for the original and any execution copy.
4. Capture process arguments, environment, loader, architecture, sysroot,
   debugger or emulator version, and input.
5. Stop on unexpected network access, persistence, privilege change, destructive
   behavior, or Scope drift.
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
