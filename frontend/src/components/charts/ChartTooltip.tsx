import type { ReactNode } from "react";

// Recharts clones whatever element is handed to `content=` and injects
// active/payload/label. Those three are therefore optional here, so the
// call site can write `<ChartTooltip formatValue={fmt} />` and typecheck.
type PayloadItem = {
  name?: string | number;
  dataKey?: string | number;
  value?: number | string | ReadonlyArray<number | string>;
  color?: string;
  stroke?: string;
  fill?: string;
  payload?: Record<string, unknown>;
};

/** Glass tooltip used by every chart wrapper — pass it as `content=`. */
export function ChartTooltip({
  active,
  payload,
  label,
  formatValue,
  formatLabel,
  /** Restrict the rows to these dataKeys (waterfall hides its invisible base). */
  only,
  /** Series names are noise on a single-series chart. */
  hideName = false,
}: {
  active?: boolean;
  payload?: ReadonlyArray<PayloadItem>;
  label?: string | number;
  formatValue: (n: number) => string;
  formatLabel?: (label: string | number) => ReactNode;
  only?: ReadonlyArray<string>;
  hideName?: boolean;
}) {
  if (!active || !payload || payload.length === 0) return null;

  const rows = only
    ? payload.filter((p) => only.includes(String(p.dataKey)))
    : payload;
  if (rows.length === 0) return null;

  return (
    <div className="rounded-lg border border-border bg-bg-subtle/90 px-3 py-2 text-xs shadow-lg backdrop-blur-glass">
      {label !== undefined && (
        <div className="mb-1.5 font-medium text-text-muted">
          {formatLabel ? formatLabel(label) : label}
        </div>
      )}
      <div className="space-y-1">
        {rows.map((row, i) => (
          <div
            key={`${String(row.dataKey)}-${i}`}
            className="flex items-center gap-2"
          >
            <span
              aria-hidden
              className="size-2 shrink-0 rounded-full"
              style={{ backgroundColor: row.color ?? row.stroke ?? row.fill }}
            />
            {!hideName && row.name !== undefined && (
              <span className="text-text-muted">{row.name}</span>
            )}
            <span className="tnum sensitive ml-auto font-medium">
              {formatValue(Number(row.value))}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
