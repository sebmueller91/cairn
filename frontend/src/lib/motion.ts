import { useEffect, useRef, useState } from "react";

/** True when the OS asks for reduced motion. Safe to call during render. */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

// ease-out-cubic: fast out of the gate, settles gently on the final digit.
function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

/**
 * Counts from the previously displayed value to `target` over `durationMs`.
 * Retargets from wherever it currently is if `target` changes mid-flight,
 * and snaps instantly under `prefers-reduced-motion: reduce`.
 */
export function useAnimatedNumber(target: number, durationMs = 600): number {
  const [display, setDisplay] = useState(target);
  // Read by the rAF loop without re-subscribing it; keeps the effect's only
  // real dependency the target itself.
  const displayRef = useRef(target);

  useEffect(() => {
    if (!Number.isFinite(target)) {
      displayRef.current = target;
      setDisplay(target);
      return;
    }
    const from = displayRef.current;
    // document.hidden covers a tab that is already in the background when
    // this mounts: no frames will fire, so animating would just freeze the
    // display on the old value.
    if (prefersReducedMotion() || durationMs <= 0 || from === target || document.hidden) {
      displayRef.current = target;
      setDisplay(target);
      return;
    }

    let frame = 0;
    let start: number | null = null;

    const step = (now: number) => {
      if (start === null) start = now;
      const t = Math.min((now - start) / durationMs, 1);
      const value = from + (target - from) * easeOutCubic(t);
      displayRef.current = value;
      setDisplay(value);
      if (t < 1) frame = requestAnimationFrame(step);
    };

    // A hidden tab stops firing frames, which would strand the display on
    // an intermediate value — a materially wrong euro figure, not just an
    // unfinished animation. Snap to the real number instead.
    const snapIfHidden = () => {
      if (!document.hidden) return;
      cancelAnimationFrame(frame);
      displayRef.current = target;
      setDisplay(target);
    };

    frame = requestAnimationFrame(step);
    document.addEventListener("visibilitychange", snapIfHidden);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("visibilitychange", snapIfHidden);
    };
  }, [target, durationMs]);

  return display;
}
