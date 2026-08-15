import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";

export function Login() {
  const { t } = useTranslation(["common", "errors"]);
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
    <div className="flex min-h-screen items-center justify-center bg-bg">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-lg border border-border bg-bg-card p-8"
      >
        <h1 className="mb-1 text-xl font-semibold text-text">Cairn</h1>
        <p className="mb-6 text-sm text-text-muted">
          {t("settings:apiToken")}
        </p>
        <input
          type="password"
          autoFocus
          value={token}
          onChange={(e) => setToken(e.target.value)}
          className="mb-4 w-full rounded-md border border-border bg-bg px-3 py-2 text-text outline-none focus:border-accent"
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
          className="w-full rounded-md bg-accent px-3 py-2 font-medium text-accent-fg disabled:opacity-50"
        >
          {t("actions.login")}
        </button>
      </form>
    </div>
  );
}
