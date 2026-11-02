"""Role- and scope-aware access, decided in code and never by the model.

Two enforcement points, both inside the retrieval service so the agent cannot
skip them or be talked out of them:

1. ``AccessFilter`` turns a principal into a payload filter applied *during*
   vector and keyword search, so unauthorised chunks are never fetched.
2. ``Authorizer.bulk_check`` re-checks every candidate against the document
   record (the source of truth) after search, catching stale index payloads
   and the ANDed extra rules carried by derived memories.

Permissions live on documents, not chunks; a chunk inherits its document's
rule, so re-chunking never touches the authorisation data. ``administer`` and
``view`` are separate grants: an admin is not automatically a reader.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .config import RolesConfig, UserDef
from .models import Access, Principal, class_rank

ALL = "*"


class UnknownUser(LookupError):
    pass


class Directory:
    """Resolves people to principals. The demo directory comes from roles.yaml;
    production maps OIDC/SAML claims from Keycloak with ``from_claims``."""

    def __init__(self, roles: RolesConfig):
        self.roles = roles
        self.users = {u.id: u for u in roles.users}

    def principal(self, user_id: str) -> Principal:
        u = self.users.get(user_id)
        if not u:
            raise UnknownUser(user_id)
        return self._build(u)

    def from_claims(self, claims: dict[str, Any]) -> Principal:
        u = UserDef(
            id=str(claims.get("preferred_username") or claims["sub"]),
            name=str(claims.get("name") or claims.get("preferred_username") or claims["sub"]),
            roles=[r for r in claims.get("roles", []) if r in self.roles.roles],
            divisions=list(claims.get("divisions", [])),
            projects=list(claims.get("projects", [])),
            groups=list(claims.get("groups", [])),
            clearance=str(claims.get("clearance", "internal")),
        )
        return self._build(u)

    def _build(self, u: UserDef) -> Principal:
        grants: set[str] = set()
        unmask: set[str] = set()
        scopes: list[dict[str, Any]] = []
        for rname in u.roles:
            r = self.roles.roles[rname]
            grants.update(r.grants)
            unmask.update(r.unmask)
            if "view" not in r.grants:
                continue
            s = r.scope
            scopes.append(
                {
                    "role": rname,
                    "divisions": _resolve(s.division, u.divisions, own=("own", "assigned"), everything=("all", "any")),
                    "projects": _resolve(s.projects, u.projects, own=("assigned", "own"), everything=("any", "all")),
                    "doc_class": list(s.doc_class),
                    "doc_types": list(s.doc_types) if s.doc_types else None,
                }
            )
        return Principal(
            user_id=u.id,
            name=u.name,
            roles=list(u.roles),
            grants=grants,
            divisions=list(u.divisions),
            projects=list(u.projects),
            groups=[*u.groups, f"user:{u.id}"],  # personal memories are a group of one
            clearance=u.clearance,
            unmask=unmask,
            role_scopes=scopes,
        )


def _resolve(
    spec: str | list[str], mine: list[str], own: tuple[str, ...], everything: tuple[str, ...]
) -> str | list[str]:
    if isinstance(spec, list):
        return spec
    if spec in everything:
        return ALL
    if spec in own:
        return list(mine)
    return [spec]


def _intersects(allowed: str | list[str], have: list[str]) -> bool:
    return allowed == ALL or bool(set(allowed) & set(have))


@dataclass
class Decision:
    allowed: bool
    reasons: list[str]


def evaluate(p: Principal, access: dict[str, Any] | Access, doc_type: str) -> Decision:
    """The one access rule. Used by the payload filter, the bulk check and the role simulator."""
    a = access if isinstance(access, Access) else Access.from_dict(access)
    reasons: list[str] = []
    if not p.can("view"):
        return Decision(False, ["no 'view' grant (administering the system does not include reading its content)"])
    if class_rank(a.doc_class) > class_rank(p.clearance):
        return Decision(False, [f"document is '{a.doc_class}', clearance is '{p.clearance}'"])
    if a.groups and not set(a.groups) & set(p.groups):
        return Decision(False, [f"need-to-know group required: {', '.join(a.groups)}"])
    for rule in a.extra_rules:
        sub = evaluate(p, {**rule, "extra_rules": []}, doc_type)
        if not sub.allowed:
            return Decision(False, ["derived item inherits a stricter source rule: " + "; ".join(sub.reasons)])
    for s in p.role_scopes:
        why = []
        if a.doc_class not in s["doc_class"]:
            why.append(f"class '{a.doc_class}' not in {s['doc_class']}")
        if ALL not in a.divisions and not _intersects(s["divisions"], a.divisions):
            why.append(f"division {a.divisions} outside scope {s['divisions']}")
        if a.projects and not _intersects(s["projects"], a.projects):
            why.append(f"project {a.projects} not assigned")
        if s["doc_types"] is not None and doc_type not in s["doc_types"]:
            why.append(f"type '{doc_type}' not in {s['doc_types']}")
        if not why:
            return Decision(True, [f"allowed by role '{s['role']}'"])
        reasons.append(f"role '{s['role']}': " + "; ".join(why))
    return Decision(False, reasons or ["no role grants a viewing scope"])


class AccessFilter:
    """Payload filter for search. Index payloads carry the document's access
    attributes and type, so the filter is evaluated without a database call."""

    def __init__(self, principal: Principal):
        self.p = principal

    def matches(self, payload: dict[str, Any]) -> bool:
        return evaluate(self.p, payload["access"], payload.get("doc_type", "")).allowed

    def to_qdrant(self) -> dict[str, Any]:
        """Equivalent Qdrant filter (JSON form). Extra rules are left to the bulk check."""
        if not self.p.can("view") or not self.p.role_scopes:
            return {"must": [{"key": "doc_id", "match": {"value": "__nothing__"}}]}
        allowed_classes = [
            c
            for c in {c for s in self.p.role_scopes for c in s["doc_class"]}
            if class_rank(c) <= class_rank(self.p.clearance)
        ]
        should = []
        for s in self.p.role_scopes:
            must: list[dict[str, Any]] = [
                {"key": "access.doc_class", "match": {"any": [c for c in s["doc_class"] if c in allowed_classes]}}
            ]
            if s["divisions"] != ALL:
                must.append({"should": [{"key": "access.divisions", "match": {"any": [ALL, *s["divisions"]]}}]})
            if s["projects"] != ALL:
                must.append(
                    {
                        "should": [
                            {"is_empty": {"key": "access.projects"}},
                            {"key": "access.projects", "match": {"any": s["projects"]}},
                        ]
                    }
                )
            if s["doc_types"] is not None:
                must.append({"key": "doc_type", "match": {"any": s["doc_types"]}})
            should.append({"must": must})
        groups_cond = {"should": [{"is_empty": {"key": "access.groups"}}]}
        if self.p.groups:
            groups_cond["should"].append({"key": "access.groups", "match": {"any": self.p.groups}})
        return {"must": [groups_cond, {"should": should}]}


class Authorizer(Protocol):
    def bulk_check(self, p: Principal, docs: dict[str, dict[str, Any]]) -> set[str]: ...
    def explain(self, p: Principal, doc: dict[str, Any]) -> Decision: ...


class LocalAuthorizer:
    """In-process relationship/attribute checks over the document records.

    The OpenFGA or SpiceDB adapter implements the same two methods with a
    ``BatchCheck`` call; the retrieval code does not change.
    """

    def bulk_check(self, p: Principal, docs: dict[str, dict[str, Any]]) -> set[str]:
        return {
            doc_id
            for doc_id, d in docs.items()
            if d.get("status") != "tombstoned" and evaluate(p, d["access"], d["doc_type"]).allowed
        }

    def explain(self, p: Principal, doc: dict[str, Any]) -> Decision:
        return evaluate(p, doc["access"], doc["doc_type"])


def strictest(accesses: list[dict[str, Any]]) -> Access:
    """Access for an item derived from several sources (memories, summaries).

    The derived item keeps the most restricted class, the intersection of
    divisions and projects, and carries every source rule as an ANDed extra
    rule so the bulk check enforces all of them exactly.
    """
    if not accesses:
        return Access()
    items = [Access.from_dict(a) for a in accesses]
    if len(items) == 1:
        return items[0]
    cls = max((a.doc_class for a in items), key=class_rank)
    divs: set[str] | None = None
    for a in items:
        if ALL in a.divisions:
            continue
        divs = set(a.divisions) if divs is None else divs & set(a.divisions)
    projs: set[str] | None = None
    for a in items:
        if a.projects:
            projs = set(a.projects) if projs is None else projs & set(a.projects)
    return Access(
        doc_class=cls,
        divisions=sorted(divs) if divs is not None else [ALL],
        projects=sorted(projs) if projs is not None else [],
        groups=[],  # each source's groups are enforced through its extra rule
        pii=sorted({x for a in items for x in a.pii}),
        extra_rules=[{k: v for k, v in a.to_dict().items() if k != "extra_rules"} for a in items],
    )
