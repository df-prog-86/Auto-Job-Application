import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

import { OtterTile } from "@/components/OtterTile";

/** A tip is plain text with optional area names, which show in the brand color so they stand out as places in the app. */
type Tip = Array<string | { area: string }>;

interface PageHelp {
  title: string;
  tips: Tip[];
}

const HELP: Record<string, PageHelp> = {
  home: {
    title: "Home",
    tips: [
      ["Not sure where to begin? ", { area: "Get started" }, " walks you from adding your resume to sending your first application, and checks off each step as you go."],
      ["Click any stage in your ", { area: "Pipeline" }, " to see the jobs sitting there. Then set a ", { area: "Weekly goal" }, " to keep yourself moving."],
      ["A friendly nudge goes a long way. ", { area: "Follow up" }, " drafts the email in one click for jobs that have gone quiet, and you stay in charge of sending it."],
    ],
  },
  jobs: {
    title: "Jobs",
    tips: [
      ["Add any job by pasting its link at the top. Need to find one again? Search your list by role or company."],
      ["Curious if a job is a good match? Score it to see how well it matches your experience."],
      ["Ready to apply? Tailor your resume to the job to get past ATS screeners. Choose how much it changes, then read ", { area: "What changed" }, " before you use it."],
    ],
  },
  "job-search": {
    title: "Job Search",
    tips: [
      ["Job searching starts here. Add one or more job titles and a city, then press Search. Not picky about where? Type United States."],
      ["Want fewer, better matches? Use ", { area: "All filters" }, " to narrow your search."],
      ["Love a job? Add it to your Jobs list. Not for you? Choose Not interested to hide it, or hide a whole company so it stays out of future searches."],
      ["Searching for the same thing again and again? Save a search to easily search it again in the future."],
    ],
  },
  profile: {
    title: "Profile",
    tips: [
      ["Start with your resume. Drop in a Word (.docx) file and we'll build your profile from it."],
      ["Spot something off? Click any field to edit it. A tidy profile means smoother autofill."],
      ["Employers ask the same questions again and again, so answer them once here. We'll reuse your answers on every application."],
      ["Your ", { area: "Master resume" }, " is where every tailored version begins. Drop in a fresh one whenever your experience changes."],
    ],
  },
  "needs-attention": {
    title: "Needs Attention",
    tips: [
      ["These are questions the extension couldn't answer while filling an application."],
      ["Answer once and it's remembered for every future application."],
      ["After you answer, fill that field yourself, or run Fill again."],
      ["To change an answer later, look under Answers I remember."],
    ],
  },
  pairing: {
    title: "Pair Extension",
    tips: [
      ["Pairing connects the OtterApply extension in Chrome to the app, so it can fill out applications for you."],
      ["Create a pairing code below, then open the extension in Chrome and paste the code in."],
      ["Each code works only once, so paste it in right away. Need another? Just create a new one."],
    ],
  },
};

const FALLBACK: PageHelp = {
  title: "OtterApply",
  tips: [["Use the menu on the left to move between pages."]],
};

function helpFor(pathname: string): PageHelp {
  const key = pathname.replace(/^\/+/, "").split("/")[0] || "home";
  return HELP[key] ?? FALLBACK;
}

/** A small Help pill, fixed to the bottom-right corner of every page. It opens a tile with tips for the page you are on. */
export function HelpButton() {
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);
  const help = helpFor(pathname);

  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col items-end gap-3 md:bottom-5 md:right-5">
      {open && (
        <section
          role="dialog"
          aria-label={`${help.title} help`}
          className="flex max-h-[70vh] w-[340px] max-w-[calc(100vw-32px)] flex-col overflow-y-auto rounded-[20px] border border-[#e9e6f4] bg-white shadow-soft"
        >
          <div className="flex items-center gap-2.5 px-4 pb-2.5 pt-3.5">
            <OtterTile size={46} />
            <div className="min-w-0">
              <h2 className="text-[15px] font-extrabold leading-tight text-ink-900">{help.title}</h2>
              <p className="text-xs text-ink-500">Quick tips for this page</p>
            </div>
            <button
              ref={closeRef}
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close help"
              className="ml-auto grid h-8 w-8 shrink-0 place-items-center rounded-full text-ink-500 hover:bg-brand-50 hover:text-ink-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-200"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className="h-4 w-4" aria-hidden="true">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>
          <ul className="flex flex-col gap-2.5 px-4 pb-4 pt-1">
            {help.tips.map((tip, i) => (
              <li key={i} className="flex gap-2.5 text-[13.5px] leading-snug text-ink-700">
                <span className="mt-[7px] h-[7px] w-[7px] shrink-0 rounded-full bg-brand-500" aria-hidden="true" />
                <span>
                  {tip.map((part, j) =>
                    typeof part === "string" ? (
                      part
                    ) : (
                      <span key={j} className="text-brand-500">
                        {part.area}
                      </span>
                    ),
                  )}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex h-12 items-center gap-2 rounded-full border border-[#ddd8f3] bg-white pl-1.5 pr-5 text-sm font-extrabold text-ink-900 shadow-soft hover:border-brand-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-200"
      >
        <OtterTile size={38} className="-translate-y-[2.5px]" />
        Help
      </button>
    </div>
  );
}
