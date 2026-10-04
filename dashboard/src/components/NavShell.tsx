import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";

import { api } from "@/api/client";
import { Badge } from "@/components/ui";

interface NavItem {
  to: string;
  label: string;
  soon?: boolean;
}

const WORK: NavItem[] = [
  { to: "/", label: "Home" },
  { to: "/jobs", label: "Jobs" },
  { to: "/needs-attention", label: "Needs Attention" },
];

const SETUP: NavItem[] = [
  { to: "/profile", label: "Profile" },
  { to: "/pairing", label: "Pair Extension" },
];

function LogoMark() {
  return (
    <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-600 shadow-glow">
      <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5 text-white" aria-hidden="true">
        <path
          d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z"
          fill="currentColor"
        />
        <path d="M18.5 15l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2z" fill="currentColor" opacity="0.8" />
      </svg>
    </div>
  );
}

function NavGroup({ title, items }: { title: string; items: NavItem[] }) {
  const attention = useQuery({ queryKey: ["needs-attention"], queryFn: api.listNeedsAttention, retry: false });
  const openCount = attention.data?.length ?? 0;
  return (
    <div>
      <div className="mb-1.5 hidden px-3 text-xs font-semibold text-ink-400 md:block">{title}</div>
      <div className="flex gap-0.5 md:flex-col">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              `flex items-center justify-between rounded-xl px-3 py-2 text-sm font-semibold transition ${
                isActive
                  ? "bg-brand-50 text-brand-700"
                  : item.soon
                    ? "text-ink-400 hover:bg-white/70"
                    : "text-ink-500 hover:bg-white/70 hover:text-ink-900"
              }`
            }
          >
            {item.label}
            {item.soon && <Badge>Soon</Badge>}
            {item.to === "/needs-attention" && openCount > 0 && <Badge tone="warning">{openCount}</Badge>}
          </NavLink>
        ))}
      </div>
    </div>
  );
}

export function NavShell() {
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="shrink-0 border-b border-white/70 bg-white/60 px-4 py-5 backdrop-blur md:sticky md:top-0 md:h-screen md:w-60 md:border-b-0 md:border-r md:py-7">
        <div className="mb-3 flex items-center gap-3 px-2 md:mb-9">
          <LogoMark />
          <div>
            <div className="text-base font-bold leading-tight text-ink-900">Job Agent</div>
            <div className="text-xs text-ink-400">Your job search, organized</div>
          </div>
        </div>
        <nav className="flex gap-2 overflow-x-auto md:flex-col md:gap-7 md:overflow-visible">
          <NavGroup title="Your search" items={WORK} />
          <NavGroup title="Setup" items={SETUP} />
        </nav>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-8 md:px-10 md:py-10">
        <div className="mx-auto max-w-4xl">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
