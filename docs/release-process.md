# Release process

## Packages and tags

| Package | Registry | Tag prefix | Version source |
|---|---|---|---|
| `saaf` (core) | PyPI | `core-v` | `packages/saaf-core/src/saaf/_version.py` |
| `@safearly/saaf` | npm | `js-v` | `packages/saaf-js/package.json` |
| `saaf-gateway` | PyPI + GHCR image | `gateway-v` | `packages/saaf-gateway/src/saaf_gateway/__init__.py` |
| `saaf-litellm`, `saaf-langchain`, `saaf-mcp` | PyPI | `litellm-v`, `langchain-v`, `mcp-v` | each `__init__.py` |
| Browser extension | Chrome Web Store / Edge Add-ons | `extension-v` | `manifest.json` |

## Steps

1. Update the version and `CHANGELOG.md` (move items from *Unreleased*).
2. For detector changes, paste benchmark deltas into the changelog entry.
3. Open a release PR; wait for CI to pass.
4. Merge, then tag: `git tag core-v0.2.0 && git push origin core-v0.2.0`.
5. `release.yml` builds, tests, publishes through PyPI Trusted Publishing (with attestations) or npm (with provenance), generates a CycloneDX SBOM, and creates a GitHub release with the artifacts.
6. Gateway image: built, pushed to GHCR, and signed with cosign (keyless).
7. Announce in Discussions and the changelog feed.

## One-time setup

- PyPI: configure a Trusted Publisher for each project → this repo, workflow `release.yml`, environment `pypi`.
- npm: an automation token in the `npm` environment secret `NPM_TOKEN`; enable provenance.
- GitHub environments `pypi` and `npm` with required reviewers.

## Launch checklist (P2-09)

- [ ] README limits section and `docs/limitations.md` current
- [ ] Lawyer has reviewed every public sentence that mentions DPDP
- [ ] No "compliant"/"compliance guaranteed" wording anywhere (`git grep -i complian`)
- [ ] Benchmark page with reproduction steps verified by an outsider
- [ ] Playground deployed; security headers set (CSP, no third-party scripts)
- [ ] `SECURITY.md` contact monitored
