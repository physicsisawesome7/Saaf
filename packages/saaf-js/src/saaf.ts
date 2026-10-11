/**
 * Session API: mask -> (LLM) -> restore, plus streaming restore.
 * Mirrors saaf/engine.py, saaf/restore.py and saaf/stream.py for the
 * browser and Node. Persistent vaults, audit signing and cross-turn
 * detection are Python-only for now (see docs/architecture.md).
 */

import { Detector, type Finding } from "./detect.js";

export type Action = "mask" | "block" | "warn" | "allow";
export type UnknownTokenPolicy = "leave" | "strip" | "flag";

export interface PolicyOptions {
  mode?: "enforce" | "shadow";
  threshold?: number;
  defaultAction?: Action;
  entities?: Record<string, { action?: Action; threshold?: number }>;
  onUnknownToken?: UnknownTokenPolicy;
  enabledEntities?: string[];
}

export interface Applied {
  finding: Finding;
  action: Action;
  token?: string;
}

export interface MaskResult {
  text: string;
  originalText: string;
  applied: Applied[];
  blocked: boolean;
  shadow: boolean;
  tokens: string[];
  entityCounts: Record<string, number>;
}

export interface RestoreResult {
  text: string;
  restored: number;
  missing: string[];
  unknown: string[];
}

interface VaultEntry {
  token: string;
  entity: string;
  original: string;
}

const TOKEN_SHAPE = /\[([A-Z][A-Z0-9_]*?)_([0-9]+|[0-9a-f]{8})\]/g;

const escapeRx = (s: string) => s.replace(/[.*+?^${}()|[\]\\/-]/g, "\\$&");

/** Tolerant regex source for one issued token (see saaf/restore.py). */
export function tokenPattern(token: string): string {
  if (token.startsWith("[") && token.endsWith("]")) {
    const core = token.slice(1, -1);
    const cut = core.lastIndexOf("_");
    const entity = core.slice(0, cut);
    const suffix = core.slice(cut + 1);
    const entityRx = entity.split("_").map(escapeRx).join("[_ \\-]?");
    return `(?<![A-Za-z0-9_])(?:\\\\?\\[\\s*)?${entityRx}[_ \\-#]${escapeRx(suffix)}(?![A-Za-z0-9])(?:\\s*\\\\?\\])?`;
  }
  const digits = [...token].filter((c) => /[0-9]/.test(c));
  if (digits.length && digits.length >= 0.6 * token.replace(/ /g, "").length) {
    return `(?<![0-9])${token.startsWith("+") ? "\\+?" : ""}${digits.join("[ \\-]?")}(?![0-9])`;
  }
  return escapeRx(token);
}

export class Saaf {
  readonly detector: Detector;
  private policy: Required<Omit<PolicyOptions, "enabledEntities">>;
  private byKey = new Map<string, string>();
  private byToken = new Map<string, VaultEntry>();
  private counters = new Map<string, number>();
  private compiled: [RegExp, VaultEntry][] = [];
  private compiledFor = -1;

  constructor(policy: PolicyOptions = {}, detector?: Detector) {
    this.policy = {
      mode: policy.mode ?? "enforce",
      threshold: policy.threshold ?? 0.5,
      defaultAction: policy.defaultAction ?? "mask",
      entities: policy.entities ?? {},
      onUnknownToken: policy.onUnknownToken ?? "leave",
    };
    this.detector = detector ?? new Detector({ entities: policy.enabledEntities });
  }

  private thresholdFor(entity: string): number {
    return this.policy.entities[entity]?.threshold ?? this.policy.threshold;
  }

  private decide(entity: string): Action {
    return this.policy.entities[entity]?.action ?? this.policy.defaultAction;
  }

  scan(text: string): Finding[] {
    const min = Math.min(
      this.policy.threshold,
      ...Object.values(this.policy.entities).map((e) => e.threshold ?? this.policy.threshold),
    );
    return this.detector.scan(text, min).filter((f) => f.score >= this.thresholdFor(f.entity));
  }

  private tokenFor(f: Finding): string {
    const key = `${f.entity}\u001f${f.canonical}`;
    const existing = this.byKey.get(key);
    if (existing) return existing;
    const n = (this.counters.get(f.entity) ?? 0) + 1;
    this.counters.set(f.entity, n);
    const token = `[${f.entity}_${n}]`;
    this.byKey.set(key, token);
    this.byToken.set(token, { token, entity: f.entity, original: f.text });
    return token;
  }

  mask(text: string): MaskResult {
    const shadow = this.policy.mode === "shadow";
    const applied: Applied[] = [];
    const repl: [number, number, string][] = [];
    for (const f of this.scan(text)) {
      const action = this.decide(f.entity);
      let token: string | undefined;
      if (action === "mask" && !shadow) {
        token = this.tokenFor(f);
        repl.push([f.start, f.end, token]);
      }
      applied.push({ finding: f, action, token });
    }
    const blocked = !shadow && applied.some((a) => a.action === "block");
    let out = text;
    if (!blocked) {
      for (const [s, e, t] of repl.sort((a, b) => b[0] - a[0])) out = out.slice(0, s) + t + out.slice(e);
    }
    const entityCounts: Record<string, number> = {};
    for (const a of applied) entityCounts[a.finding.entity] = (entityCounts[a.finding.entity] ?? 0) + 1;
    return {
      text: out,
      originalText: text,
      applied,
      blocked,
      shadow,
      tokens: applied.filter((a) => a.token).map((a) => a.token!),
      entityCounts,
    };
  }

  /** Register a token -> original mapping (used by tests and integrations). */
  store(token: string, entity: string, original: string): void {
    this.byToken.set(token, { token, entity, original });
  }

  tokens(): string[] {
    return this.patterns().map(([, e]) => e.token);
  }

  private patterns(): [RegExp, VaultEntry][] {
    if (this.compiledFor !== this.byToken.size) {
      this.compiled = [...this.byToken.values()]
        .sort((a, b) => b.token.length - a.token.length)
        .map((e) => [new RegExp(tokenPattern(e.token), "gi"), e]);
      this.compiledFor = this.byToken.size;
    }
    return this.compiled;
  }

  restore(text: string, expected?: string[]): RestoreResult {
    const result: RestoreResult = { text, restored: 0, missing: [], unknown: [] };
    const seen = new Set<string>();
    let out = text;
    for (const [rx, entry] of this.patterns()) {
      out = out.replace(rx, () => {
        result.restored++;
        seen.add(entry.token);
        return entry.original;
      });
    }
    out = out.replace(TOKEN_SHAPE, (m, entity: string, n: string) => {
      result.unknown.push(m);
      if (this.policy.onUnknownToken === "strip") return "";
      if (this.policy.onUnknownToken === "flag") return `[UNVERIFIED ${entity}_${n}]`;
      return m;
    });
    if (expected) result.missing = expected.filter((t) => !seen.has(t));
    result.text = out;
    return result;
  }

  streamRestorer(): StreamRestorer {
    return new StreamRestorer(this);
  }
}

const TOKENISH = /^[A-Za-z0-9_[\]\\ +#-]*$/;
const squash = (s: string) => s.toLowerCase().replace(/[[\]\\ \-_+#]/g, "");

export class StreamRestorer {
  private buf = "";
  restored = 0;
  unknown: string[] = [];

  constructor(private saaf: Saaf) {}

  private couldBePrefix(suffix: string, forms: string[]): boolean {
    if (suffix === "\\") return true;
    if (suffix.startsWith("[") || suffix.startsWith("\\[")) return !suffix.includes("]");
    const sq = squash(suffix);
    return sq.length > 0 && forms.some((f) => f.startsWith(sq));
  }

  private split(): number {
    const forms = this.saaf.tokens().map(squash);
    const limit = Math.max(0, ...forms.map((f) => f.length)) * 2 + 8;
    const buf = this.buf;
    for (let i = Math.max(0, buf.length - limit); i < buf.length; i++) {
      const ch = buf[i]!;
      if (!/[A-Za-z0-9[\\+]/.test(ch)) continue; // a token (or fake) can only start here
      const prev = i > 0 ? buf[i - 1]! : "";
      if (prev === "[" || prev === "\\" || (/[A-Za-z0-9]/.test(prev) && /[A-Za-z0-9]/.test(ch))) continue;
      const suffix = buf.slice(i);
      if (!TOKENISH.test(suffix)) continue;
      if (this.couldBePrefix(suffix, forms)) return i;
    }
    return buf.length;
  }

  feed(chunk: string): string {
    this.buf += chunk;
    const cut = this.split();
    const ready = this.buf.slice(0, cut);
    this.buf = this.buf.slice(cut);
    return this.emit(ready);
  }

  flush(): string {
    const ready = this.buf;
    this.buf = "";
    return this.emit(ready);
  }

  private emit(text: string): string {
    if (!text) return "";
    const r = this.saaf.restore(text);
    this.restored += r.restored;
    this.unknown.push(...r.unknown);
    return r.text;
  }
}
