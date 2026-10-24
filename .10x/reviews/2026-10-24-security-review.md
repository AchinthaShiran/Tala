# Security review: v3.0.0

Scope: argument handling, command execution, approval flow, pack loading, prompt injection, persistence.
See `.10x/decisions/security/v3-core.md` for findings and status. Additional item found in final live testing:

- **High, fixed:** three state-changing tools shipped as `read_only` (adb_install_apk, adb_reboot_bootloader, fastboot_reboot_bootloader), so they would have run without approval. Fixed by an explicit reviewed risk list and regression tests (verb scanner over all builtin commands + pinned labels).

Verdict: no open high/medium findings. Residual risks (no OS sandbox, approved commands run as the user, secrets in audit log) are documented in docs/safety.md.
