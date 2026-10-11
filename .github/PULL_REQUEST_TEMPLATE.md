## What and why

<!-- Plan task ID if any, e.g. P1-04. Link the issue. -->

## Checklist

- [ ] Tests added or updated; CI is green
- [ ] **Detector change?** Conformance vectors added in `spec/conformance/`, `python scripts/sync_spec.py` run, both Python and TypeScript suites pass
- [ ] **Detector change?** Benchmark deltas pasted below (`make bench`)
- [ ] No new runtime dependency in `saaf-core` / `saaf-js`
- [ ] No raw values can reach logs, errors, audit or telemetry from this change
- [ ] All identifiers in tests and fixtures are synthetic
- [ ] Docs and `CHANGELOG.md` (*Unreleased*) updated
- [ ] No compliance claims in user-facing text

## Benchmark deltas (detector changes only)

```
strict micro-F1   x -> y
hard-neg FP/1k    x -> y
```
