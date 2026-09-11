# Security Policy

## Supported Versions

Security fixes are currently considered for the latest published `0.1.x`
release line and the repository's current default branch.

| Version | Supported |
| --- | --- |
| Latest `0.1.x` | Yes |
| Older snapshots | No guaranteed support |

## Reporting a Vulnerability

Do not open a public issue for a suspected vulnerability or include secrets,
private network details, personal data, certificates, or private keys in public
repository content.

Use GitHub's private vulnerability reporting flow:

<https://github.com/PowellWells/gongshu/security/advisories/new>

Include:

- the affected version or commit;
- the affected component and environment;
- reproduction steps or a minimal proof of concept;
- the potential impact;
- any known mitigation;
- whether the report contains sensitive data that needs special handling.

Maintainers aim to acknowledge a complete report within seven days. Validation,
remediation, and disclosure timing depend on severity, reproducibility,
third-party dependencies, and maintainer availability. This is a response goal,
not a service-level guarantee.

## Scope Notes

Gongshu is an experimentation and simulation platform, not a safety-certified
robot controller. Reports involving physical hardware must clearly distinguish
tested behavior from simulation or hypothetical impact. Vulnerabilities in
third-party runtimes or models may need coordinated reporting to their upstream
maintainers.
