import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import deCommon from "./locales/de/common.json";
import deDashboard from "./locales/de/dashboard.json";
import deAssets from "./locales/de/assets.json";
import deSettings from "./locales/de/settings.json";
import deErrors from "./locales/de/errors.json";
import enCommon from "./locales/en/common.json";
import enDashboard from "./locales/en/dashboard.json";
import enAssets from "./locales/en/assets.json";
import enSettings from "./locales/en/settings.json";
import enErrors from "./locales/en/errors.json";

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
        dashboard: deDashboard,
        assets: deAssets,
        settings: deSettings,
        errors: deErrors,
      },
      en: {
        common: enCommon,
        dashboard: enDashboard,
        assets: enAssets,
        settings: enSettings,
        errors: enErrors,
      },
    },
    lng: stored === "en" ? "en" : "de",
    fallbackLng: "de",
    defaultNS: "common",
    ns: ["common", "dashboard", "assets", "settings", "errors"],
    interpolation: { escapeValue: false },
  });

i18n.on("languageChanged", (lng) => {
  localStorage.setItem(STORAGE_KEY, lng);
  document.documentElement.lang = lng;
});

export default i18n;
