# Contributing to Saaf

Thanks for helping. Read this once before your first PR.

## Ground rules

1. **Never commit real personal data.** Not in tests, fixtures, issues, screenshots or benchmark samples. Use synthetic identifiers: `python -c "from saaf.validators import verhoeff_check_digit as c; p='23456789012'; print(p + c(p))"`.
2. **Detector changes need vectors.** Any change to `spec/entities.json` or a validator needs new lines in `spec/conformance/*.jsonl`, and both the Python and TypeScript suites must pass.
3. **No new runtime dependencies** in `saaf-core` or `saaf-js`.
4. **No raw values in logs, errors or audit.** Add a test when you touch those paths.
5. **No compliance claims** in code, docs or UI ("DPDP compliant" and similar). Say "evidence and safeguards".

## Setup

Requirements: Python 3.11+, Node 20+, [uv](https://docs.astral.sh/uv/) (recommended).

```bash
make setup          # uv sync --all-packages, npm install, pre-commit install
make test           # everything CI runs
make lint           # ruff, mypy, tsc
```

Without make:

```bash
uv sync --all-packages
npm install
python scripts/sync_spec.py --check
uv run pytest packages/saaf-core packages/saaf-gateway plugins bench
npm test --workspaces --if-present
```

## Workflow

- Branch from `main`; keep PRs small. Use Conventional Commit titles, with the plan task ID when there is one: `feat(core): P1-04 Hinglish context variants`.
- Fill in the PR template. Detector PRs paste benchmark deltas (`make bench`).
- One approving review. CODEOWNERS review is required for `spec/`, vault, audit, policy and release workflows.
- Add an entry under *Unreleased* in `CHANGELOG.md`.

## Changing the spec

See [docs/detector-spec.md](docs/detector-spec.md). In short: edit `spec/entities.json` → `python scripts/sync_spec.py` → add vectors → implement any new validator in both ports → run both suites and the benchmark.

## Benchmark contributions

New hand-written samples are very welcome (synthetic values only). Add them to `bench/corpus/community/` as JSONL with exact spans. Two maintainers review each sample before it is merged.

## Reporting false positives / negatives

Use the issue template. Include a synthetic reproduction and the `saaf scan --json` output (which contains no values).

## Security issues

Do not open public issues. See [SECURITY.md](SECURITY.md).

## Licence

By contributing, you agree that your contributions are licensed under Apache-2.0.
