// Formatting through Intl, never hardcoded (ADR 0006 rule 3). The
// currency stays EUR always — only the notation follows the language.
// en-GB, not en-US: 03/08/2026 is ambiguous between "3 August" and
// "8 March" depending on the reader; en-GB and de-DE agree on
// day-month-year, which is the whole point of picking it.

const INTL_LOCALE: Record<string, string> = {
  de: "de-DE",
  en: "en-GB",
};

function intlLocale(lang: string): string {
  return INTL_LOCALE[lang] ?? "de-DE";
}

export function formatCurrency(value: number | string, lang: string): string {
  const n = typeof value === "string" ? Number(value) : value;
  return new Intl.NumberFormat(intlLocale(lang), {
    style: "currency",
    currency: "EUR",
  }).format(n);
}

export function formatNumber(
  value: number | string,
  lang: string,
  options?: Intl.NumberFormatOptions,
): string {
  const n = typeof value === "string" ? Number(value) : value;
  return new Intl.NumberFormat(intlLocale(lang), options).format(n);
}

export function formatPercent(
  value: number | string,
  lang: string,
  options?: Intl.NumberFormatOptions,
): string {
  const n = typeof value === "string" ? Number(value) : value;
  return new Intl.NumberFormat(intlLocale(lang), {
    style: "percent",
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
    ...options,
  }).format(n);
}

export function formatDate(value: string | Date, lang: string): string {
  const d = typeof value === "string" ? new Date(value) : value;
  return new Intl.DateTimeFormat(intlLocale(lang), {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

export function formatDateTime(value: string | Date, lang: string): string {
  const d = typeof value === "string" ? new Date(value) : value;
  return new Intl.DateTimeFormat(intlLocale(lang), {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(d);
}
