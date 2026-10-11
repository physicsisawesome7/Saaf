# ADR 0003: Apache-2.0 for the open core

- Status: accepted
- Date: 2026-10-07

## Context
Enterprise legal review in BFSI and health is a sales bottleneck. MIT lacks an explicit patent grant.

## Decision
Library, CLI, basic gateway, plugins, playground and benchmark are Apache-2.0. The console, SSO/RBAC, KMS vault backends, sector packs, evidence exports and support form the commercial tier (separate licence, separate directory or repository when built).

## Consequences
- An explicit patent grant and a familiar licence for legal teams.
- The open/commercial boundary must be kept clear in code layout (no commercial code in `packages/`).
