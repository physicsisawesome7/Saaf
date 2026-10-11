import assert from "node:assert/strict";
import { test } from "node:test";

import { Saaf, normalize, toOriginal } from "../src/index.js";

const AADHAAR = "2345 6789 0124";
const PAN = "ABCPE1234F";

test("mask and restore round trip", () => {
  const v = new Saaf();
  const text = `Aadhaar ${AADHAAR}, PAN ${PAN}, UPI ravi@okaxis`;
  const r = v.mask(text);
  assert.equal(r.text, "Aadhaar [AADHAAR_1], PAN [PAN_1], UPI [UPI_ID_1]");
  assert.deepEqual(r.entityCounts, { AADHAAR: 1, PAN: 1, UPI_ID: 1 });
  assert.equal(v.restore(r.text).text, text);
});

test("same value gets the same token", () => {
  const v = new Saaf();
  v.mask(`PAN ${PAN}`);
  assert.equal(v.mask(`again ${PAN.toLowerCase()}`).text, "again [PAN_1]");
});

test("shadow mode changes nothing", () => {
  const v = new Saaf({ mode: "shadow" });
  const r = v.mask(`PAN ${PAN}`);
  assert.equal(r.text, `PAN ${PAN}`);
  assert.equal(r.applied.length, 1);
});

test("block action", () => {
  const v = new Saaf({ entities: { PAN: { action: "block" } } });
  const r = v.mask(`PAN ${PAN}`);
  assert.ok(r.blocked);
  assert.equal(r.text, `PAN ${PAN}`);
});

test("stream restore across arbitrary chunking", () => {
  const v = new Saaf();
  v.mask(`Aadhaar ${AADHAAR} PAN ${PAN}`);
  const output = "Verified [AADHAAR_1]. PAN_1 ok; **\\[PAN_1\\]** and [aadhaar_1]'s record.";
  const expected = v.restore(output).text;
  for (let size = 1; size <= 7; size++) {
    const s = v.streamRestorer();
    let got = "";
    for (let i = 0; i < output.length; i += size) got += s.feed(output.slice(i, i + size));
    got += s.flush();
    assert.equal(got, expected, `chunk size ${size}`);
  }
});

test("closing bracket never leaks when a word follows a token (found by property tests)", () => {
  const v = new Saaf();
  const masked = v.mask(`Aadhaar ${AADHAAR} Aadhaar ${AADHAAR}`).text;
  const reply = `Sure. ${masked}`;
  for (let size = 1; size <= 7; size++) {
    const s = v.streamRestorer();
    let got = "";
    for (let i = 0; i < reply.length; i += size) got += s.feed(reply.slice(i, i + size));
    got += s.flush();
    assert.equal(got, `Sure. Aadhaar ${AADHAAR} Aadhaar ${AADHAAR}`, `chunk size ${size}`);
  }
});

test("offsets map through surrogate pairs and zero-width chars", () => {
  const text = "😀 PAN​ ABCPE1234F";
  const n = normalize(text);
  const s = n.text.indexOf("ABCPE");
  const [os, oe] = toOriginal(n, s, s + 10);
  assert.equal(text.slice(os, oe), PAN);
  const v = new Saaf();
  assert.equal(v.mask(text).text, "😀 PAN​ [PAN_1]");
});
