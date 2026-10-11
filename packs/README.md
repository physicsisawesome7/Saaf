# Sector packs

A sector pack bundles domain knowledge a generic tool will not have:

1. **Entity definitions**: extra identifiers and context words for the sector (added to `spec/entities.json` behind the pack's `enabled_entities`, or as a pack-local spec overlay in Phase 3).
2. **Default policy**: which entities to mask, block or allow, per destination.
3. **Test corpus**: synthetic documents typical of the sector, with gold spans, scored by IndicPII-Bench.
4. **Evidence template**: what an auditor in that sector asks for.

| Pack | Phase | Status |
|---|---|---|
| `bfsi` (KYC, loan documents) | 3 (P3-03) | starter policy |
| `health` (ABHA, lab reports) | 4 (P4-05) | planned |
| `hr` (background verification) | 4 (P4-05) | planned |
| `legal` | later | planned |

Packs are part of the commercial tier (ADR 0003). This directory holds the open starter material.
