import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

export function PageHeader({ title, description, action }: PageHeaderProps) {
  return (
    <div className="mb-7 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-ink-900">{title}</h1>
        {description && <p className="mt-1.5 max-w-xl text-sm leading-relaxed text-ink-500">{description}</p>}
      </div>
      {action}
    </div>
  );
}
