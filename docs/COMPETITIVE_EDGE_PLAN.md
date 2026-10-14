# Competitive edge plan: beating Presidio, NeMo Guardrails and the rest on Indian PII

**Date:** 12 October 2026. **Horizon:** 12 weeks. **Source of the facts below:** `reports/Saaf tools and viability audit.md` (private) plus dataset checks made on 12 Oct 2026.

**Bottom line.** "22 Indian identifiers with checksums" is not an edge. Presidio already validates Aadhaar with Verhoeff, and LiteLLM already restores masked PII. Saaf can still win, but only by being **measurably** better on things the others cannot fix in a weekend:

1. Names and addresses in Hinglish and Indian scripts.
2. Restore that survives streaming and tool calls.
3. Far fewer false alarms on look-alike numbers.
4. Speed and footprint.
5. Being present *inside* their ecosystems.
6. Regulator-mapped evidence.

Every claim must come from a benchmark that anyone can reproduce, run against the competitors at their best settings.

---

## 1. Where each competitor is structurally weak (verified)

| Competitor | What it already does well | Structural gap Saaf can own |
|---|---|---|
| **Presidio** (MIT, now under data-privacy-stack) | Aadhaar with Verhoeff; vehicle registration checksum; huge ecosystem; image redactor | India recognizers are **off by default and English-only**. GSTIN "validation" never computes the check character. **PAN has no validator.** There is **no UPI, IFSC, ABHA, Indian mobile or bank account** support. There is no Hinglish or Indic-script context and no OCR digit repair. Its spaCy dependency is heavy. |
| **NeMo Guardrails** (Apache-2.0, NVIDIA) | Rail framework; Presidio, GLiNER and Private AI backends; retrieval-stage masking | PII rails are **one-way, with no restore**. India coverage is whatever Presidio gives it. |
| **LiteLLM guardrails** | Presidio guardrail with `output_parse_pii` restore | Inherits Presidio's India gaps. **Streaming restore is undocumented; test it and publish the result.** |
| **LLM Guard** (MIT) | Anonymize → Vault → Deanonymize, with fuzzy matching | **Archived** after Palo Alto bought Protect AI; English and Chinese only. Its users need somewhere to go. |
| **GLiNER PII models** (Apache-2.0) | Strong zero-shot name, address and ID spans | **No checkpoint covers any Indian language.** The best ones are multilingual only across en, fr, de, es, it, pt and nl. |
| **Cloud DLP** (AWS Comprehend, Google SDP, Azure) | Aadhaar and PAN entity types, managed | Data leaves your network. Per-character pricing. No restore after the LLM, no Hinglish context, English-only for Comprehend. |
| **Protecto, Skyflow** | Funded; DPDP vault and masking sold in India | Closed and commercial. Saaf is open, self-hosted and benchmarked in public. |

## 2. The six edges and how each is proven

| # | Edge | Proof (a public, reproducible number) |
|---|---|---|
| E1 | **Out-measure:** own the reference benchmark | IndicPII-Bench v1 with tuned Presidio, NeMo, LiteLLM, LLM Guard, GLiNER-PII and AWS/Google reference rows |
| E2 | **Out-detect** names and addresses in Hinglish and Indian scripts | PERSON and ADDRESS recall ≥ 0.85 on the Hinglish and Devanagari slices, versus measured Presidio and GLiNER |
| E3 | **Out-restore:** streaming, tool calls, multi-turn | 100% restore under the mangling suite **and** under random streaming chunking, with competitors measured the same way |
| E4 | **Out-harden:** robustness to evasion | Recall under PyRIT and garak obfuscations (spacing, homoglyphs, superscript, bidi, Devanagari digits, transliteration) |
| E5 | **Out-run:** latency and footprint | p50/p99 ms per 1 KB, install size, cold start, versus Presidio with `en_core_web_lg` |
| E6 | **Be inside them:** distribution plus evidence | A `saaf-presidio` pack, a NeMo rail, an LLM Guard migration path, and evidence mapped to UIDAI Circular 14/2025 and RBI's draft model-risk rules |

### The scoreboard Saaf must win (fill in from the benchmark; targets are commitments)

| Metric (on held-out data) | Presidio tuned | NeMo + Presidio | LiteLLM + Presidio | GLiNER-PII | Saaf target |
|---|---|---|---|---|---|
| Strict micro-F1, structured Indian IDs | measure | measure | measure | measure | ≥ best + 5 pts |
| Hard-negative false positives per 1k tokens | measure | measure | measure | measure | ≤ 50% of best |
| PERSON/ADDRESS recall, Hinglish and Devanagari | measure | measure | measure | measure | ≥ 0.85 and ≥ best + 15 pts |
| Recall under obfuscation suite | measure | measure | measure | measure | ≥ best + 10 pts |
| Restore accuracy, streamed and mangled | n/a | **no restore** | measure | n/a | 100% |
| p99 latency per 1 KB (CPU) | measure | measure | measure | measure | ≤ 1/5 of Presidio |
| Install size | measure | measure | measure | measure | core < 1 MB; NER extra < 60 MB |

**Kill criterion (from the audit):** if tuned Presidio lands within about 3 F1 points on independent data and Saaf has no clear lead on rows 3–5, stop leading with accuracy. Reposition as the restore, evidence and integration layer on top of others' detectors.

## 3. Workstreams, deliverables and weeks

### E1 · Benchmark v1 with honest baselines (weeks 1–4)
- Adapters in `bench/indicpii_bench/adapters.py`:
  - **Presidio, in two configurations:** default, and tuned (all six India recognizers on, `en_core_web_lg`, context words added).
  - **NeMo Guardrails** with the Presidio and GLiNER rails.
  - **LiteLLM** with the Presidio guardrail and `output_parse_pii`.
  - **LLM Guard** Anonymize/Deanonymize.
  - **GLiNER-PII:** `urchade/gliner_multi_pii-v1` and `fastino/gliner2-privacy-filter-PII-multi`.
  - **AWS Comprehend and Google SDP** as optional reference rows.
- Add slices: structured IDs, look-alike numbers, Hinglish, Devanagari and Tamil scripts, OCR noise, obfuscation, streaming restore.
- **Publish the gaps neutrally,** with the code that shows them: Presidio's GSTIN, PAN and default-off findings.
- **Upstream decision:** send Presidio the small GSTIN check-character fix. Being a good open-source citizen earns credibility, and the fix is trivial for them anyway. Keep the hard parts (Hinglish context, OCR repair, streaming restore, NER) in Saaf.

### E2 · Indic name and address model (weeks 3–10), the largest real moat
- **Gap:** no GLiNER PII model covers Indian languages, and Presidio's NER is English spaCy.
- **Approach:**
  - **Teachers:** GLiNER-PII handles the English parts and IndicNER (MIT, 11 languages) handles Indic tokens; an LLM labels the hard Hinglish cases.
  - **Student:** a small multilingual encoder (MuRIL- or IndicBERT-class; check each licence), distilled and exported to ONNX at under 60 MB, behind the `[ner]` extra.
- **Train on:** Naamapadam (CC0); synthetic Hinglish and Indic sentences with names and addresses built from PIN-directory and place-name lists; and HiNER (CC BY-SA, kept as a separate eval because of share-alike).
- **Release:** the model on Hugging Face under Apache-2.0, with a model card covering data provenance, bias across regions and genders, and known failure modes.

### E3 · Restore superiority (weeks 2–5)
- Run every competitor that restores (LiteLLM, LLM Guard) under the same mangling and streaming-chunking harness, then publish the results.
- Add to Saaf:
  - cross-turn restore checks;
  - restore inside JSON tool-call **streams** (partial JSON);
  - LLM Guard-style fuzzy matching as an opt-in;
  - checksum-valid format-preserving fakes for every structured entity, not just Aadhaar and mobile.

### E4 · Robustness and red-team in CI (weeks 3–6)
- **PyRIT converters** generate obfuscated variants of every conformance vector. Track recall under obfuscation as a benchmark metric.
- **garak** runs encoding and low-resource-language buffs through the gateway's REST endpoint.
- **Promptfoo** runs `pii:direct`, `pii:session`, `pii:social` and `pii:api-db` against the gateway, nightly.
- **Every miss becomes a conformance vector,** so the regression gate keeps it fixed.

### E5 · Speed and footprint (weeks 2–4)
- Profile the detector; precompile one combined regex per canonical class; cache context matchers.
- Publish p50/p99 and install size next to Presidio's on the same hardware.

### E6 · Distribution inside their ecosystems (weeks 4–8)
- **`saaf-presidio`**: a pip pack registering Saaf's India recognizers (UPI, IFSC, ABHA, mobile, bank account, PAN validator, real GSTIN check) into any Presidio `AnalyzerEngine`. Every Presidio stack becomes a Saaf user.
- **NeMo Guardrails rail:** `saaf mask pii on input` / `saaf restore pii on output`, the first rail with restore. Submit it to the NeMo library or docs.
- **LLM Guard migration guide:** a drop-in Anonymize/Deanonymize equivalent for its now-orphaned users.
- **LiteLLM:** keep the guardrail current; add a docs comparison with the built-in Presidio guardrail.

### E7 · Documents and OCR (weeks 8–12)
- Run Tesseract or PaddleOCR on images and PDFs, then Saaf detection, then bounding-box redaction. Borrow Presidio's image redactor design.
- Use a synthetic card and form renderer for training and evaluation. **Never use real ID card images.**

### E8 · Evidence mapped to regulators (weeks 6–12)
- Evidence-pack templates mapped clause by clause to UIDAI Circular 14 of 2025 (Aadhaar Data Vault), RBI's draft model-risk principles (genAI inventory, vendor validation) and DPDP duties. Have counsel review them.
- None of the open-source competitors does this. It is also what a design partner can buy.

---

## 4. Data plan: what to collect, from where, and what never to scrape

### Principles
1. **Synthetic first.**
   - The structured IDs come from Saaf's own checksum generators.
   - Names, addresses and context come from open reference lists.
2. **Never scrape real personal data.**
   - No social-media profiles, leaked dumps, election affidavits or real ID images.
   - The DPDP Act, the Aadhaar Act's restrictions on publishing Aadhaar numbers, and the sites' own terms make this a legal and reputational risk.
3. **Licence-check every source before use,** and record it in `bench/corpus/PROVENANCE.md`.
   - Non-commercial data may be used for evaluation only, and only with permission; never for training.
4. **Aadhaar collisions:** a random Verhoeff-valid number can match a real person's.
   - Never pair generated numbers with realistic name and address sets in a published corpus.
   - Mark every file as synthetic, and get counsel's view before publishing at scale.
5. **Keep a private held-out split** of about 30%, rotated every release, so nobody overfits the public split, including us.

### Sources (licences checked on 12 Oct 2026 unless marked)

| Source | Use in Saaf | Licence | Verdict |
|---|---|---|---|
| [Naamapadam](https://huggingface.co/datasets/ai4bharat/naamapadam) (AI4Bharat) | Indic NER training: PERSON, LOC, ORG in 11 languages; 1–10M sentences, machine-annotated | **CC0-1.0** | **Use:** the main NER training base |
| [IndicNER](https://huggingface.co/ai4bharat/IndicNER) model | Teacher for Indic name spans | **MIT** | **Use** as teacher or baseline |
| [HiNER](https://huggingface.co/datasets/cfilt/HiNER-original) | Hindi NER evaluation | **CC BY-SA 4.0** | **Use for evaluation;** keep separate because of share-alike |
| [Nemotron-PII](https://huggingface.co/datasets/nvidia/Nemotron-PII) (NVIDIA) | English PII spans, 55+ types, 100k records; English-slice baseline and teacher data | **CC-BY-4.0** | **Use** (with attribution) |
| [Gretel synthetic PII finance](https://huggingface.co/datasets/gretelai/synthetic_pii_finance_multilingual) | Financial-document templates and structure ideas; 56k records, European languages | **Apache-2.0** | **Use** for templates; no Indian content |
| [AI4Privacy open-pii-masking-500k](https://huggingface.co/datasets/ai4privacy/open-pii-masking-500k-ai4privacy) | One of the few PII sets with **Hindi and Telugu** | **Non-commercial only;** commercial use needs a written licence | **Avoid for training.** Evaluation only with permission; ask partnerships@ai4privacy.com |
| [GLiNER PII models](https://huggingface.co/urchade/gliner_multi_pii-v1) (urchade, fastino, knowledgator) | Baselines and English teachers | **Apache-2.0** (`nvidia/gliner-PII` is "other") | **Use** |
| [Razorpay IFSC](https://github.com/razorpay/ifsc) | Every real IFSC code, bank and branch name, for realistic bank text | **MIT** | **Use** |
| [All India Pincode Directory](https://aikosh.indiaai.gov.in/home/datasets/details/all_india_pincode_directory_till_last_month_1.html) (India Post via data.gov.in / AIKosh) | Real PIN, post-office, district and state combinations for synthetic addresses | **GODL listed;** an older 2015 review said non-commercial | **Use** after confirming the current licence notice on data.gov.in |
| IndicCorp v2 (AI4Bharat) | Clean Indic-language text for context and hard negatives; 23 languages | **Not confirmed** (the card was cut off) | Check the licence first |
| L3Cube-HingCorpus | Real Hinglish (52.9M Roman-script sentences); context patterns | **Not confirmed;** scraped from Twitter | **Study only.** Don't redistribute; generate our own Hinglish instead |
| LinCE / GLUECoS Hindi-English NER | Code-mixed NER evaluation | **Not confirmed** | Check each licence; use for evaluation only |
| Kaggle "PII Data Detection" (Learning Agency Lab, 2024) | English student essays with surrogate PII; good false-positive realism | Governed by the competition rules (**not confirmed**) | Read the rules; evaluation reference only, probably non-commercial |
| UPI handle list (NPCI) | The known-PSP-handle validator | NPCI publishes participants; no clean list was found | Curate by hand from npci.org.in and refresh each quarter |
| State and RTO codes, GST state codes | Validators and generators | Official lists (CBIC, MoRTH) | Already in the spec; keep a dated source note |

### How the corpus gets built (the pipeline)
1. **Scenario templates.** Use an LLM to write Indian scenarios with placeholders, never real values: KYC chats, loan calls, hospital discharge notes, BPO tickets, WhatsApp-style Hinglish, legal notices. Have each template reviewed by a person. Target 2,000 templates across 8 domains and 4 language mixes: English, Hinglish, Hindi in Devanagari, and Tamil, Telugu or Bengali.
2. **Value fillers.**
   - **Structured IDs:** Saaf's own checksum generators.
   - **Names:** drawn from the Naamapadam entity lists, balanced by region and gender.
   - **Addresses:** built from PIN-directory combinations.
   - **Banks:** names and codes from the Razorpay IFSC data.
3. **Augmenters.** Transliteration (Roman ↔ Devanagari), Indic digits, spacing and hyphen variants, zero-width and homoglyph injection, OCR confusions, typos, PyRIT converters, and cross-turn splits.
4. **Hard negatives.** Order, AWB, UTR, invoice, PNR, IMEI and ticket numbers in realistic layouts, including ones that pass checksums by chance.
5. **Documents.** Render synthetic cards, forms and statements to images, then add scan noise, for the OCR track.
6. **Human gold set.** Have 2,000 to 3,000 samples written or corrected by paid annotators fluent in each language mix, in Label Studio or Argilla.
   - Use two annotators per sample, and publish the agreement score (target κ ≥ 0.8).
   - This becomes the held-out core that makes the benchmark credible.
7. **Community submissions.** Accept synthetic-only pull requests with a review checklist.
   - Design partners in shadow mode contribute only types and counts, never text.

**Scale targets for v1:** 10,000 public documents; a 3,000-document private held-out set; 200,000 NER training sentences, of which at least 30% are Hinglish or Indian-script.

---

## 5. Twelve-week timeline

| Weeks | Ships | Exit check |
|---|---|---|
| 1–2 | Pin CI actions to commit SHAs; Presidio, NeMo, LiteLLM and LLM Guard adapters; provenance file; licence checks done | Baselines run on corpus v0 |
| 3–4 | Benchmark v1 slices + 2,000 templates + human gold set started; latency harness; restore and streaming tests of competitors | First honest scoreboard (internal) |
| 5–6 | Red-team in CI (PyRIT, garak, Promptfoo); `saaf-presidio` pack; GSTIN upstream PR | Obfuscation recall tracked; pack on PyPI |
| 7–8 | NeMo rail; LLM Guard migration guide; NER student v0 | Rail merged or listed; NER v0 numbers |
| 9–10 | NER v1 (ONNX, under 60 MB); human gold set done (held-out) | Rows 3–5 of the scoreboard met, or the kill criterion triggered |
| 11–12 | OCR path v0; evidence templates for UIDAI and RBI; **publish benchmark v1 and the leaderboard** | Public launch of the results; 2–3 design partners shown the numbers |

**What it costs, roughly (estimates):**
- Annotation for 2,000–3,000 samples: about ₹3–6 lakh, at local annotator rates (verify quotes).
- GPU for distillation: a few hundred dollars of cloud credit.
- Everything else is engineering time.
