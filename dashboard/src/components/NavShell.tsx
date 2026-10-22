import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";

import { api } from "@/api/client";
import { Otter } from "@/components/Otter";
import { Badge } from "@/components/ui";

interface NavItem {
  to: string;
  label: string;
  soon?: boolean;
}

const MAIN: NavItem[] = [
  { to: "/", label: "Home" },
  { to: "/jobs", label: "Jobs" },
  { to: "/job-search", label: "Job Search" },
  { to: "/profile", label: "Profile" },
];

const BOTTOM: NavItem[] = [
  { to: "/needs-attention", label: "Needs Attention" },
  { to: "/pairing", label: "Pair Extension" },
];

function LogoMark() {
  return (
    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#15122e] shadow-glow">
      <Otter size={32} />
    </div>
  );
}

function NavGroup({ items, className = "" }: { items: NavItem[]; className?: string }) {
  const attention = useQuery({ queryKey: ["needs-attention"], queryFn: api.listNeedsAttention, retry: false });
  const openCount = attention.data?.length ?? 0;
  return (
    <div className={className}>
      <div className="flex gap-0.5 md:flex-col">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              `flex items-center justify-between rounded-full px-3.5 py-2.5 text-sm font-bold transition ${
                isActive
                  ? "bg-brand-100 text-brand-700"
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
      <aside className="flex shrink-0 flex-col bg-white/80 px-4 py-5 shadow-soft backdrop-blur md:sticky md:top-0 md:h-screen md:w-60 md:py-7">
        <div className="mb-3 flex items-center gap-3 px-2 md:mb-9">
          <LogoMark />
          <div>
            <div className="text-base font-bold leading-tight text-ink-900">OtterApply</div>
            <div className="text-xs leading-snug text-ink-400">Because applying shouldn&apos;t suck</div>
          </div>
        </div>
        <nav className="flex gap-2 overflow-x-auto md:min-h-0 md:flex-1 md:flex-col md:overflow-visible">
          <NavGroup items={MAIN} />
          <NavGroup items={BOTTOM} className="md:mt-auto md:border-t md:border-[#ebe8f6] md:pt-3" />
        </nav>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-8 md:px-10 md:py-10">
        <div className="mx-auto max-w-5xl">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
