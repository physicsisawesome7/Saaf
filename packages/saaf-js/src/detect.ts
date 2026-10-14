/** Detection pipeline. Mirrors saaf/detect.py. */

import { normalize, toOriginal, type Normalized } from "./normalize.js";
import { canonicalize, parseSpec, type EntitySpec, type Spec } from "./spec.js";
import { SPEC } from "./spec.generated.js";

export interface Finding {
  entity: string;
  start: number;
  end: number;
  text: string;
  score: number;
  canonical: string;
  severity: string;
  validated: boolean;
  contextHit: boolean;
  detector: "regex" | "ocr" | "spelled";
  ocrRepaired: boolean;
  priority: number;
}

const LETTER_TO_DIGIT: Record<string, string> = { O: "0", o: "0", I: "1", l: "1", S: "5", B: "8" };
const DIGIT_TO_LETTERS: Record<string, string[]> = { "0": ["O"], "1": ["I", "L"], "5": ["S"], "8": ["B"] };
const MAX_OCR_VARIANTS = 64;

const escapeRx = (s: string) => s.replace(/[.*+?^${}()|[\]\\/-]/g, "\\$&");
const isAscii = (s: string) => /^[\x00-\x7f]*$/.test(s);

// Number words (English, Romanised Hindi, Devanagari); keep in step with detect.py.
const DIGIT_WORDS: Record<string, string> = {
  zero: "0", oh: "0", shunya: "0", shoonya: "0", sunya: "0", "शून्य": "0",
  one: "1", ek: "1", "एक": "1",
  two: "2", do: "2", "दो": "2",
  three: "3", teen: "3", tin: "3", "तीन": "3",
  four: "4", char: "4", chaar: "4", "चार": "4",
  five: "5", paanch: "5", panch: "5", "पांच": "5", "पाँच": "5",
  six: "6", chhah: "6", chhe: "6", che: "6", chah: "6", "छह": "6", "छः": "6",
  seven: "7", saat: "7", sat: "7", "सात": "7",
  eight: "8", aath: "8", aat: "8", "आठ": "8",
  nine: "9", nau: "9", nao: "9", "नौ": "9",
};
const WORD_ALT = Object.keys(DIGIT_WORDS)
  .sort((a, b) => b.length - a.length)
  .map(escapeRx)
  .join("|");
const NOT_WORD = "a-z\\u0900-\\u097f";
const SPELLED_WORD = new RegExp(`(?<![${NOT_WORD}])(?:${WORD_ALT})(?![${NOT_WORD}])`, "gi");
const SPELLED_RUN = new RegExp(
  `(?<![${NOT_WORD}])(?:${WORD_ALT})(?:[ ,.\\-]+(?:${WORD_ALT})){9,15}(?![${NOT_WORD}])`,
  "gi",
);
const SPELLED_TARGETS_BY_LEN: Record<number, string> = { 12: "AADHAAR", 10: "PHONE_IN" };

class ContextMatcher {
  private rx: RegExp | null;
  private other: string[];
  constructor(keywords: string[]) {
    const ascii = keywords.filter(isAscii).sort((a, b) => b.length - a.length);
    this.other = keywords.filter((k) => !isAscii(k));
    this.rx = ascii.length ? new RegExp(`(?<![a-z0-9])(?:${ascii.map(escapeRx).join("|")})(?![a-z0-9])`, "g") : null;
  }
  /** Distance from the candidate to the closest keyword, or null. */
  nearest(before: string, after: string): number | null {
    let best: number | null = null;
    const take = (d: number) => (best = best === null ? d : Math.min(best, d));
    if (this.rx) {
      const hits = [...before.matchAll(this.rx)];
      const last = hits[hits.length - 1];
      if (last) take(before.length - (last.index! + last[0].length));
      const first = after.matchAll(this.rx).next();
      if (!first.done) take(first.value.index!);
    }
    for (const k of this.other) {
      const i = before.lastIndexOf(k);
      if (i >= 0) take(before.length - i - k.length);
      const j = after.indexOf(k);
      if (j >= 0) take(j);
    }
    return best;
  }
}

// Negative context only counts inside the candidate's own line and sentence.
const CLAUSE_BREAK = /[\n.!?;](?:\s|$)|\n/g;

function clauseBefore(before: string): string {
  let cut = 0;
  for (const m of before.matchAll(CLAUSE_BREAK)) cut = m.index! + m[0].length;
  return before.slice(cut);
}

function clauseAfter(after: string): string {
  const m = after.matchAll(CLAUSE_BREAK).next();
  return m.done ? after : after.slice(0, m.value.index!);
}

let defaultSpecCache: Spec | null = null;
export function defaultSpec(): Spec {
  return (defaultSpecCache ??= parseSpec(SPEC));
}

export interface DetectorOptions {
  spec?: Spec;
  entities?: string[];
  threshold?: number;
  contextWindow?: number;
  ocrRepair?: boolean;
}

export class Detector {
  readonly spec: Spec;
  readonly entities: EntitySpec[];
  readonly threshold: number;
  private window: number;
  private ocrRepair: boolean;
  private ctx = new Map<string, ContextMatcher>();
  private neg = new Map<string, ContextMatcher>();

  constructor(opts: DetectorOptions = {}) {
    this.spec = opts.spec ?? defaultSpec();
    const allowed = opts.entities ? new Set(opts.entities) : null;
    if (allowed) {
      const unknown = [...allowed].filter((id) => !this.spec.byId.has(id));
      if (unknown.length) throw new Error(`unknown entities: ${unknown.join(", ")}`);
    }
    this.entities = this.spec.entities.filter((e) => !allowed || allowed.has(e.id));
    this.threshold = opts.threshold ?? this.spec.threshold;
    this.window = opts.contextWindow ?? this.spec.contextWindow;
    this.ocrRepair = opts.ocrRepair ?? true;
    for (const e of this.entities) {
      this.ctx.set(e.id, new ContextMatcher(e.context));
      this.neg.set(e.id, new ContextMatcher(e.negativeContext));
    }
  }

  scan(text: string, threshold?: number): Finding[] {
    const cut = threshold ?? this.threshold;
    return resolveOverlaps(this.candidates(text, normalize(text)).filter((f) => f.score >= cut));
  }

  scanAll(text: string): Finding[] {
    return this.candidates(text, normalize(text));
  }

  private windowAt(ntext: string, s: number, t: number): [string, string] {
    return [ntext.slice(Math.max(0, s - this.window), s).toLowerCase(), ntext.slice(t, t + this.window).toLowerCase()];
  }

  private score(e: EntitySpec, base: number, [before, after]: [string, string]): [number, boolean] | null {
    const pos = e.context.length ? this.ctx.get(e.id)!.nearest(before, after) : null;
    const hit = pos !== null;
    if (e.requiresContext && !hit) return null;
    let score = base + (hit ? e.contextBoost : 0);
    if (e.negativeContext.length) {
      const neg = this.neg.get(e.id)!.nearest(clauseBefore(before), clauseAfter(after));
      // The nearest label wins outright: the nearer negative label also cancels a farther boost.
      if (neg !== null && (pos === null || neg < pos)) score = base - e.negativePenalty;
    }
    return [Math.round(Math.max(0, Math.min(1, score)) * 1e6) / 1e6, hit];
  }

  private candidates(original: string, norm: Normalized): Finding[] {
    const out: Finding[] = [];
    const ntext = norm.text;
    for (const e of this.entities) {
      for (const p of e.patterns) {
        p.regex.lastIndex = 0;
        for (const m of ntext.matchAll(p.regex)) {
          const [s, t] = p.group ? m.indices![p.group]! : [m.index!, m.index! + m[0].length];
          if (s === t) continue;
          const canonical = canonicalize(e.canonical, ntext.slice(s, t));
          let validated = false;
          if (e.validator) {
            validated = e.validator(canonical);
            if (!validated && e.onInvalid === "drop") continue;
          }
          const scored = this.score(e, validated ? e.validatedScore : e.baseScore, this.windowAt(ntext, s, t));
          if (!scored) continue;
          const [os, ot] = toOriginal(norm, s, t);
          out.push({
            entity: e.id, start: os, end: ot, text: original.slice(os, ot), score: scored[0], canonical,
            severity: e.severity, validated, contextHit: scored[1], detector: "regex", ocrRepaired: false,
            priority: e.priority,
          });
        }
      }
      if (this.ocrRepair && e.ocr && e.validator) out.push(...this.ocrCandidates(e, original, norm));
    }
    out.push(...this.spelledCandidates(original, norm));
    return out;
  }

  /** Identifiers written as number words ("two three four ...", "ek do teen ...", "एक दो ..."). */
  private spelledCandidates(original: string, norm: Normalized): Finding[] {
    const out: Finding[] = [];
    const ntext = norm.text;
    for (const m of ntext.matchAll(SPELLED_RUN)) {
      const words = m[0].match(SPELLED_WORD) ?? [];
      const digits = words.map((w) => DIGIT_WORDS[w.toLowerCase()] ?? "").join("");
      const id = SPELLED_TARGETS_BY_LEN[digits.length];
      const e = id ? this.entities.find((x) => x.id === id) : undefined;
      if (!e || !e.validator || !e.validator(digits)) continue;
      const s = m.index!;
      const t = s + m[0].length;
      const scored = this.score(e, e.validatedScore, this.windowAt(ntext, s, t));
      if (!scored) continue;
      const [os, ot] = toOriginal(norm, s, t);
      out.push({
        entity: e.id, start: os, end: ot, text: original.slice(os, ot), score: scored[0], canonical: digits,
        severity: e.severity, validated: true, contextHit: scored[1], detector: "spelled", ocrRepaired: false,
        priority: e.priority,
      });
    }
    return out;
  }

  private ocrCandidates(e: EntitySpec, original: string, norm: Normalized): Finding[] {
    const out: Finding[] = [];
    const ntext = norm.text;
    const ocr = e.ocr!;
    for (const m of ntext.matchAll(ocr.regex)) {
      const s = m.index!;
      const t = s + m[0].length;
      const raw = m[0].replace(/[ -]/g, "");
      if ((raw.match(/[0-9]/g)?.length ?? 0) < ocr.minDigits) continue;
      const passing = ocrVariants(raw, ocr.shape).filter((v) => e.validator!(canonicalize(e.canonical, v)));
      if (!passing.length) continue;
      const scored = this.score(e, ocr.score, this.windowAt(ntext, s, t));
      if (!scored) continue;
      const [os, ot] = toOriginal(norm, s, t);
      out.push({
        entity: e.id, start: os, end: ot, text: original.slice(os, ot), score: scored[0],
        canonical: canonicalize(e.canonical, passing[0]!), severity: e.severity, validated: true,
        contextHit: scored[1], detector: "ocr", ocrRepaired: true, priority: e.priority,
      });
    }
    return out;
  }
}

export function ocrVariants(raw: string, shape: string): string[] {
  const chars = [...raw];
  if (chars.length !== shape.length) return [];
  const options: string[][] = [];
  let changed = false;
  for (let i = 0; i < chars.length; i++) {
    const ch = chars[i]!;
    if (shape[i] === "D") {
      if (/[0-9]/.test(ch)) options.push([ch]);
      else if (LETTER_TO_DIGIT[ch]) {
        options.push([LETTER_TO_DIGIT[ch]!]);
        changed = true;
      } else return [];
    } else {
      if (/[A-Za-z]/.test(ch)) options.push([ch.toUpperCase()]);
      else if (DIGIT_TO_LETTERS[ch]) {
        options.push(DIGIT_TO_LETTERS[ch]!);
        changed = true;
      } else return [];
    }
  }
  if (!changed) return [];
  let variants = [""];
  for (const opts of options) {
    variants = variants.flatMap((v) => opts.map((o) => v + o)).slice(0, MAX_OCR_VARIANTS);
  }
  return variants;
}

export function resolveOverlaps(findings: Finding[]): Finding[] {
  const ranked = [...findings].sort(
    (a, b) => b.score - a.score || b.priority - a.priority || b.end - b.start - (a.end - a.start) || a.start - b.start,
  );
  const chosen: Finding[] = [];
  for (const f of ranked) {
    if (chosen.every((c) => f.end <= c.start || f.start >= c.end)) chosen.push(f);
  }
  return chosen.sort((a, b) => a.start - b.start);
}
