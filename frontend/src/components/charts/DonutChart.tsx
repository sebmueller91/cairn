import type { ReactNode } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { ChartTooltip } from "./ChartTooltip";

export type DonutSlice = { name: string; value: number; color: string };

/**
 * Allocation donut. Collapsing a long tail into "Other" is the caller's job —
 * only the caller knows how many slices are meaningful for its data.
 * `children` renders as a centred overlay (Recharts' own label positioning
 * for a donut hole is more trouble than an absolutely positioned div).
 */
export function DonutChart({
  data,
  height = 240,
  formatValue,
  children,
}: {
  data: DonutSlice[];
  height?: number;
  formatValue: (n: number) => string;
  children?: ReactNode;
}) {
  return (
    <div className="relative" style={{ height }}>
      <ResponsiveContainer width="100%" height={height}>
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="name"
            innerRadius="62%"
            outerRadius="85%"
            paddingAngle={2}
            stroke="none"
          >
            {data.map((slice) => (
              <Cell key={slice.name} fill={slice.color} />
            ))}
          </Pie>
          <Tooltip content={<ChartTooltip formatValue={formatValue} />} />
        </PieChart>
      </ResponsiveContainer>
      {children && (
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
          {children}
        </div>
      )}
    </div>
  );
}
