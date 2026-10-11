# saaf-litellm

A LiteLLM proxy guardrail: masks before the call, restores after it (including streams).

```bash
pip install saaf-litellm
```

```yaml
# litellm config.yaml
guardrails:
  - guardrail_name: saaf
    litellm_params:
      guardrail: saaf_litellm.guardrail.SaafGuardrail
      mode: [pre_call, post_call]
      default_on: true
```

Set `SAAF_POLICY=/path/policy.toml` to use a policy file. A `block` decision raises an error that LiteLLM returns to the caller.
