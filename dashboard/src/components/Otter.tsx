import { useId } from "react";

const BLOB_A = "M60 20C86 18 104 36 102 62C100 88 82 104 58 102C34 100 18 84 20 58C22 34 36 22 60 20Z";
const BLOB_B = "M62 24C84 24 100 42 98 64C96 86 80 100 60 98C38 96 22 80 24 60C26 40 40 24 62 24Z";

/** The OtterApply character: a soft, gradient otter that slowly drifts and blinks. */
export function Otter({ size = 32, className = "" }: { size?: number; className?: string }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg viewBox="0 0 120 120" width={size} height={size} className={className} aria-hidden="true" style={{ overflow: "visible" }}>
      <defs>
        <linearGradient id={`${id}g`} x1="1" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffc59a" />
          <stop offset=".5" stopColor="#a49dff" />
          <stop offset="1" stopColor="#46dccb" />
        </linearGradient>
        <radialGradient id={`${id}h`}>
          <stop offset=".55" stopColor="#7d7af8" stopOpacity=".55" />
          <stop offset="1" stopColor="#7d7af8" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="60" cy="62" r="56" fill={`url(#${id}h)`} />
      <circle cx="30" cy="30" r="8" fill={`url(#${id}g)`} />
      <circle cx="90" cy="30" r="8" fill={`url(#${id}g)`} />
      <path fill={`url(#${id}g)`} d={BLOB_A}>
        <animate attributeName="d" dur="6s" repeatCount="indefinite" calcMode="spline" keyTimes="0;.5;1" keySplines=".4 0 .6 1;.4 0 .6 1" values={`${BLOB_A};${BLOB_B};${BLOB_A}`} />
      </path>
      <path d="M40 40q20-14 40 0" stroke="#fff" strokeOpacity=".35" strokeWidth="6" strokeLinecap="round" fill="none" />
      <g className="otter-blink">
        <circle cx="46" cy="60" r="5.5" fill="#1d1844" />
        <circle cx="74" cy="60" r="5.5" fill="#1d1844" />
      </g>
      <circle cx="47.5" cy="58" r="1.8" fill="#fff" />
      <circle cx="75.5" cy="58" r="1.8" fill="#fff" />
      <ellipse cx="60" cy="72" rx="5" ry="3.4" fill="#1d1844" />
      <path d="M54 77q6 5 12 0" fill="none" stroke="#1d1844" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}
