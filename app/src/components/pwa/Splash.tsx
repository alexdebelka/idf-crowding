"use client";

import { useEffect, useRef, useState } from "react";
import { INTRO_OPTIONS, SPLASH_KEY, SPLASH_TO, introReady, reducedMotion, splashTime } from "@/lib/intro";

/** Runs before the first paint (inline, in <head>): when the installed app opens for the first
 *  time, hold the screen on Nuit so the home does not flash before the intro. */
export const SPLASH_BOOT = `try{if((matchMedia("(display-mode: standalone)").matches||navigator.standalone)&&!localStorage.getItem("${SPLASH_KEY}")&&!matchMedia("(prefers-reduced-motion: reduce)").matches)document.documentElement.classList.add("splash")}catch(e){}`;

/** Launch intro of the installed app: about 2.5 s, once per device, tap to skip, no sound.
 *  Never shown in a browser tab, nor to people who ask for reduced motion. */
export function Splash() {
  const host = useRef<HTMLDivElement>(null);
  const [on, setOn] = useState(false);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    const root = document.documentElement;
    if (!root.classList.contains("splash")) return;
    if (reducedMotion()) {
      root.classList.remove("splash");
      return;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- decided on the device, after load
    setOn(true);
    let raf = 0;
    let done = false;
    let handle: { draw: (t: number) => void; destroy: () => void } | null = null;
    const finish = () => {
      if (done) return;
      done = true;
      cancelAnimationFrame(raf);
      try {
        window.localStorage.setItem(SPLASH_KEY, "1");
      } catch {
        /* storage unavailable: the intro may play again */
      }
      root.classList.remove("splash");
      setLeaving(true);
      window.setTimeout(() => {
        handle?.destroy();
        setOn(false);
      }, 320);
    };
    // Offline or slow: do not keep the person waiting for an animation.
    const giveUp = window.setTimeout(finish, 1500);
    introReady()
      .then((api) => {
        window.clearTimeout(giveUp);
        if (done) return;
        if (!host.current) return finish();
        handle = api.mount(host.current, INTRO_OPTIONS);
        const t0 = performance.now();
        const frame = (now: number) => {
          const t = splashTime((now - t0) / 1000);
          if (t == null) {
            handle?.draw(SPLASH_TO);
            window.setTimeout(finish, 350);
            return;
          }
          handle?.draw(t);
          raf = requestAnimationFrame(frame);
        };
        raf = requestAnimationFrame(frame);
      })
      .catch(finish);
    window.addEventListener("pointerdown", finish, { once: true });
    window.addEventListener("keydown", finish, { once: true });
    return () => {
      window.clearTimeout(giveUp);
      cancelAnimationFrame(raf);
      window.removeEventListener("pointerdown", finish);
      window.removeEventListener("keydown", finish);
      root.classList.remove("splash");
    };
  }, []);

  if (!on) return null;
  return <div ref={host} aria-hidden="true" className={`splash-stage${leaving ? " is-leaving" : ""}`} />;
}
