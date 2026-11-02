---
name: validate-acceptance-letter
description: Check a draft Letter of Acceptance against the bid, the current GCC with its correction slips, and the powers of acceptance in force; optionally produce a clean draft.
requires: [validate]
autonomy: L2
tools: [search_knowledge, get_document]
inputs:
  letter_text: {type: text, label: Draft letter of acceptance}
  letter_date: {type: date, label: Letter date}
  acceptor: {type: text, label: Accepting authority (designation)}
  finance_vetted: {type: bool, label: Associate Finance vetting recorded}
  bid: {type: object, label: Bid facts from the tabulation statement (tender_no, value_cr, completion_months, offer_valid_until)}
  make_draft: {type: bool, label: Produce a clean draft from the template}
owner: Works procurement cell (named domain owner signs off every rule change)
---

# Validate a Letter of Acceptance

**When to use:** an officer has a tender committee recommendation and a draft
LOA and wants it checked before it goes for approval.

**How it works:** the model (or rules) extracts the letter's fields; coded
rules judge them; every finding cites the document and clause it relies on.

Checks, each a deterministic function in `validators/check.py`:

| Check | Rule | Source of truth |
|---|---|---|
| `tender_no_matches` | Letter's tender number equals the bid's | Bid tabulation |
| `value_matches` | Accepted value equals the bid value | Bid tabulation |
| `completion_matches` | Completion period equals the bid | Bid tabulation |
| `pg_terms_current` | PG percentage and submission days match clause 16.1 *as amended on the letter date* | GCC + correction slips (retrieved) |
| `acceptor_power` | Acceptor's power covers the value | Powers of acceptance in force (retrieved, never hard-coded) |
| `finance_vetting` | Vetting recorded when the value is above the vetting threshold | Same letter |
| `offer_validity` | Letter dated on or before the offer validity date | Bid |
| `slips_cited` | Letter cites GCC with the latest correction slip in force | Supersession graph |

The platform never issues or signs. Every draft carries the AI-assisted mark
and the officer's edits are measured.
