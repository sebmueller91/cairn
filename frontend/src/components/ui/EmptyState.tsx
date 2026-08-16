import type { ReactNode } from "react";

/** "Nothing here yet" placeholder — icon slot, title, one line of guidance. */
export function EmptyState({
  icon,
  title,
  hint,
  action,
  className = "",
}: {
  /** A lucide icon element, sized by the caller. */
  icon?: ReactNode;
  title: ReactNode;
  hint?: ReactNode;
  /** Optional call to action, e.g. a button. */
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-col items-center justify-center gap-2 px-6 py-10 text-center ${className}`}
    >
      {icon && <div className="text-text-muted opacity-70">{icon}</div>}
      <div className="font-medium">{title}</div>
      {hint && (
        <div className="max-w-xs text-sm text-text-muted">{hint}</div>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
