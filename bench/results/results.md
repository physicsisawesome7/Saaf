| System | Strict micro F1 | Relaxed micro F1 | Hard-neg FP / 1k tokens | Restore round-trip | p50 ms | p99 ms |
|---|---|---|---|---|---|---|
| saaf | 0.967 | 0.967 | 0.83 | 1.000 | 0.252 | 0.498 |
| regex-baseline | 0.571 | 0.571 | 236.95 | - | 0.038 | 0.101 |

Per-entity (strict) for each system:

**saaf**

| Entity | P | R | F1 | Support |
|---|---|---|---|---|
| AADHAAR | 0.918 | 1.000 | 0.957 | 180 |
| BANK_ACCOUNT | 1.000 | 1.000 | 1.000 | 60 |
| CREDIT_CARD | 0.984 | 1.000 | 0.992 | 60 |
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
