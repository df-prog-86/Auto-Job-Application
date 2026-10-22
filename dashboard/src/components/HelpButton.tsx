import { useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";

import { HelpOtter } from "@/components/HelpOtter";

interface PageHelp {
  title: string;
  tips: ReactNode[];
}

const HELP: Record<string, PageHelp> = {
  home: {
    title: "Home",
    tips: [
      "Work down the Get started list. It takes you from adding your resume to your first application.",
      "New matches from your saved search show up here. Refresh the search to look again.",
      "Select a stage in the pipeline to see its jobs. Set a weekly goal to track applications sent.",
      "Under Follow up, jobs you applied to with no reply get a draft email. Edit it, then send it yourself.",
    ],
  },
  jobs: {
    title: "Jobs",
    tips: [
      "Paste a job link at the top to add a job, or search your list by role or company.",
      "Open a job to compare it with your resume and see how well it fits.",
      "Tailor your resume for a job. Choose how much it changes, then check What changed.",
      "Use the stage tabs to see jobs by where they stand.",
    ],
  },
  "job-search": {
    title: "Job Search",
    tips: [
      "Type a job title and a city (or United States), then press Search. Suggestions appear as you type.",
      "All filters has salary, work type, how recent, keywords like denials or Epic, and companies to leave out.",
      "Open a result to see why it fits your search and how it compares with your resume.",
      "Add the ones you like to Jobs. Not interested hides a job, and you can hide a whole company too.",
      "Save a search and its new matches show up on Home.",
    ],
  },
  profile: {
    title: "Profile",
    tips: [
      "Start by dropping in your resume. Word (.docx) works best, and we fill in your profile from it.",
      "Check what we found, then click any field to fix it.",
      "Answers used on every application, like relocation or visa questions, only need setting once.",
      "Keep your master resume up to date. Every tailored version starts from it.",
    ],
  },
  "needs-attention": {
    title: "Needs Attention",
    tips: [
      "These are questions the extension couldn't answer while filling an application.",
      "Answer once and it's remembered for every future application.",
      "After you answer, fill that field yourself, or run Fill again.",
      "To change an answer later, look under Answers I remember.",
    ],
  },
  pairing: {
    title: "Pair Extension",
    tips: [
      "Pairing connects the OtterApply extension in Chrome so it can fill applications for you.",
      "Create a pairing code here, then open the extension and paste it in.",
      "The code works once, so use it right away.",
    ],
  },
};

const FALLBACK: PageHelp = {
  title: "OtterApply",
  tips: ["Use the menu on the left to move between pages."],
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
            <HelpOtter size={46} />
            <div className="min-w-0">
              <h2 className="text-[15px] font-extrabold leading-tight text-ink-900">{help.title}</h2>
              <p className="text-xs text-ink-500">Quick tips for this page</p>
            </div>
            <button
              ref={closeRef}
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close help"
              className="ml-auto rounded-lg px-2 text-xl leading-none text-ink-500 hover:bg-brand-50 hover:text-ink-900 focus:outline-none focus:ring-2 focus:ring-brand-200"
            >
              ×
            </button>
          </div>
          <ul className="flex flex-col gap-2.5 px-4 pb-4 pt-1">
            {help.tips.map((tip, i) => (
              <li key={i} className="flex gap-2.5 text-[13.5px] leading-snug text-ink-700">
                <span className="mt-[7px] h-[7px] w-[7px] shrink-0 rounded-full bg-brand-500" aria-hidden="true" />
                <span>{tip}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex h-11 items-center gap-2 rounded-full border border-[#ddd8f3] bg-white pl-1.5 pr-[18px] text-sm font-extrabold text-ink-900 shadow-soft hover:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-200"
      >
        <HelpOtter size={46} />
        Help
      </button>
    </div>
  );
}
