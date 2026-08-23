import { Component, type ErrorInfo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { QueryErrorResetBoundary, useQueryClient, type QueryKey } from "@tanstack/react-query";

type Variant = "page" | "card";

interface OwnProps {
  children: ReactNode;
  /** "page" (default): full-screen, used once at the root as a last
   * resort. "card": compact, sized to sit inside a dashboard card — see
   * `CardErrorBoundary` below, which is what components should actually
   * use. */
  variant?: Variant;
  /** Called right before the caught error is cleared. `CardErrorBoundary`
   * uses this to reset the underlying queries' error state too — plain
   * re-rendering the previous children is not enough to recover, see its
   * docstring. */
  onRetry?: () => void;
}

type Props = OwnProps & { t: TFunction<"common"> };

interface State {
  error: Error | null;
}

/**
 * Catches a render throw from its subtree and shows a fallback with a way
 * out, instead of React unmounting everything above it (the default, and
 * why a single bad array index in one card used to blank the entire app).
 *
 * A class component because `componentDidCatch` has no hook equivalent —
 * one of the two things hooks still cannot do.
 *
 * Deliberately not styled with the design system's components: whatever
 * went wrong may have come from them, so this uses plain markup and CSS
 * variables only. It also keeps the error text visible rather than hiding
 * it behind a generic apology — on a self-hosted app the person reading it
 * is the person who can fix it.
 */
class ErrorBoundaryClass extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // No telemetry to send it to (spec 6.4: nothing leaves the LAN), so the
    // console is the record — reachable via remote debugging on the phone,
    // which is where this last went unnoticed.
    console.error("Unhandled render error:", error, info.componentStack);
  }

  handleRetry = () => {
    // Must run *before* clearing local state: for `CardErrorBoundary` this
    // is what actually gives the retry a chance of working (resets the
    // query error state), not just re-rendering the identical, still-broken
    // tree that crashed a moment ago.
    this.props.onRetry?.();
    this.setState({ error: null });
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    const { variant = "page", t } = this.props;
    return variant === "card" ? (
      <CardFallback error={error} onRetry={this.handleRetry} t={t} />
    ) : (
      <PageFallback error={error} onRetry={this.handleRetry} t={t} />
    );
  }
}

function PageFallback({
  error,
  onRetry,
  t,
}: {
  error: Error;
  onRetry: () => void;
  t: TFunction<"common">;
}) {
  return (
    <div
      style={{
        minHeight: "100dvh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "1.5rem",
        background: "var(--bg)",
        color: "var(--text)",
      }}
    >
      <div style={{ maxWidth: "32rem", width: "100%" }}>
        <h1 style={{ fontSize: "1.125rem", fontWeight: 600, marginBottom: "0.5rem" }}>
          {t("errorBoundary.pageTitle")}
        </h1>
        <p style={{ fontSize: "0.875rem", color: "var(--text-muted)", marginBottom: "1rem" }}>
          {t("errorBoundary.pageBody")}
        </p>
        <ErrorDetail error={error} />
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button
            type="button"
            onClick={onRetry}
            style={{
              borderRadius: "9999px",
              border: "1px solid var(--border)",
              padding: "0.375rem 0.875rem",
              fontSize: "0.875rem",
              color: "var(--text-muted)",
              background: "transparent",
            }}
          >
            {t("actions.retry")}
          </button>
          <button
            type="button"
            onClick={() => window.location.assign("/")}
            style={{
              borderRadius: "9999px",
              border: "none",
              padding: "0.375rem 0.875rem",
              fontSize: "0.875rem",
              fontWeight: 500,
              color: "var(--accent-fg)",
              background: "var(--accent)",
            }}
          >
            {t("actions.backToOverview")}
          </button>
        </div>
      </div>
    </div>
  );
}

function CardFallback({
  error,
  onRetry,
  t,
}: {
  error: Error;
  onRetry: () => void;
  t: TFunction<"common">;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.5rem",
        padding: "1rem",
        background: "var(--bg-subtle)",
        border: "1px solid var(--border)",
        borderRadius: "0.75rem",
        color: "var(--text)",
      }}
    >
      <p style={{ fontSize: "0.8125rem", fontWeight: 600 }}>{t("status.error")}</p>
      <p style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
        {t("errorBoundary.cardBody")}
      </p>
      <ErrorDetail error={error} compact />
      <button
        type="button"
        onClick={onRetry}
        style={{
          alignSelf: "flex-start",
          borderRadius: "9999px",
          border: "1px solid var(--border)",
          padding: "0.25rem 0.75rem",
          fontSize: "0.75rem",
          color: "var(--text-muted)",
          background: "transparent",
        }}
      >
        {t("actions.retry")}
      </button>
    </div>
  );
}

function ErrorDetail({ error, compact }: { error: Error; compact?: boolean }) {
  return (
    <pre
      style={{
        fontSize: compact ? "0.6875rem" : "0.75rem",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        background: compact ? "transparent" : "var(--bg-subtle)",
        border: compact ? "none" : "1px solid var(--border)",
        borderRadius: compact ? 0 : "0.5rem",
        padding: compact ? 0 : "0.75rem",
        margin: 0,
        marginBottom: compact ? 0 : "1rem",
      }}
    >
      {error.message}
    </pre>
  );
}

/** Thin hook-to-props bridge: `ErrorBoundaryClass` needs `t` as a prop
 * (class components can't call hooks), and re-rendering here on a language
 * change is what makes the fallback's own text respond to the language
 * toggle while it's showing. */
export function ErrorBoundary(props: OwnProps) {
  const { t } = useTranslation("common");
  return <ErrorBoundaryClass {...props} t={t} />;
}

/**
 * What card components should actually wrap themselves in — the root
 * `ErrorBoundary` in main.tsx stays a page-wide last resort only, catching
 * whatever slips past every card's own boundary.
 *
 * Passing `queryKeys` matters whenever the crash could plausibly be caused
 * by (or correlated with) a specific query being in an error/malformed
 * state: retry then calls `queryClient.resetQueries` for each key, on top
 * of `QueryErrorResetBoundary`'s own `reset()` (which un-sticks any query
 * using `throwOnError`). Without `queryKeys`, retry still remounts the
 * subtree — which is enough on its own for a query sitting in `"error"`
 * status, since TanStack refetches an errored query on mount by default
 * (`retryOnMount`) — but does nothing for a query that fetched fine and
 * simply returned data this card couldn't handle; that class of bug needs
 * fixing in the card itself, not a better retry button.
 *
 * Usage:
 *   <CardErrorBoundary queryKeys={[["positions", accountId]]}>
 *     <SomeCard />
 *   </CardErrorBoundary>
 */
export function CardErrorBoundary({
  children,
  queryKeys,
}: {
  children: ReactNode;
  queryKeys?: readonly QueryKey[];
}) {
  const queryClient = useQueryClient();
  return (
    <QueryErrorResetBoundary>
      {({ reset }) => (
        <ErrorBoundary
          variant="card"
          onRetry={() => {
            reset();
            queryKeys?.forEach((key) => queryClient.resetQueries({ queryKey: key }));
          }}
        >
          {children}
        </ErrorBoundary>
      )}
    </QueryErrorResetBoundary>
  );
}
