# saaf-presidio

Saaf's India recognizers for [Microsoft Presidio](https://github.com/microsoft/presidio).

Presidio's built-in India recognizers are off by default and English only. `IN_GSTIN` never computes the GSTIN check character, `IN_PAN` has no validator, and there is no UPI, IFSC, ABHA, Indian mobile or bank-account type. This pack runs Saaf's checksum-validated, Hinglish- and Indic-aware detector inside Presidio and reports results under Presidio-style names (`IN_AADHAAR`, `IN_PAN`, `IN_UPI_ID`, `IN_IFSC`, `IN_MOBILE`, ...).

```python
from presidio_analyzer import AnalyzerEngine
from saaf_presidio import add_saaf

analyzer = AnalyzerEngine()
add_saaf(analyzer.registry)  # replaces Presidio's IN_* recognizers
analyzer.analyze("mera adhaar २३४५ ६७८९ ०१२४ hai, UPI ravi@okaxis", language="en")
```

`add_saaf(registry, replace_builtin_india=False)` keeps Presidio's own India recognizers alongside. `SaafRecognizer(include_person=True)` also reports Saaf's labelled-name rule as `PERSON`.

On IndicPII-Bench v1, Presidio with this pack scores strict micro-F1 0.620, against 0.437 for Presidio with its own India recognizers turned on and tuned. See [`bench/results/v1`](../../bench/results/v1/README.md).
