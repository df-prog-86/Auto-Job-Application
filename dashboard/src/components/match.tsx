import { useState } from "react";

/** The match score pieces shared by Job Search and Jobs, so a score looks the same everywhere. */

export function scoreColor(score: number): string {
  if (score >= 0.75) return "#12b76a";
  if (score >= 0.5) return "#f59e0b";
  return "#9a99b3";
}

export function scoreLabel(score: number): string {
  if (score >= 0.75) return "Strong fit";
  if (score >= 0.5) return "Partial fit";
  return "Weak fit";
}

/** Soft colors for each fit level, shared by the pill, the card edge and the explanation panel. */
export function fitTone(score: number): { pillBg: string; pillFg: string; tint: string } {
  if (score >= 0.75) return { pillBg: "#e8f6ee", pillFg: "#17603f", tint: "#f2faf6" };
  if (score >= 0.5) return { pillBg: "#fff4dc", pillFg: "#8a5a00", tint: "#fffaf0" };
  return { pillBg: "#efedf7", pillFg: "#5a5570", tint: "#f6f6fa" };
}

/** "Strong fit", "Partial fit" or "Weak fit" as a small tinted pill. */
export function FitPill({ score }: { score: number }) {
  const tone = fitTone(score);
  return (
    <span
      className="rounded-full px-3 py-1 text-xs font-extrabold"
      style={{ backgroundColor: tone.pillBg, color: tone.pillFg }}
    >
      {scoreLabel(score)}
    </span>
  );
}

const SHOWN_GAPS = 3;

/** Splits a summary into sentences so each one reads as its own point. */
function sentences(text: string): string[] {
  return text
    .split(/(?<=[.!?])\s+(?=[A-Z$0-9"'(])/)
    .map((t) => t.trim())
    .filter(Boolean);
}

function Mark({ kind }: { kind: "ok" | "gap" }) {
  return (
    <span
      className={`mt-[1px] flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-[11px] font-extrabold text-white ${
        kind === "ok" ? "bg-emerald-500" : "bg-amber-500"
      }`}
      aria-hidden="true"
    >
      {kind === "ok" ? "\u2713" : "!"}
    </span>
  );
}

const rowClass = "flex min-w-0 gap-[9px] text-[13px] leading-[1.45] text-ink-700 [&+&]:border-t [&+&]:border-ink-900/5 [&+&]:pt-[9px]";

/** The "Why it fits" box: one row per point, tinted by how good the fit is. */
export function WhyItFits({ score, summary }: { score: number; summary: string | null | undefined }) {
  const points = sentences((summary ?? "").trim());
  if (points.length === 0) return null;
  return (
    <div className="min-w-0 rounded-2xl px-4 py-3.5" style={{ backgroundColor: fitTone(score).tint }}>
      <h3 className="mb-2.5 text-[13px] font-extrabold text-ink-900">Why it fits</h3>
      <ul className="flex flex-col gap-[9px]">
        {points.map((t, i) => (
          <li key={i} className={rowClass}>
            <Mark kind="ok" />
            <span className={i === 0 ? "font-semibold text-ink-900" : ""}>{t}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The "What's missing" box: what the posting lists that the resume doesn't show. */
export function WhatsMissing({ gaps }: { gaps: string[] }) {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? gaps : gaps.slice(0, SHOWN_GAPS);
  const hidden = gaps.length - visible.length;
  const empty = gaps.length === 0;
  return (
    <div className={`min-w-0 rounded-2xl px-4 py-3.5 ${empty ? "bg-[#f2faf6]" : "bg-amber-50"}`}>
      <h3 className="mb-2.5 text-[13px] font-extrabold text-ink-900">What&apos;s missing</h3>
      {empty ? (
        <p className="flex items-center gap-2 text-[13px] font-semibold text-[#17603f]">
          <Mark kind="ok" />
          Nothing important missing
        </p>
      ) : (
        <>
          <ul className="flex flex-col gap-[9px]">
            {visible.map((gap) => (
              <li key={gap} className={rowClass}>
                <Mark kind="gap" />
                <span>{gap}</span>
              </li>
            ))}
          </ul>
          {(hidden > 0 || showAll) && gaps.length > SHOWN_GAPS && (
            <button
              type="button"
              onClick={() => setShowAll((v) => !v)}
              className="mt-2 text-xs font-bold text-brand-600 hover:text-brand-700 hover:underline"
            >
              {showAll ? "Show fewer" : `Show ${hidden} more`}
            </button>
          )}
        </>
      )}
    </div>
  );
}
