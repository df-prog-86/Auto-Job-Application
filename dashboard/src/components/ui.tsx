import type { ButtonHTMLAttributes, ReactNode } from "react";

/** Shared building blocks so every page feels like one app. */

export const inputClass =
  "w-full rounded-xl border border-[#ddd8f3] bg-white px-3.5 py-2 text-sm text-ink-900 placeholder:text-ink-400 transition focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-200";

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-2xl bg-white shadow-soft ${className}`}>
      {children}
    </section>
  );
}

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-gradient-to-b from-brand-400 to-brand-500 text-white shadow-glow hover:from-brand-500 hover:to-brand-600",
  secondary: "border border-[#ddd8f3] bg-white text-brand-700 hover:bg-brand-50",
  ghost: "text-ink-500 hover:bg-brand-50 hover:text-brand-700",
  danger: "bg-red-600 text-white hover:bg-red-700",
};

export function Button({
  variant = "secondary",
  size = "md",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  const sizing = size === "sm" ? "px-3.5 py-2 text-[13px]" : "px-5 py-2.5 text-sm";
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-1.5 rounded-full font-bold transition disabled:cursor-not-allowed disabled:opacity-50 ${sizing} ${VARIANTS[variant]} ${className}`}
    />
  );
}

type Tone = "neutral" | "success" | "warning" | "brand";

const TONES: Record<Tone, string> = {
  neutral: "bg-ink-900/5 text-ink-500",
  success: "bg-emerald-50 text-emerald-700",
  warning: "bg-amber-50 text-amber-700",
  brand: "bg-brand-50 text-brand-700",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}

export function CheckIcon({ className = "h-3.5 w-3.5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" className={className} aria-hidden="true">
      <path
        d="M4.5 10.5l3.5 3.5 7.5-8"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Circular progress / score ring. `value` is 0 to 1. */
export function Ring({
  value,
  size = 64,
  stroke = 7,
  color = "#5b57f5",
  children,
}: {
  value: number;
  size?: number;
  stroke?: number;
  color?: string;
  children?: ReactNode;
}) {
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(1, value));
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="#ece9ff" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - clamped)}
          style={{ transition: "stroke-dashoffset 700ms ease-out" }}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">{children}</div>
    </div>
  );
}
