import { Search } from "lucide-react";

/** Client-side substring filter input, styled to match the dark theme. */
export function SearchField({
  value,
  onChange,
  placeholder,
  className = "",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  className?: string;
}) {
  return (
    <div className={`relative ${className}`}>
      <Search
        className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-text-muted"
        aria-hidden
      />
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        className="w-full rounded-md border border-border bg-bg-subtle py-1.5 pl-8 pr-3 text-sm text-text outline-none placeholder:text-text-muted focus:border-accent"
      />
    </div>
  );
}
