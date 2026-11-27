# Reverse Engineering Domain

Hash and preserve every original artifact. Identify format, architecture,
endianness, entry points, sections, imports, strings, symbols, and protections
before selecting static or dynamic analysis. Start with `reverse-orchestrator`
for standalone analysis or CTF; an assessment retains
`security-orchestrator` as workflow owner. Load `native-reverse-engineering`
for ELF, PE, Mach-O, shared libraries, firmware, stripped Go or Rust binaries,
JNI libraries, and custom native protocols. Load `binary-exploitation` after
initial triage when a CTF Pwn or assessment memory-corruption hypothesis needs
exploitability proof, while keeping standalone `analysis` strictly non-exploit.
When Android analysis discovers a `.so`, retain the Android workflow and hand
off only the native component. Run the smallest experiment that separates the
leading hypotheses.

Record tool versions, base addresses, offsets, symbols, patches, and runtime
inputs. Keep extraction, decoding, emulation, debugger, and patch scripts under
`scripts/`; save disassembly excerpts, traces, and recovered data under
`artifacts/`. Verify the recovered behavior or flag from a clean copy.
