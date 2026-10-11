"""Gateway configuration, read from environment variables.

=========================  ===============================  =====================================
Variable                   Default                          Meaning
=========================  ===============================  =====================================
SAAF_UPSTREAM_OPENAI       https://api.openai.com           OpenAI-compatible upstream base URL
SAAF_UPSTREAM_ANTHROPIC    https://api.anthropic.com        Anthropic upstream base URL
SAAF_POLICY_DIR            (unset)                          dir of ``<tenant>.toml`` policies
SAAF_DEFAULT_POLICY        (unset)                          policy file for unknown tenants
SAAF_TENANT_HEADER         x-saaf-tenant                    request header naming the tenant
SAAF_AUDIT_LOG             (unset)                          JSONL audit log path
SAAF_AUDIT_KEY             (unset)                          hex HMAC key for audit signatures
SAAF_TIMEOUT               120                              upstream timeout, seconds
=========================  ===============================  =====================================
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

_TENANT_RX = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


@dataclass(frozen=True)
class GatewayConfig:
    upstream_openai: str = "https://api.openai.com"
    upstream_anthropic: str = "https://api.anthropic.com"
    policy_dir: Path | None = None
    default_policy: Path | None = None
    tenant_header: str = "x-saaf-tenant"
    audit_log: Path | None = None
    audit_key: bytes | None = field(default=None, repr=False)
    timeout: float = 120.0

    @classmethod
    def from_env(cls) -> GatewayConfig:
        env = os.environ.get
        key = env("SAAF_AUDIT_KEY")
        return cls(
            upstream_openai=env("SAAF_UPSTREAM_OPENAI", cls.upstream_openai).rstrip("/"),
            upstream_anthropic=env("SAAF_UPSTREAM_ANTHROPIC", cls.upstream_anthropic).rstrip("/"),
            policy_dir=Path(p) if (p := env("SAAF_POLICY_DIR")) else None,
            default_policy=Path(p) if (p := env("SAAF_DEFAULT_POLICY")) else None,
            tenant_header=env("SAAF_TENANT_HEADER", cls.tenant_header).lower(),
            audit_log=Path(p) if (p := env("SAAF_AUDIT_LOG")) else None,
            audit_key=bytes.fromhex(key) if key else None,
            timeout=float(env("SAAF_TIMEOUT", "120")),
        )

    @staticmethod
    def valid_tenant(name: str) -> bool:
        """Tenant names become file names; keep them boring."""
        return bool(_TENANT_RX.match(name)) and name not in {".", ".."}
