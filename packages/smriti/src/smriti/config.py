"""Settings and tenant packs.

A tenant pack is a directory of YAML and Markdown files; the platform holds no
customer-specific code. Packs layer: platform defaults, then each pack named in
``extends`` (a vertical such as Railways), then the tenant pack, then
environment overrides. Later wins. Every file is validated on load so a bad
pack fails fast with a readable error instead of misbehaving at query time.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_PACKS_DIR = PACKAGE_DIR.parent.parent / "packs"


class PackError(ValueError):
    pass


# ---------------------------------------------------------------- settings


@dataclass
class Settings:
    data_dir: Path
    database_url: str
    packs: list[Path]
    vector_backend: str = "local"  # local | qdrant
    qdrant_url: str | None = None
    blob_url: str | None = None  # None -> <data_dir>/blobs ; s3://bucket/prefix for S3-compatible stores
    auth_mode: str = "demo"  # demo (X-Smriti-User header) | token (SMRITI_API_TOKENS)
    api_tokens: dict[str, str] = field(default_factory=dict)  # token -> user_id
    default_tenant: str | None = None
    scheduler: bool = True
    public_base_url: str = "http://127.0.0.1:8000"

    @classmethod
    def from_env(cls, **overrides: Any) -> Settings:
        data_dir = Path(os.environ.get("SMRITI_DATA_DIR", "data")).resolve()
        packs_env = os.environ.get("SMRITI_PACKS")
        packs = (
            [Path(p).resolve() for p in packs_env.split(os.pathsep) if p]
            if packs_env
            else [DEFAULT_PACKS_DIR / "tenants" / "railways-demo"]
        )
        tokens: dict[str, str] = {}
        for pair in os.environ.get("SMRITI_API_TOKENS", "").split(","):
            if ":" in pair:
                tok, user = pair.split(":", 1)
                tokens[tok.strip()] = user.strip()
        s = cls(
            data_dir=data_dir,
            database_url=os.environ.get("SMRITI_DATABASE_URL", f"sqlite:///{(data_dir / 'smriti.db').as_posix()}"),
            packs=packs,
            vector_backend=os.environ.get("SMRITI_VECTOR_BACKEND", "local"),
            qdrant_url=os.environ.get("SMRITI_QDRANT_URL"),
            blob_url=os.environ.get("SMRITI_BLOB_URL"),
            auth_mode=os.environ.get("SMRITI_AUTH", "demo"),
            api_tokens=tokens,
            default_tenant=os.environ.get("SMRITI_DEFAULT_TENANT"),
            scheduler=os.environ.get("SMRITI_SCHEDULER", "1") not in ("0", "false", "no"),
            public_base_url=os.environ.get("SMRITI_PUBLIC_URL", "http://127.0.0.1:8000"),
        )
        for k, v in overrides.items():
            setattr(s, k, v)
        return s


# ---------------------------------------------------------------- pack schemas


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelRoute(_Strict):
    base_url: str | None = None  # OpenAI-compatible endpoint (vLLM, SGLang, Ollama, LiteLLM)
    model: str | None = None
    api_key_env: str | None = None
    timeout_s: float = 60.0
    max_tokens: int = 900
    temperature: float = 0.1


class ModelsConfig(_Strict):
    bundle: str = "sovereign"  # sovereign | performance
    chat: ModelRoute = Field(default_factory=ModelRoute)
    router: ModelRoute | None = None
    extract: ModelRoute | None = None
    judge: ModelRoute | None = None
    guard: ModelRoute | None = None
    embed: ModelRoute | None = None  # /v1/embeddings ; None -> built-in hashing embedder
    rerank: ModelRoute | None = None  # TEI-style /rerank ; None -> built-in lexical reranker
    byo_api_fallback: bool = False  # disabled for sovereign tenants by default
    licence_register: dict[str, str] = Field(default_factory=dict)


class RetrievalConfig(_Strict):
    candidates: int = 50
    top_k: int = 8
    rrf_k: int = 60
    min_support: float = 0.18  # below this the reranked evidence is too weak and we abstain
    index_pii: bool = False  # index raw text (True) or the masked rendition (False, privacy-first)
    boilerplate: list[str] = Field(default_factory=list)  # regexes for stock lines never worth quoting


class TenantConfig(_Strict):
    id: str
    name: str
    locale: str = "en-IN"
    languages: list[str] = Field(default_factory=lambda: ["en", "hi"])
    extends: list[str] = Field(default_factory=list)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    retention: dict[str, Any] = Field(default_factory=dict)
    policy: str = ""  # tenant policy prompt layer
    seed: list[dict[str, Any]] = Field(default_factory=list)  # documents loaded by `smriti seed`


class RoleScope(BaseModel):
    model_config = ConfigDict(extra="allow")
    division: str | list[str] = "all"  # own | assigned | all | explicit list
    projects: str | list[str] = "any"  # assigned | any | explicit list
    doc_class: list[str] = Field(default_factory=lambda: ["public"])
    doc_types: list[str] | None = None


class RoleDef(_Strict):
    description: str = ""
    grants: list[str] = Field(default_factory=list)
    scope: RoleScope = Field(default_factory=RoleScope)
    unmask: list[str] = Field(default_factory=list)
    prompt: str = ""


class UserDef(_Strict):
    id: str
    name: str
    roles: list[str]
    title: str = ""
    divisions: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    clearance: str = "internal"


class RolesConfig(_Strict):
    roles: dict[str, RoleDef]
    users: list[UserDef] = Field(default_factory=list)  # demo directory; production reads SSO claims


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    source: str
    adapter_version: int = 1
    mode: str = "http"  # http | file | rss | playwright
    schedule: str | None = None
    start_urls: list[str] = Field(default_factory=list)
    path: str | None = None  # for mode=file
    discover: dict[str, Any] = Field(default_factory=dict)
    fetch: dict[str, Any] = Field(default_factory=dict)
    documents: dict[str, Any] = Field(default_factory=dict)
    dedupe: dict[str, Any] = Field(default_factory=dict)
    classify: dict[str, Any] = Field(default_factory=dict)
    supersession: dict[str, Any] = Field(default_factory=dict)
    access: dict[str, Any] = Field(default_factory=dict)
    alert: dict[str, Any] = Field(default_factory=dict)
    volatile: dict[str, Any] = Field(default_factory=dict)
    legal_status: str = "unknown"  # every source carries one (section 17)


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    meta: dict[str, Any]
    body: str


@dataclass
class TenantPack:
    config: TenantConfig
    roles: RolesConfig
    sources: list[SourceConfig]
    guardrails: dict[str, Any]
    glossary: dict[str, Any]
    schemas: dict[str, Any]
    prompts: dict[str, str]
    skills: dict[str, Skill]
    workflows: dict[str, Any]
    evals: dict[str, Any]
    roots: list[Path]  # every directory that contributed, base first

    @property
    def id(self) -> str:
        return self.config.id

    def resolve(self, rel: str) -> Path | None:
        """Find a pack-relative file, searching the tenant pack before its bases."""
        for root in reversed(self.roots):
            p = (root / rel).resolve()
            if p.exists():
                return p
        return None


# ---------------------------------------------------------------- loading


PLATFORM_GUARDRAILS: dict[str, Any] = {
    "input": {
        "injection": {"action": "block", "threshold": 0.7},
        "pii": {"engine": "saaf", "action": "mask_and_restore"},
        "max_query_chars": 4000,
    },
    "retrieval": {"untrusted_content": {"wrap": "data_block", "scan": True}, "require_current_version": True},
    "output": {
        "citations": {"required": True, "min_per_answer": 1},
        "faithfulness": {"min_score": 0.6, "on_fail": "abstain"},
        "numeric_check": {"recompute": True},
        "secrets": {"block": True},
    },
    "tools": {},
}


def deep_merge(base: Any, over: Any) -> Any:
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = deep_merge(base[k], v) if k in base else copy.deepcopy(v)
        return out
    if isinstance(base, list) and isinstance(over, list):
        return over
    return copy.deepcopy(over)


def _yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise PackError(f"{path}: invalid YAML: {e}") from e


def _front_matter(text: str) -> tuple[dict[str, Any], str]:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            meta = yaml.safe_load(text[3:end]) or {}
            return meta, text[end + 4 :].lstrip()
    return {}, text


def _layers(tenant_dir: Path, seen: set[Path] | None = None) -> list[Path]:
    seen = seen or set()
    tenant_dir = tenant_dir.resolve()
    if tenant_dir in seen:
        raise PackError(f"circular 'extends' at {tenant_dir}")
    seen.add(tenant_dir)
    cfg_path = tenant_dir / "tenant.yaml"
    pack_path = tenant_dir / "pack.yaml"
    meta = _yaml(cfg_path) if cfg_path.exists() else _yaml(pack_path) if pack_path.exists() else {}
    roots: list[Path] = []
    for base in meta.get("extends", []) or []:
        roots.extend(_layers((tenant_dir / base), seen))
    roots.append(tenant_dir)
    return roots


def load_pack(tenant_dir: Path) -> TenantPack:
    tenant_dir = Path(tenant_dir).resolve()
    if not (tenant_dir / "tenant.yaml").exists():
        raise PackError(f"{tenant_dir}: no tenant.yaml")
    roots = _layers(tenant_dir)

    merged_tenant: dict[str, Any] = {}
    merged_roles: dict[str, Any] = {"roles": {}, "users": []}
    guardrails: dict[str, Any] = copy.deepcopy(PLATFORM_GUARDRAILS)
    glossary: dict[str, Any] = {"abbreviations": {}, "synonyms": {}}
    schemas: dict[str, Any] = {}
    prompts: dict[str, str] = {}
    skills: dict[str, Skill] = {}
    workflows: dict[str, Any] = {}
    evals: dict[str, Any] = {"golden": [], "redteam": []}
    sources: dict[str, dict[str, Any]] = {}

    for root in roots:
        if (root / "tenant.yaml").exists():
            merged_tenant = deep_merge(merged_tenant, _yaml(root / "tenant.yaml"))
        rf = root / "roles" / "roles.yaml"
        if rf.exists():
            r = _yaml(rf)
            merged_roles["roles"] = deep_merge(merged_roles["roles"], r.get("roles", {}))
            merged_roles["users"] = [*merged_roles["users"], *r.get("users", [])]
        for f in sorted((root / "guardrails").glob("*.yaml")) if (root / "guardrails").is_dir() else []:
            guardrails = deep_merge(guardrails, _yaml(f).get("guardrails", {}))
        gf = root / "glossary.yaml"
        if gf.exists():
            g = _yaml(gf)
            for k in ("abbreviations", "synonyms"):
                glossary[k] = {**glossary[k], **(g.get(k) or {})}
        for f in sorted((root / "schemas").glob("*.yaml")) if (root / "schemas").is_dir() else []:
            schemas.update(_yaml(f).get("schemas", {}))
        for f in sorted((root / "prompts").glob("*.md")) if (root / "prompts").is_dir() else []:
            prompts[f.stem] = f.read_text(encoding="utf-8")
        for f in sorted((root / "sources").glob("*.yaml")) if (root / "sources").is_dir() else []:
            s = _yaml(f)
            sources[s.get("source", f.stem)] = deep_merge(sources.get(s.get("source", f.stem), {}), s)
        for f in sorted((root / "workflows").glob("*.yaml")) if (root / "workflows").is_dir() else []:
            workflows = deep_merge(workflows, _yaml(f))
        for name in ("golden", "redteam"):
            ef = root / "evals" / f"{name}.yaml"
            if ef.exists():
                evals[name] = [*evals[name], *(_yaml(ef).get("cases", []))]
        sk_dir = root / "skills"
        if sk_dir.is_dir():
            for d in sorted(p for p in sk_dir.iterdir() if (p / "SKILL.md").exists()):
                meta, body = _front_matter((d / "SKILL.md").read_text(encoding="utf-8"))
                name = meta.get("name", d.name)
                skills[name] = Skill(name=name, description=meta.get("description", ""), path=d, meta=meta, body=body)

    try:
        tcfg = TenantConfig(**merged_tenant)
        rcfg = RolesConfig(**merged_roles)
        scfg = [SourceConfig(**s) for s in sources.values()]
    except ValidationError as e:
        raise PackError(f"{tenant_dir}: {e}") from e

    for u in rcfg.users:
        missing = [r for r in u.roles if r not in rcfg.roles]
        if missing:
            raise PackError(f"user {u.id} references unknown roles {missing}")

    return TenantPack(
        config=tcfg,
        roles=rcfg,
        sources=scfg,
        guardrails=guardrails,
        glossary=glossary,
        schemas=schemas,
        prompts=prompts,
        skills=skills,
        workflows=workflows,
        evals=evals,
        roots=roots,
    )
