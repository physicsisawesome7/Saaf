"""Saaf: India-first PII masking and restore for LLM traffic."""

from saaf._version import __version__
from saaf.audit import AuditLogger, JsonlSink, MemorySink, verify_chain
from saaf.detect import Detector, Finding
from saaf.engine import Applied, MaskResult, Saaf, SaafBlocked
from saaf.policy import Policy, PolicyError, Rule
from saaf.restore import RestoreResult
from saaf.spec import Spec, default_spec, load_spec
from saaf.stream import StreamRestorer
from saaf.vault import InMemoryVault, RedisVault, SQLiteVault, StaticKeyProvider, Vault

__all__ = [
    "Applied",
    "AuditLogger",
    "Detector",
    "Finding",
    "InMemoryVault",
    "JsonlSink",
    "MaskResult",
    "MemorySink",
    "Policy",
    "PolicyError",
    "RedisVault",
    "RestoreResult",
    "Rule",
    "SQLiteVault",
    "Saaf",
    "SaafBlocked",
    "Spec",
    "StaticKeyProvider",
    "StreamRestorer",
    "Vault",
    "__version__",
    "default_spec",
    "load_spec",
    "verify_chain",
]
