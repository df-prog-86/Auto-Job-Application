import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

import { api } from "@/api/client";

export type SuggestKind = "place" | "title" | "keyword";

/** Suggestions for what has been typed so far. Waits a moment after typing and ignores answers that arrive late. */
export function useSuggestions(kind: SuggestKind | undefined, text: string, active: boolean): string[] {
  const [items, setItems] = useState<string[]>([]);
  useEffect(() => {
    const q = text.trim();
    if (!kind || !active || q.length < 2) {
      setItems([]);
      return;
    }
    let stale = false;
    const t = setTimeout(() => {
      api
        .suggestWords(kind, q)
        .then((rows) => {
          if (!stale) setItems(rows.filter((r) => r.toLowerCase() !== q.toLowerCase()));
        })
        .catch(() => {
          if (!stale) setItems([]);
        });
    }, 150);
    return () => {
      stale = true;
      clearTimeout(t);
    };
  }, [kind, text, active]);
  return items;
}

/** Up and down move through the suggestions, Enter picks the highlighted one, Escape closes the list. */
export function useListKeys(items: string[], pick: (value: string) => void, close: () => void) {
  const [index, setIndex] = useState(-1);
  const count = useRef(0);
  count.current = items.length;
  useEffect(() => setIndex(-1), [items]);
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>): boolean => {
    if (items.length === 0) return false;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setIndex((i) => (i + 1) % count.current);
      return true;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setIndex((i) => (i <= 0 ? count.current - 1 : i - 1));
      return true;
    }
    if (e.key === "Escape") {
      close();
      return true;
    }
    if ((e.key === "Enter" || e.key === "Tab") && index >= 0 && items[index]) {
      e.preventDefault();
      pick(items[index]);
      return true;
    }
    return false;
  };
  return { index, setIndex, onKeyDown };
}
