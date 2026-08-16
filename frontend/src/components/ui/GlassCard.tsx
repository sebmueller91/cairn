import type { ReactNode } from "react";

/** Translucent, blurred panel — the default surface for everything on a page. */
export function GlassCard({
  children,
  glow = false,
  className = "",
}: {
  children: ReactNode;
  /** Adds the accent halo. Reserve it for the one hero panel per screen. */
  glow?: boolean;
  className?: string;
}) {
  return (
    <div
      // rounded-card / backdrop-blur-glass come from the @theme tokens in
      // index.css, so the radius and blur strength are tunable in one place.
      className={`rounded-card border border-border bg-bg-card p-4 backdrop-blur-glass md:p-5 ${className}`}
      style={glow ? { boxShadow: "var(--glow-accent)" } : undefined}
    >
      {children}
    </div>
  );
}
