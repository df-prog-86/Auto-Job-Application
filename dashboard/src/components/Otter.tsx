import { useId } from "react";

const BLOB_A = "M60 24C88 22 106 40 104 63C102 86 84 100 58 98C34 96 16 84 16 60C16 38 34 26 60 24Z";
const BLOB_B = "M62 27C86 26 102 43 100 64C98 84 82 96 60 95C38 94 20 82 21 61C22 42 38 27 62 27Z";

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
      <circle cx="25" cy="37" r="7.5" fill={`url(#${id}g)`} />
      <circle cx="95" cy="37" r="7.5" fill={`url(#${id}g)`} />
      <path fill={`url(#${id}g)`} d={BLOB_A}>
        <animate attributeName="d" dur="6s" repeatCount="indefinite" calcMode="spline" keyTimes="0;.5;1" keySplines=".4 0 .6 1;.4 0 .6 1" values={`${BLOB_A};${BLOB_B};${BLOB_A}`} />
      </path>
      <path d="M38 41q22-12 44 0" stroke="#fff" strokeOpacity=".35" strokeWidth="6" strokeLinecap="round" fill="none" />
      <ellipse cx="60" cy="77" rx="25" ry="15" fill="#fff" fillOpacity=".5" />
      <path d="M38 75L22 72M38 80L22 83M82 75L98 72M82 80L98 83" stroke="#fff" strokeOpacity=".75" strokeWidth="1.8" strokeLinecap="round" />
      <g className="otter-blink">
        <circle cx="46" cy="60" r="5.5" fill="#1d1844" />
        <circle cx="74" cy="60" r="5.5" fill="#1d1844" />
      </g>
      <circle cx="47.5" cy="58" r="1.8" fill="#fff" />
      <circle cx="75.5" cy="58" r="1.8" fill="#fff" />
      <path d="M53 67q7-5 14 0q-2 6-7 7q-5-1-7-7z" fill="#1d1844" />
      <path d="M60 74v3M53 79q3.5 4 7 0q3.5 4 7 0" fill="none" stroke="#1d1844" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      <g fill="#1d1844" opacity=".35">
        <circle cx="45" cy="72" r="1.1" />
        <circle cx="42" cy="76" r="1.1" />
        <circle cx="75" cy="72" r="1.1" />
        <circle cx="78" cy="76" r="1.1" />
      </g>
    </svg>
  );
}
