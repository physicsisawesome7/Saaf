"""Skills: draft-and-validate workflows that load on demand.

A skill is a folder in the pack: ``SKILL.md`` (front matter says when to use
it, the grant it needs and its autonomy level), templates, deterministic
validators in Python, and eval cases with planted defects. Only the one-line
description is visible to the router until the skill is selected.

The pattern is always: the model extracts, coded rules judge, the model
explains. Estimates, totals and thresholds come from code and from retrieved
documents, never from free-text generation. The platform never issues or
signs; it drafts, validates, routes for approval and logs how much the
officer changed.
"""

from __future__ import annotations

import difflib
import importlib.util
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import yaml

from .config import Skill
from .engine import Tenant
from .models import Passage, Principal
from .store import drafts

DRAFT_MARK = "DRAFT FOR OFFICER REVIEW · AI-ASSISTED · NOT AN ISSUED DOCUMENT"


@dataclass
class Finding:
    check: str
    severity: str  # critical | major | minor | info | pass
    message: str
    citation: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"check": self.check, "severity": self.severity, "message": self.message, "citation": self.citation}


@dataclass
class SkillContext:
    """What a validator may touch. Every lookup goes through the same
    access-checked retrieval as chat, so a skill cannot see more than the
    officer running it."""

    tenant: Tenant
    principal: Principal
    skill: Skill
    citations: list[dict[str, Any]] = field(default_factory=list)

    def search(self, query: str, *, as_of: str | None = None, top_k: int = 5) -> list[Passage]:
        ps, _ = self.tenant.retrieve(self.principal, query, as_of=as_of, top_k=top_k)
        return ps

    def cite(self, p: Passage) -> dict[str, Any]:
        c = {
            "doc_id": p.doc_id,
            "title": p.title,
            "ref_no": p.ref_no,
            "clause_id": p.clause_id,
            "section": p.section,
            "date": p.doc_date,
        }
        self.citations.append(c)
        return c

    def table_rows(self, p: Passage) -> tuple[list[str], list[list[str]]] | None:
        c = self.tenant.store.get_chunks(self.tenant.id, [p.chunk_id]).get(p.chunk_id)
        if not c or not c.get("table_id"):
            return None
        t = self.tenant.store.get_table(self.tenant.id, c["table_id"])
        return (t["columns"], t["rows"]) if t else None

    def extract(self, instruction: str, text: str, schema: dict[str, Any]) -> dict[str, Any] | None:
        return self.tenant.gw.extract_json("extract", instruction, text, schema)

    def template(self, name: str) -> str:
        return (self.skill.path / "templates" / name).read_text(encoding="utf-8")

    def config(self, name: str) -> dict[str, Any]:
        return yaml.safe_load((self.skill.path / name).read_text(encoding="utf-8")) or {}

    def relations(self, doc_id: str) -> list[dict[str, Any]]:
        return self.tenant.store.relations_for(self.tenant.id, doc_id)

    def impact(self, doc_id: str) -> list[dict[str, Any]]:
        from .access import evaluate

        return [
            x for x in self.tenant.impact_of(doc_id) if evaluate(self.principal, x["access"], x["doc_type"]).allowed
        ]


def list_skills(t: Tenant, p: Principal) -> list[dict[str, Any]]:
    out = []
    for s in t.pack.skills.values():
        need = s.meta.get("requires", [])
        out.append(
            {
                "name": s.name,
                "description": s.description,
                "requires": need,
                "allowed": all(p.can(g) for g in need),
                "autonomy": s.meta.get("autonomy", "L0"),
                "inputs": s.meta.get("inputs", {}),
                "example": _example(s),
            }
        )
    return out


def _example(s: Skill) -> dict[str, Any] | None:
    f = s.path / "evals" / "cases.yaml"
    if not f.exists():
        return None
    cases = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("cases", [])
    return cases[0]["inputs"] if cases else None


def _load(skill: Skill) -> Any:
    files = sorted((skill.path / "validators").glob("*.py"))
    if not files:
        raise RuntimeError(f"skill {skill.name} has no validators")
    spec = importlib.util.spec_from_file_location(f"smriti_skill_{skill.name.replace('-', '_')}", files[0])
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_skill(t: Tenant, p: Principal, name: str, inputs: dict[str, Any]) -> dict[str, Any]:
    skill = t.pack.skills.get(name)
    if not skill:
        raise KeyError(name)
    need = skill.meta.get("requires", [])
    missing = [g for g in need if not p.can(g)]
    if missing:
        t.audit.record(p.user_id, "skill_denied", skill=name, missing=missing)
        raise PermissionError(f"skill '{name}' needs grants {missing}")
    ctx = SkillContext(t, p, skill)
    t0 = time.perf_counter()
    mod = _load(skill)
    out: dict[str, Any] = mod.run(ctx, inputs)
    findings = [f.to_dict() if isinstance(f, Finding) else f for f in out.get("findings", [])]
    order = {"critical": 0, "major": 1, "minor": 2, "info": 3, "pass": 4}
    findings.sort(key=lambda f: order.get(f["severity"], 9))
    res: dict[str, Any] = {
        "skill": name,
        "fields": out.get("fields", {}),
        "findings": findings,
        "summary": {s: sum(1 for f in findings if f["severity"] == s) for s in order},
        "citations": _dedupe(ctx.citations),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }
    if out.get("draft"):
        draft = f"{DRAFT_MARK}\n\n{out['draft']}"
        did = t.store.insert(
            drafts,
            tenant=t.id,
            skill=name,
            owner=p.user_id,
            status="draft",
            content=draft,
            original=draft,
            findings=json.dumps(findings),
            updated_at=time.time(),
        )
        res["draft"] = {"id": did, "content": draft, "open_fields": re.findall(r"\[\[TO FILL: ([^\]]+)\]\]", draft)}
    for k in ("impact", "extra"):
        if k in out:
            res[k] = out[k]
    t.audit.record(
        p.user_id,
        "skill_run",
        skill=name,
        findings=res["summary"],
        draft=res.get("draft", {}).get("id"),
        cited=[c["doc_id"] for c in res["citations"]],
    )
    return res


def _dedupe(cs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for c in cs:
        k = (c["doc_id"], c.get("clause_id"))
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


# ---------------------------------------------------------------- approvals


def update_draft(t: Tenant, p: Principal, draft_id: int, action: str, content: str | None = None) -> dict[str, Any]:
    rows = t.store.rows(drafts, tenant=t.id, id=draft_id)
    if not rows:
        raise KeyError(draft_id)
    d = rows[0]
    if action == "edit":
        if d["owner"] != p.user_id or d["status"] not in ("draft", "returned"):
            raise PermissionError("only the owner can edit a draft that is not under review")
        t.store.update_row(drafts, {"id": draft_id}, content=content or d["content"], updated_at=time.time())
    elif action == "submit":
        if d["owner"] != p.user_id:
            raise PermissionError("only the owner can submit")
        t.store.update_row(drafts, {"id": draft_id}, status="submitted", updated_at=time.time())
    elif action in ("approve", "return"):
        if not p.can("approve"):
            raise PermissionError("needs the 'approve' grant")
        if d["owner"] == p.user_id:
            raise PermissionError("maker and checker must be different people")
        t.store.update_row(
            drafts,
            {"id": draft_id},
            status="approved" if action == "approve" else "returned",
            approver=p.user_id,
            updated_at=time.time(),
        )
    else:
        raise ValueError(action)
    d = t.store.rows(drafts, tenant=t.id, id=draft_id)[0]
    ratio = difflib.SequenceMatcher(None, d["original"], d["content"]).ratio()
    t.audit.record(
        p.user_id, f"draft_{action}", draft_id=draft_id, skill=d["skill"], officer_edit_share=round(1 - ratio, 3)
    )
    return {**d, "findings": json.loads(d["findings"] or "[]"), "officer_edit_share": round(1 - ratio, 3)}


def list_drafts(t: Tenant, p: Principal) -> list[dict[str, Any]]:
    rows = t.store.rows(drafts, order_by="id", tenant=t.id)
    vis = [
        r
        for r in rows
        if r["owner"] == p.user_id or (p.can("approve") and r["status"] in ("submitted", "approved", "returned"))
    ]
    return [{**r, "findings": json.loads(r["findings"] or "[]")} for r in vis]


# ---------------------------------------------------------------- evals


def eval_skill(t: Tenant, name: str) -> dict[str, Any]:
    """Planted-defect recall: each case lists the checks that must fail."""
    skill = t.pack.skills[name]
    f = skill.path / "evals" / "cases.yaml"
    cases = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("cases", []) if f.exists() else []
    planted = caught = false_alarms = 0
    rows = []
    for c in cases:
        p = t.principal(c["as_user"])
        res = run_skill(t, p, name, c["inputs"])
        failing = {x["check"] for x in res["findings"] if x["severity"] in ("critical", "major")}
        expect = set(c.get("expect_fail", []))
        planted += len(expect)
        caught += len(expect & failing)
        false_alarms += len(failing - expect)
        rows.append(
            {
                "case": c["name"],
                "expected": sorted(expect),
                "flagged": sorted(failing),
                "missed": sorted(expect - failing),
            }
        )
    return {
        "skill": name,
        "cases": len(cases),
        "defect_recall": round(caught / planted, 3) if planted else None,
        "false_alarms": false_alarms,
        "rows": rows,
    }
