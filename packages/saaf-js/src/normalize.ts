/**
 * Text normalization with an offset map back to the original string.
 * Mirrors packages/saaf-core/src/saaf/normalize.py; the conformance suite
 * keeps them in step. Offsets are UTF-16 code units (JS string indices).
 */

const ZERO_WIDTH = new Set([0x200b, 0x200c, 0x200d, 0x2060, 0xfeff, 0x00ad]);
const INDIC_DIGIT_ZEROS = [0x0966, 0x09e6, 0x0a66, 0x0ae6, 0x0b66, 0x0be6, 0x0c66, 0x0ce6, 0x0d66];
const DASHES = new Set([0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212, 0xfe63, 0xff0d]);

const HOMOGLYPHS: Record<string, string> = {
  // Cyrillic
  "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
  "Р": "P", "С": "C", "Т": "T", "Х": "X", "У": "Y", "І": "I", "Ј": "J", "Ѕ": "S",
  "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
  "і": "i", "ј": "j", "ѕ": "s",
  // Greek
  "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K",
  "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
  "ο": "o",
};

export interface Normalized {
  text: string;
  /** indexMap[i] = original index of text[i] */
  indexMap: number[];
  /** widthMap[i] = UTF-16 width of the original char behind text[i] */
  widthMap: number[];
  originalLength: number;
}

export function foldChar(ch: string): string {
  const cp = ch.codePointAt(0)!;
  if (ZERO_WIDTH.has(cp)) return "";
  for (const zero of INDIC_DIGIT_ZEROS) {
    if (cp >= zero && cp <= zero + 9) return String.fromCharCode(0x30 + cp - zero);
  }
  if (DASHES.has(cp)) return "-";
  const h = HOMOGLYPHS[ch];
  if (h !== undefined) return h;
  if (cp < 0x80) return ch;
  return ch.normalize("NFKC");
}

export function normalize(text: string): Normalized {
  let out = "";
  const indexMap: number[] = [];
  const widthMap: number[] = [];
  let i = 0;
  for (const ch of text) {
    const folded = foldChar(ch);
    out += folded;
    for (let k = 0; k < folded.length; k++) {
      indexMap.push(i);
      widthMap.push(ch.length);
    }
    i += ch.length;
  }
  return { text: out, indexMap, widthMap, originalLength: text.length };
}

/** Map a half-open span in normalized text back to the original. */
export function toOriginal(n: Normalized, start: number, end: number): [number, number] {
  if (start >= end) {
    const pos = start < n.indexMap.length ? n.indexMap[start]! : n.originalLength;
    return [pos, pos];
  }
  return [n.indexMap[start]!, n.indexMap[end - 1]! + n.widthMap[end - 1]!];
}
