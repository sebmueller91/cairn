import { describe, expect, it } from "vitest";
import {
  ASSET_CLASSES,
  ASSET_PRESETS,
  matchesPreset,
  type AssetClass,
} from "./assetClasses";

describe("asset presets", () => {
  it("only ever names classes that exist", () => {
    // A typo here would silently produce a preset that can never match,
    // and a chip that appears to do nothing when clicked.
    for (const preset of ASSET_PRESETS) {
      for (const cls of preset.classes) {
        expect(ASSET_CLASSES).toContain(cls);
      }
    }
  });

  it("never offers an empty preset", () => {
    // selectOnly() ignores an empty list, so an empty preset would be a
    // dead chip rather than a visible error.
    for (const preset of ASSET_PRESETS) {
      expect(preset.classes.length).toBeGreaterThan(0);
    }
  });

  it("pairs the house with the loan against it", () => {
    const property = ASSET_PRESETS.find((p) => p.key === "property");
    expect(property?.classes).toEqual(["REAL_ESTATE", "LIABILITY"]);
  });

  it("keeps the house, car, pensions and cash out of the depot", () => {
    const depot = ASSET_PRESETS.find((p) => p.key === "depot");
    expect(depot?.classes).not.toContain("REAL_ESTATE");
    expect(depot?.classes).not.toContain("VEHICLE");
    expect(depot?.classes).not.toContain("BOND");
    expect(depot?.classes).not.toContain("CASH");
    expect(depot?.classes).not.toContain("LIABILITY");
  });
});

describe("matchesPreset", () => {
  const depot: readonly AssetClass[] = ["EQUITY", "CRYPTO", "COMMODITY"];

  it("matches regardless of insertion order", () => {
    expect(matchesPreset(new Set<AssetClass>(["COMMODITY", "EQUITY", "CRYPTO"]), depot)).toBe(
      true,
    );
  });

  it("does not match a superset", () => {
    // The whole point of the highlight: adding one class means you are no
    // longer looking at "Depot", and the row must stop claiming you are.
    expect(
      matchesPreset(new Set<AssetClass>(["EQUITY", "CRYPTO", "COMMODITY", "CASH"]), depot),
    ).toBe(false);
  });

  it("does not match a subset", () => {
    expect(matchesPreset(new Set<AssetClass>(["EQUITY", "CRYPTO"]), depot)).toBe(false);
  });

  it("matches the all-preset exactly when nothing is filtered out", () => {
    const all = ASSET_PRESETS.find((p) => p.key === "all")!;
    expect(matchesPreset(new Set(ASSET_CLASSES), all.classes)).toBe(true);
  });
});
