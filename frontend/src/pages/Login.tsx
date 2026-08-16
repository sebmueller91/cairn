import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";
import { GlassCard } from "../components/ui/GlassCard";

export function Login() {
  const { t } = useTranslation(["common", "settings", "errors"]);
  const { login } = useAuth();
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(token);
    } catch (err) {
      setError(err instanceof ApiError ? t(`errors:${err.code}`) : t("errors:generic"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    // No background paint here — the ambient glow lives on <body> (index.css)
    // and glass cards are only glass if it shows through.
    <div className="flex min-h-screen items-center justify-center p-4">
      <GlassCard glow className="w-full max-w-sm">
        <form onSubmit={handleSubmit}>
          <div className="mb-6 flex items-center justify-center gap-2">
            <span
              aria-hidden
              className="size-2 rounded-full bg-accent"
              style={{ boxShadow: "var(--glow-accent)" }}
            />
            <span className="text-lg font-semibold tracking-tight text-text">Cairn</span>
          </div>
          <label className="mb-1 block text-xs text-text-muted" htmlFor="login-token">
            {t("settings:apiToken")}
          </label>
          <input
            id="login-token"
            type="password"
            autoFocus
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className="mb-4 w-full rounded-md border border-border bg-bg-subtle px-3 py-2 text-sm text-text outline-none focus:border-accent"
            placeholder={t("settings:apiToken")}
          />
          {error && (
            <p className="mb-4 text-sm text-negative" role="alert">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={submitting || !token}
            className="w-full rounded-md bg-accent px-3 py-2 text-sm font-medium text-accent-fg shadow-glow-accent disabled:opacity-50 disabled:shadow-none"
          >
            {t("actions.login")}
          </button>
        </form>
      </GlassCard>
    </div>
  );
}
