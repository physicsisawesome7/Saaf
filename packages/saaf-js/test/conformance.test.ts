/** Runs the shared vectors in spec/conformance against the TS port. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { Detector, VALIDATORS, Saaf, parseSpec } from "../src/index.js";
import type { RawSpec } from "../src/index.js";

// Compiled to packages/saaf-js/build-test/test/ -> repo root is four levels up.
const here = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(here, "../../../..");
const CONF = resolve(ROOT, "spec/conformance");

function jsonl<T>(name: string): T[] {
  return readFileSync(resolve(CONF, name), "utf8")
    .split("\n")
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l) as T);
}

interface ValidatorCase { validator: string; input: string; expect: boolean }
interface DetectCase { id: string; text: string; expect: { entity: string; text: string }[] }
interface RestoreCase { id: string; vault: Record<string, string>; input: string; expect: string; unknown?: string[] }

for (const c of jsonl<ValidatorCase>("validators.jsonl")) {
  test(`validator ${c.validator}:${c.input}`, () => {
    assert.equal(VALIDATORS[c.validator]!(c.input), c.expect);
  });
}

const canonicalSpec = parseSpec(JSON.parse(readFileSync(resolve(ROOT, "spec/entities.json"), "utf8")) as RawSpec);
const detector = new Detector({ spec: canonicalSpec });

for (const c of jsonl<DetectCase>("detect.jsonl")) {
  test(`detect ${c.id}`, () => {
    const got = detector.scan(c.text).map((f) => ({ entity: f.entity, text: f.text }));
    assert.deepEqual(got, c.expect);
  });
}

for (const c of jsonl<RestoreCase>("restore.jsonl")) {
  test(`restore ${c.id}`, () => {
    const v = new Saaf();
    for (const [token, original] of Object.entries(c.vault)) v.store(token, "X", original);
    const r = v.restore(c.input);
    assert.equal(r.text, c.expect);
    assert.deepEqual(r.unknown, c.unknown ?? []);
  });
}
