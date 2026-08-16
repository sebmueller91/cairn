import { useTranslation } from "react-i18next";
import { ChipToggleGroup, type ChipItem } from "./ui/ChipToggleGroup";
import { ASSET_CLASSES, ASSET_CLASS_COLORS, assetClassLabelKey } from "../lib/assetClasses";
import { useAssetFilter } from "../lib/assetFilter";

/** The global asset-class filter row — shared by every page that scopes to it. */
export function AssetClassChips({ className = "" }: { className?: string }) {
  const { t } = useTranslation("common");
  const { selected, toggle, reset, allSelected } = useAssetFilter();

  const items: ChipItem[] = ASSET_CLASSES.map((c) => ({
    key: c,
    label: t(assetClassLabelKey(c)),
    color: ASSET_CLASS_COLORS[c],
    selected: selected.has(c),
  }));

  if (!allSelected) {
    items.push({ key: "__reset", label: t("filter.reset"), selected: false });
  }

  function handleToggle(key: string) {
    if (key === "__reset") {
      reset();
      return;
    }
    toggle(key as (typeof ASSET_CLASSES)[number]);
  }

  return <ChipToggleGroup items={items} onToggle={handleToggle} className={className} />;
}
