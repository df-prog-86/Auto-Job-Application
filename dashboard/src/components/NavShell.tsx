import { NavLink, Outlet } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/", label: "Home" },
  { to: "/profile", label: "Profile" },
  { to: "/preferences", label: "Job Preferences" },
  { to: "/jobs", label: "Jobs" },
  { to: "/applications", label: "Applications" },
  { to: "/needs-attention", label: "Needs Attention" },
  { to: "/accounts", label: "Accounts" },
  { to: "/pairing", label: "Pair Extension" },
] as const;

export function NavShell() {
  return (
    <div className="flex min-h-screen">
      <aside className="w-56 shrink-0 border-r border-slate-200 bg-white px-4 py-6">
        <div className="mb-8 px-2 text-lg font-semibold text-brand-600">Job Agent</div>
        <nav className="flex flex-col gap-1">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-brand-50 text-brand-700"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="flex-1 bg-slate-50 px-8 py-6">
        <Outlet />
      </main>
    </div>
  );
}
