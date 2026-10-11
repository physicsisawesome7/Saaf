# ADR 0002: Declarative detectors plus a shared conformance suite, not a Rust/WASM core

- Status: accepted
- Date: 2026-10-07

## Context
We need detection in Python (servers, notebooks), Node and the browser (extension, playground). Options: (a) one Rust core compiled to a Python extension and to WASM, or (b) a declarative spec (regexes, scores, context) plus small named validators, implemented natively in each language and tested against shared vectors.

## Decision
Option (b). Patterns are written in the regex subset common to Python `re` and JavaScript `RegExp`. Validators are pure functions of a canonical string. `spec/conformance/*.jsonl` defines expected behaviour, and both ports run it in CI.

## Consequences
- Zero native build tooling; a pure-Python wheel; a tiny JS bundle.
- Validators exist twice (about 200 lines each) and must be kept in step; the vectors catch drift.
- Revisit this only if client-side NER in the browser extension proves demand (see Phase 3).
