/**
 * Named validators referenced by spec/entities.json.
 * Port of packages/saaf-core/src/saaf/validators.py; pinned by
 * spec/conformance/validators.jsonl.
 */

const D = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
  [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
  [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
  [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
  [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
  [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
  [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
  [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
  [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
  [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
];
const P = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
  [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
  [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
  [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
  [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
  [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
  [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
  [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
];
const INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9];

const isDigits = (v: string) => /^[0-9]+$/.test(v);
const isAlpha = (v: string) => /^[A-Za-z]+$/.test(v);
const isAlnum = (v: string) => /^[A-Za-z0-9]+$/.test(v);

export function verhoeff(value: string): boolean {
  if (!isDigits(value)) return false;
  let c = 0;
  const digits = [...value].reverse();
  digits.forEach((ch, i) => {
    c = D[c]![P[i % 8]![Number(ch)]!]!;
  });
  return c === 0;
}

export function verhoeffCheckDigit(payload: string): string {
  let c = 0;
  [...payload].reverse().forEach((ch, i) => {
    c = D[c]![P[(i + 1) % 8]![Number(ch)]!]!;
  });
  return String(INV[c]);
}

export function aadhaar(value: string): boolean {
  return value.length === 12 && "23456789".includes(value[0]!) && verhoeff(value);
}

export function luhn(value: string): boolean {
  if (!isDigits(value) || value.length < 2) return false;
  let total = 0;
  [...value].reverse().forEach((ch, i) => {
    let d = Number(ch);
    if (i % 2 === 1) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    total += d;
  });
  return total % 10 === 0;
}

const CARD_PREFIXES = [
  "4", "51", "52", "53", "54", "55", "34", "37", "36", "38", "300", "301", "302", "303", "304", "305",
  "60", "65", "81", "82", "508", "353", "356", "6011", "644", "645", "646", "647", "648", "649", "35",
];

export function card(value: string): boolean {
  if (value.length < 13 || value.length > 19 || new Set(value).size === 1) return false;
  const iin = Number(value.slice(0, 4));
  if (!CARD_PREFIXES.some((p) => value.startsWith(p)) && !(iin >= 2221 && iin <= 2720)) return false;
  return luhn(value);
}

const PAN_HOLDER_TYPES = "ABCFGHJLPT";

export function pan(value: string): boolean {
  const v = value.toUpperCase();
  return (
    v.length === 10 &&
    isAlpha(v.slice(0, 5)) &&
    isDigits(v.slice(5, 9)) &&
    isAlpha(v[9]!) &&
    PAN_HOLDER_TYPES.includes(v[3]!)
  );
}

const GST_STATE_CODES = new Set([
  ...Array.from({ length: 38 }, (_, i) => String(i + 1).padStart(2, "0")),
  "97",
  "99",
]);
const GST_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";

export function gstinCheckChar(first14: string): string {
  let total = 0;
  [...first14].forEach((ch, i) => {
    const product = GST_CHARS.indexOf(ch) * (i % 2 ? 2 : 1);
    total += Math.floor(product / 36) + (product % 36);
  });
  return GST_CHARS[(36 - (total % 36)) % 36]!;
}

export function gstin(value: string): boolean {
  const v = value.toUpperCase();
  if (v.length !== 15 || !isAlnum(v)) return false;
  if (!GST_STATE_CODES.has(v.slice(0, 2)) || !pan(v.slice(2, 12))) return false;
  return gstinCheckChar(v.slice(0, 14)) === v[14];
}

export function ifsc(value: string): boolean {
  const v = value.toUpperCase();
  return v.length === 11 && isAlpha(v.slice(0, 4)) && v[4] === "0" && isAlnum(v.slice(5));
}

export const UPI_HANDLES = new Set(
  `okaxis okhdfcbank okicici oksbi ybl ibl axl paytm ptyes ptaxis pthdfc ptsbi
  upi apl yapl rapl waicici wahdfcbank waaxis wasbi axisbank axisb icici hdfcbank
  sbi kotak kotak811 freecharge airtel airtelpaymentsbank jio fbl idfcbank idfcfirst
  indus pnb barodampay unionbankofindia unionbank ikwik mbk abfspay timecosmos
  naviaxis superyes kbl cnrb boi citi citigold hsbc yesbank yesbankltd aubank dbs
  federal rbl sib kvb tjsb equitas ujjivan jupiteraxis fam slice postbank ippb
  dlb pingpay pockets payzapp idbi uco mahb indianbank centralbank iob`
    .split(/\s+/)
    .filter(Boolean),
);

export function upiHandle(value: string): boolean {
  const at = value.lastIndexOf("@");
  if (at < 0) return false;
  return at >= 2 && UPI_HANDLES.has(value.slice(at + 1).toLowerCase());
}

export function inMobile(value: string): boolean {
  let digits = value;
  if (digits.length === 12 && digits.startsWith("91")) digits = digits.slice(2);
  else if (digits.length === 11 && digits.startsWith("0")) digits = digits.slice(1);
  if (digits.length !== 10 || !"6789".includes(digits[0]!)) return false;
  return new Set(digits.slice(1)).size > 1;
}

export const STATE_CODES = new Set(
  `AN AP AR AS BR CH CG CT DD DL DN GA GJ HR HP JK JH KA KL LA LD MP MH MN ML MZ
  NL OD OR PB PY RJ SK TN TS TG TR UP UK UA WB`
    .split(/\s+/)
    .filter(Boolean),
);

export function inStateCode(value: string): boolean {
  return STATE_CODES.has(value.slice(0, 2).toUpperCase());
}

export function udyam(value: string): boolean {
  const v = value.toUpperCase();
  return v.startsWith("UDYAM") && STATE_CODES.has(v.slice(5, 7));
}

export const VALIDATORS: Record<string, (v: string) => boolean> = {
  verhoeff,
  aadhaar,
  luhn,
  card,
  pan,
  gstin,
  ifsc,
  upi_handle: upiHandle,
  in_mobile: inMobile,
  in_state_code: inStateCode,
  udyam,
};
