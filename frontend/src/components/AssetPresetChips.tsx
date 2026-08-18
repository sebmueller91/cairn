import { useTranslation } from "react-i18next";
import { ChipToggleGroup, type ChipItem } from "./ui/ChipToggleGroup";
import { ASSET_PRESETS, matchesPreset } from "../lib/assetClasses";
import { useAssetFilter } from "../lib/assetFilter";

/** Second filter row: named combinations of the class chips above.
 *
 * A preset is a shortcut, not a separate filter — it writes the same
 * selection the individual chips write, so the two rows can never disagree
 * about what is showing. */
export function AssetPresetChips({ className = "" }: { className?: string }) {
  const { t } = useTranslation("common");
  const { selected, selectOnly } = useAssetFilter();

  const items: ChipItem[] = ASSET_PRESETS.map((preset) => ({
    key: preset.key,
    label: t(`presets.${preset.key}`),
    selected: matchesPreset(selected, preset.classes),
  }));

  function handleToggle(key: string) {
    const preset = ASSET_PRESETS.find((p) => p.key === key);
    if (preset) selectOnly(preset.classes);
  }

  return <ChipToggleGroup items={items} onToggle={handleToggle} className={className} />;
}
