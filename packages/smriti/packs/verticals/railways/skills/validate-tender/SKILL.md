---
name: validate-tender
description: Check a notice inviting tender or bid document for mandatory annexures, the current GCC edition and slips, clause cross-references that resolve, and consistent dates.
requires: [validate]
autonomy: L2
inputs:
  tender_text: {type: text, label: Tender document text}
  notice_date: {type: date, label: Notice date}
---

# Validate a tender document

Deterministic checks (`validators/check.py`), configured by `checklist.yaml`
so a zone adds an annexure without a code change:

- every mandatory annexure in the checklist is present
- every "Clause X of GCC" reference resolves to a clause in the GCC in force
- the latest correction slip in force on the notice date is cited
- the bid closing date is after the notice date and at least the minimum
  period away
