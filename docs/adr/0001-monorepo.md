# ADR 0001: One monorepo for engine, ports, gateway, plugins and apps

- Status: accepted
- Date: 2026-10-07

## Context
The Python and TypeScript engines must stay behaviourally identical, and every plugin depends on the engine. Two engineers cannot coordinate releases across eight repositories.

## Decision
A single repository with `spec/`, `packages/`, `plugins/`, `apps/`, `bench/`. A uv workspace for Python and npm workspaces for TypeScript. Each package is versioned and released independently, using tag prefixes.

## Consequences
- One PR can change the spec, both ports and the vectors together. CI enforces consistency.
- CI must use path filters to stay fast.
- Plugin repositories that ecosystems require (for example, the Open WebUI community site) are publish targets, not sources of truth.
