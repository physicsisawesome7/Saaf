# Saaf development plan

**Source:** *Saaf — Execution Plan* (6 October 2026). This document turns that plan into engineering work: phases, epics, tasks, acceptance criteria, gates, process and quality bars.
**Status as of 7 October 2026:** Phase 0 is in progress. The repository scaffold, the engine and the first version of every surface exist and pass their tests (see §2).
**Owner:** engineering lead. Review this document at every phase gate.

---

## 1. What we are building, in one paragraph

Saaf is an India-first PII firewall for LLM traffic. It detects Indian identifiers (Aadhaar, PAN, GSTIN, UPI, mobile, bank and card numbers, ABHA, EPIC and others), validates them with checksums and structure rules, masks them with reversible tokens before a prompt leaves the organisation, and restores them in the model's reply, including streamed replies. It ships as a zero-dependency library (Python and TypeScript), an OpenAI- and Anthropic-compatible gateway, plugins for the places teams already work (LiteLLM, Open WebUI, LangChain, MCP, Claude Code, n8n, a browser extension), and a console. **We compete on accuracy and evidence, not on "India support".** The open IndicPII-Bench benchmark is how we prove that, and it is also the kill gate.

## 2. Where the repository stands today

| Area | State on 7 Oct 2026 | Location |
|---|---|---|
| Declarative detector spec (22 entity types, P0 + P1) | Done, v0.1.0 | `spec/entities.json` |
| Shared conformance vectors (validators, detection, restore) | 98 vectors; both ports pass | `spec/conformance/` |
| Python engine: normalize, validate, context, OCR repair, overlap, policy, tokens, vaults, tolerant restore, streaming, cross-turn, audit, evidence, CLI | Done, 177 tests incl. Hypothesis property tests, ruff + mypy strict clean | `packages/saaf-core` |
| TypeScript port: detection, policy subset, mask/restore, streaming | Done, 105 tests | `packages/saaf-js` |
| Gateway: OpenAI + Anthropic compatible, streaming restore, per-tenant policy, signed audit | Done (v0), 10 tests | `packages/saaf-gateway` |
| LiteLLM guardrail, Open WebUI filter, LangChain, MCP server, Claude Code hook | Done (v0), tested | `plugins/*` |
| Browser extension (warn and mask on submit) | v0, manual testing only | `plugins/browser-extension` |
| n8n node | Scaffold, not built in CI | `plugins/n8n-node` |
| Website safearly.com: a minimal single page with the live demo, security, pricing and FAQ; brand assets | v2, verified in a browser (light/dark, mobile) | `apps/website` |
| IndicPII-Bench: generator, harness, corpus v0 (420 docs) | v0; first results below | `bench/` |
| Console, benchmark site | Not started (Phases 3–4) | `apps/console`, `apps/bench-site` |
| CI, release signing, SBOM, CodeQL, Dependabot, templates | Configured, not yet run on GitHub | `.github/` |

**First benchmark result (corpus v0, synthetic only, so treat it as a smoke test):** Saaf strict micro-F1 0.967 against 0.571 for a bare-regex baseline. Hard-negative false positives were 0.83 per 1,000 tokens against 236.95. Restore round-trip under mangling was 100%. The benchmark already found and fixed one real bug: negative context leaked across lines and suppressed every phone number in KYC forms. The property tests found two more: a closing `]` could leak during streaming restore, and restore returns the first-seen spelling of a value (now documented and tested as intended behaviour). The remaining gaps are honest ones. PERSON recall is 0.50, because all-caps names on ID cards are missed. AADHAAR precision is 0.918, because 12-digit UTR and AWB numbers pass Verhoeff by chance when there is no context. These two gaps are the first targets for Phase 1.

## 3. Principles that decide trade-offs

1. **Evidence over claims.** Every accuracy claim must cite a reproducible benchmark run. We never say "compliant"; we say "evidence and safeguards".
2. **One spec, many ports.** Detectors are data (`spec/entities.json`) plus named validators. Python and TypeScript must pass the same conformance vectors. A detector change without a vector is incomplete.
3. **Zero runtime dependencies in the core.** Optional extras: `[crypto]`, `[redis]`, `[ner]`, `[ocr]`. The core install must stay under 200 KB.
4. **Raw values never leave the process in logs, audit records, errors or telemetry.** Tests assert this.
5. **Safe defaults.** The vault is in memory by default. Persistence is encrypted or refused. TTLs are on by default. Shadow mode makes adoption cheap.
6. **Small team, so every phase has a gate and a cut list.** When a phase runs late, cut scope and keep the date.

## 4. Team and ownership (assumed)

| Role | Owns | Allocation |
|---|---|---|
| Eng lead / detection | spec, saaf-core, saaf-js, benchmark, NER (Phase 3) | 1.0 |
| Full-stack engineer | gateway, plugins, extension, playground, console | 1.0 |
| Founder / GTM | design partners, teardown interviews, legal wording, pricing discovery | 0.5 |
| External | vault cryptography review (Phase 4), lawyer review of public wording (Phase 2) | contract |

If the team is one person, follow the **cut lists**. Do not stretch the timeline.

## 5. Timeline at a glance

Weeks are Monday–Friday. Week 1 starts on 12 October 2026.

| Phase | Weeks | Dates | Ships | Gate (must be true to continue) |
|---|---|---|---|---|
| 0 · Decide | 0–1 | 7–16 Oct | Name/licence check, threat model, teardown of 5 competitors, design-partner list | Teardown notes show where each competitor fails |
| 1 · Engine + benchmark v0 | 1–4 | 12 Oct – 6 Nov | P0 detectors hardened, tolerant restore, vaults, CLI, corpus v0 + hand-written set, harness with competitor adapters | **Beats the best open-source tool on hard-negative FPs and on messy-text recall** (kill gate) |
| 2 · Gateway + launch | 5–8 | 9 Nov – 4 Dec | Gateway GA (streaming, async), LiteLLM + Open WebUI plugins, playground, bench v1, launch post | Public launch; 3 design partners agree to shadow mode |
| 3 · Surfaces + depth | 9–14 | 7 Dec – 15 Jan | Browser extension in stores, Console v1, BFSI pack, Indic NER v0, OCR repair v2 | Partners see real findings in shadow mode |
| 4 · Enterprise | 15–24 | 18 Jan – 26 Mar 2027 | SSO/RBAC, encrypted vault backends GA, signed audit + evidence pack, crypto review, health + HR packs | First paid pilot |
| Buffer | 25–31 | 29 Mar – 12 May 2027 | Hardening, pilots → contracts | DPDP baseline obligations on **13 May 2027** |

The DPDP baseline date is 13 May 2027. If MeitY compresses the timeline (reports pointed at November 2026; this was not confirmed), pull the launch into week 6 by cutting Phase 2 scope as listed in §6.3.

## 6. Phase plans

Task IDs are referenced in issues and PR titles (for example `feat(core): P1-04 Hinglish context`). Estimates are ideal engineer-days (d).

### 6.1 Phase 0 · Decide (7–16 Oct)

| ID | Task | Owner | Est | Acceptance criteria |
|---|---|---|---|---|
| P0-1 | Name and licence check: brand decided (Saaf by Safearly, safearly.com); still to do: register PyPI/npm names and run a trademark search | GTM | 1d | `docs/naming.md` decision recorded; package names reserved; rename script run if needed |
| P0-2 | Repository skeleton, CI, conformance-vector format | Eng | — | **Done** in the scaffold; CI green on first push |
| P0-3 | Competitor teardown: install Armos, pygovernor/svitch, bharat-pii, Presidio (India recognizers), LLM Guard; run 50 hand-built messy samples | Eng | 3d | `docs/competitor-teardown.md` filled in; adapters in `bench/indicpii_bench/adapters.py`; per-tool failure table |
| P0-4 | Threat model v1 reviewed | Eng | 1d | `docs/threat-model.md` reviewed by both engineers; open items filed as issues |
| P0-5 | 8–10 design-partner targets (fintech, health, legal, BPO); outreach offering a shadow-mode pilot | GTM | 2d | `docs/design-partners.md` (private copy) with status per target |
| P0-6 | 50 hand-written messy samples (Hinglish, OCR, split numbers, hard negatives) | Eng + GTM | 2d | `bench/corpus/handwritten/v0.jsonl`, each sample reviewed by two people |

**Exit:** a teardown table that shows where each competitor fails, and a naming decision.

### 6.2 Phase 1 · Engine and benchmark v0 (12 Oct – 6 Nov)

**Goal:** be measurably better than the best open-source option on the two metrics that matter, false positives on hard negatives and recall on messy text, and prove it reproducibly.

| ID | Epic / task | Est | Acceptance criteria |
|---|---|---|---|
| P1-01 | Validators complete for P0 entities (Verhoeff, Luhn + IIN, PAN, GSTIN check char, IFSC, UPI handles, mobile, state codes) | — | **Done**; each has ≥3 vectors (valid, invalid, edge) |
| P1-02 | Normalization: NFKC, zero-width, homoglyphs, Indic digits, dashes, with offset map | — | **Done**, with Hypothesis property tests (offset map monotonic and in bounds, spans valid, no crash on arbitrary text) |
| P1-03 | Context scoring: nearest label wins, negative context clipped to the clause | — | **Done** (bug found by the benchmark); add 20 vectors from the teardown |
| P1-04 | Hinglish and Hindi context coverage: spelling variants (aadhar/adhaar/aadhaar no), Devanagari keywords, Romanised Hindi ("mera", "khata") | 2d | Recall on the Hinglish slice ≥ 0.95 with no hard-negative regression |
| P1-05 | AADHAAR precision on 12-digit UTR/AWB/order numbers: transaction-row heuristics (`UPI/…/`, `NEFT-`, column layouts) as negative context | 2d | AADHAAR precision ≥ 0.97 on corpus v0 |
| P1-06 | OCR repair v1 (O/0, I/1, S/5, B/8; shape-based for PAN) | — | **Done**; extend with G/6, Z/2, T/7 behind a flag, measured on the OCR slice |
| P1-07 | Tolerant restore (case, brackets, spaces, markdown, possessives, JSON) + hallucinated or missing token policy | — | **Done**; round-trip ≥ 99.5% under the mangling suite |
| P1-08 | Streaming buffer | — | **Done**; property test passes: any chunking gives output identical to non-streamed restore |
| P1-09 | Vaults: in-memory (TTL), SQLite + Redis (AES-GCM, HMAC lookup, crypto-shredding) | — | **Done**; add a key-rotation design note (Phase 4 implementation) |
| P1-10 | CLI `saaf scan / mask / restore / validate / audit / evidence` + pre-commit hook | — | **Done**; document it in the README |
| P1-11 | Corpus v0: synthetic generator (6 domains + hard negatives) **plus** the hand-written set (P0-6) **plus** a private held-out split | 3d | Held-out split stored outside git (encrypted bucket); generator deterministic by seed |
| P1-12 | Harness: per-entity P/R/F1 strict and relaxed, hard-negative FP/1k tokens, restore round-trip, latency, install size, cold start | 2d | `indicpii-bench run` reproduces published numbers byte-for-byte from a seed |
| P1-13 | Competitor adapters (from P0-3) | 3d | All five tools scored on the public and held-out splits |
| P1-14 | Performance budget | 1d | p99 < 2 ms per 1 KB of text (CPython 3.12, laptop CPU); a regression > 20% fails CI |

**Kill gate (6 Nov).** Compare against the best open-source tool from P1-13 on the held-out split:
- hard-negative false positives per 1k tokens: **Saaf ≤ 50% of the best competitor**;
- recall on the messy slices (Hinglish, OCR, Indic digits, spaced/zero-width): **Saaf ≥ best + 10 points**.

**If the gate fails:** stop and rethink. The fallback is to become the integration and evidence layer (gateway, plugins, audit, console) on top of someone else's detectors. The adapters in `bench/` make that switch cheap.

**Cut list (in order):** P1-06 extensions → P1-14 CI enforcement (keep the measurement) → P1-04 Devanagari keywords beyond Aadhaar/PAN.

### 6.3 Phase 2 · Gateway and launch (9 Nov – 4 Dec)

| ID | Task | Est | Acceptance criteria |
|---|---|---|---|
| P2-01 | Gateway hardening: connection pooling, timeouts, retries pass-through, request size limits, structured logs without values, `/metrics` (Prometheus) | 3d | Load test: 200 rps, p99 overhead < 10 ms on 4 KB prompts |
| P2-02 | Gateway coverage: Responses API, embeddings, tool calls in streams, `n > 1`, Anthropic tool_use streaming | 3d | Contract tests recorded from real APIs (VCR cassettes with keys scrubbed) |
| P2-03 | OpenTelemetry export of audit events (types and counts) | 1d | Spans and events visible in a local collector |
| P2-04 | Docker image (non-root, distroless or slim), Helm chart, docker-compose example | 2d | `docker run` → working proxy in < 1 minute; image signed with cosign |
| P2-05 | LiteLLM guardrail: test against a real LiteLLM proxy; publish | 1d | Listed in the LiteLLM docs PR |
| P2-06 | Open WebUI filter: publish on the community site | 0.5d | Install counts tracked |
| P2-07 | Playground: share links (state in the URL fragment, never sent to a server), the benchmark samples, a "what it doesn't catch" panel | 2d | Lighthouse ≥ 95; works offline once loaded |
| P2-08 | Benchmark v1: hand-written + community submissions, leaderboard JSON, methodology page | 3d | `apps/bench-site` renders `results.json`; reproduction steps verified by someone outside the team |
| P2-09 | Launch: blog post, README, docs site, Show HN / FOSS United / Indian dev communities, lawyer review of public wording | 3d | Launch checklist in `docs/release-process.md` complete |
| P2-10 | Design partners: 3 in shadow mode via the gateway or LiteLLM | GTM | Signed pilot letters; weekly findings call scheduled |

**Gate (4 Dec):** public launch done; 3 design partners running shadow mode.
**Cut list (in order):** P2-03 → P2-04 Helm (keep Docker) → P2-07 share links → P2-02 Responses API.
**If DPDP is compressed:** launch in week 6 with P2-01, P2-05, P2-07 (core only) and P2-09, and push the rest into Phase 3.

### 6.4 Phase 3 · Surfaces and depth (7 Dec – 15 Jan)

| ID | Task | Est | Acceptance criteria |
|---|---|---|---|
| P3-01 | Browser extension: Chrome + Edge store listing, Firefox port, per-site selector config served as a signed JSON update, Playwright smoke tests against recorded DOM snapshots | 5d | Store approval; warn-and-mask works on ChatGPT, Claude and Gemini; selector breakage alert within 24 h |
| P3-02 | Console v1: policy editor (TOML with validation and diff), shadow-mode feed (types and counts only), false-positive triage that exports conformance vectors, audit and evidence export, vault TTL controls, team access | 10d | A design partner configures a policy without help |
| P3-03 | BFSI sector pack: KYC and loan-document entities, default policy, test corpus, evidence template | 4d | Pack recall ≥ 0.95 on its own corpus; partner sign-off |
| P3-04 | Indic NER v0 for names and addresses: distilled model, ONNX, < 50 MB, trained on synthetic Indian names/addresses plus open Indic NER datasets (**licence verified per dataset**) | 8d | PERSON recall ≥ 0.85 on the hand-written set; p99 < 15 ms per 1 KB on CPU; behind the `[ner]` extra |
| P3-05 | OCR repair v2 and image/PDF path: bounding-box redaction for Aadhaar card uploads (`[ocr]` extra) | 4d | Masks the 12-digit number on 20 sample card images |
| P3-06 | Cross-turn detection v2 (TS port; spelled-out digits in English and Hindi; base64; reversed strings) as the red-team corpus | 3d | Evasion slice added to the benchmark |
| P3-07 | n8n node published; LlamaIndex postprocessor | 2d | Listed in the n8n community nodes |

**Gate (15 Jan):** partners see real findings in shadow mode (at least one "we didn't know that was happening" finding per partner).
**Cut list:** P3-07 → P3-06 → Firefox port → P3-05 image path (keep OCR text repair).

### 6.5 Phase 4 · Enterprise (18 Jan – 26 Mar 2027)

| ID | Task | Est | Acceptance criteria |
|---|---|---|---|
| P4-01 | SSO (OIDC/SAML) and RBAC in the console and gateway admin API | 6d | Okta and Azure AD tested |
| P4-02 | Vault backends GA: KMS-backed key providers (AWS KMS, GCP KMS, Vault Transit), key rotation, per-tenant crypto-shredding runbook | 5d | Rotation without downtime; shred verified by test |
| P4-03 | Signed audit GA: Ed25519 signatures (in addition to HMAC), external anchoring of the hash chain, evidence pack v1 (data-flow summary, processor list, retention configuration) | 4d | Third party verifies a log with the public key only |
| P4-04 | **External review of the vault cryptography** before any enterprise pitch | contract | Report published; all high findings fixed |
| P4-05 | Health pack (ABHA, lab reports) and HR/background-verification pack | 6d | Same bar as P3-03 |
| P4-06 | On-prem deployment guide, air-gapped install, support runbooks | 3d | Partner installs without our help |
| P4-07 | Pricing from design partners (do not guess) | GTM | Paid pilot signed |

**Gate (26 Mar):** first paid pilot.

## 7. Workstream view

| Workstream | P0 | P1 | P2 | P3 | P4 |
|---|---|---|---|---|---|
| Detection | spec format | P0 detectors, OCR v1, context | Hinglish depth | NER v0, OCR v2, evasion | packs |
| Benchmark | teardown | corpus v0, harness, gate | v1, site, launch | evasion slice | packs' corpora |
| Gateway | — | — | GA | console API | SSO/RBAC, KMS |
| Plugins | — | CLI, pre-commit | LiteLLM, Open WebUI | extension, n8n | — |
| UI | — | — | playground | console v1 | console enterprise |
| Trust | threat model | no-raw-values tests | SBOM, signing, wording review | selector update signing | crypto review, Ed25519 |
| GTM | partner list | outreach | launch, 3 shadow pilots | findings reviews | paid pilot |

## 8. Engineering process

**Branching:** trunk-based. Short-lived branches off `main`, squash-merge, linear history. `main` is always releasable.

**Commits and PRs:** Conventional Commits (`feat(core):`, `fix(gateway):`, `docs:`, `bench:`) with the task ID when one exists. Every PR uses the template checklist: tests, vectors for detector changes, docs, changelog entry, and no raw PII in fixtures beyond the synthetic test set.

**Reviews:** one approving review. Changes to `spec/`, `vault.py`, `audit.py`, `policy.py` or the release workflows need a CODEOWNERS review.

**Versioning:**
- Packages follow SemVer independently: `saaf`, `@safearly/saaf`, `saaf-gateway` and the plugins.
- `spec_version` in `entities.json` follows SemVer too: adding an entity is a minor change; changing a score that alters default detections is a minor change, noted in the changelog with benchmark deltas; renaming an entity id is a major change.
- Until 1.0, minor versions may break APIs; every break is noted in `CHANGELOG.md`.

**Releases:** tag `core-v0.2.0`, `js-v0.2.0`, `gateway-v0.2.0` and so on → the `release.yml` workflow builds, tests and publishes with PyPI Trusted Publishing (attestations) and npm provenance, attaches a CycloneDX SBOM, and signs the container image with cosign. Release cadence is every two weeks during Phases 1–3. See `docs/release-process.md`.

**Definition of done:**
1. Code, tests and docs merged; CI green on Linux, macOS and Windows for Python 3.11–3.13 and Node 20/22.
2. Detector changes include conformance vectors and a benchmark run with deltas pasted into the PR.
3. No new runtime dependency in `saaf-core` or `saaf-js`.
4. A test proves that the new code never logs, returns or stores raw values where it should not.
5. `CHANGELOG.md` updated.

## 9. Testing strategy

| Layer | Tooling | Where | Gate |
|---|---|---|---|
| Unit | pytest, node:test | each package | every PR |
| Conformance (cross-port) | shared JSONL vectors | `spec/conformance` | every PR; both ports must pass |
| Spec drift | `scripts/sync_spec.py --check` | CI | every PR |
| Property-based | Hypothesis (offset mapping, streaming equals batch, mask→restore identity) | `packages/saaf-core/tests` | every PR (P1-02, P1-08) |
| Fuzz | Atheris on normalize, detect, restore | nightly | crashes block release |
| Benchmark regression | `indicpii-bench` on corpus v0 + held-out | nightly + PRs labelled `detector` | micro-F1 −0.5 pt or hard-negative FP +10% blocks merge |
| Gateway contract | httpx MockTransport today; VCR cassettes from real APIs in P2-02 | `packages/saaf-gateway/tests` | every PR |
| Extension e2e | Playwright against recorded DOM snapshots + a weekly live smoke test | `plugins/browser-extension/tests` | weekly; alert on failure |
| Performance | pytest-benchmark | CI | > 20% regression fails |

## 10. Quality bars

| Metric | Bar | Today |
|---|---|---|
| Hard-negative false positives | < 1 per 1k tokens | 0.83 (v0 synthetic) |
| Strict micro-F1, P0 entities | ≥ 0.97 | 0.967 overall (P0 only: higher) |
| Restore round-trip under mangling | ≥ 99.5% | 100% (v0) |
| Streaming correctness | 100% (property test) | Hypothesis: 150 random texts x chunkings pass |
| Latency | p99 < 2 ms per 1 KB | p99 0.51 ms per doc (v0) |
| Core install size | < 200 KB, zero dependencies | zero dependencies |
| Coverage | ≥ 85% lines on core | enforced in CI |

## 11. Security and trust plan

- **Threat model:** `docs/threat-model.md`, reviewed at each phase gate.
- **Supply chain:** GitHub Actions pinned to full commit SHAs before the first public release (Dependabot keeps them current), CodeQL, OpenSSF Scorecard, CycloneDX SBOM per release, PyPI attestations, npm provenance, cosign-signed images.
- **Data handling:** no raw values in logs, audit or errors (tested); vault in memory by default; encrypted persistence required; TTLs; crypto-shredding.
- **Disclosure:** `SECURITY.md` with a private reporting channel and 90-day coordinated disclosure.
- **Before any enterprise pitch:** an external review of the vault cryptography (P4-04).
- **Wording:** "evidence and safeguards", never "DPDP compliant"; lawyer review before launch (P2-09).

## 12. Metrics we track

- **Quality:** benchmark numbers per release (published), false-positive triage rate from partners, time to fix a reported miss.
- **Adoption:** PyPI and npm downloads, Docker pulls, extension installs, GitHub stars and contributors, community benchmark submissions.
- **Business:** design partners in shadow mode, findings per partner per week, pilots, then paid pilots.

## 13. Risk register

| Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|
| False sense of security | High | High | `docs/limitations.md`, limits in the README and in the playground, shadow-mode reports show what is *not* covered | Eng lead |
| Vault is a concentrated PII store | Medium | High | In memory by default, encrypted persistence, TTL, crypto-shredding, external crypto review | Eng lead |
| Compliance overclaim | Medium | High | Fixed wording, lawyer review, no "compliant" in any artifact (CI grep) | GTM |
| Fast followers (Armos adds streaming) | High | Medium | The moat is the benchmark, Indic depth and sector packs, not single features | All |
| Benchmark overfitting | Medium | High | Private held-out split, community samples, rotate the held-out split each release | Eng lead |
| Extension upkeep as sites change | High | Medium | Selector config as signed remote JSON, weekly live smoke test, budget 0.5 d/week | Full-stack |
| Name unavailable on PyPI or trademark conflict for "Saaf" | Medium | Medium | Fallback `safearly-saaf` distribution name (import stays `saaf`); trademark search in P0-1 | GTM |
| DPDP timeline compression | Medium | Medium | Week-6 launch plan (§6.3) | GTM |
| NER dataset licensing | Medium | High | Licence check per dataset before training; record provenance in the model card | Eng lead |
| Python/TS port drift | Medium | Medium | Shared vectors + spec drift check in CI | Eng lead |

## 14. The next 7 days (7–16 Oct)

- [ ] Push the scaffold to GitHub; confirm CI is green on all three operating systems (P0-2).
- [ ] Install and run Armos, pygovernor/svitch, bharat-pii, Presidio and LLM Guard against 50 hand-built messy samples; log failures in `docs/competitor-teardown.md` (P0-3, P0-6).
- [ ] Decide the name: check PyPI, npm and domains; reserve packages (P0-1).
- [ ] Review the threat model together (P0-4).
- [ ] Start P1-05 (AADHAAR precision on UTR/AWB) and P1-04 (Hinglish), the two gaps the first benchmark run exposed.
- [ ] Contact 8–10 design-partner targets with a shadow-mode pilot offer (P0-5).

## Appendix A · Repository map

```
spec/                     canonical detector spec + JSON schema + conformance vectors
packages/saaf-core/       Python engine + CLI (zero dependencies)       -> PyPI: saaf
packages/saaf-js/         TypeScript port (Node + browser)              -> npm: @safearly/saaf
packages/saaf-gateway/    OpenAI/Anthropic-compatible proxy             -> PyPI + container image
plugins/                  litellm, open-webui, langchain, mcp-server, claude-code-hook,
                          browser-extension, n8n-node
apps/website/             safearly.com (static, single page with live demo)
apps/console/             Phase 3
apps/bench-site/          Phase 2
bench/                    IndicPII-Bench generator, harness, corpus v0, results
packs/                    sector packs (BFSI first)
examples/                 policies, quickstarts, docker-compose
docs/                     this plan, architecture, threat model, limitations, ADRs, ...
scripts/                  spec sync, dev helpers
```

## Appendix B · Source

Execution plan (6 October 2026), sections 1–10, including the competitive scan (Armos, svitch/pygovernor, bharat-pii, Vishwa-Mask, LiteLLM + Presidio, Google SDP, Skyflow, AuthBridge) and the DPDP timing notes. Package details found then (for example, Armos's lack of streaming support) may have changed; re-verify them in P0-3.
