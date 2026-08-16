// A sheen sweeps left-to-right across a flat block. The keyframe lives in
// index.css (`animate-shimmer`) so the global prefers-reduced-motion block
// can stop it — reduced motion leaves a plain, still placeholder.
const SHIMMER =
  "animate-shimmer bg-bg-subtle bg-[length:200%_100%] " +
  "bg-[linear-gradient(90deg,transparent_0%,var(--skeleton-sheen)_50%,transparent_100%)]";

/**
 * Loading placeholder. Size it entirely through `className`
 * (e.g. `h-8 w-40`) so it can mimic whatever it stands in for.
 */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden className={`rounded-md ${SHIMMER} ${className}`} />;
}

/** Two or three staggered lines, for a paragraph-shaped loading state. */
export function SkeletonText({
  lines = 3,
  className = "",
}: {
  lines?: number;
  className?: string;
}) {
  // Ragged widths, like real text — a stack of equal bars reads as a table.
  const widths = ["w-full", "w-11/12", "w-2/3", "w-3/4", "w-5/6"];
  return (
    <div className={`space-y-2 ${className}`}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={`h-3 ${widths[i % widths.length]}`} />
      ))}
    </div>
  );
}
