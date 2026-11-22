"use client";

import { useRef } from "react";
import styles from "./station.module.css";

/** Date pill ("Aujourd’hui", 44 px, ink fill), limited to the Place's forecast dates.
 *  The real control is the native date input, laid invisibly over the pill:
 *  - touch screens: the tap lands on the input and the system opens its own picker (iOS does
 *    not open a date picker from script, so a button calling `showPicker()` does nothing there);
 *  - mouse: the input lets the click through to the pill, which opens the picker;
 *  - keyboard and screen readers: the input is the focusable, labelled control. */
export function DatePill({
  label,
  accessibleLabel,
  value,
  min,
  max,
  onPick,
}: {
  label: string;
  accessibleLabel: string;
  value: string;
  min: string;
  max: string;
  onPick: (date: string) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const open = () => {
    const el = input.current;
    if (!el) return;
    try {
      el.showPicker();
    } catch {
      el.focus();
    }
  };
  return (
    <span className={styles.pillWrap}>
      <button type="button" className={`pill ${styles.datePill}`} tabIndex={-1} aria-hidden="true" onClick={open}>
        {label}
        <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      <input
        ref={input}
        type="date"
        className={styles.dateInput}
        aria-label={accessibleLabel}
        value={value}
        min={min}
        max={max}
        onChange={(e) => {
          if (e.target.value) onPick(e.target.value);
        }}
      />
    </span>
  );
}

/** The way back to today from a chosen date: an outlined pill next to the date. */
export function TodayButton({ label, accessibleLabel, onClick }: { label: string; accessibleLabel: string; onClick: () => void }) {
  return (
    <button type="button" className={styles.todayButton} aria-label={accessibleLabel} onClick={onClick}>
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M19 12H5" />
        <path d="M11 6l-6 6 6 6" />
      </svg>
      {label}
    </button>
  );
}
