# Policy reference

Policies are TOML (or JSON) files. The gateway loads `<policy_dir>/<tenant>.toml` per tenant; the library takes `Policy.load(path)`; the CLI takes `--policy`.

```toml
[policy]
id = "bfsi-default"          # recorded (with a fingerprint) in every audit record
mode = "enforce"             # "enforce" or "shadow" (observe only, change nothing)
threshold = 0.5              # minimum detection score
default_action = "mask"      # mask | hash | block | warn | allow
token_style = "label"        # label [PAN_1] | hmac [PAN_3fa2b1c9] | fake (format-preserving)
on_unknown_token = "leave"   # leave | strip | flag : tokens in output the vault never issued
# enabled_entities = ["AADHAAR", "PAN"]   # default: all

[entities.SECRET]
action = "block"             # never send API keys

[entities.IFSC]
action = "allow"             # a branch code is not personal data on its own

[entities.AADHAAR]
threshold = 0.6              # per-entity threshold

# Rules are checked in order; the first match wins, then [entities.*], then default_action.
[[rules]]
entities = ["AADHAAR", "PAN"]
destinations = ["*.in-region.example.com"]   # glob on the upstream host
roles = ["kyc-officer"]                      # glob on the caller role
action = "allow"
```

## Actions

| Action | Text sent upstream | Restorable | Reported |
|---|---|---|---|
| `mask` | token | yes | yes |
| `hash` | keyed irreversible token | no | yes |
| `block` | nothing: the request is refused | n/a | yes |
| `warn` | original | n/a | yes |
| `allow` | original | n/a | yes (as allowed) |

In **shadow** mode every finding is reported with the action that *would* have applied, and nothing is changed or blocked.

## Rollout recipe for a new team

1. Start in `mode = "shadow"` for one to two weeks. Review the types and counts in audit / the console.
2. Triage false positives into `allow` rules or per-entity thresholds. Report misses as synthetic vectors.
3. Switch to `enforce` with `mask` as the default and `block` for `SECRET`.
4. Add destination rules for approved in-region endpoints if your data-flow policy permits them.
