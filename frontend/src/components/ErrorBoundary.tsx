import { Component, type ErrorInfo, type ReactNode } from "react";

interface State {
  error: Error | null;
}

/**
 * Last line of defence: React unmounts the whole tree when a render throws,
 * which is why a single bad array index blanked the entire page instead of
 * breaking one card. This turns that into a message with a way out.
 *
 * A class component because `componentDidCatch` has no hook equivalent —
 * this is one of the two things hooks still cannot do.
 *
 * Deliberately not styled with the design system's components: whatever went
 * wrong may have come from them, so this uses plain markup and CSS variables
 * only. It also keeps the error text visible rather than hiding it behind a
 * generic apology — on a self-hosted app the person reading it is the person
 * who can fix it.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
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

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

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
            Da ist etwas schiefgelaufen
          </h1>
          <p style={{ fontSize: "0.875rem", color: "var(--text-muted)", marginBottom: "1rem" }}>
            Die Ansicht konnte nicht dargestellt werden. Deine Daten sind davon
            nicht betroffen — es ist ein Anzeigefehler.
          </p>
          <pre
            style={{
              fontSize: "0.75rem",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              background: "var(--bg-subtle)",
              border: "1px solid var(--border)",
              borderRadius: "0.5rem",
              padding: "0.75rem",
              marginBottom: "1rem",
            }}
          >
            {error.message}
          </pre>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button
              type="button"
              onClick={() => this.setState({ error: null })}
              style={{
                borderRadius: "9999px",
                border: "1px solid var(--border)",
                padding: "0.375rem 0.875rem",
                fontSize: "0.875rem",
                color: "var(--text-muted)",
                background: "transparent",
              }}
            >
              Erneut versuchen
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
              Zur Übersicht
            </button>
          </div>
        </div>
      </div>
    );
  }
}
