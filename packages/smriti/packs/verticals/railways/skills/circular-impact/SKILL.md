---
name: circular-impact
description: When a circular or correction slip arrives, list the templates, tenders and SOPs it touches, with a proposed redline for each affected clause.
requires: [view]
autonomy: L1
inputs:
  document: {type: text, label: Circular or correction slip (reference, alias or document id)}
---

# Circular impact analysis

Uses the clause relations in the supersession graph: the new document
`modifies` clause X of a base document, and every template, tender or SOP that
`refers_to` clause X is affected. For each one the skill shows the base text,
the amended text and a word-level redline. Only documents the officer can open
are listed.
