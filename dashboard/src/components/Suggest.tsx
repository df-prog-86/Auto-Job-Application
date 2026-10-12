import { useState } from "react";

import { useListKeys, useSuggestions } from "@/lib/useSuggest";
import type { SuggestKind } from "@/lib/useSuggest";

/** The drop-down list under a box. Clicking a row does not take focus away from the box. */
export function SuggestList({
  id,
  items,
  index,
  onHover,
  onPick,
  label,
}: {
  id: string;
  items: string[];
  index: number;
  onHover: (i: number) => void;
  onPick: (value: string) => void;
  label: string;
}) {
  if (items.length === 0) return null;
  return (
    <ul
      id={id}
      role="listbox"
      aria-label={label}
      className="absolute left-0 top-full z-30 mt-1.5 max-h-72 w-full min-w-[220px] overflow-auto rounded-2xl border border-[#e6e2fa] bg-white p-1.5 shadow-lift"
    >
      {items.map((it, i) => (
        <li
          key={it}
          id={`${id}-${i}`}
          role="option"
          aria-selected={i === index}
          onMouseDown={(e) => e.preventDefault()}
          onMouseEnter={() => onHover(i)}
          onClick={() => onPick(it)}
          className={`cursor-pointer rounded-xl px-3 py-2 text-[13px] font-semibold text-ink-900 ${i === index ? "bg-[#efedff]" : ""}`}
        >
          {it}
          {i === 0 && <span className="ml-2 text-[11px] font-normal text-ink-500">Top match</span>}
        </li>
      ))}
    </ul>
  );
}

/** A single-value text box with suggestions, such as the place box. */
export function SuggestInput({
  id,
  value,
  onChange,
  kind,
  placeholder,
  maxLength,
  className,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  kind: SuggestKind;
  placeholder?: string;
  maxLength?: number;
  className?: string;
}) {
  const [focused, setFocused] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const items = useSuggestions(kind, value, focused && !dismissed);
  const pick = (v: string) => {
    onChange(v);
    setDismissed(true);
  };
  const keys = useListKeys(items, pick, () => setDismissed(true));
  return (
    <>
      <input
        id={id}
        value={value}
        role="combobox"
        aria-expanded={items.length > 0}
        aria-controls={`${id}-list`}
        aria-autocomplete="list"
        aria-activedescendant={keys.index >= 0 ? `${id}-list-${keys.index}` : undefined}
        autoComplete="off"
        onChange={(e) => {
          setDismissed(false);
          onChange(e.target.value);
        }}
        onKeyDown={(e) => {
          keys.onKeyDown(e);
        }}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        placeholder={placeholder}
        maxLength={maxLength}
        className={className}
      />
      <SuggestList id={`${id}-list`} items={items} index={keys.index} onHover={keys.setIndex} onPick={pick} label="Suggestions" />
    </>
  );
}
