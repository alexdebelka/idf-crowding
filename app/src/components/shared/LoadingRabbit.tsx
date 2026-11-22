"use client";

import { useSyncExternalStore } from "react";

// The rabbit of the mark in its four parts (same numbers as public/brand/intro.js).
const BODY =
  "M0 0.01C2.6 0.01 5.22 -0.15 7.8 -0.49C10.38 -0.82 12.96 -1.32 15.47 -2C17.98 -2.68 20.48 -3.52 22.85 -4.58C25.22 -5.63 27.57 -6.85 29.72 -8.3C31.86 -9.76 33.96 -11.41 35.72 -13.29C37.49 -15.17 39.16 -17.3 40.33 -19.58C41.51 -21.86 42.41 -24.44 42.79 -26.97C43.17 -29.5 43.02 -32.21 42.63 -34.76C42.24 -37.31 41.46 -39.87 40.45 -42.25C39.43 -44.62 38.07 -46.92 36.53 -49C35 -51.09 33.01 -52.84 31.24 -54.75C29.48 -56.65 27.21 -58.24 25.93 -60.42C24.64 -62.6 24.06 -65.28 23.55 -67.8C23.03 -70.32 23.46 -73.08 22.83 -75.57C22.2 -78.06 21.14 -80.57 19.76 -82.72C18.37 -84.88 16.53 -86.9 14.52 -88.48C12.5 -90.06 10.1 -91.37 7.68 -92.21C5.26 -93.05 2.56 -93.5 -0 -93.5C-2.56 -93.5 -5.26 -93.05 -7.68 -92.21C-10.1 -91.37 -12.5 -90.06 -14.52 -88.48C-16.53 -86.9 -18.37 -84.88 -19.76 -82.72C-21.14 -80.57 -22.2 -78.06 -22.83 -75.57C-23.46 -73.08 -23.03 -70.32 -23.55 -67.8C-24.06 -65.28 -24.64 -62.6 -25.93 -60.42C-27.21 -58.24 -29.48 -56.65 -31.24 -54.75C-33.01 -52.84 -35 -51.09 -36.53 -49C-38.07 -46.92 -39.43 -44.62 -40.45 -42.25C-41.46 -39.87 -42.24 -37.31 -42.63 -34.76C-43.02 -32.21 -43.17 -29.5 -42.79 -26.97C-42.41 -24.44 -41.51 -21.86 -40.33 -19.58C-39.16 -17.3 -37.49 -15.17 -35.72 -13.29C-33.96 -11.41 -31.86 -9.76 -29.72 -8.3C-27.57 -6.85 -25.22 -5.63 -22.85 -4.58C-20.48 -3.52 -17.98 -2.68 -15.47 -2C-12.96 -1.32 -10.38 -0.82 -7.8 -0.49C-5.22 -0.15 -2.6 0.01 0 0.01Z";
const EAR = "M-10.6 6C-12.93 -20 -11.87 -40 0 -40C11.87 -40 12.93 -20 10.6 6Z";
const EAR_X = 12.2;
const EAR_Y = 83;
const EAR_LEFT = -7;
const EAR_RIGHT = 17;
const NOSE_Y = 22;
const NOSE_R = 9.5;

/**
 * Loading rabbit: body, nose, left ear, right ear bounce in, hold, then every part shrinks
 * towards the middle. Styles only (globals.css, "Loading rabbit"): it has to move while the
 * page's scripts are still on their way. Hidden for the first half second, so a fast
 * connection never sees it; still when the device asks for reduced motion.
 * Drawn in the screen's ink; the nose takes the screen's ground.
 */
export function LoadingRabbit({ size, label }: { size: "large" | "small"; label?: string }) {
  return (
    <div className={`boot boot-${size}`} role="status">
      <svg aria-hidden="true" viewBox="-50 -128 100 134" overflow="visible" className="boot-mark">
        <g className="boot-part boot-ear-l">
          <g transform={`translate(${-EAR_X} ${-EAR_Y}) rotate(${EAR_LEFT})`}>
            <path d={EAR} />
          </g>
        </g>
        <g className="boot-part boot-ear-r">
          <g transform={`translate(${EAR_X} ${-EAR_Y}) rotate(${EAR_RIGHT})`}>
            <path d={EAR} />
          </g>
        </g>
        <path className="boot-part boot-body" d={BODY} />
        <circle className="boot-part boot-nose" cx={0} cy={-NOSE_Y} r={NOSE_R} />
      </svg>
      {label ? <span className={size === "large" ? "boot-label" : "sr-only"}>{label}</span> : null}
    </div>
  );
}

const noop = () => () => {};
/** False in the static HTML and until the page's code runs on the device. */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    noop,
    () => true,
    () => false,
  );
}
