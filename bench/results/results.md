| System | Strict micro F1 | Relaxed micro F1 | Hard-neg FP / 1k tokens | Restore round-trip | p50 ms | p99 ms | ms per KB | Cold start ms |
|---|---|---|---|---|---|---|---|---|
| saaf | 0.968 | 0.968 | 0.00 | 1.000 | 0.301 | 0.622 | 1.973 | 18.3 |
| regex-baseline | 0.571 | 0.571 | 236.95 | - | 0.038 | 0.079 | 0.253 | 0.7 |

Strict F1 by slice (recall in brackets):

| Slice | saaf | regex-baseline |
|---|---|---|
| bank_statement | 0.974 (1.00) | 0.646 (0.80) |
| hard_negative | - | 0.000 (0.00) |
| hinglish_chat | 1.000 (1.00) | 0.785 (0.86) |
| invoice | 1.000 (1.00) | 0.500 (1.00) |
| kyc | 1.000 (1.00) | 0.735 (0.70) |
| ocr_scan | 0.800 (0.67) | 0.144 (0.08) |
| support_ticket | 1.000 (1.00) | 0.642 (0.79) |

Per-entity (strict) for each system:

**saaf**

| Entity | P | R | F1 | Support |
|---|---|---|---|---|
| AADHAAR | 0.918 | 1.000 | 0.957 | 180 |
| BANK_ACCOUNT | 1.000 | 1.000 | 1.000 | 60 |
| CREDIT_CARD | 1.000 | 1.000 | 1.000 | 60 |
| DATE_OF_BIRTH | 1.000 | 1.000 | 1.000 | 60 |
| EMAIL | 1.000 | 1.000 | 1.000 | 60 |
| GSTIN | 1.000 | 1.000 | 1.000 | 120 |
| IFSC | 1.000 | 1.000 | 1.000 | 60 |
| PAN | 1.000 | 1.000 | 1.000 | 120 |
| PERSON | 1.000 | 0.500 | 0.667 | 120 |
| PHONE_IN | 1.000 | 1.000 | 1.000 | 120 |
| UPI_ID | 1.000 | 1.000 | 1.000 | 235 |

**regex-baseline**

| Entity | P | R | F1 | Support |
|---|---|---|---|---|
| AADHAAR | 0.168 | 0.744 | 0.274 | 180 |
| BANK_ACCOUNT | 0.000 | 0.000 | 0.000 | 60 |
| CREDIT_CARD | 0.606 | 1.000 | 0.755 | 60 |
| DATE_OF_BIRTH | 0.000 | 0.000 | 0.000 | 60 |
| EMAIL | 1.000 | 1.000 | 1.000 | 60 |
| GSTIN | 1.000 | 1.000 | 1.000 | 120 |
| IFSC | 1.000 | 1.000 | 1.000 | 60 |
| PAN | 1.000 | 0.792 | 0.884 | 120 |
| PERSON | 0.000 | 0.000 | 0.000 | 120 |
| PHONE_IN | 0.266 | 0.425 | 0.327 | 120 |
| UPI_ID | 1.000 | 1.000 | 1.000 | 235 |
