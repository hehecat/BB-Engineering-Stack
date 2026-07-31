# Android Domain

Treat the APK and supplied device context as one reproducible analysis unit.
Hash and preserve the original, inspect package metadata, manifest, resources,
signing, components, native libraries, and network configuration before
instrumentation. Route Android analysis through `reverse-orchestrator`, then
load `android-pentest` for the active static or dynamic lead.

Static analysis must work without a connected device. Before dynamic actions,
record the device/emulator, ABI, Android version, root state, Frida versions,
and package build. Save decoded output under `artifacts/`, reusable ADB/Frida
steps under `scripts/`, and exact class, method, component, and offset references
in the solve log.
