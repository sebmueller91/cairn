import type { ReactNode } from "react";
import { useAnimatedNumber } from "../../lib/motion";

/** The one big number on a screen: label, animated value, optional delta chip and sparkline. */
export function StatHero({
  label,
  value,
  format,
  delta,
  formatDelta,
  deltaCaption,
  children,
  className = "",
}: {
  label: ReactNode;
  value: number;
  /** Caller owns locale/currency — pass e.g. `(n) => formatCurrency(n, i18n.language)`. */
  format: (n: number) => string;
  /** Signed change over the selected period; renders a coloured ± chip. */
  delta?: number;
  /** Defaults to `format`. Pass a percent formatter when the delta is relative. */
  formatDelta?: (n: number) => string;
  /** Small note beside the delta chip — what period the delta and the
   * sparkline actually cover. Without it the chip is an unlabelled number. */
  deltaCaption?: ReactNode;
  /** Slot under the value — a Sparkline fits here. */
  children?: ReactNode;
  className?: string;
}) {
  const animated = useAnimatedNumber(value);
  const deltaFmt = formatDelta ?? format;
  const up = (delta ?? 0) >= 0;

  return (
    <div className={className}>
      <div className="text-sm text-text-muted">{label}</div>
      <div className="mt-1 flex flex-wrap items-baseline gap-3">
        <span className="tnum text-4xl font-[650] tracking-tight md:text-5xl">
          {format(animated)}
        </span>
        {delta !== undefined && (
          <span
            className={`tnum inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-sm font-medium ${
              up
                ? "border-positive/30 bg-positive/10 text-positive"
                : "border-negative/30 bg-negative/10 text-negative"
            }`}
            style={{
              boxShadow: up ? "var(--glow-positive)" : "var(--glow-negative)",
            }}
          >
            <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
              <path
                d={up ? "M5 1 L9 8 L1 8 Z" : "M5 9 L1 2 L9 2 Z"}
                fill="currentColor"
              />
            </svg>
            {deltaFmt(delta)}
          </span>
        )}
        {deltaCaption && (
          <span className="text-xs text-text-muted">{deltaCaption}</span>
        )}
      </div>
      {children && <div className="mt-3">{children}</div>}
    </div>
  );
}
