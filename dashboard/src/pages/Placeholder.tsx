import { Badge, Card } from "@/components/ui";
import { PageHeader } from "@/components/PageHeader";

interface ComingSoonProps {
  title: string;
  description: string;
  points: string[];
}

/** Shared page for tabs that aren't built yet. */
export function ComingSoon({ title, description, points }: ComingSoonProps) {
  return (
    <div>
      <PageHeader title={title} description={description} action={<Badge tone="brand">Coming soon</Badge>} />
      <Card className="p-8">
        <div className="flex flex-col gap-6 md:flex-row md:items-center">
          <div className="flex h-24 w-24 shrink-0 items-center justify-center rounded-3xl bg-gradient-to-br from-brand-100 to-sky-100">
            <svg viewBox="0 0 24 24" fill="none" className="h-10 w-10 text-brand-500" aria-hidden="true">
              <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z" fill="currentColor" />
            </svg>
          </div>
          <div>
            <h2 className="text-lg font-bold text-ink-900">Here is what this will do</h2>
            <ul className="mt-3 space-y-2 text-sm text-ink-500">
              {points.map((p) => (
                <li key={p} className="flex gap-2.5">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-400" />
                  {p}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Card>
    </div>
  );
}
