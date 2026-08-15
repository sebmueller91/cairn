import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Account, type AccountType } from "../lib/api";
import { formatDate } from "../lib/format";
import { Card } from "../components/Card";
import { OfflineNotice } from "../components/OfflineNotice";
import { useOnlineStatus } from "../lib/online";

const ACCOUNT_TYPES: AccountType[] = [
  "BROKERAGE",
  "CRYPTO_WALLET",
  "PHYSICAL_STORAGE",
  "REAL_ESTATE",
  "VEHICLE",
  "LOAN",
  "CASH",
];

export function Accounts() {
  const { t, i18n } = useTranslation(["assets", "common", "errors"]);
  const queryClient = useQueryClient();
  const online = useOnlineStatus();
  const { data: accounts, isLoading } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => api.get<Account[]>("/api/accounts"),
  });

  const [name, setName] = useState("");
  const [type, setType] = useState<AccountType>("BROKERAGE");
  const [currency, setCurrency] = useState("EUR");
  const [error, setError] = useState<string | null>(null);

  const createAccount = useMutation({
    mutationFn: () => api.post<Account>("/api/accounts", { name, type, currency }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      setName("");
    },
    onError: (err) =>
      setError(err instanceof ApiError ? t(`errors:${err.code}`) : t("errors:generic")),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    createAccount.mutate();
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">{t("assets:accounts.title")}</h1>

      <Card>
        <h2 className="mb-3 font-medium">{t("assets:accounts.new")}</h2>
        <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs text-text-muted">
              {t("common:fields.name")}
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-text-muted">
              {t("common:fields.type")}
            </label>
            <select
              value={type}
              onChange={(e) => setType(e.target.value as AccountType)}
              className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
            >
              {ACCOUNT_TYPES.map((tp) => (
                <option key={tp} value={tp}>
                  {t(`assets:accounts.types.${tp}`)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-text-muted">
              {t("common:fields.currency")}
            </label>
            <input
              value={currency}
              onChange={(e) => setCurrency(e.target.value.toUpperCase())}
              maxLength={3}
              required
              className="w-16 rounded-md border border-border bg-bg px-3 py-1.5 text-sm uppercase"
            />
          </div>
          <button
            type="submit"
            disabled={createAccount.isPending || !online}
            className="rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-accent-fg disabled:opacity-50"
          >
            {t("common:actions.create")}
          </button>
        </form>
        {!online && <OfflineNotice />}
        {error && (
          <p className="mt-2 text-sm text-negative" role="alert">
            {error}
          </p>
        )}
      </Card>

      <Card className="p-0">
        {isLoading ? (
          <p className="p-5 text-text-muted">{t("common:status.loading")}</p>
        ) : !accounts?.length ? (
          <p className="p-5 text-text-muted">{t("common:status.empty")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-muted">
                <th className="px-5 py-2 font-medium">{t("common:fields.name")}</th>
                <th className="px-5 py-2 font-medium">{t("common:fields.type")}</th>
                <th className="px-5 py-2 font-medium">{t("common:fields.currency")}</th>
                <th className="px-5 py-2 font-medium">{t("assets:accounts.institution")}</th>
                <th className="px-5 py-2 font-medium">{t("common:fields.date")}</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <tr key={a.id} className="border-b border-border last:border-0">
                  <td className="px-5 py-2">{a.name}</td>
                  <td className="px-5 py-2">{t(`assets:accounts.types.${a.type}`)}</td>
                  <td className="px-5 py-2">{a.currency}</td>
                  <td className="px-5 py-2 text-text-muted">{a.institution ?? "—"}</td>
                  <td className="tnum px-5 py-2 text-text-muted">
                    {formatDate(a.created_at, i18n.language)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
