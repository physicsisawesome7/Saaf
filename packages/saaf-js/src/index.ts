export { Detector, defaultSpec, ocrVariants, resolveOverlaps, type Finding, type DetectorOptions } from "./detect.js";
export { normalize, toOriginal, type Normalized } from "./normalize.js";
export { canonicalize, parseSpec, type Spec, type EntitySpec, type RawSpec } from "./spec.js";
export { VALIDATORS, verhoeff, verhoeffCheckDigit, aadhaar, luhn, card, pan, gstin, ifsc } from "./validators.js";
export {
  Saaf,
  StreamRestorer,
  tokenPattern,
  type Action,
  type Applied,
  type MaskResult,
  type PolicyOptions,
  type RestoreResult,
} from "./saaf.js";

export const VERSION = "0.1.0-dev.0";
