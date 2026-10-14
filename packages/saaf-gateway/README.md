# saaf-gateway

An OpenAI- and Anthropic-compatible proxy. It masks Indian PII in requests before they reach the provider and restores it in responses, including streams.

```bash
pip install saaf-gateway
# until the first PyPI release:
pip install "saaf[crypto] @ git+https://github.com/physicsisawesome7/Saaf#subdirectory=packages/saaf-core" "saaf-gateway @ git+https://github.com/physicsisawesome7/Saaf#subdirectory=packages/saaf-gateway"
saaf-gateway --port 8787
# or, from the repository root:
docker build -f packages/saaf-gateway/Dockerfile -t saaf-gateway . && docker run -p 8787:8787 saaf-gateway
```

```python
OpenAI(base_url="http://localhost:8787/v1")  # /v1/chat/completions
Anthropic(base_url="http://localhost:8787")  # /v1/messages
```

| Env var | Default | |
|---|---|---|
| `SAAF_UPSTREAM_OPENAI` | `https://api.openai.com` | any OpenAI-compatible base URL |
| `SAAF_UPSTREAM_ANTHROPIC` | `https://api.anthropic.com` | |
| `SAAF_POLICY_DIR` | (unset) | `<tenant>.toml` per tenant |
| `SAAF_DEFAULT_POLICY` | (unset) | fallback policy file |
| `SAAF_TENANT_HEADER` | `x-saaf-tenant` | |
| `SAAF_AUDIT_LOG` / `SAAF_AUDIT_KEY` | (unset) | signed JSONL audit (types and counts only) |
| `SAAF_CORS_ORIGINS` | (unset) | browser origins allowed to call the gateway, e.g. `https://safearly.com` for the [playground](https://safearly.com/playground) |

Behaviour:
- A new masking session per request; tokens never cross requests or tenants.
- Only `authorization`, `x-api-key`, `openai-*` and `anthropic-*` headers are forwarded.
- A `block` policy returns HTTP 403 `{"error": {"type": "saaf_blocked", "entities": [...]}}`; the upstream is never called.
- Response headers: `x-saaf-entities: AADHAAR=1,PAN=1`, `x-saaf-mode`.
- Extra endpoints: `GET /healthz`, `GET /v1/saaf/entities`, `POST /v1/saaf/scan`.
