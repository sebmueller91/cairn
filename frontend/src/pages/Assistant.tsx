import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Check, ImagePlus, Loader2, Plus, Send, Trash2, X } from "lucide-react";
import { PageHeader } from "../components/ui/PageHeader";
import { GlassCard } from "../components/ui/GlassCard";
import { EmptyState } from "../components/ui/EmptyState";
import { OfflineNotice } from "../components/OfflineNotice";
import { ApiError } from "../lib/api";
import {
  agentApi,
  prepareImage,
  type AgentConversation,
  type AgentProposal,
  type OutgoingImage,
  type PreviewRow,
  type PreviewTxn,
} from "../lib/agent";
import { formatCurrency, formatDate, formatNumber } from "../lib/format";
import { useAuth } from "../lib/auth";
import { useOnlineStatus } from "../lib/online";

const PREVIEW_FIELDS = ["date", "quantity", "price", "fees", "amount_eur", "provisional"] as const;

function changedFields(row: PreviewRow): Set<string> {
  if (row.action !== "update" || !row.before || !row.after) return new Set();
  return new Set(PREVIEW_FIELDS.filter((f) => row.before![f] !== row.after![f]));
}

function TxnLine({ txn, row, highlight }: { txn: PreviewTxn; row: PreviewRow; highlight: Set<string> }) {
  const { t, i18n } = useTranslation("assistant");
  const lang = i18n.language;
  const mark = (field: string) => (highlight.has(field) ? "font-semibold text-accent" : "");
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-sm">
      <span className={`tabular-nums ${mark("date")}`}>{formatDate(txn.date, lang)}</span>
      <span className="text-text-muted">{t(`types.${txn.type}`, { defaultValue: txn.type })}</span>
      <span className="min-w-0 truncate">
        {row.instrument_name ?? row.account_name}
        {row.instrument_name && <span className="text-text-muted"> · {row.account_name}</span>}
      </span>
      {txn.quantity && (
        <span className={`tabular-nums ${mark("quantity")}`}>
          {formatNumber(txn.quantity, lang, { maximumFractionDigits: 8 })} ×{" "}
          <span className={mark("price")}>
            {txn.price ? formatNumber(txn.price, lang, { maximumFractionDigits: 6 }) : "–"}
          </span>
        </span>
      )}
      {Number(txn.fees) !== 0 && (
        <span className={`sensitive tabular-nums text-text-muted ${mark("fees")}`}>
          {t("fees")} {formatCurrency(txn.fees, lang)}
        </span>
      )}
      <span className={`sensitive ml-auto tabular-nums font-medium ${mark("amount_eur")}`}>
        {formatCurrency(txn.amount_eur, lang)}
      </span>
      {txn.provisional && (
        <span className={`rounded-full bg-warning/15 px-2 py-0.5 text-xs text-warning ${mark("provisional")}`}>
          {t("provisional")}
        </span>
      )}
    </div>
  );
}

function ProposalCard({
  proposal,
  conversationId,
  readOnly,
}: {
  proposal: AgentProposal;
  conversationId: number;
  readOnly: boolean;
}) {
  const { t } = useTranslation(["assistant", "errors"]);
  const queryClient = useQueryClient();
  const online = useOnlineStatus();
  const [error, setError] = useState<string | null>(null);

  const decide = useMutation({
    mutationFn: (apply: boolean) =>
      apply ? agentApi.apply(proposal.id) : agentApi.reject(proposal.id),
    onSuccess: () => {
      setError(null);
      // Applying changes the ledger, and with it nearly every view.
      queryClient.invalidateQueries();
    },
    onError: (err) => {
      setError(err instanceof ApiError ? t(`errors:${err.code}`, err.params) : t("errors:generic"));
      queryClient.invalidateQueries({ queryKey: ["agent", "conversation", conversationId] });
    },
  });

  const pending = proposal.status === "pending";
  const shownError =
    error ?? (proposal.error ? t(`errors:${proposal.error.code}`, proposal.error.params) : null);

  return (
    <div className="space-y-3 rounded-card border border-accent/40 bg-bg-subtle p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-medium">{proposal.summary}</div>
        {!pending && (
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${
              proposal.status === "applied" ? "bg-positive/15 text-positive" : "bg-bg-card text-text-muted"
            }`}
          >
            {t(`status.${proposal.status}`)}
          </span>
        )}
      </div>
      <ul className="space-y-2">
        {proposal.preview.map((row, i) => {
          const highlight = changedFields(row);
          return (
            <li key={i} className="space-y-1 border-t border-border pt-2 first:border-t-0 first:pt-0">
              <div className="text-xs font-medium uppercase tracking-wide text-text-muted">
                {t(`actions.${row.action}`)}
                {row.reason && <span className="normal-case tracking-normal"> — {row.reason}</span>}
              </div>
              {row.action === "update" && row.before && (
                <div className="opacity-60">
                  <TxnLine txn={row.before} row={row} highlight={new Set()} />
                </div>
              )}
              {row.action === "delete" && row.before && (
                <div className="line-through opacity-60">
                  <TxnLine txn={row.before} row={row} highlight={new Set()} />
                </div>
              )}
              {row.after && <TxnLine txn={row.after} row={row} highlight={highlight} />}
            </li>
          );
        })}
      </ul>
      {shownError && <p className="text-sm text-negative">{shownError}</p>}
      {pending && !readOnly && (
        <div className="flex gap-2">
          <button
            type="button"
            disabled={!online || decide.isPending}
            onClick={() => decide.mutate(true)}
            className="inline-flex items-center gap-1.5 rounded-full bg-accent px-3.5 py-1.5 text-sm font-medium text-accent-fg disabled:opacity-50"
          >
            <Check className="size-4" aria-hidden />
            {t("apply")}
          </button>
          <button
            type="button"
            disabled={!online || decide.isPending}
            onClick={() => decide.mutate(false)}
            className="inline-flex items-center gap-1.5 rounded-full border border-border px-3.5 py-1.5 text-sm text-text-muted hover:text-text disabled:opacity-50"
          >
            <X className="size-4" aria-hidden />
            {t("reject")}
          </button>
        </div>
      )}
    </div>
  );
}

function Composer({ conversationId }: { conversationId: number }) {
  const { t } = useTranslation(["assistant", "errors"]);
  const queryClient = useQueryClient();
  const online = useOnlineStatus();
  const [text, setText] = useState("");
  const [images, setImages] = useState<OutgoingImage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  async function addFiles(files: Iterable<File>) {
    const accepted = [...files].filter((f) => f.type.startsWith("image/"));
    try {
      const prepared = await Promise.all(accepted.map(prepareImage));
      setImages((current) => [...current, ...prepared].slice(0, 6));
    } catch {
      setError(t("imageFailed"));
    }
  }

  const send = useMutation({
    mutationFn: () => agentApi.send(conversationId, text, images),
    onSuccess: (conversation) => {
      queryClient.setQueryData(["agent", "conversation", conversationId], conversation);
      queryClient.invalidateQueries({ queryKey: ["agent", "conversations"] });
      images.forEach((i) => URL.revokeObjectURL(i.preview));
      setText("");
      setImages([]);
      setError(null);
    },
    onError: (err) => {
      setError(err instanceof ApiError ? t(`errors:${err.code}`, err.params) : t("errors:generic"));
      // The user's message is kept server-side even when the model call
      // failed; show it.
      queryClient.invalidateQueries({ queryKey: ["agent", "conversation", conversationId] });
    },
  });

  const canSend = online && !send.isPending && (text.trim() !== "" || images.length > 0);

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (canSend) send.mutate();
  }

  return (
    <form
      onSubmit={submit}
      onDragOver={(e: DragEvent) => e.preventDefault()}
      onDrop={(e: DragEvent) => {
        e.preventDefault();
        void addFiles(e.dataTransfer.files);
      }}
      className="space-y-2 border-t border-border pt-3"
    >
      {images.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {images.map((img, i) => (
            <div key={img.preview} className="relative">
              <img src={img.preview} alt="" className="h-16 w-16 rounded-md border border-border object-cover" />
              <button
                type="button"
                aria-label={t("removeImage")}
                onClick={() => {
                  URL.revokeObjectURL(img.preview);
                  setImages((current) => current.filter((_, j) => j !== i));
                }}
                className="absolute -right-1.5 -top-1.5 rounded-full border border-border bg-bg-card p-0.5"
              >
                <X className="size-3" aria-hidden />
              </button>
            </div>
          ))}
        </div>
      )}
      {error && <p className="text-sm text-negative">{error}</p>}
      <div className="flex items-end gap-2">
        <button
          type="button"
          onClick={() => fileInput.current?.click()}
          aria-label={t("addImage")}
          title={t("addImage")}
          className="rounded-full p-2 text-text-muted hover:text-text"
        >
          <ImagePlus className="size-5" aria-hidden />
        </button>
        <input
          ref={fileInput}
          type="file"
          accept="image/*"
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files) void addFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onPaste={(e: ClipboardEvent) => {
            const files = [...e.clipboardData.files];
            if (files.length > 0) {
              e.preventDefault();
              void addFiles(files);
            }
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={2}
          placeholder={t("placeholder")}
          className="min-h-[2.75rem] flex-1 resize-y rounded-md border border-border bg-bg-subtle px-3 py-2 text-sm outline-none focus:border-accent"
        />
        <button
          type="submit"
          disabled={!canSend}
          aria-label={t("send")}
          className="rounded-full bg-accent p-2.5 text-accent-fg disabled:opacity-50"
        >
          {send.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" aria-hidden />}
        </button>
      </div>
      {send.isPending && <p className="text-xs text-text-muted">{t("working")}</p>}
    </form>
  );
}

function Chat({ conversation, readOnly }: { conversation: AgentConversation; readOnly: boolean }) {
  const { t } = useTranslation("assistant");
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [conversation.items.length]);

  return (
    <div className="space-y-4">
      {conversation.items.length === 0 && (
        <EmptyState icon={<Bot className="size-8" />} title={t("emptyTitle")} hint={t("emptyHint")} />
      )}
      {conversation.items.map((item, i) =>
        item.proposal ? (
          <ProposalCard key={i} proposal={item.proposal} conversationId={conversation.id} readOnly={readOnly} />
        ) : (
          <div key={i} className={item.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div
              className={`max-w-[85%] whitespace-pre-wrap rounded-card px-3 py-2 text-sm ${
                item.role === "user" ? "bg-accent/15" : "bg-bg-subtle"
              }`}
            >
              {item.image_count > 0 && (
                <div className="mb-1 text-xs text-text-muted">
                  {t("imagesAttached", { count: item.image_count })}
                </div>
              )}
              {item.text}
            </div>
          </div>
        ),
      )}
      <div ref={bottom} />
    </div>
  );
}

export function Assistant() {
  const { t } = useTranslation("assistant");
  const { scope } = useAuth();
  const readOnly = scope !== "full";
  const queryClient = useQueryClient();
  const online = useOnlineStatus();
  const [selected, setSelected] = useState<number | null>(null);

  const status = useQuery({ queryKey: ["agent", "status"], queryFn: agentApi.status });
  const conversations = useQuery({ queryKey: ["agent", "conversations"], queryFn: agentApi.list });
  const activeId = selected ?? conversations.data?.[0]?.id ?? null;
  const conversation = useQuery({
    queryKey: ["agent", "conversation", activeId],
    queryFn: () => agentApi.get(activeId!),
    enabled: activeId !== null,
  });

  const create = useMutation({
    mutationFn: agentApi.create,
    onSuccess: (c) => {
      queryClient.setQueryData(["agent", "conversation", c.id], c);
      queryClient.invalidateQueries({ queryKey: ["agent", "conversations"] });
      setSelected(c.id);
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => agentApi.remove(id),
    onSuccess: () => {
      setSelected(null);
      queryClient.invalidateQueries({ queryKey: ["agent", "conversations"] });
    },
  });

  const newButton = !readOnly && (
    <button
      type="button"
      disabled={!online || create.isPending || !status.data?.configured}
      onClick={() => create.mutate()}
      className="inline-flex items-center gap-1.5 rounded-full bg-accent px-3.5 py-1.5 text-sm font-medium text-accent-fg disabled:opacity-50"
    >
      <Plus className="size-4" aria-hidden />
      {t("newChat")}
    </button>
  );

  return (
    <div className="space-y-6">
      <PageHeader title={t("title")} actions={newButton} />
      {!online && <OfflineNotice />}

      {status.data && !status.data.configured && (
        <GlassCard>
          <EmptyState icon={<Bot className="size-8" />} title={t("notConfiguredTitle")} hint={t("notConfiguredHint")} />
        </GlassCard>
      )}

      {status.data?.configured && (
        <div className="grid gap-4 md:grid-cols-[14rem_1fr]">
          <GlassCard className="space-y-1 p-2 md:p-2">
            {conversations.data?.length === 0 && (
              <p className="px-2 py-1 text-sm text-text-muted">{t("noChats")}</p>
            )}
            {conversations.data?.map((c) => (
              <div
                key={c.id}
                className={`group flex items-center gap-1 rounded-md ${
                  c.id === activeId ? "bg-accent/10 text-accent" : "text-text-muted hover:text-text"
                }`}
              >
                <button
                  type="button"
                  onClick={() => setSelected(c.id)}
                  className="min-w-0 flex-1 truncate px-2 py-1.5 text-left text-sm"
                >
                  {c.title ?? t("untitled")}
                </button>
                {!readOnly && (
                  <button
                    type="button"
                    aria-label={t("deleteChat")}
                    onClick={() => {
                      if (window.confirm(t("deleteChatConfirm"))) remove.mutate(c.id);
                    }}
                    className="p-1.5 opacity-0 group-hover:opacity-100 focus:opacity-100"
                  >
                    <Trash2 className="size-3.5" aria-hidden />
                  </button>
                )}
              </div>
            ))}
          </GlassCard>

          <GlassCard className="flex min-h-[60vh] flex-col justify-between gap-4">
            {conversation.data ? (
              <>
                <Chat conversation={conversation.data} readOnly={readOnly} />
                {!readOnly && (
                  <Composer conversationId={conversation.data.id} />
                )}
              </>
            ) : (
              <EmptyState
                icon={<Bot className="size-8" />}
                title={t("startTitle")}
                hint={t("startHint")}
                action={newButton}
              />
            )}
          </GlassCard>
        </div>
      )}
    </div>
  );
}
