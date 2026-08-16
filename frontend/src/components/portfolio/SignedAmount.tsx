import { formatCurrency } from "../../lib/format";

/**
 * Sign carried by colour AND a leading +/− glyph, never colour alone
 * (spec 8.2) — colour-blind-safe by construction.
 */
export function SignedAmount({
  value,
  lang,
  className = "",
}: {
  value: string | number | null | undefined;
  lang: string;
  className?: string;
}) {
  if (value === null || value === undefined) {
    return <span className="text-text-muted">—</span>;
  }
  const n = typeof value === "string" ? Number(value) : value;
  const cls = n > 0 ? "text-positive" : n < 0 ? "text-negative" : "text-text-muted";
  return (
    <span className={`tnum ${cls} ${className}`}>
      {n > 0 ? "+" : ""}
      {formatCurrency(n, lang)}
    </span>
  );
}
