import { PageHeader } from "@/components/PageHeader";

interface PlaceholderProps {
  title: string;
  description: string;
  milestoneNote: string;
}

/** Shared shell for pages whose real content arrives in a later milestone. */
export function Placeholder({ title, description, milestoneNote }: PlaceholderProps) {
  return (
    <div>
      <PageHeader title={title} description={description} />
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-400">
        {milestoneNote}
      </div>
    </div>
  );
}
