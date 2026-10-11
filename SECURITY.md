# Security policy

## Supported versions

Until 1.0, only the latest minor release of each package receives security fixes.

## Reporting a vulnerability

**Do not open a public issue.** Report privately by email to **lalit@safearly.com**, or through GitHub's *Report a vulnerability* (Security → Advisories) on this repository.

Please include affected package and version, impact, and a reproduction that uses **synthetic data only**.

What to expect:
- acknowledgement within 3 working days;
- a triage decision and severity within 10 working days;
- coordinated disclosure, by default within 90 days of the report, or sooner once a fix ships;
- credit in the advisory, if you want it.

## Scope

In scope: detection bypasses that defeat a documented guarantee, restore or vault flaws that leak values across sessions or tenants, raw values appearing in logs/audit/errors, cryptographic weaknesses in vaults or audit signing, gateway header or tenant isolation issues, and supply-chain issues in our release process.

Detection misses for formats listed in [docs/limitations.md](docs/limitations.md) are known limitations. Report them as normal issues using synthetic examples.

## Release integrity

Python packages are published through PyPI Trusted Publishing with attestations; npm packages carry provenance; container images are signed with cosign; each release includes a CycloneDX SBOM.
