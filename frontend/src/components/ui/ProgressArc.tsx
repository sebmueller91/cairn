import { useEffect, useState, type ReactNode } from "react";

/** Circular progress ring with a centred label — for goals and milestones. */
export function ProgressArc({
  pct,
  size = 128,
  strokeWidth = 8,
  color = "var(--accent)",
  label,
  sublabel,
  className = "",
}: {
  /** 0..100; values outside are clamped. */
  pct: number;
  size?: number;
  strokeWidth?: number;
  color?: string;
  label?: ReactNode;
  sublabel?: ReactNode;
  className?: string;
}) {
  const clamped = Math.max(0, Math.min(100, Number.isFinite(pct) ? pct : 0));
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;

  // Start empty, then flip to the real value one paint later so the browser
  // has a previous value to transition *from*. Reduced motion is handled by
  // the global rule in index.css, which collapses the transition duration.
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const id = requestAnimationFrame(() => setShown(clamped));
    return () => cancelAnimationFrame(id);
  }, [clamped]);

  return (
    <div
      className={`relative inline-flex items-center justify-center ${className}`}
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} aria-hidden className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--border)"
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - shown / 100)}
          style={{
            transition: "stroke-dashoffset 900ms cubic-bezier(0.22, 1, 0.36, 1)",
            filter: `drop-shadow(0 0 6px color-mix(in srgb, ${color} 40%, transparent))`,
          }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
        {label && (
          <div className="tnum text-xl font-[650] tracking-tight">{label}</div>
        )}
        {sublabel && (
          <div className="mt-0.5 text-xs text-text-muted">{sublabel}</div>
        )}
      </div>
    </div>
  );
}
