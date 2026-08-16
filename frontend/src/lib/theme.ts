import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark" | "system";

const STORAGE_KEY = "cairn-theme";

/** Dark is the product's default look; "system" is now an opt-in, not the fallback. */
const DEFAULT_THEME: Theme = "dark";

const THEME_COLOR: Record<"light" | "dark", string> = {
  dark: "#05070d",
  light: "#ffffff",
};

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") {
    // No data-theme => the CSS cascade falls through to the media queries.
    // Note this is *persisted* rather than represented by an absent key:
    // since the default flipped to dark, "nothing stored" and "follow the
    // OS" are no longer the same answer.
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", theme);
  }
  localStorage.setItem(STORAGE_KEY, theme);

  const isDark =
    theme === "dark" ||
    (theme === "system" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", isDark ? THEME_COLOR.dark : THEME_COLOR.light);
}

function readStoredTheme(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === "light" || stored === "dark" || stored === "system"
    ? stored
    : DEFAULT_THEME;
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(readStoredTheme);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // On "system", the OS can flip underneath us; keep the address-bar tint
  // in sync with what the cascade is actually rendering.
  useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  const setTheme = useCallback((t: Theme) => setThemeState(t), []);

  return [theme, setTheme];
}
