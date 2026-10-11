# Saaf filter for Open WebUI

Masks Indian PII before messages reach the model and restores it in replies, per chat.

Install: **Admin Panel → Functions → +**, paste [`saaf_filter.py`](saaf_filter.py), save, and enable it globally or per model. Open WebUI installs `saaf` from the `requirements` header.

Valves: `mode` (enforce/shadow), `block_entities` (e.g. `AADHAAR,PAN`), `allow_entities` (e.g. `IFSC`), `threshold`.
