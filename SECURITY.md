# Security Policy

## Supported versions

IntentFlow is pre-1.0 and moves fast. Security fixes are applied to the latest
released version on the `0.x` line and to `main`; older versions are not
maintained.

| Version | Supported |
|---------|-----------|
| latest `0.x` release | ✅ |
| `main` | ✅ |
| older releases | ❌ |

## Reporting a vulnerability

Please **do not open a public issue** for a suspected vulnerability.

Report it privately through GitHub's
[private vulnerability reporting](https://github.com/dgenio/intentflow/security/advisories/new)
("Report a vulnerability" under the repository's **Security** tab). If that is
unavailable to you, open a minimal public issue asking for a private contact
channel — without disclosing details — and a maintainer will follow up.

When reporting, please include:

- a description of the issue and its impact;
- steps to reproduce (a minimal `.iflow` program or script is ideal);
- affected version(s) and environment.

We aim to acknowledge reports within a few days and to coordinate a fix and
disclosure timeline with you.

## Scope

IntentFlow's security posture is documented in
[`docs/threat-model.md`](docs/threat-model.md), including what the design
enforces, what it mitigates, and explicit non-goals. In particular, note that:

- **Registered tools are not sandboxed.** A vulnerability in a Python function
  *you* register as a governed action is not an IntentFlow vulnerability; the
  gate governs authorization, not tool internals.
- **Model jailbreaks are assumed.** The design confines a run's *actions*, not
  the model's *text*. A model producing undesirable text within its allowed
  envelope is expected behavior, not a security bug.

Reports about the action gate being bypassable, a tampered witness auditing as
conformant, evidence content escaping its data boundary into instructions in a
way the design intends to prevent, or trace-signature verification being
forgeable are all in scope and very welcome.
