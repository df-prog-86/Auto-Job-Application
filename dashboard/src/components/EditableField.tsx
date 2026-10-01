import { useState } from "react";

import { Button, inputClass } from "@/components/ui";

interface EditableFieldProps {
  label: string;
  value: string;
  onSave: (value: string) => Promise<unknown>;
  required?: boolean;
  type?: "text" | "email" | "tel" | "url" | "month";
  /** Shown instead of "Add ..." when an optional value is empty (e.g. "Present"). */
  emptyLabel?: string;
  /** Formats the saved value for reading (e.g. a month). */
  format?: (value: string) => string;
  className?: string;
  bold?: boolean;
}

/**
 * One cell on the profile. Click to edit, Enter or Save to keep it, Escape
 * to cancel. A required cell that is empty is flagged "Needs completion".
 */
export function EditableField({
  label,
  value,
  onSave,
  required = false,
  type = "text",
  emptyLabel,
  format,
  className = "",
  bold = false,
}: EditableFieldProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isEmpty = value.trim() === "";
  const needsCompletion = required && isEmpty;

  function open() {
    setDraft(value);
    setError(null);
    setEditing(true);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await onSave(draft.trim());
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save. Try again.");
    } finally {
      setSaving(false);
    }
  }

  if (editing) {
    return (
      <form
        className={className}
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") setEditing(false);
        }}
      >
        <label className="mb-1 block text-xs font-semibold text-ink-500">{label}</label>
        <input
          autoFocus
          type={type}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className={inputClass}
        />
        <div className="mt-2 flex items-center gap-2">
          <Button type="submit" variant="primary" size="sm" disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        </div>
        {error && <p className="mt-1.5 text-xs text-red-600">{error}</p>}
      </form>
    );
  }

  return (
    <div className={className}>
      <div className="mb-1 flex items-center gap-2 text-xs font-semibold text-ink-500">
        {label}
        {needsCompletion && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
            Needs completion
          </span>
        )}
      </div>
      <button
        type="button"
        onClick={open}
        title={`Edit ${label.toLowerCase()}`}
        className={`group flex w-full items-center justify-between gap-2 rounded-xl border px-3 py-2 text-left text-sm transition ${
          needsCompletion
            ? "border-dashed border-amber-300 bg-amber-50/60 text-amber-800 hover:border-amber-400"
            : "border-transparent bg-ink-900/[0.03] hover:border-brand-200 hover:bg-brand-50/60"
        }`}
      >
        <span className={`min-w-0 truncate ${bold ? "font-bold" : "font-medium"} ${isEmpty && !needsCompletion ? "text-ink-400" : ""}`}>
          {isEmpty ? (needsCompletion ? `Add ${label.toLowerCase()}` : (emptyLabel ?? `Add ${label.toLowerCase()}`)) : format ? format(value) : value}
        </span>
        <span className="shrink-0 text-xs font-semibold text-brand-600 opacity-0 transition group-hover:opacity-100 group-focus-visible:opacity-100">
          Edit
        </span>
      </button>
    </div>
  );
}

interface SelectFieldProps {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onSave: (value: string) => Promise<unknown>;
  required?: boolean;
}

/** A dropdown cell that saves as soon as a choice is made. */
export function SelectField({ label, value, options, onSave, required = false }: SelectFieldProps) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const needsCompletion = required && value === "";

  async function change(next: string) {
    setSaving(true);
    setError(null);
    try {
      await onSave(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save. Try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div className="mb-1 flex items-center gap-2 text-xs font-semibold text-ink-500">
        {label}
        {needsCompletion && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
            Needs completion
          </span>
        )}
        {saving && <span className="font-normal text-ink-400">Saving…</span>}
      </div>
      <select
        value={value}
        disabled={saving}
        onChange={(e) => void change(e.target.value)}
        className={`w-full rounded-xl border px-3 py-2 text-sm font-medium transition focus:outline-none focus:ring-2 focus:ring-brand-200 ${
          needsCompletion
            ? "border-dashed border-amber-300 bg-amber-50/60 text-amber-800"
            : "border-transparent bg-ink-900/[0.03] text-ink-900 hover:border-brand-200"
        }`}
      >
        <option value="" disabled>
          Choose one
        </option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {error && <p className="mt-1.5 text-xs text-red-600">{error}</p>}
    </div>
  );
}
