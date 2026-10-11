# BFSI pack (starter)

Targets KYC onboarding, loan documents, collections and support transcripts.

Planned for P3-03:
- Entities: CKYC number, loan account numbers (context-gated), cheque MICR, UTR/RRN as **hard negatives**, NACH/UMRN.
- Corpus: KYC forms, bank statements, salary slips, loan sanction letters (synthetic), each with gold spans.
- Evidence template: data-flow summary per product, processor list, retention per policy.
- Acceptance: pack recall >= 0.95 on its corpus, hard-negative FP < 1 per 1k tokens, design-partner sign-off.
