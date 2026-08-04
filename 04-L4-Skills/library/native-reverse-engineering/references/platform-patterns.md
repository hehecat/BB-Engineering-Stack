# Native Platform Patterns

Read only the section matching evidence from deterministic triage.

## ELF And Shared Objects

- Inspect the ELF header, program headers, dynamic section, relocations, symbol
  tables, notes, interpreter, RPATH, and RUNPATH.
- Record PIE, NX, RELRO, canary, stripped state, build ID, and required shared
  libraries.
- Anchor analysis at entry points, constructors, exported functions, imported
  comparison or crypto routines, and strings with high information value.
- Treat `.init_array`, TLS callbacks, IFUNC resolvers, and JNI registration as
  possible pre-main behavior.

## PE And DLL

- Inspect machine type, subsystem, sections, imports, exports, resources,
  relocations, exception data, TLS callbacks, and Authenticode metadata.
- Record ASLR, DEP, CFG, stack protection, packing signals, and managed-runtime
  headers.
- Route CLR assemblies to a managed-code workflow; keep mixed-mode or native
  exports here.

## Mach-O

- Inspect architecture slices, load commands, imported dylibs, symbols,
  Objective-C metadata, Swift symbols, entitlements, and code-signing data.
- Keep device actions under the authorized iOS assessment workflow.

## Go

- Confirm Go build metadata, `pclntab`, module data, runtime symbols, type
  descriptors, goroutine entry points, and embedded files.
- Recover function names from metadata before manually renaming stripped code.
- Separate runtime scaffolding from application packages and trace from
  `main.main` or exported handlers.

## Rust

- Inspect demangled symbols, panic strings, crate paths, trait objects, vtables,
  `Result` or `Option` branches, and allocator calls.
- Treat bounds checks and panic paths as compiler scaffolding unless evidence
  makes them semantically relevant.

## C++

- Recover RTTI, vtables, constructors, destructors, exception tables, name
  mangling, and standard-library container layouts.
- Record compiler and ABI assumptions before applying structure layouts.

## JNI And Android Native Libraries

- Map `JNI_OnLoad`, exported `Java_*` symbols, and `RegisterNatives` tables.
- Join native method signatures to Java or Kotlin call sites from the Android
  decompilation output.
- Track ABI split, load order, library extraction rules, and any dynamically
  resolved function names.

## ARM64

- Record the platform ABI and calling convention before interpreting register
  use.
- Track ADRP/ADD address construction, literal pools, veneers, PAC/BTI markers,
  and condition flags across branches.
- Distinguish compiler-generated prologues and stack checks from application
  logic.

## Firmware

- Hash the container and every extracted member.
- Identify container headers, partition table, compression, filesystem,
  architecture, endianness, boot chain, and update/signature metadata.
- Preserve offsets and extraction commands so each member can be traced back to
  the original image.
- Do not flash hardware or invoke update mechanisms without explicit Scope and
  a recovery procedure.

## Custom Protocols

- Capture at least two messages when available and separate framing, length,
  type, sequence, checksum, compression, encryption, and payload fields.
- Correlate parser and serializer functions before assigning field semantics.
- Implement a minimal offline decoder and verify round-trip behavior against
  captured samples.

## Patch And Binary Diff

- Confirm architecture, compiler family, build configuration, and dependency
  versions are comparable.
- Match functions using symbols, constants, strings, control-flow shape, and
  call relationships.
- Report changed behavior and evidence before discussing exploitability.
- Keep exploit construction behind the active workflow and authorization gate.
