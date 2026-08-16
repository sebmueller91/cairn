#!/usr/bin/env node
// Verifies the two locale trees carry exactly the same key set. A key
// present in one language and missing in the other silently falls back
// (i18next `fallbackLng: "de"`) or renders the raw key — either way it's a
// bug that's easy to miss by eye, so CI checks it structurally instead.
// No dependencies: this repo only ever needs plain fs/path.

import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const LOCALES_DIR = path.join(__dirname, "..", "src", "i18n", "locales");
const LANGUAGES = ["de", "en"];

function readJson(filePath) {
  return JSON.parse(readFileSync(filePath, "utf-8"));
}

/** Flattens a nested object into dot-joined key paths, e.g. "nav.overview". */
function flattenKeys(obj, prefix = "") {
  const keys = [];
  for (const [key, value] of Object.entries(obj)) {
    const path_ = prefix ? `${prefix}.${key}` : key;
    if (value !== null && typeof value === "object" && !Array.isArray(value)) {
      keys.push(...flattenKeys(value, path_));
    } else {
      keys.push(path_);
    }
  }
  return keys;
}

function listJsonFiles(dir) {
  try {
    return readdirSync(dir).filter((f) => f.endsWith(".json"));
  } catch {
    return [];
  }
}

const dirsByLang = Object.fromEntries(
  LANGUAGES.map((lng) => [lng, path.join(LOCALES_DIR, lng)]),
);

const filesByLang = Object.fromEntries(
  LANGUAGES.map((lng) => [lng, new Set(listJsonFiles(dirsByLang[lng]))]),
);

const allFiles = new Set([...filesByLang.de, ...filesByLang.en]);

let hasMismatch = false;

for (const file of Array.from(allFiles).sort()) {
  const [de, en] = LANGUAGES;
  const dePresent = filesByLang[de].has(file);
  const enPresent = filesByLang[en].has(file);

  if (!dePresent) {
    console.error(`${file}: missing entirely in locales/${de}`);
    hasMismatch = true;
    continue;
  }
  if (!enPresent) {
    console.error(`${file}: missing entirely in locales/${en}`);
    hasMismatch = true;
    continue;
  }

  const deKeys = new Set(flattenKeys(readJson(path.join(dirsByLang[de], file))));
  const enKeys = new Set(flattenKeys(readJson(path.join(dirsByLang[en], file))));

  const missingInEn = [...deKeys].filter((k) => !enKeys.has(k)).sort();
  const missingInDe = [...enKeys].filter((k) => !deKeys.has(k)).sort();

  for (const key of missingInEn) {
    console.error(`${file}: ${key} present in ${de}, missing in ${en}`);
    hasMismatch = true;
  }
  for (const key of missingInDe) {
    console.error(`${file}: ${key} present in ${en}, missing in ${de}`);
    hasMismatch = true;
  }
}

if (hasMismatch) {
  process.exit(1);
} else {
  console.log(`i18n OK: ${allFiles.size} namespace file(s), ${LANGUAGES.join("/")} in sync.`);
  process.exit(0);
}
