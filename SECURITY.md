# Security Policy

SYNTHESIS assumes it will be attacked — not just its website, but the
**integrity of its analytical history** (vision §41, §51). Reports about
either are equally welcome.

## Reporting

Please open a **private security advisory** on GitHub
(Security → Advisories → Report a vulnerability). Do not open public issues
for exploitable problems.

Especially interesting classes of report:

| Class | Example |
|---|---|
| Evidence-chain integrity | Any way to alter analytical history without the C/Python/TS verifiers noticing |
| Federation identity | Forging a node identity or getting an unsigned/mis-signed bundle ingested |
| Prompt-injection | Getting external content interpreted as instructions anywhere in the ingest path |
| Zero-trust bypass | An adapter or peer writing world state directly instead of proposing |
| Classic web/API | Injection, authz, SSRF, deserialization, rate-limit bypass (OWASP ASVS scope) |

## Principles under test

- Never trust an input merely because it is connected.
- Never trust an inference merely because an AI generated it.
- No single compromised component may compromise the system.
- Every consequential conclusion must remain traceable to evidence.

## Scope notes

This is an MVP: authentication, rate limiting and secret management are
documented targets (vision §18, §24) and not yet fully implemented — reports
that turn those sections into working code are as valuable as vulnerability
reports.
