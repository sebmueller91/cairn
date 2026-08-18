import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "cairn-privacy";
const ATTRIBUTE = "data-privacy";

/**
 * Privacy mode: euro amounts are blurred so the app can be shown to someone
 * without showing them the numbers.
 *
 * Deliberately a root attribute plus one CSS rule rather than React state
 * threaded through every card. Blurring is presentation, so nothing has to
 * re-render when it flips — the toggle is instant, it cannot get out of step
 * with what is on screen, and a component added later inherits the behaviour
 * by wearing the `sensitive` class rather than by subscribing to anything.
 *
 * What it hides is only the money. Percentages, weights, dates, ranges and
 * instrument names stay legible, because those are what make the app worth
 * showing to someone in the first place.
 *
 * It is a screen-sharing courtesy, not a security control: the values are
 * still in the DOM, and anyone with the developer tools or the page source
 * can read them. Blur protects against a glance over your shoulder, nothing
 * more.
 */
function apply(on: boolean) {
  const root = document.documentElement;
  if (on) root.setAttribute(ATTRIBUTE, "on");
  else root.removeAttribute(ATTRIBUTE);
  localStorage.setItem(STORAGE_KEY, on ? "on" : "off");
}

function readStored(): boolean {
  return localStorage.getItem(STORAGE_KEY) === "on";
}

export function usePrivacy() {
  const [enabled, setEnabled] = useState(readStored);

  // Runs on mount too, so a reload restores the blur before anything is
  // painted rather than flashing the real numbers first.
  useEffect(() => {
    apply(enabled);
  }, [enabled]);

  const toggle = useCallback(() => setEnabled((v) => !v), []);

  return { enabled, toggle };
}
