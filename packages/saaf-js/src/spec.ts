/** Load and compile the declarative detector spec. Mirrors saaf/spec.py. */

import { VALIDATORS } from "./validators.js";

export interface RawPattern {
  pattern: string;
  flags?: string;
  group?: number;
}

export interface RawEntity {
  id: string;
  label?: string;
  phase?: string;
  severity?: string;
  priority?: number;
  canonical?: string;
  patterns: RawPattern[];
  validator?: string;
  on_invalid?: string;
  base_score?: number;
  validated_score?: number;
  requires_context?: boolean;
  context?: string[];
  context_boost?: number;
  negative_context?: string | string[];
  negative_penalty?: number;
  ocr?: { pattern: string; flags?: string; shape: string; min_digits?: number; score: number };
  fake?: string;
}

export interface RawSpec {
  spec_version?: string;
  defaults?: { context_window?: number; threshold?: number };
  context_sets?: Record<string, string[]>;
  entities: RawEntity[];
  [key: string]: unknown;
}

export interface CompiledPattern {
  regex: RegExp;
  group: number;
}

export interface EntitySpec {
  id: string;
  label: string;
  phase: string;
  severity: string;
  priority: number;
  canonical: string;
  patterns: CompiledPattern[];
  validator: ((v: string) => boolean) | null;
  validatorName: string | null;
  onInvalid: string;
  baseScore: number;
  validatedScore: number;
  requiresContext: boolean;
  context: string[];
  contextBoost: number;
  negativeContext: string[];
  negativePenalty: number;
  ocr: { regex: RegExp; shape: string; minDigits: number; score: number } | null;
  fake: string | null;
}

export interface Spec {
  version: string;
  contextWindow: number;
  threshold: number;
  entities: EntitySpec[];
  byId: Map<string, EntitySpec>;
}

function compile(pattern: string, flags = "", group = 0): RegExp {
  return new RegExp(pattern, "g" + (group ? "d" : "") + (flags.includes("i") ? "i" : ""));
}

export function canonicalize(kind: string, text: string): string {
  switch (kind) {
    case "digits":
      return text.replace(/[^0-9]/g, "");
    case "alnum_upper":
      return text.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
    case "lower":
      return text.trim().toLowerCase();
    default:
      return text.trim();
  }
}

function resolveSet(value: string | string[] | undefined, sets: Record<string, string[]>): string[] {
  if (value === undefined) return [];
  if (typeof value === "string") {
    if (!value.startsWith("@")) throw new Error(`context set reference must start with '@': ${value}`);
    const set = sets[value.slice(1)];
    if (!set) throw new Error(`unknown context set ${value}`);
    return set;
  }
  return value;
}

export function parseSpec(raw: RawSpec): Spec {
  const sets = raw.context_sets ?? {};
  const entities: EntitySpec[] = raw.entities.map((e) => {
    const vname = e.validator ?? null;
    const validator = vname ? VALIDATORS[vname] : null;
    if (vname && !validator) throw new Error(`unknown validator ${vname}`);
    return {
      id: e.id,
      label: e.label ?? e.id,
      phase: e.phase ?? "P0",
      severity: e.severity ?? "medium",
      priority: e.priority ?? 50,
      canonical: e.canonical ?? "strip",
      patterns: e.patterns.map((p) => ({ regex: compile(p.pattern, p.flags, p.group ?? 0), group: p.group ?? 0 })),
      validator: validator ?? null,
      validatorName: vname,
      onInvalid: e.on_invalid ?? "drop",
      baseScore: e.base_score ?? 0,
      validatedScore: e.validated_score ?? e.base_score ?? 0,
      requiresContext: e.requires_context ?? false,
      context: (e.context ?? []).map((k) => k.toLowerCase()),
      contextBoost: e.context_boost ?? 0,
      negativeContext: resolveSet(e.negative_context, sets).map((k) => k.toLowerCase()),
      negativePenalty: e.negative_penalty ?? 0,
      ocr: e.ocr
        ? { regex: compile(e.ocr.pattern, e.ocr.flags), shape: e.ocr.shape, minDigits: e.ocr.min_digits ?? 0, score: e.ocr.score }
        : null,
      fake: e.fake ?? null,
    };
  });
  const byId = new Map(entities.map((e) => [e.id, e]));
  if (byId.size !== entities.length) throw new Error("duplicate entity ids in spec");
  return {
    version: raw.spec_version ?? "0",
    contextWindow: raw.defaults?.context_window ?? 50,
    threshold: raw.defaults?.threshold ?? 0.5,
    entities,
    byId,
  };
}
