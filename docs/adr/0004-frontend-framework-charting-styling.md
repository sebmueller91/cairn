# 0004 — Frontend framework, charting library, styling

**Status:** proposed
**Date:** 2026-08-15

## Context
PWA on phone/tablet/desktop, must stay usable offline, must chart a decade
of daily data without lag on modest client hardware, needs dark mode and
i18n baked in structurally, sober "financial terminal" visual direction.

## Options considered
- **React + TS + Vite**, spec's choice — vs. Svelte/SvelteKit (smaller
  runtime, less ecosystem for PWA persistence patterns) or plain Vue.
- **Charting: Recharts alone vs. Recharts+uPlot split vs. uPlot alone.**

## Decision
React + TypeScript + Vite, TanStack Query with an IndexedDB persister,
Tailwind + Radix primitives (not a full component library), vite-plugin-pwa
(Workbox). **Charting: Recharts only**, relying on the API's existing
`granularity=day|week|month` parameter (spec 7.1) to downsample wide date
ranges instead of adding a second, canvas-based charting library.

## Rationale
React/Vite/TanStack Query is the best-supported combination for exactly the
stale-while-revalidate + IndexedDB-persistence pattern the offline strategy
needs (ADR 0005) — this isn't a close call. The charting decision is the one
worth arguing: an SVG library like Recharts rendering 3,650+ daily points for
a 10-year net worth line can visibly lag on a phone, which is why the spec
suggested uPlot (canvas, handles tens of thousands of points effortlessly) as
an alternative. But uPlot isn't React-idiomatic and has no turnkey donut or
treemap, so taking it on means running two charting libraries for two
different chart shapes. The API already has the lever to avoid that: request
`granularity=month` for a 10-year view and the point count drops to ~120,
trivial for Recharts; only short ranges (1M/3M) ask for daily granularity,
where the point count is small regardless. One library, server does the
downsampling work it needs to do anyway for the "must not refold the ledger
per request" reason (ADR 0003).

## Consequences
Makes easy: one charting API to learn and theme, consistent tooltips/legends/
i18n across all chart types. Makes hard: if a future view genuinely needs
dense daily rendering client-side (not just a wide time range — e.g. an
interactive daily-resolution zoom-and-pan), Recharts will start to strain and
uPlot becomes the right answer for that view specifically. Revisit then, not
preemptively.
