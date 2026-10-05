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

export function GapDetails({ gaps }: { gaps: string[] }) {
  return (
    <details className="mt-2 text-sm text-ink-500">
      <summary className="cursor-pointer select-none text-xs font-semibold text-brand-600 hover:text-brand-700">
        See what's missing ({gaps.length})
      </summary>
      <ul className="mt-2 space-y-1.5 pl-1">
        {gaps.map((gap) => (
          <li key={gap} className="flex gap-2 text-xs leading-relaxed">
            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
            {gap}
          </li>
        ))}
      </ul>
    </details>
  );
}
