/**
 * Normalises a hand-typed amount into the plain decimal string the API
 * expects (ADR 0001 — money crosses the wire as a string, never a float).
 *
 * The cash-balance modal is the only place a human still types a number
 * into Cairn, and they type it the way their keyboard and locale suggest:
 * "12.345,67" in German, "12,345.67" in English, sometimes with a currency
 * symbol pasted along. Whichever separator comes last is the decimal one;
 * everything else is grouping.
 *
 * Returns null when the result would not be a plain decimal, so the caller
 * can refuse to submit rather than send something the backend will reject.
 */
export function parseDecimalInput(raw: string): string | null {
  const cleaned = raw.replace(/[\s €$£]/g, "");
  if (!cleaned) return null;

  const lastComma = cleaned.lastIndexOf(",");
  const lastDot = cleaned.lastIndexOf(".");
  let normalized: string;

  if (lastComma >= 0 && lastDot >= 0) {
    // Both present: the rightmost separates the decimals, the other groups.
    const decimalSep = lastComma > lastDot ? "," : ".";
    const groupSep = decimalSep === "," ? "." : ",";
    normalized = cleaned.split(groupSep).join("").replace(decimalSep, ".");
  } else if (lastComma >= 0) {
    // A lone comma is always a decimal comma here: German is the default
    // locale, and "1,5" meaning one-and-a-half is the common case.
    normalized = cleaned.replace(",", ".");
  } else {
    // A lone dot is already valid decimal syntax; leave it alone rather
    // than guessing that "12.345" meant twelve thousand.
    normalized = cleaned;
  }

  return /^-?\d+(\.\d+)?$/.test(normalized) ? normalized : null;
}
