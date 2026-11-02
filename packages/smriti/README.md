# Smriti by Safearly

**Permission-aware institutional memory.** Smriti (स्मृति, "memory") reads an organisation's own documents and the government sites it depends on. It keeps them fresh and versioned, and answers questions with verified citations. It runs on open-weight models the customer hosts, or on no model at all.

It is an implementation of the *Institutional Memory Platform: Development Plan* (29 Oct 2026). The MVP modules are Connect, Parse, Remember, Ask and Govern. It also ships parts of Watch, Act, Operate and Configure, plus the Indian Railways vertical pack.

```bash
pip install -e packages/smriti            # from the monorepo root; Saaf comes from the workspace
smriti --data-dir data serve --seed       # http://127.0.0.1:8000, demo tenant seeded on first start
```

Open the app, pick a person under **Viewing as**, and ask *"What is the period for submitting the performance guarantee under clause 16.1?"*. Then ask it again *as of 2024-06-01*. Switch to Asha and ask about the P-17 land schedule, or to Vikram (who sees it with owners masked) and Rakesh (who sees owners unmasked). Every document in the demo is **synthetic**.

## What is different

| | Typical enterprise RAG (Glean, Onyx, RAGFlow, Open WebUI) | Smriti |
|---|---|---|
| Versions | Latest file wins | Supersession and amendment graph. "As of" any date. Superseded text is never quoted as current. |
| Amendments | Base clause and correction slip are retrieved separately, if at all | A clause always comes with every slip in force on the date asked. The answer leads with the amended text. |
| Access | Usually one filter, or connector permission sync in a paid tier | Two enforcement points in code: a payload filter during search and a bulk re-check against the source of truth. Admins are not readers. The leakage suite runs in CI. |
| PII | Off, or all-or-nothing | Field-level masking by role. Land-owner names are masked for an engineer and visible to the land officer. The index holds masked text by default. Built on Saaf. |
| Wrong answers | Model output shown as is | Every sentence is checked against the passages it cites, including numbers. A failing model answer is replaced by a verified extractive one, or the system abstains and says what is missing. |
| Tables | The model adds up numbers | Totals are computed in code from source rows and cite the table. |
| Watching sources | Re-crawl and re-index | Change detection, a "what changed" note, and **circular impact**: a new slip lists every tender, template and SOP that cites the changed clause, filtered to what each reader may open. |
| Domain work | Chat only | Skills with coded validators. In the demo, planted-defect recall is 100% for both skills. Thresholds are retrieved from the document in force, never hard-coded. |
| Model | Hard-wired API | Any OpenAI-compatible server, routed per task. It also works offline with no model, so a sovereign install answers on day one. |

## Measured on the demo tenant

`smriti eval gate` runs these, and CI blocks a release on failure:

| Gate | Result |
|---|---|
| Golden set (14 questions: permission, superseded-version, Hindi, table, unanswerable, admin-is-not-a-reader traps) | 14/14, recall@10 1.0, MRR 1.0, abstention 1.0, citation precision 1.0 |
| Leakage suite (every person × every document they may not see × 3 probes) | 0 leaked chunks in 102 probes |
| Red team (direct, Hindi and indirect injection, role escalation, prompt extraction) | 6/6 stopped |
| LOA validator, planted defects | recall 1.0, 0 false alarms |
| Tender validator, planted defects | recall 1.0, 0 false alarms |

These numbers come from a small synthetic corpus with the built-in offline components. They show the gates work. They are not a claim about real-world accuracy, which must be measured on each customer's own golden set.

## Architecture

```
            ┌──────────── Watch (site adapters, file drops, RSS) ─────────────┐
            │  robots.txt · rate limits · conditional GET · change detection   │
            ▼                                                                  │
 files ──► Parse (router: PDF, Word, Excel, HTML, email, ZIP; garble/OCR flags) │
            ▼                                                                  │
         Remember: immutable blobs ─ Postgres/SQLite (docs, versions, chunks,  │
                   relations, tables, audit) ─ index (local or Qdrant)         │
            ▼                                                                  │
 question ► guard input (injection, Saaf PII) ► expand (glossary, Hindi)        │
            ► hybrid search with the access filter ► bulk re-check             │
            ► version rules + amendments ► rerank ► table maths / generate     │
            ► verify citations and numbers ► answer or abstain ► trace + audit │
            ▼                                                                  │
         Act: skills (extract → coded rules → explain) · drafts · approvals ◄──┘
```

| Concern | Built in (offline, zero GPUs) | Production (same code, set in `tenant.yaml` or env) |
|---|---|---|
| Relational store | SQLite | PostgreSQL (`SMRITI_DATABASE_URL`, CloudNativePG/Patroni for HA) |
| Vectors and keywords | numpy dense + BM25, filter-first | Qdrant named dense and sparse vectors with IDF, server-side RRF, int8 quantisation (`SMRITI_VECTOR_BACKEND=qdrant`) |
| Embeddings | `smriti-hash-v1` feature hashing (script-agnostic) | Qwen3-Embedding / BGE-M3 via any `/v1/embeddings` server (`models.embed`) |
| Reranker | lexical coverage, clause-aware | bge-reranker-v2-m3 / Qwen3 reranker via TEI `/rerank` (`models.rerank`) |
| Answer writer | verified extractive | Sarvam, Mistral, gpt-oss, DeepSeek or Qwen via vLLM/SGLang (`models.chat`). It falls back to extractive when verification fails. |
| Guard model | heuristic injection scoring | Granite Guardian, Qwen3Guard or Shieldstral (`models.guard`), consulted only when the heuristics are unsure |
| PII | Saaf (checksum-validated Indian IDs) plus labelled names and schema columns | same |
| Raw files | content-addressed local store | S3-compatible: SeaweedFS, Garage, Ceph (`SMRITI_BLOB_URL=s3://…`) |
| Schedules | in-process cron thread | Temporal workflows calling the same `run_source` |
| Identity | demo directory in `roles.yaml` | Keycloak OIDC claims through `Directory.from_claims`, or API tokens (`SMRITI_AUTH=token`) |
| Authorisation | `LocalAuthorizer` | OpenFGA or SpiceDB behind the same two methods |
| Malware scan | off | ClamAV INSTREAM (`SMRITI_CLAMD=host:port`) |

The API is stateless apart from the per-tenant local index. Replicas rebuild that index from the store and embedding cache on start, with no model calls. With Qdrant there is nothing to rebuild.

## Configuration: tenant packs

Each customer is a directory of YAML and Markdown. Platform defaults load first, then the vertical pack (`packs/verticals/railways`), then the tenant pack (`packs/tenants/railways-demo`). Later layers win.

```
tenant.yaml        models per task, retrieval knobs, retention, policy prompt, seed list
roles/roles.yaml   roles → grants, scope (division/project/class/type), unmask; demo users
sources/*.yaml     site adapters and file connectors (selectors, schedule, politeness, legal status, alert routing)
schemas/*.yaml     document types, classification keywords, PII-bearing columns
guardrails/*.yaml  input, retrieval, output and domain policies
glossary.yaml      abbreviations (LOA, GCC, PG…) and Hindi-English synonyms
skills/<name>/     SKILL.md + validators/*.py + templates/ + evals/cases.yaml
evals/             golden.yaml, redteam.yaml
```

`smriti validate-pack packs/tenants/railways-demo` checks a pack without starting anything.

## Interfaces

- **Web app** at `/`: Ask (streaming, evidence, verification, trace), Library (versions, diffs, supersession graph, "why can't X see this"), Watch, Skills (validators, drafts, maker-checker approval), Memory, Govern (audit chain, release gates, role simulator).
- **REST** under `/api`. OpenAPI docs are at `/api/docs`.
- **OpenAI-compatible** `POST /v1/chat/completions` with model `smriti/<tenant>`. Any chat client or IDE plugs in, and the answer carries its sources.
- **MCP**: `smriti mcp --as <user>` exposes `search_knowledge`, `ask_question` and `get_document` with the caller's permissions fixed at start.
- **CLI**: `seed`, `ingest`, `crawl`, `ask`, `eval`, `audit-verify`, `validate-pack`.

## Deploy

`deploy/docker-compose.yml` runs Smriti with PostgreSQL and Qdrant. A commented `vllm` service shows the GPU profile. The same image fits the single-server appliance, Kubernetes (Helm values follow the compose services) and air-gapped installs, since nothing calls out unless a model route says so.

## Honest limits of this build

- OCR for scanned pages, Docling layout parsing and speech-to-text are plug-in points (`parsers.EXTERNAL_PARSERS`), not bundled. Scanned pages are flagged low-confidence and queued.
- Keycloak, OpenFGA and Temporal integrations are interfaces with local implementations. The adapters still need to be written against a live deployment.
- The offline extractive writer is faithful but terse. Fluent drafting needs a configured model, which is then held to the same verification.
- Licences of any model you configure must be checked before shipping (see `models.licence_register`).
