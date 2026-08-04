# Dynamic Analysis Gate

Use dynamic analysis only after static triage produces a testable hypothesis.

## Prepare

- [ ] Confirm the workflow, authorization state, Scope, artifact hash, and
      requested outcome.
- [ ] Choose a disposable VM, container, emulator, or dedicated test device.
- [ ] Remove unrelated credentials, shared home mounts, host sockets, and
      writable source mounts.
- [ ] Define network policy before execution; default to no network.
- [ ] Record the loader, sysroot, architecture, CPU model, arguments,
      environment, input, and timeout.
- [ ] Prepare process, filesystem, and network observation before launch.

## Choose The Smallest Probe

- Use debugger breakpoints at a known comparison, parser, crypto, or output
  function when one observation can answer the hypothesis.
- Use syscall tracing to identify file, process, memory, and network behavior
  without first reconstructing every function.
- Use library-call tracing only when dynamic linking exposes the relevant call.
- Use Frida when a stable symbol, export, runtime registration, or module offset
  provides a bounded hook point.
- Use QEMU user emulation for foreign Linux userland; use full-system emulation
  only when kernel, device, or boot behavior is material.

## Stop Conditions

Stop immediately and preserve evidence when any of these occurs:

- The process attempts unexpected external network access.
- The process requests privilege escalation or accesses host secrets.
- The process creates persistence, modifies boot state, or targets unrelated
  processes.
- The observed target, device, account, or address leaves written Scope.
- The environment cannot contain the behavior or restore a clean snapshot.

## Record

- Save debugger and instrumentation scripts under `scripts/`.
- Save traces, dumps, screenshots, and recovered values under
  `artifacts/native-analysis/`.
- Record exact module bases, rebasing method, offsets, symbols, versions, and
  invocation commands in `notes/analysis-log.md`.
- Verify the recovered behavior again from a clean snapshot or clean execution
  copy.
