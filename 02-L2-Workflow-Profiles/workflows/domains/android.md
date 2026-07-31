# Android Domain

Treat the APK and supplied device context as one reproducible analysis unit.
Hash and preserve the original, inspect package metadata, manifest, resources,
signing, components, native libraries, and network configuration before
instrumentation. Route Android analysis through `reverse-orchestrator`, then
load `android-reverse-engineering` for framework fingerprinting, decompilation,
Kotlin/R8 name recovery, API extraction, and call-flow analysis. Load
`android-pentest` for component security, device, ADB, Frida, storage, TLS, and
other dynamic leads.

Static analysis must work without a connected device. Before dynamic actions,
record the device/emulator, ABI, Android version, root state, Frida versions,
and package build. Save decoded output under `artifacts/`, reusable ADB/Frida
steps under `scripts/`, and exact class, method, component, and offset references
in the solve log.
