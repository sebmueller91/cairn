import type { ReactNode } from "react";

export type ChipItem = {
  key: string;
  label: ReactNode;
  /** Any CSS colour; asset-class filters pass `ASSET_CLASS_COLORS[cls]`. */
  color?: string;
  selected: boolean;
};

/** Multi-select pill row — filter chips that scroll sideways instead of wrapping. */
export function ChipToggleGroup({
  items,
  onToggle,
  className = "",
}: {
  items: ChipItem[];
  onToggle: (key: string) => void;
  className?: string;
}) {
  return (
    <div
      role="group"
      className={`no-scrollbar -mx-1 flex gap-2 overflow-x-auto px-1 py-1 ${className}`}
    >
      {items.map((item) => {
        const color = item.color ?? "var(--accent)";
        return (
          <button
            key={item.key}
            type="button"
            aria-pressed={item.selected}
            onClick={() => onToggle(item.key)}
            className={`inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-full border px-3 text-sm font-medium transition-colors ${
              item.selected
                ? ""
                : "border-border text-text-muted hover:text-text"
            }`}
            // Per-item colours can't be Tailwind classes (they're runtime
            // values), so the selected skin is composed with color-mix here.
            style={
              item.selected
                ? {
                    color,
                    borderColor: `color-mix(in srgb, ${color} 55%, transparent)`,
                    backgroundColor: `color-mix(in srgb, ${color} 15%, transparent)`,
                    boxShadow: `0 0 12px color-mix(in srgb, ${color} 22%, transparent)`,
                  }
                : undefined
            }
          >
            {item.color && (
              <span
                aria-hidden
                className="size-2 shrink-0 rounded-full"
                style={{ backgroundColor: color }}
              />
            )}
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
