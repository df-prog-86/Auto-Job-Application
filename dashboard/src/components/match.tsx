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

/** Why a job fits and what is missing, tinted by how good the fit is. */
export function MatchPanel({
  score,
  summary,
  gaps,
  stacked = false,
  note,
}: {
  score: number;
  summary: string | null | undefined;
  gaps: string[];
  /** One column, for narrow spaces. Otherwise two columns on wide screens. */
  stacked?: boolean;
  note?: string;
}) {
  const [showAll, setShowAll] = useState(false);
  const text = (summary ?? "").trim();
  // The first sentence reads as a headline; the rest is the supporting detail.
  const cut = text.search(/[.!?](\s|$)/);
  const headline = cut >= 0 ? text.slice(0, cut + 1) : text;
  const rest = cut >= 0 ? text.slice(cut + 1).trim() : "";
  const visible = showAll ? gaps : gaps.slice(0, SHOWN_GAPS);
  const hidden = gaps.length - visible.length;

  return (
    <div
      className="rounded-2xl px-[18px] py-4"
      style={{ backgroundColor: fitTone(score).tint }}
    >
      <div className={stacked ? "space-y-4" : "grid gap-x-6 gap-y-4 md:grid-cols-[1.4fr_1fr]"}>
        {text && (
          <div className="min-w-0">
            <h3 className="text-xs font-extrabold text-ink-900">Why it fits</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-ink-700">
              <strong className="font-bold text-ink-900">{headline}</strong>
              {rest ? ` ${rest}` : ""}
            </p>
          </div>
        )}
        <div className="min-w-0">
          <h3 className="text-xs font-extrabold text-ink-900">Gaps</h3>
          {gaps.length === 0 ? (
            <p className="mt-1.5 flex items-center gap-2 text-[13px] font-semibold text-[#17603f]">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.6"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="h-4 w-4"
                aria-hidden="true"
              >
                <path d="M5 12.5l4.5 4.5L19 7.5" />
              </svg>
              No gaps found
            </p>
          ) : (
            <>
              <ul className="mt-1.5 space-y-1.5">
                {visible.map((gap) => (
                  <li key={gap} className="flex gap-2 text-[13px] leading-relaxed text-ink-700">
                    <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
                    {gap}
                  </li>
                ))}
              </ul>
              {(hidden > 0 || showAll) && gaps.length > SHOWN_GAPS && (
                <button
                  type="button"
                  onClick={() => setShowAll((v) => !v)}
                  className="mt-1.5 text-xs font-bold text-brand-600 hover:text-brand-700 hover:underline"
                >
                  {showAll ? "Show fewer" : `Show ${hidden} more`}
                </button>
              )}
            </>
          )}
        </div>
      </div>
      {note && <p className="mt-3 text-xs text-amber-700">{note}</p>}
    </div>
  );
}
