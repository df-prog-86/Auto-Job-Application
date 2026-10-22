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
      "Add your resume on Profile once. Every tailored version starts from it.",
      "Paste a job link, or save one from the extension.",
      "Select a stage in the pipeline to see the jobs in it.",
      "Set a weekly goal and watch applications sent add up. Change it any time.",
    ],
  },
  jobs: {
    title: "Jobs",
    tips: [
      "Paste a job link at the top to add a job.",
      "Open a job to see how well it fits your resume.",
      "Tailor your resume for a job. It keeps your words and shows exactly what changed.",
      "Already applied? We'll draft a follow-up email in one click. You send it yourself.",
    ],
  },
  "job-search": {
    title: "Job Search",
    tips: [
      "Type a job title and a city, then press Search. Suggestions appear as you type.",
      <>
        <b>All filters</b> has salary, work type and how recent. <b>Clear all</b> starts fresh.
      </>,
      <>
        <b>Sort</b> sits next to the match count.
      </>,
      "Add the ones you like to Jobs. Choose Not interested to hide a job (or a whole company).",
    ],
  },
  profile: {
    title: "Profile",
    tips: [
      "Fill out your profile once and it autofills every future application.",
      "Click any field to edit it.",
      "Drop in a fresh resume any time. Word (.docx) works best.",
      "Your answers to questions like relocation or visa are used on every application.",
    ],
  },
  "needs-attention": {
    title: "Needs Attention",
    tips: [
      "These are questions we couldn't answer yet.",
      "Answer once and it's filled in every time after.",
      "Look under Answers I remember to change one later.",
    ],
  },
  pairing: {
    title: "Pair Extension",
    tips: [
      "Create a pairing code here, then open the OtterApply extension in Chrome and paste it in.",
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
