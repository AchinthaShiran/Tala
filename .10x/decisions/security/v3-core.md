# Security: v3-core threat model and review

See docs/safety.md for the threat table. Review outcome:

| Finding | Severity | Status |
| --- | --- | --- |
| Project-local packs auto-loaded from the cwd (malicious repo could declare `risk: read_only` for any command) | High | **Fixed**: untrusted until `deskaide packs trust`; trust stored outside the repo; doctor warns; tests |
| v2 `adb shell` tools allowed remote-shell injection via path/package parameters | High | **Fixed** in migration: strict patterns + test proving `;` and `$()` are rejected |
| Option injection through values starting with `-` | Medium | **Fixed**: leading-dash guard by default |
| Unknown `output_encoding` could raise at runtime | Low | **Fixed**: validated at load |
| Approval decision type confusion | Low | `decisions.get(id) is True` is strict; anything else is denial |
| Audit log may contain secrets passed as arguments | Low | Documented; do not pass secrets as tool arguments |
| No OS sandbox; approved commands run as the user | Accepted | Documented residual risk; never run elevated |
| Read-only tools may place sensitive data in model context | Accepted | Documented; matters only for non-local providers |
| Prompt injection via tool output | Medium | Mitigated (fence, neutralised markers, post-output tightening); cannot be eliminated for approved actions |
| `tree /A /F {path}` treats a `/`-prefixed value as an option on Windows | Info | Harmless (`/?` prints help); noted |
Dependencies: pinned major ranges in pyproject; add `pip-audit` in CI later.
Sign-off: acceptable for local, single-user use at v3.0.
