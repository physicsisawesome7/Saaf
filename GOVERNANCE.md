# Governance

## Roles

- **Maintainers** merge PRs, cut releases and own the roadmap ([docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md)). They are listed in `.github/CODEOWNERS`.
- **Benchmark stewards** (a subset of maintainers) own `bench/` and the private held-out split. They review every benchmark sample and adapter, and they must not tune detectors on the held-out data.
- **Contributors**: anyone with a merged PR.

## Decisions

- Day-to-day decisions happen in PRs, by lazy consensus.
- Architecture decisions are recorded as ADRs in `docs/adr/`. An ADR is accepted after 3 working days without unresolved objections from a maintainer.
- Spec changes that alter default detections need benchmark evidence in the PR.

## Open core

The Apache-2.0 packages in this repository stay open. Commercial features (console enterprise features, SSO/RBAC, KMS vault backends, sector packs, evidence exports) live outside `packages/` and `plugins/` (see ADR 0003). Fixes to the open core are never held back for the commercial tier.

## Becoming a maintainer

Sustained, high-quality contributions plus nomination by an existing maintainer, with no objections within one week.
