import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ASSET_CLASSES, type AssetClass } from "./assetClasses";

const STORAGE_KEY = "cairn-asset-filter";

function readStoredSelection(): Set<AssetClass> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set(ASSET_CLASSES);
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set(ASSET_CLASSES);
    const valid = parsed.filter((v): v is AssetClass =>
      (ASSET_CLASSES as readonly string[]).includes(v as string),
    );
    // Garbage or an emptied-out array both fall back to "all" — an empty
    // filter is never a meaningful persisted state (see toggle() below).
    return valid.length > 0 ? new Set(valid) : new Set(ASSET_CLASSES);
  } catch {
    return new Set(ASSET_CLASSES);
  }
}

interface AssetFilterState {
  selected: Set<AssetClass>;
  toggle: (c: AssetClass) => void;
  reset: () => void;
  allSelected: boolean;
}

const AssetFilterContext = createContext<AssetFilterState | null>(null);

export function AssetFilterProvider({ children }: { children: ReactNode }) {
  const [selected, setSelected] = useState<Set<AssetClass>>(readStoredSelection);

  const persist = useCallback((next: Set<AssetClass>) => {
    setSelected(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(next)));
  }, []);

  const toggle = useCallback(
    (c: AssetClass) => {
      setSelected((prev) => {
        const next = new Set(prev);
        if (next.has(c)) {
          // Never allow the empty set — a portfolio chart with nothing
          // selected is meaningless, so a toggle that would empty it is
          // simply ignored rather than auto-resetting back to "all"
          // (which would silently discard the user's other deselections).
          if (next.size === 1) return prev;
          next.delete(c);
        } else {
          next.add(c);
        }
        localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(next)));
        return next;
      });
    },
    [],
  );

  const reset = useCallback(() => {
    persist(new Set(ASSET_CLASSES));
  }, [persist]);

  const allSelected = selected.size === ASSET_CLASSES.length;

  const value = useMemo(
    () => ({ selected, toggle, reset, allSelected }),
    [selected, toggle, reset, allSelected],
  );

  return (
    <AssetFilterContext.Provider value={value}>{children}</AssetFilterContext.Provider>
  );
}

export function useAssetFilter(): AssetFilterState {
  const ctx = useContext(AssetFilterContext);
  if (!ctx) throw new Error("useAssetFilter must be used within AssetFilterProvider");
  return ctx;
}
