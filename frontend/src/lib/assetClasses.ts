// The asset-class vocabulary and its one true colour mapping. Everything
// that paints an asset class — donut slices, stacked areas, legend chips,
// table dots — reads from here, so a class cannot be sky-blue in one view
// and violet in the next.
//
// Colours resolve to CSS vars rather than literals on purpose: the light
// theme darkens every hue a step, and `var(--chart-equity)` picks that up
// for free, including inside SVG `fill`/`stroke` attributes.

export const ASSET_CLASSES = [
  "EQUITY",
  "BOND",
  "COMMODITY",
  "CRYPTO",
  "REAL_ESTATE",
  "VEHICLE",
  "CASH",
  "LIABILITY",
] as const;

export type AssetClass = (typeof ASSET_CLASSES)[number];

export const ASSET_CLASS_COLORS: Record<AssetClass, string> = {
  EQUITY: "var(--chart-equity)",
  BOND: "var(--chart-bond)",
  COMMODITY: "var(--chart-commodity)",
  CRYPTO: "var(--chart-crypto)",
  REAL_ESTATE: "var(--chart-real-estate)",
  VEHICLE: "var(--chart-vehicle)",
  CASH: "var(--chart-cash)",
  LIABILITY: "var(--chart-liability)",
};

/**
 * i18n key for an asset class label, e.g. `assetClass.EQUITY`.
 * The translations themselves land in a later phase.
 */
export function assetClassLabelKey(c: AssetClass): string {
  return `assetClass.${c}`;
}

/**
 * Named combinations of asset classes offered as one-click presets.
 *
 * `depot` is the set that behaves like an actual investment portfolio —
 * things bought to grow — as opposed to the house, the car, the pension
 * wrappers and the current account, which are wealth but not positions you
 * revisit. `property` pairs the house with the loan against it, because
 * either one alone is a misleading number.
 */
export const ASSET_PRESETS: {
  key: string;
  classes: readonly AssetClass[];
}[] = [
  { key: "all", classes: ASSET_CLASSES },
  { key: "depot", classes: ["EQUITY", "CRYPTO", "COMMODITY"] },
  { key: "equityOnly", classes: ["EQUITY"] },
  { key: "property", classes: ["REAL_ESTATE", "LIABILITY"] },
];

/** True when `selection` is exactly `classes` — a preset counts as active
 * only on an exact match, so touching any single class chip afterwards
 * drops the highlight rather than leaving a stale label on the row. */
export function matchesPreset(
  selection: Set<AssetClass>,
  classes: readonly AssetClass[],
): boolean {
  return selection.size === classes.length && classes.every((c) => selection.has(c));
}
