import { useId } from "react";

// Hand-rolled SVG rather than Recharts: these are decorative, appear many
// to a screen (one per row in a list), and a ResponsiveContainer per row
// would cost a ResizeObserver each. No axes, no tooltip, no interaction.

/** Tiny trend line with a fading area fill. Decorative — pair it with a real number. */
export function Sparkline({
  data,
  width = 100,
  height = 28,
  color = "var(--accent)",
  className = "",
}: {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  className?: string;
}) {
  // Unique per instance so several sparklines on one page don't share a
  // gradient id — different `color` props would otherwise collide. React's
  // useId wraps its value in punctuation that has no business in a FuncIRI
  // fragment, hence the strip.
  const gradientId = `spark-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;

  if (data.length < 2) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  // A flat series would divide by zero; draw it down the middle instead.
  const span = max - min || 1;
  const pad = 1.5; // keeps the 1.5px stroke from clipping at the edges
  const stepX = width / (data.length - 1);

  const points = data.map((v, i) => {
    const x = i * stepX;
    const y = pad + (1 - (v - min) / span) * (height - pad * 2);
    return [x, y] as const;
  });

  const line = points.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  const area = `${line} ${width},${height} 0,${height}`;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-hidden
      className={className}
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.35} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <polygon points={area} fill={`url(#${gradientId})`} />
      <polyline
        points={line}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
