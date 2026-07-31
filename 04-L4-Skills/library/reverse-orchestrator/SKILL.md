---
name: reverse-orchestrator
description: Orchestrate first-pass reverse engineering of an authorized binary, APK, firmware image, or CTF artifact. Use to inventory formats and protections, choose static versus dynamic analysis, preserve scripts and evidence, and route to Android or other specialist skills.
---

# Reverse Engineering Orchestrator

1. Hash and identify every supplied artifact; preserve originals unchanged.
2. Record architecture, format, protections, imports, strings, and entry points.
3. Choose the smallest static or dynamic experiment that distinguishes the
   leading hypotheses.
4. For APK/XAPK/JAR/AAR static triage, load `android-reverse-engineering`.
   For device, component, Frida, storage, TLS, or runtime security testing, load
   `android-pentest`. For mixed Web surfaces, route the HTTP component to
   `ctf-web`.
5. Save extraction, patching, instrumentation, and reproduction scripts.
6. Verify the recovered behavior, secret, flag, or security impact and checkpoint
   exact offsets, symbols, tool versions, and next actions.
