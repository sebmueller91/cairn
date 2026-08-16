// Deliberately not Recharts: a ranked list of ~10 rows is a layout problem,
// not a charting one. Plain divs give real text (selectable, wrappable,
// screen-reader friendly), no ResponsiveContainer, and no chart bundle cost.

import { useEffect, useState, type ReactNode } from "react";

export type HBarItem = {
  label: ReactNode;
  value: number;
  color?: string;
  /** Extra right-hand slot — a P/L chip, a weight percentage. */
  secondary?: ReactNode;
  key?: string;
};

/** Ranked horizontal bars — top holdings, biggest movers, allocation by X. */
export function HBarList({
  items,
  formatValue,
  className = "",
}: {
  items: HBarItem[];
  formatValue: (n: number) => string;
  className?: string;
}) {
  // Bars grow from zero on mount. One flag for the whole list, so the rows
  // animate together rather than racing each other.
  const [grown, setGrown] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setGrown(true));
    return () => cancelAnimationFrame(id);
  }, []);

  // Scale to the largest magnitude present, so a list of negatives still
  // fills the width instead of collapsing to slivers.
  const max = items.reduce((m, i) => Math.max(m, Math.abs(i.value)), 0) || 1;

  return (
    <div className={`space-y-2.5 ${className}`}>
      {items.map((item, i) => {
        const color = item.color ?? "var(--accent)";
        const pct = (Math.abs(item.value) / max) * 100;
        return (
          <div key={item.key ?? i}>
            <div className="flex items-baseline gap-2 text-sm">
              <span className="truncate">{item.label}</span>
              <span className="tnum ml-auto shrink-0 font-medium">
                {formatValue(item.value)}
              </span>
              {item.secondary && (
                <span className="shrink-0">{item.secondary}</span>
              )}
            </div>
            <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-border/60">
              <div
                className="h-full rounded-full"
                style={{
                  width: grown ? `${pct}%` : "0%",
                  transition: "width 700ms cubic-bezier(0.22, 1, 0.36, 1)",
                  background: `linear-gradient(90deg, ${color}, color-mix(in srgb, ${color} 15%, transparent))`,
                  boxShadow: `0 0 10px color-mix(in srgb, ${color} 30%, transparent)`,
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
