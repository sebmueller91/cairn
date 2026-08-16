import type { ReactNode } from "react";

/** Page title with an optional actions slot and a row beneath it for filters. */
export function PageHeader({
  title,
  actions,
  children,
  className = "",
}: {
  title: ReactNode;
  /** Right-aligned controls — a SegmentedControl, a button, a menu. */
  actions?: ReactNode;
  /** Row below the title, typically a ChipToggleGroup. */
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`space-y-3 ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  );
}
