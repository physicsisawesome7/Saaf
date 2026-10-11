# Competitor teardown (P0-3, to be filled in)

Goal: show, with reproducible evidence, where each competitor fails. Use the same 50 hand-written messy samples for every tool (`bench/corpus/handwritten/v0.jsonl`) and record versions.

Facts below come from the 6 October 2026 execution plan and the public pages it cites. **Re-verify each one when installing**; packages change quickly.

| Tool | Licence | What it claims | To verify | Version tested | Result |
|---|---|---|---|---|---|
| Armos | MIT | Aadhaar + PAN masking with restore; wraps OpenAI and Anthropic SDKs | streaming and async support (absent on the page reviewed) | | |
| svitch / pygovernor | Apache-2.0 | zero-dependency; Aadhaar, PAN, UPI, IFSC, mobile, GST, bank accounts; markets itself as "DPDP-compliant" | checksum depth; hard negatives; restore | | |
| bharat-pii | ? | regex + validation, Presidio adapter, CLI; PDF/OCR on roadmap | context handling; Hinglish | | |
| Vishwa-Mask | ? | hackathon proxy, reversible tokens, audit dashboard | maintenance status | | |
| Presidio + India recognizers | MIT | IN_AADHAAR, IN_PAN, IN_VOTER, IN_PASSPORT, IN_VEHICLE_REGISTRATION | Verhoeff use; weight/cold start | | |
| LLM Guard | MIT | Anonymize scanner (Presidio-based) | India coverage; latency | | |
| LiteLLM Presidio hook | MIT | pre-call masking across a fleet | streaming restore | | |
| Google SDP | commercial | built-in Aadhaar/PAN detectors, FPE | reference point only | | |

## Per-tool failure log template

```
Tool / version:
Install size / cold start:
Samples failed (ids) and why:
  - hn-003: masked order ID 234567890124 as Aadhaar (no checksum/context)
  - hi-011: missed Devanagari digits
Streaming restore: yes/no (evidence)
Restore under mangling: x/y
Notes for adapter (label mapping, thresholds):
```
