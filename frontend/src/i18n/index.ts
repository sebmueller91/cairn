import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import deCommon from "./locales/de/common.json";
import deAssets from "./locales/de/assets.json";
import deSettings from "./locales/de/settings.json";
import deErrors from "./locales/de/errors.json";
import dePerformance from "./locales/de/performance.json";
import deTax from "./locales/de/tax.json";
import deOverview from "./locales/de/overview.json";
import deWealth from "./locales/de/wealth.json";
import dePortfolio from "./locales/de/portfolio.json";
import deData from "./locales/de/data.json";
import enCommon from "./locales/en/common.json";
import enAssets from "./locales/en/assets.json";
import enSettings from "./locales/en/settings.json";
import enErrors from "./locales/en/errors.json";
import enPerformance from "./locales/en/performance.json";
import enTax from "./locales/en/tax.json";
import enOverview from "./locales/en/overview.json";
import enWealth from "./locales/en/wealth.json";
import enPortfolio from "./locales/en/portfolio.json";
import enData from "./locales/en/data.json";

const STORAGE_KEY = "cairn-language";

// German default per spec 8.3. Mirrored to localStorage (not just the
// server-side `setting` row a future phase will add) so the right
// language is available immediately on a cold start, before any network
// round trip — this becomes load-bearing once phase 6 makes offline the
// normal case, not just a nicety now.
const stored = localStorage.getItem(STORAGE_KEY);

i18n
  .use(initReactI18next)
  .init({
    resources: {
      de: {
        common: deCommon,
        assets: deAssets,
        settings: deSettings,
        errors: deErrors,
        performance: dePerformance,
        tax: deTax,
        overview: deOverview,
        wealth: deWealth,
        portfolio: dePortfolio,
        data: deData,
      },
      en: {
        common: enCommon,
        assets: enAssets,
        settings: enSettings,
        errors: enErrors,
        performance: enPerformance,
        tax: enTax,
        overview: enOverview,
        wealth: enWealth,
        portfolio: enPortfolio,
        data: enData,
      },
    },
    lng: stored === "en" ? "en" : "de",
    fallbackLng: "de",
    defaultNS: "common",
    ns: [
      "common",
      "assets",
      "settings",
      "errors",
      "performance",
      "tax",
      "overview",
      "wealth",
      "portfolio",
      "data",
    ],
    interpolation: { escapeValue: false },
  });

i18n.on("languageChanged", (lng) => {
  localStorage.setItem(STORAGE_KEY, lng);
  document.documentElement.lang = lng;
});

export default i18n;
