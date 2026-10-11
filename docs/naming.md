# Naming (P0-1)

## Decision (11 October 2026)

| | Name | Notes |
|---|---|---|
| Company | **Safearly** | Domain: `safearly.com` |
| Product | **Saaf** | साफ़, "clean" in Hindi and Urdu. It shares the "Saf" of Safearly and says what the product does to prompts. |
| Full form | **Saaf by Safearly** | Use it on first mention; "Saaf" afterwards. |
| Tagline | *Clean prompts. Caught early.* | |

The working name before this decision was "Veil". It was dropped because it collides with a well-known penetration-testing framework, which would have muddied search results in exactly our category.

## Package names

| Surface | Name | Fallback if taken |
|---|---|---|
| Python import / CLI | `saaf` | — |
| PyPI (core) | `saaf` | `safearly-saaf` |
| PyPI (others) | `saaf-gateway`, `saaf-litellm`, `saaf-langchain`, `saaf-mcp` | `safearly-…` prefix |
| npm | `@safearly/saaf` | scoped to the org, so it can't be squatted |
| Container image | `ghcr.io/safearly/saaf-gateway` | — |
| GitHub | `safearly/saaf` | — |
| Environment variables | `SAAF_*` | — |
| HTTP headers | `x-saaf-*` | — |

## Still to check before launch

- [ ] Register the PyPI names (`saaf`, `saaf-gateway`, …) and the npm org `@safearly`. If `saaf` is taken on PyPI, switch the distribution name to `safearly-saaf`. The import name stays `saaf`.
- [ ] Create the GitHub org `safearly`.
- [ ] Trademark search for "Safearly" and "Saaf" in Class 9/42 (IP India public search + WIPO Global Brand Database).
- [ ] Defensive domains: `safearly.in`, `saaf.dev` (optional).
- [ ] Search-collision check for "saaf pii" and "saaf security". "SAAF" is also an air-force acronym, so always pair the name with "Safearly" or "PII" in titles and SEO.

Brand usage rules are in [brand.md](brand.md).
