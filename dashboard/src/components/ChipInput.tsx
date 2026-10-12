import { useId, useState } from "react";
import type { KeyboardEvent } from "react";

import { SuggestList } from "@/components/Suggest";
import { useListKeys, useSuggestions } from "@/lib/useSuggest";
import type { SuggestKind } from "@/lib/useSuggest";

/**
 * A list of short words shown as removable chips, with a box to add more. Press
 * Enter or a comma to add one. The "title" look sits inside the search bar; the
 * "box" look is a normal bordered field.
 */
export function ChipInput({
  values,
  onChange,
  draft,
  onDraft,
  placeholder,
  label,
  variant = "box",
  maxLength = 80,
  suggest,
}: {
  values: string[];
  onChange: (next: string[]) => void;
  draft: string;
  onDraft: (text: string) => void;
  placeholder: string;
  label: string;
  variant?: "title" | "box";
  maxLength?: number;
  /** Offer completions while typing: job titles or keywords. */
  suggest?: SuggestKind;
}) {
  const listId = useId();
  const [focused, setFocused] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const items = useSuggestions(suggest, draft, focused && !dismissed);
  const add = (text: string) => {
    const parts = text
      .split(",")
      .map((p) => p.trim())
      .filter(Boolean);
    if (parts.length === 0) return;
    const next = [...values];
    for (const p of parts) {
      if (!next.some((v) => v.toLowerCase() === p.toLowerCase())) next.push(p);
    }
    onChange(next);
  };

  const pick = (text: string) => {
    add(text);
    onDraft("");
    setDismissed(false);
  };
  const keys = useListKeys(items, pick, () => setDismissed(true));

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (keys.onKeyDown(e)) return;
    if (e.key === "Enter" || e.key === ",") {
      if (draft.trim()) {
        e.preventDefault();
        add(draft);
        onDraft("");
      } else if (e.key === "," || variant === "box") {
        e.preventDefault();
      }
    } else if (e.key === "Backspace" && !draft && values.length > 0) {
      onChange(values.slice(0, -1));
    }
  };

  const wrap =
    variant === "title"
      ? "relative flex min-w-0 flex-1 flex-wrap items-center gap-2"
      : "relative flex min-h-[42px] flex-wrap items-center gap-1.5 rounded-[14px] border border-[#8f88bb] bg-white px-2.5 py-1 focus-within:border-brand-400 focus-within:ring-2 focus-within:ring-brand-200";

  return (
    <div className={wrap}>
      {values.map((v) => (
        <span
          key={v}
          className="inline-flex items-center gap-1.5 rounded-full bg-[#efebfd] py-1 pl-3 pr-1.5 text-[13px] font-bold text-[#4a35b0]"
        >
          {v}
          <button
            type="button"
            aria-label={`Remove ${v}`}
            onClick={() => onChange(values.filter((x) => x !== v))}
            className="flex h-4 w-4 items-center justify-center rounded-full bg-white text-[10px] font-extrabold text-brand-600 hover:bg-brand-100"
          >
            &#10005;
          </button>
        </span>
      ))}
      <input
        aria-label={label}
        role={suggest ? "combobox" : undefined}
        aria-expanded={suggest ? items.length > 0 : undefined}
        aria-controls={suggest ? listId : undefined}
        aria-autocomplete={suggest ? "list" : undefined}
        autoComplete="off"
        value={draft}
        maxLength={maxLength}
        onChange={(e) => {
          const t = e.target.value;
          setDismissed(false);
          if (t.includes(",")) {
            add(t);
            onDraft("");
          } else {
            onDraft(t);
          }
        }}
        onKeyDown={onKeyDown}
        onFocus={() => setFocused(true)}
        onBlur={() => {
          setFocused(false);
          if (draft.trim()) {
            add(draft);
            onDraft("");
          }
        }}
        placeholder={values.length === 0 ? placeholder : variant === "title" ? "Add another title" : "Add another"}
        className={`min-w-[120px] flex-1 border-0 bg-transparent text-ink-900 placeholder:text-[#6a6585] focus:outline-none ${
          variant === "title" ? "min-h-[40px] text-[15px]" : "py-1.5 text-[13px]"
        }`}
      />
      {suggest && <SuggestList id={listId} items={items} index={keys.index} onHover={keys.setIndex} onPick={pick} label="Suggestions" />}
    </div>
  );
}
