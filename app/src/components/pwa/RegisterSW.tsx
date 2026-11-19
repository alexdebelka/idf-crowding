"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { notifyStationOpened, registerServiceWorker } from "./register";

/**
 * Registers the service worker (public/sw.js) once, in production, and tells it which station
 * page is showing (client-side navigation included). Renders nothing.
 */
export function RegisterSW() {
  const pathname = usePathname();
  useEffect(() => {
    registerServiceWorker();
  }, []);
  useEffect(() => {
    notifyStationOpened(pathname);
  }, [pathname]);
  return null;
}
