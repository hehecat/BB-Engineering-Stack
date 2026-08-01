# iOS Domain

Route through `security-orchestrator`, then use `ios-pentest` for IPA structure,
entitlements, URL schemes, local storage, Keychain, IPC, network security,
jailbreak checks, Frida instrumentation, and runtime validation. Preserve the
original IPA and record hashes, bundle id, signing state, architecture, device,
iOS version, jailbreak state, and tool versions before dynamic work.

Static analysis must remain useful when no device is connected. Save extracted
artifacts and traces under `artifacts/`, reusable Frida or device procedures
under `scripts/`, and distinguish device-dependent gaps from completed checks.
