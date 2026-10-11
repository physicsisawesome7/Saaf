# What Saaf doesn't catch

Saaf reduces how much personal data reaches an LLM. It does not make a prompt "safe" or a workflow "compliant". Read this before you rely on it.

## Not detected, or detected unreliably

- **Names without an honorific.** "Lakshmi Iyer called" is missed; "Smt. Lakshmi Iyer" is caught. All-caps names on ID cards are missed (benchmark PERSON recall: 0.50). The Indic NER model (Phase 3) targets this.
- **Free-text addresses and other quasi-identifiers.** Street addresses, landmarks, employer + city + age combinations. PIN codes are caught only next to a "PIN"/"pincode" label.
- **Images, PDFs and scans** sent as files. Only the text you pass to Saaf is checked. Image OCR redaction is planned for Phase 3.
- **Numbers without context that pass a checksum by chance.** About 1 in 10 random 12-digit numbers passes Verhoeff. Without a label like "order" or "ref" nearby, such a number may be masked as an Aadhaar (a false positive, which is the safe direction).
- **Bank account numbers, PIN codes, dates of birth, passports, voter IDs and TANs without a label.** These formats are too generic to detect safely without context.
- **Spelled-out or obfuscated identifiers** ("two three four five…", base64, reversed). Planned as the P3-06 evasion work.
- **Identifiers split across messages.** The Python library detects simple cases when `cross_turn=True`. Earlier turns have already been sent and can only be reported, not recalled.
- **Non-Indian identifiers** beyond email, payment cards and common API keys.

## Behaviour to be aware of

- **Restore depends on the model echoing tokens recognisably.** Tolerant matching covers case, brackets, spacing, markdown and possessives. A model that paraphrases a token ("the first Aadhaar") cannot be restored.
- **Shadow mode changes nothing.** It is for measuring, not protecting.
- **The vault is personal data.** While the mapping exists, masked text is pseudonymised, not anonymised.
- **Thresholds trade recall for precision.** The default (0.5) favours catching more. Tune per entity in policy.

## Reporting a miss

Open a "False negative / false positive" issue with a **synthetic** reproduction. Never paste real personal data into an issue.
