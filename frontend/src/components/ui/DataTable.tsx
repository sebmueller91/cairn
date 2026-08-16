import type { ReactNode } from "react";

export type Column<T> = {
  key: string;
  header: ReactNode;
  align?: "left" | "right" | "center";
  render: (row: T) => ReactNode;
};

const ALIGN: Record<"left" | "right" | "center", string> = {
  left: "text-left",
  right: "text-right tnum",
  center: "text-center",
};

/**
 * Table shell with a sticky header and horizontal overflow. Deliberately
 * dumb — sorting, filtering and pagination stay with the caller, who owns
 * the data anyway.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  maxHeight,
  className = "",
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  /**
   * CSS length. `overflow-x: auto` makes this div a scroll container on
   * both axes, so the sticky header only actually sticks once the box has
   * a bounded height — pass one for long tables.
   */
  maxHeight?: string;
  className?: string;
}) {
  return (
    <div
      className={`overflow-x-auto ${className}`}
      style={{ WebkitOverflowScrolling: "touch", maxHeight }}
    >
      <table className="w-full min-w-full border-collapse text-sm">
        <thead className="sticky top-0 z-10 bg-bg-subtle">
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={`border-b border-border px-3 py-2 text-xs font-medium uppercase tracking-wide text-text-muted ${
                  ALIGN[col.align ?? "left"]
                }`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={`border-b border-border/60 transition-colors hover:bg-bg-subtle/60 ${
                onRowClick ? "cursor-pointer" : ""
              }`}
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={`px-3 py-2.5 ${ALIGN[col.align ?? "left"]}`}
                >
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
