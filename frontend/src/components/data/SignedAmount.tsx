import { formatCurrency } from "../../lib/format";

/**
 * Signed EUR amount — colour carries the sign but never carries it alone
 * (spec 8.2): an arrow glyph repeats the same information for colour-blind
 * readers. Shared by the Ledger and Positions tabs.
 */
export function SignedAmount({ value, lang }: { value: string | null | undefined; lang: string }) {
  if (value == null) return <span className="text-text-muted">—</span>;
  const n = Number(value);
  const cls = n > 0 ? "text-positive" : n < 0 ? "text-negative" : "text-text-muted";
  const arrow = n > 0 ? "▲" : n < 0 ? "▼" : "";
  return (
    <span className={cls}>
      {arrow} {formatCurrency(value, lang)}
    </span>
  );
}
